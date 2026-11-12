"""Local workspace, immutable archive receipts and one batch publication pointer."""
from __future__ import annotations

from contextvars import copy_context
from datetime import datetime, timezone
import errno
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
import tomllib
import uuid

from . import PARSER_VERSION
from .source.extraction import RULE_VERSION, proposals
from .domain.research_store import stage_records
from .core.progress import ProgressStep, outcome, phase, task, track
from .core.graph import canonical, hash_text, read_json
from .core.fs import (managed_path as _managed, read_regular as _read_regular,
                      hash_regular as _hash_regular, matches_regular as _matches_regular,
                      read_operational_status as read_operational_status)
from .registry import Registry
from .source.package import Limits, PackageError, SourceTree, unpack
from .store import extraction_semantics, extraction_tool_identity, ingest, source_span_index
from .core.transactions import ManagedDataError, atomic_bytes, atomic_json, immutable_json, writer_lock
from .llm.config import render_config_template

CONFIG = 'qecgraph.toml'
FORMAT = 'qecgraph.workspace'
PROCESSOR = f'archive-structure-v2:parser-{PARSER_VERSION}:{RULE_VERSION}'
HEX = re.compile(r'[0-9a-f]{64}')
JOB = re.compile(r'[0-9a-f]{32}')
AI_EXTRACTION_SKILLS = ('extract_theorems', 'extract_assumptions', 'extract_data', 'extract_thoughts')


def _ai_complete(outcome):
    return ({item['skill'] for item in outcome.get('written', []) if item.get('proposal_sha256')} == set(AI_EXTRACTION_SKILLS)
            and not outcome.get('errors'))


def now():
    return datetime.now(timezone.utc).isoformat()



def _inbox_name(name):
    if not name or Path(name).name != name or name in ('.', '..') or name.startswith('.'):
        raise ValueError('Expected a file name directly inside inputs/')
    return name


def _move_input(source, destination):
    # Exclusive destination creation also makes a retry after linking safe.
    if source.is_symlink():
        try:
            destination.symlink_to(os.readlink(source))
        except FileExistsError:
            return False
    else:
        try:
            os.link(source, destination, follow_symlinks=False)
        except FileExistsError:
            if not os.path.samestat(source.lstat(), destination.lstat()):
                return False
    source.unlink()
    return True


def locate(path=None, *, default=None):
    if path is not None:
        return Path(path).expanduser().resolve()
    start = Path.cwd()
    local = next((p for p in (start, *start.parents) if (p / CONFIG).is_file()), None)
    return local or (Path(default).expanduser().resolve() if default else start)


class WorkspaceConfigError(ManagedDataError):
    def __init__(self, path, message, *, location=None):
        self.location = {}
        if location is not None:
            line, column = location
            self.location = {'line': line, 'column': column}
            message += f' at line {line}, column {column}'
        super().__init__(path, message)


class InputDestinationExists(ValueError):
    def __init__(self, source, destination):
        self.source, self.destination = source, destination
        super().__init__(f'Input already exists at the destination: {destination}')


def _toml_location(exc, text):
    line, column = getattr(exc, 'lineno', None), getattr(exc, 'colno', None)
    if line is not None and column is not None:
        return line, column
    # Before Python 3.14, tomllib reports the position in its message only.
    message = str(exc)
    if match := re.search(r'\(at line (\d+), column (\d+)\)$', message):
        return int(match[1]), int(match[2])
    if message.endswith('(at end of document)'):
        lines = text.replace('\r\n', '\n').split('\n')
        return len(lines), len(lines[-1]) + 1
    return None


def init_directory_error(root):
    """Return why *root* is not a clean new workspace, or None when it is."""
    root = Path(root)
    if root.exists() and not root.is_dir():
        return 'cannot initialize: the target path is not a directory'
    if not root.exists():
        return None
    entries = sorted((path for path in root.iterdir() if not path.name.startswith('.')),
                     key=lambda path: path.name)
    other = [path.name for path in entries if path.name != 'inputs']
    if other:
        shown = ', '.join(other[:8]) + ('...' if len(other) > 8 else '')
        return ('cannot initialize: the target directory contains other entries: '
                f'{shown}; use an empty directory or one containing only inputs/')
    inputs = root / 'inputs'
    if inputs.exists() or inputs.is_symlink():
        if inputs.is_symlink() or not inputs.is_dir():
            return 'cannot initialize: inputs must be a real directory'
    return None


class Workspace:
    def __init__(self, root=None):
        self.root = locate(root)
        self.registry = Registry(self.path('machine'))

    def path(self, relative):
        return _managed(self.root, relative)

    def config(self):
        path = self.path(CONFIG)
        try:
            text = path.read_bytes().decode('utf-8')
            cfg = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise WorkspaceConfigError(path, 'The workspace configuration is not valid TOML',
                                       location=_toml_location(exc, text)) from exc
        except UnicodeDecodeError as exc:
            raise WorkspaceConfigError(path, 'The workspace configuration is not valid UTF-8') from exc
        if cfg.get('format') != FORMAT or not isinstance(cfg.get('workspace_id'), str):
            raise WorkspaceConfigError(path, 'Invalid workspace configuration')
        if set(cfg) - {'format', 'workspace_id', 'limits', 'entrypoints', 'sources', 'ai', 'retrieval'}:
            raise WorkspaceConfigError(path, 'Unsupported workspace settings')
        for field in ('limits', 'entrypoints', 'sources', 'ai', 'retrieval'):
            if not isinstance(cfg.get(field, {}), dict):
                raise WorkspaceConfigError(path, f'{field} must be a table')
        from .retrieval import configuration
        try:
            configuration(cfg.get('retrieval', {}))
        except ValueError as exc:
            raise WorkspaceConfigError(path, str(exc)) from exc
        try:
            Limits(**cfg.get('limits', {}))
        except TypeError as exc:
            raise WorkspaceConfigError(path, 'Unknown workspace limit') from exc
        except ValueError as exc:
            raise WorkspaceConfigError(path, str(exc)) from exc
        for key, entry in cfg.get('entrypoints', {}).items():
            if not HEX.fullmatch(key) or not isinstance(entry, str) or not entry:
                raise WorkspaceConfigError(path, 'Entry overrides use source tree hashes and exact relative member names')
        for key, source in cfg.get('sources', {}).items():
            if (not HEX.fullmatch(key) or not isinstance(source, dict)
                    or set(source) - {'work_id', 'upstream_version', 'title', 'canonical_url'}
                    or not isinstance(source.get('work_id'), str) or not source['work_id'].strip()
                    or not all(isinstance(x, str) and x.strip() for x in source.values())):
                raise WorkspaceConfigError(path, 'Invalid explicit source metadata')
            if 'canonical_url' in source:
                from .knowledge import public_url
                if not public_url(source['canonical_url']):
                    raise WorkspaceConfigError(path, 'canonical_url must be a public HTTP(S) citation URL')
        return cfg

    def init(self, *, no_ingest=False, keep_inputs=False, progress=None):
        if progress:
            progress(0, 1, 'Initializing workspace')
        self.root.mkdir(parents=True, exist_ok=True)
        with writer_lock(self.path('.qecgraph')):
            target = self.path(CONFIG)
            configured = target.exists()
            cfg = self.config() if configured else None
            if configured and self.path('machine/CURRENT.json').is_file():
                return {'status': 'already_initialized', 'workspace_id': cfg['workspace_id'], 'next': 'qec-graph sync'}
            for path in ('inputs/.processing', 'archive/blobs/sha256', 'archive/receipts', 'sources', 'machine'):
                self.path(path).mkdir(parents=True, exist_ok=True)
            if not configured:
                workspace_id = 'workspace:' + uuid.uuid4().hex
                atomic_bytes(target, f'format = "{FORMAT}"\nworkspace_id = "{workspace_id}"\n'.encode())
                cfg = self.config()
            return self._run(cfg, scan_inputs=not no_ingest, rebuild=False,
                             keep_inputs=no_ingest or keep_inputs, progress=progress)

    def prepare(self):
        """Create inputs/ and the AI configuration, without extracting anything."""
        configured = self.path(CONFIG).is_file()
        if not configured:
            problem = init_directory_error(self.root)
            if problem:
                raise ValueError(problem)
        else:
            inputs = self.path('inputs')
            if (inputs.exists() or inputs.is_symlink()) and (inputs.is_symlink() or not inputs.is_dir()):
                raise ValueError('cannot initialize: inputs must be a real directory')
        self.root.mkdir(parents=True, exist_ok=True)
        self.path('inputs').mkdir(parents=True, exist_ok=True)
        target = self.path(CONFIG)
        if not target.exists():
            atomic_bytes(target, render_config_template('workspace:' + uuid.uuid4().hex).encode())
        try:
            target.chmod(0o600)
        except OSError:
            pass
        cfg = self.config()
        if self.path('machine/CURRENT.json').is_file():
            return {'status': 'already_initialized', 'workspace_id': cfg['workspace_id'],
                    'next': 'qec-graph sync'}
        return {'status': 'initialized', 'workspace_id': cfg['workspace_id'],
                'next': 'qec-graph sync',
                'message': 'Edit [ai] in qecgraph.toml, put source packages in inputs/, and run qec-graph sync.'}

    def _ai_client(self):
        from .llm.client import LLMClient
        from .llm.config import AIConfigError, load_ai_config
        from .llm.providers.cli import is_claude

        try:
            config = load_ai_config(self.root)
            if not config.allow_source_upload:
                return None
            provider = config.require_ready()
            if provider.kind == 'cli' and is_claude(provider.name, provider.command) and not provider.resolved_key():
                return None
            return LLMClient(config, cache_dir=self.path('.qecgraph/ai-cache'))
        except AIConfigError:
            return None

    def _resolve_normalization(self, client, tree, prior):
        from .llm.artifacts import load_normalization, normalization_binding, revalidate_legacy_normalization, write_normalization
        from .llm.normalize import NormalizationError, normalize_package

        if prior.get('normalization_manifest_sha256'):
            source, _ = load_normalization(self.registry.root, prior, tree=tree)
            binding = {field: prior[field] for field in (
                'normalization_id', 'normalization_sha256', 'normalization_manifest_sha256')}
            return SourceTree(tree.format, {**tree.files, 'main.tex': source.data}), binding
        if prior.get('normalization_id'):
            try:
                source, binding = revalidate_legacy_normalization(self.registry.root, prior, tree)
                return SourceTree(tree.format, {**tree.files, 'main.tex': source.data}), binding
            except NormalizationError:
                if client is None:
                    raise
        with task('AI checking TeX entry point', retain=True):
            normalized = normalize_package(tree, client)
        artifact, manifest = write_normalization(self.registry.root, normalized, tree)
        return (SourceTree(tree.format, {**tree.files, 'main.tex': normalized.source.data}),
                normalization_binding(artifact, manifest))

    def _english_ai_outcome(self, material):
        """Reuse English proposals and schedule legacy CJK output for extraction."""
        from .core.language import require_english
        from .llm.review import read_bound_proposal

        previous = material.get('ai_extraction', {})
        written = []
        for binding in previous.get('written', []):
            if not binding.get('proposal_sha256'):
                continue
            proposal = read_bound_proposal(self.registry, binding, material)
            try:
                require_english(proposal)
            except ValueError:
                continue
            written.append(binding)
        return {**previous, 'written': written}

    @task('Preparing AI source evidence')
    def _extract_ai(self, client, material, previous, limits, version, reusable=(), on_skill_done=None):
        import copy
        from .core.language import require_english
        from .llm.artifacts import load_normalization
        from .llm.client import LLMResult
        from .llm.extract import ExtractionResult, extract, validate_extraction, validate_source_refs
        from .llm.normalize import original_document
        from .llm.redact import redact
        from .llm.review import read_bound_proposal

        try:
            digest = material['archive_sha256']
            raw = _read_regular(self.path('archive/blobs/sha256/' + digest), 128 << 20)
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError('Archived source hash mismatch')
            tree = unpack(raw, limits)
            if tree.digest != material['source_tree_hash']:
                raise ValueError('Archived source tree mismatch')
            if material.get('normalization_id'):
                normalized, _ = load_normalization(self.registry.root, material, tree=tree)
            else:
                normalized = original_document(tree, material['entrypoint'])
            # Use the selected entry's registered file closure, not every .tex
            # in an archive: unrelated manuscripts must not enter the request.
            graph, _, _ = self.registry._load_verified_source(version)
            additional = {}
            for node in graph['nodes']:
                if node['kind'] != 'source_file':
                    continue
                path = node['data']['path']
                source = normalized if path == material['entrypoint'] else original_document(tree, path)
                if source.sha256 != node['data']['sha256']:
                    raise ValueError('AI evidence differs from its registered source')
                if path != material['entrypoint']:
                    additional[path] = source
        except (OSError, ValueError, RuntimeError, KeyError):
            with task('Extracting AI content', total=len(AI_EXTRACTION_SKILLS), unit='tasks', retain=True) as failed:
                failed.outcome('failed', detail='AI extraction could not read its registered source')
            outcome('failed', detail='AI extraction could not read its registered source')
            return [], [{'error': 'AI extraction could not read its registered source'}]

        completed = {item['skill'] for item in previous.get('written', []) if item.get('proposal_sha256')}
        results, errors = [], []
        evidence = {path: source.sha256 for path, source in
                    {material['entrypoint']: normalized, **additional}.items()}
        for binding, old_snapshot in reusable:
            if binding['skill'] in completed:
                continue
            try:
                proposal = copy.deepcopy(read_bound_proposal(
                    self.registry, binding, {**material, 'source_snapshot_id': old_snapshot}))
                # A tool-only snapshot change may keep every evidence byte the
                # same. Rebind proposals only, never reviews, after checking the
                # full file closure and validating citations against this source.
                prior_sources = proposal.get('evidence_sources', [])
                if (len(prior_sources) != len(evidence)
                        or {row['path']: row['sha256'] for row in prior_sources} != evidence):
                    continue
                require_english(proposal)
                data = {k: proposal[k] for k in ('items', 'unresolved', 'paper') if k in proposal}
                validate_extraction(binding['skill'], data)
                validate_source_refs(normalized, material['entrypoint'], binding['skill'], data,
                                     additional_sources=additional)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            provenance = proposal['provenance']
            provenance.setdefault('source_rebindings', []).append({
                'snapshot_id': old_snapshot, 'proposal_path': binding['path'],
                'proposal_sha256': binding['proposal_sha256'],
                'reason': 'Identical source files; citations revalidated for the new snapshot'})
            ai_result = LLMResult(data=data, text=canonical(data), model=provenance['model'],
                                  usage=provenance['usage'], request_id=provenance.get('request_id'),
                                  attempts=0, cached=provenance['cached'], run_id=provenance['run_id'],
                                  prompt_sha256=provenance['prompt_sha256'])
            results.append(ExtractionResult(binding['skill'], data, proposal, ai_result))
            completed.add(binding['skill'])
        labels = dict(zip(AI_EXTRACTION_SKILLS, ('Theorems', 'Assumptions', 'Data', 'Research thoughts')))
        steps = tuple(ProgressStep(skill, label) for skill, label in labels.items())
        with task('Extracting AI content', total=len(steps), unit='tasks', kind='ai_plan', steps=steps, retain=True) as plan:
            for skill, label in labels.items():
                plan.step(skill, 'running')
                with task(label, kind='ai_step') as activity:
                    if skill in completed:
                        detail = 'Reusing source-bound proposal; no new request'
                        activity.outcome('reused', detail=detail)
                        plan.step(skill, 'reused', detail=detail)
                        plan.advance()
                        if on_skill_done:
                            on_skill_done()
                        continue
                    try:
                        result = extract(normalized, client, skill, projection_path=material['entrypoint'],
                                         additional_sources=additional)
                    except (OSError, ValueError, RuntimeError) as exc:
                        error = redact(str(exc), client.secrets)
                        errors.append({'skill': skill, 'error': error})
                        activity.outcome('failed', detail=error)
                        plan.step(skill, 'failed', detail=error)
                    else:
                        results.append(result)
                        state = 'reused' if result.ai_result.cached else 'finished'
                        detail = (f'{len(result.data.get("items", []))} items | '
                                  f'{len(result.data.get("unresolved", []))} unresolved | proposed')
                        activity.outcome(state, detail=detail)
                        plan.step(skill, state, detail=detail)
                        plan.advance()
                        if on_skill_done:
                            on_skill_done()
            if errors:
                plan.outcome('partial', detail='; '.join(f'{labels[item["skill"]]}: {item["error"]}' for item in errors))
        if errors:
            outcome('partial')
        return results, errors

    def _stage_ai(self, identity, previous, results, errors):
        source_version_id, snapshot_id = identity
        written = [item for item in previous.get('written', []) if item.get('proposal_sha256')]
        for result in results:
            skill, run_id = result.skill, result.ai_result.run_id
            proposal = {**result.proposal, 'source_version_id': source_version_id, 'snapshot_id': snapshot_id}
            try:
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', run_id):
                    raise ValueError('Invalid AI extraction run ID')
                target = self.path(f'machine/ai/proposals/{hash_text(source_version_id)}/{snapshot_id}/{skill}-{run_id}.json')
                immutable_json(target, proposal)
            except (OSError, ValueError):
                errors.append({'skill': skill, 'error': 'AI proposal could not be stored'})
            else:
                written.append({'skill': skill, 'path': target.relative_to(self.registry.root).as_posix(),
                                'run_id': run_id, 'proposal_sha256': hash_text(canonical(proposal))})
        return {'status': 'pending' if errors else 'complete', 'written': written, 'errors': errors}

    def _complete_ai(self, client, materials, digests, versions, previous, limits):
        from concurrent.futures import ThreadPoolExecutor, as_completed

        jobs = {}
        for digest in sorted(digests):
            material = materials[digest]
            if not material.get('processing_completed'):
                continue
            identity = material['source_version_id'], material['source_snapshot_id']
            if (versions[identity[0]]['snapshot_id'] == identity[1]
                    and not _ai_complete(previous.get(identity, {}))):
                jobs.setdefault(identity, material)

        reusable = {
            identity: [(binding, old_snapshot) for (source_id, old_snapshot), outcome in previous.items()
                       if source_id == identity[0] and old_snapshot != identity[1]
                       for binding in outcome.get('written', []) if binding.get('proposal_sha256')]
            for identity in jobs
        }

        def extract_one(identity):
            material = jobs[identity]
            name = next(iter(material.get('original_names', [])), material['archive_sha256'][:12])
            with task(name, kind='package') as package:
                result = self._extract_ai(client, material, previous.get(identity, {}), limits,
                                          versions[identity[0]], reusable[identity], on_skill_done=batch.advance)
                if result[1]:
                    package.outcome('partial')
                return result

        workers = min(client.config.max_parallel_packages, len(jobs))
        if not jobs:
            return
        with task('Extracting AI content', total=len(jobs) * len(AI_EXTRACTION_SKILLS),
                  unit='AI tasks', retain=True) as batch:
            if workers > 1:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    pending = {pool.submit(copy_context().run, extract_one, identity): identity for identity in jobs}
                    for future in as_completed(pending):
                        identity = pending.pop(future)
                        previous[identity] = self._stage_ai(identity, previous.get(identity, {}), *future.result())
                        if previous[identity]['status'] == 'pending':
                            batch.outcome('partial')
            else:
                for identity in jobs:
                    previous[identity] = self._stage_ai(identity, previous.get(identity, {}), *extract_one(identity))
                    if previous[identity]['status'] == 'pending':
                        batch.outcome('partial')

    def sync(self, *, dry_run=False, keep_inputs=False, progress=None):
        if dry_run:
            self.config()
            return {'status': 'planned', 'inputs': [p.name for p in self._inbox()],
                    'pending_claims': sum(1 for _ in self._pending_jobs())}
        with writer_lock(self.path('.qecgraph')):
            return self._run(self.config(), scan_inputs=True, rebuild=False, keep_inputs=keep_inputs,
                             progress=progress, ai_client=self._ai_client())

    def rebuild(self, *, include_inputs=False, keep_inputs=False, progress=None):
        self.config()
        with writer_lock(self.path('.qecgraph')):
            cfg = self.config()
            before = None
            ai_client = self._ai_client()
            if include_inputs:
                before = self._run(cfg, scan_inputs=True, rebuild=False, keep_inputs=keep_inputs, progress=progress,
                                   ai_client=ai_client)
            result = self._run(cfg, scan_inputs=False, rebuild=True, keep_inputs=True, progress=progress,
                               ai_client=ai_client)
        if before is not None:
            result['sync'] = before
            if before['status'] == 'partial_batch':
                result['status'] = 'partial_batch'
        return result

    def _inbox(self):
        for path in sorted(self.path('inputs').iterdir()):
            if (not path.name.startswith('.') and not path.name.endswith(('.part', '.tmp', '.crdownload', '.download'))
                    and (path.is_symlink() or not path.is_dir())):
                yield path

    def _cleanup_empty_claims(self):
        directory = self.path('inputs/.processing')
        if not directory.is_dir():
            return
        for job in directory.iterdir():
            if not JOB.fullmatch(job.name) or job.is_symlink() or not job.is_dir():
                continue
            try:
                if not any(job.iterdir()):
                    job.rmdir()
            except OSError:
                pass

    def _remove_claim(self, job):
        for name in ('payload', 'job.json', 'commit.json'):
            try:
                (job / name).unlink()
            except FileNotFoundError:
                pass
        try:
            job.rmdir()
        except FileNotFoundError:
            pass

    def _pending_jobs(self):
        parent = self.path('inputs/.processing')
        for job in sorted(parent.iterdir()):
            if JOB.fullmatch(job.name):
                job = self.path('inputs/.processing/' + job.name)
                try:
                    (job / 'payload').lstat()
                except (FileNotFoundError, NotADirectoryError):
                    continue
                meta = job / 'job.json'
                if meta.exists() and not meta.is_symlink():
                    yield job, read_json(meta)

    def _claim(self, path, keep_inputs):
        job = self.path('inputs/.processing/' + uuid.uuid4().hex)
        job.mkdir()
        meta = {'name': path.name, 'claimed_at': now(), 'keep_inputs': keep_inputs}
        atomic_json(job / 'job.json', meta)
        path.rename(job / 'payload')
        return job, meta

    def _restore(self, job, payload, name):
        return _move_input(payload, self.root / 'inputs' / _inbox_name(name))

    def _quarantined_inputs(self):
        directory = self.path('inputs/.quarantine')
        if not directory.exists():
            return []
        rows = []
        for path in sorted(directory.iterdir()):
            error = None
            try:
                digest = _hash_regular(path, 128 << 20)
            except PackageError as exc:
                if exc.status != 'limit_exceeded':
                    raise
                digest = None
                error = str(exc)
            except OSError as exc:
                # A foreign/linked entry may be unreadable; keep it visible
                # without turning the whole status command into a failure.
                digest = None
                error = str(exc)
            row = {'name': path.name, 'archive_sha256': digest}
            if error is not None:
                row['error'] = error
            rows.append(row)
        return rows

    def list_inputs(self):
        self.config()
        return {'status': 'ok', 'inputs': [path.name for path in self._inbox()],
                'pending_claims': sum(1 for _ in self._pending_jobs()),
                'quarantined_inputs': self._quarantined_inputs()}

    def move_quarantine(self, name, *, restore=False):
        name = _inbox_name(name)
        self.config()
        with writer_lock(self.path('.qecgraph')):
            directory = self.path('inputs/.quarantine')
            inbox = self.path('inputs/' + name)
            held = self.path('inputs/.quarantine/' + name)
            source, destination = (held, inbox) if restore else (inbox, held)
            if not source.exists():
                raise FileNotFoundError(errno.ENOENT, 'Input file is missing', source)
            if not source.is_file():
                raise ValueError(f'Expected an input file at {source}')
            directory.mkdir(exist_ok=True)
            if not _move_input(source, destination):
                raise InputDestinationExists(source, destination)
        return {'status': 'restored' if restore else 'quarantined', 'name': name}

    def _archive(self, job, meta, limit):
        directory = self.path('archive/blobs/sha256')
        fd, temporary = tempfile.mkstemp(prefix='.archive-', dir=directory)
        try:
            with os.fdopen(fd, 'wb') as output:
                digest = _hash_regular(job / 'payload', limit, copy_to=output)
                size = output.tell()
                blob = self.path('archive/blobs/sha256/' + digest)
                exists = blob.exists()
                if exists:
                    if _hash_regular(blob, limit) != digest:
                        raise ValueError('Archived blob does not match claimed input')
                else:
                    output.flush()
                    os.fsync(output.fileno())
            if not exists:
                os.replace(temporary, blob)
        finally:
            Path(temporary).unlink(missing_ok=True)
        receipt = {'id': job.name, 'archive_sha256': digest, 'size_bytes': size,
                   'original_name': meta['name'], 'claimed_at': meta['claimed_at']}
        immutable_json(self.path('archive/receipts/' + job.name + '.json'), receipt)
        return digest

    def _recover_source(self, parsed, *, raw, entry, state, prior, source_id, client, report):
        from .llm.client import BudgetExceeded, ResponseSchemaError
        from .llm.errors import LLMError
        from .llm.structure import recover_structure
        from .source.structure import StructureError, StructureIneligible, StructureNeedsReview, body_evidence, parsed_structure

        allowed = {'latex_parse_error', 'structural_scan_incomplete'}
        errors = {d['code'] for d in parsed['diagnostics'] if d['severity'] == 'error'}
        if not errors or not errors <= allowed or parsed.get('includes') or len(parsed['files']) != 1:
            report['structure_recovery'] = {'status': 'ineligible', 'reason': 'local_structure_or_dependency_error'}
            return None
        try:
            evidence = body_evidence(entry, raw)
            previous = state['versions'].get(source_id)
            if (previous and previous.get('structure_recovery')
                    and prior.get('source_snapshot_id') == previous['snapshot_id'] and prior.get('entrypoint') == entry):
                graph, _, _ = self.registry.source_graph_from_state(state, source_id, None, verify=True)
                return parsed_structure(evidence, graph['structure_recovery'])
            if client is None or not client.config.structure_fallback:
                reason = 'fallback_provider_unavailable' if client is None else 'fallback_disabled'
                report['structure_recovery'] = {'status': 'unavailable', 'reason': reason}
                return None
            with task('AI checking source structure', retain=True):
                return recover_structure(evidence, client)
        except StructureIneligible:
            reason = 'body_outside_supported_scope'
        except StructureNeedsReview:
            reason = 'provider_requested_review'
        except BudgetExceeded:
            reason = 'fallback_budget_exceeded'
        except (StructureError, ResponseSchemaError):
            reason = 'invalid_structure_plan'
        except LLMError:
            reason = 'fallback_provider_failed'
        report['structure_recovery'] = {'status': 'pending', 'reason': reason}
        return None

    @task('Extracting source structure', retain=True)
    def _prepare(self, cfg, state, digest, prior, reused, limits, *, captured, manifest_hashes, tool_identity, ai_client=None, progress=None):
        result = {'archive_sha256': digest, 'status': 'archived_only', 'processing_completed': False,
                  'semantic_status': 'not_extracted', 'processor': PROCESSOR}
        from .llm.normalize import NormalizationError

        normalization = None
        try:
            raw = _read_regular(self.path('archive/blobs/sha256/' + digest), 128 << 20)
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError('Archived source hash mismatch')
            phase('Unpacking source package')
            tree = unpack(raw, limits)
            del raw
            tree_hash = tree.digest
            extract_tree = tree
            result.update(format=tree.format, source_tree_hash=tree_hash)
            metadata = cfg.get('sources', {}).get(tree_hash, {})
            work_id = metadata.get('work_id', 'work:local:' + tree_hash)
            upstream = metadata.get('upstream_version')
            result.update(work_id=work_id, upstream_version=upstream)
            entry = cfg.get('entrypoints', {}).get(tree_hash)
            if entry not in tree.files:
                candidates = tree.entrypoints()
                if entry is None and len(candidates) == 1:
                    entry = candidates[0]
                elif entry is None and len(candidates) > 1 and (ai_client is not None or prior.get('normalization_id')):
                    try:
                        phase('Resolving TeX entry point')
                        if progress:
                            progress(0, 'Resolving TeX entry point')
                        extract_tree, normalization = self._resolve_normalization(ai_client, tree, prior)
                        entry = 'main.tex'
                    except NormalizationError as exc:
                        result.update(status='needs_entrypoint', entrypoint_candidates=candidates, reason=str(exc))
                        return self._keep_prior(result, prior)
                    except (OSError, ValueError, RuntimeError) as exc:
                        result.update(status='ai_failed', reason=str(exc).replace(str(self.root), '<workspace>'))
                        return self._keep_prior(result, prior)
                else:
                    result.update(status='needs_entrypoint', entrypoint_candidates=candidates)
                    return self._keep_prior(result, prior)
            source_id = 'source:local:' + hash_text(canonical([tree_hash, work_id, upstream]))
            build_key = (source_id, entry, normalization and normalization['normalization_sha256'])
            version = reused.get(build_key)
            result['entrypoint'] = entry
            saved = self.path('sources/' + tree_hash)
            preserve = not saved.exists()
            if not preserve:
                for path, original in sorted(tree.files.items()):
                    if not _matches_regular(self.path('sources/' + tree_hash + '/' + path), limits.member_bytes, original):
                        raise ValueError('Preserved source tree does not match archive')
            if preserve or version is None:
                with tempfile.TemporaryDirectory(prefix='ingest-', dir=self.path('.qecgraph')) as temporary:
                    temporary = Path(temporary)
                    if preserve:
                        expanded = temporary / 'expanded'
                        tree.materialize(expanded)
                        expanded.rename(saved)
                    if version is None:
                        project = temporary / 'project'
                        extract_tree.materialize(project)
                        def recover(parsed):
                            return self._recover_source(parsed, raw=tree.files[entry], entry=entry, state=state,
                                                        prior=prior, source_id=source_id, client=ai_client, report=result)

                        extraction = ingest(project / entry, 'source-' + source_id.rsplit(':', 1)[-1],
                                            temporary / 'store', project_root=project, strict=True,
                                            _tool_identity=tool_identity,
                                            _recover_source=recover if normalization is None else None)
                        if not extraction.get('published'):
                            result.update(status='parse_failed', reason='Structural extraction is partial; see diagnostics',
                                          diagnostics=extraction.get('diagnostics', []))
                            return self._keep_prior(result, prior)
                        version = self.registry.stage_source(
                            state, work_id, source_id, temporary / 'store', title=metadata.get('title'),
                            upstream_version=upstream, canonical_url=metadata.get('canonical_url'), replace_projection=True,
                            captured=captured, manifest_hashes=manifest_hashes)
            reused[build_key] = version
            if normalization is not None:
                result.update(normalization)
            if version.get('structure_recovery'):
                result['structure_recovery'] = version['structure_recovery']
            result.update(status='processing_completed', processing_completed=True, semantic_status='semantic_pending',
                          source_version_id=source_id, source_snapshot_id=version['snapshot_id'])
            return result
        except PackageError as exc:
            result.update(status=exc.status, reason=str(exc))
        except (OSError, ValueError, RuntimeError) as exc:
            result.update(status='parse_failed', reason=str(exc).replace(str(self.root), '<workspace>'))
        return self._keep_prior(result, prior)

    @staticmethod
    def _keep_prior(result, prior):
        outcome('partial', detail=result.get('reason', result['status']))
        if prior.get('source_version_id'):
            result.update(source_version_id=prior['source_version_id'], source_snapshot_id=prior['source_snapshot_id'],
                          retained_prior_extraction=True)
            for field in ('normalization_id', 'normalization_sha256', 'normalization_manifest_sha256'):
                if field in prior:
                    result[field] = prior[field]
        return result

    @staticmethod
    def _matching_extraction(state, material, fingerprint):
        if material.get('processing_completed') and material.get('config_fingerprint') == fingerprint:
            version = state['versions'].get(material['source_version_id'])
            if version and version['snapshot_id'] == material['source_snapshot_id']:
                return version
        return None

    @task('Archiving inbox packages', retain=True)
    def _archive_inbox(self, limit, keep_inputs):
        claims, rows = [], []
        for path in track(list(self._inbox()), 'Claiming inbox files', unit='files', detail=lambda p: p.name):
            if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                rows.append({'input': path.name, 'status': 'unsafe_input', 'input_consumed': False})
                continue
            self._claim(path, keep_inputs)
        for job, meta in track(list(self._pending_jobs()), 'Archiving inbox packages', unit='packages',
                               detail=lambda item: item[1]['name']):
            try:
                digest = self._archive(job, meta, limit)
            except (OSError, ValueError) as exc:
                rows.append({'input': meta['name'], 'status': 'archive_failed', 'reason': str(exc),
                             'input_consumed': False, 'restored': self._restore(job, job / 'payload', meta['name'])})
                continue
            claims.append((job, meta, digest))
        if rows:
            outcome('partial', detail=f'{len(rows)} inputs need attention')
        return claims, rows

    def _archived_digests(self):
        digests = {p.name for p in self.path('archive/blobs/sha256').iterdir() if HEX.fullmatch(p.name)}
        for receipt_path in self.path('archive/receipts').iterdir():
            if JOB.fullmatch(receipt_path.stem) and receipt_path.suffix == '.json':
                receipt = read_json(self.path('archive/receipts/' + receipt_path.name))
                digest = receipt['archive_sha256']
                if not HEX.fullmatch(digest):
                    raise ValueError('Invalid archive receipt hash')
                digests.add(digest)
        return digests

    def _archived_names(self):
        """Snapshot receipt filenames for views without using them as source IDs."""
        names = {}
        for path in self.path('archive/receipts').iterdir():
            if JOB.fullmatch(path.stem) and path.suffix == '.json':
                receipt = read_json(self.path('archive/receipts/' + path.name))
                if not isinstance(receipt, dict):
                    raise ValueError('Invalid archive receipt')
                digest, name = receipt.get('archive_sha256'), receipt.get('original_name')
                if (not isinstance(digest, str) or not HEX.fullmatch(digest)
                        or not isinstance(name, str) or not name or name in {'.', '..'}
                        or '\x00' in name or Path(name).name != name):
                    raise ValueError('Invalid archive receipt filename binding')
                names.setdefault(digest, set()).add(name)
        return {digest: sorted(values) for digest, values in names.items()}

    def _finish_claims(self, claims, materials, release, limit, keep_inputs):
        # Recovery replays the exact claim and verifies the published result.
        for job, meta, digest in claims:
            material = materials[digest]
            payload = job / 'payload'
            finished = material['processing_completed']
            decision = {'release_id': release, 'archive_sha256': digest, 'source_registered': True,
                        'outputs_committed': finished, 'keep_inputs': keep_inputs or meta['keep_inputs']}
            atomic_json(job / 'commit.json', decision)
            row = {'input': meta['name'], 'receipt_id': job.name, **material, **decision, 'input_consumed': False}
            try:
                if finished and not material['source_version_conflict'] and not decision['keep_inputs']:
                    if _hash_regular(payload, limit) != digest:
                        raise ValueError('Claim changed after archiving')
                    payload.unlink()
                    row['input_consumed'] = True
                    try:
                        self._remove_claim(job)
                    except OSError as exc:
                        row['cleanup_error'] = str(exc)
                        row['status'] = 'committed_pending_cleanup'
                else:
                    row['restored'] = self._restore(job, payload, meta['name'])
                    if not row['restored']:
                        row['retained_claim'] = job.name
            except (OSError, ValueError) as exc:
                row['cleanup_error'] = str(exc)
                row['status'] = 'committed_pending_cleanup' if finished else material['status']
            yield row

    def _write_operational_status(self, release, counts):
        self.path('machine/operational').mkdir(exist_ok=True)
        operational = self.path('machine/operational/status.json')
        prior_human = read_operational_status(operational).get('human')
        if not isinstance(prior_human, dict):
            prior_human = {}
        rendered = prior_human.get('rendered_release_id')
        if not isinstance(rendered, str) or not HEX.fullmatch(rendered):
            rendered = None
        human_status = 'current' if rendered == release and prior_human.get('status') == 'current' else 'human_stale'
        atomic_json(operational, {'observed_at': now(), 'release_id': release, 'counts': counts,
                    'human': {'status': human_status, 'target_release_id': release, 'rendered_release_id': rendered}})

    def _normalization_issues(self, state, limits):
        from .llm.artifacts import load_normalization

        for digest, material in state.get('materials', {}).items():
            if not material.get('normalization_id'):
                continue
            if not material.get('normalization_manifest_sha256'):
                yield {'code': 'normalization_unbound', 'archive_sha256': digest, 'severity': 'warning',
                       'message': 'Historical normalization is missing a bound source map'}
                continue
            try:
                raw = _read_regular(self.path('archive/blobs/sha256/' + digest), 128 << 20)
                if hashlib.sha256(raw).hexdigest() != digest:
                    raise ValueError('Archived source hash mismatch')
                source, _ = load_normalization(self.registry.root, material, tree=unpack(raw, limits))
                version = state['versions'][material['source_version_id']]
                if (version['snapshot_id'] == material['source_snapshot_id']
                        and not _matches_regular(self.path('machine/' + version['snapshot_path'] + '/sources/main.tex'),
                                                 limits.expanded_bytes, source.data)):
                    raise ValueError('Registered projection differs from the normalized TeX')
            except (OSError, ValueError, KeyError, TypeError) as exc:
                yield {'code': 'normalization_invalid', 'archive_sha256': digest, 'severity': 'error',
                       'message': str(exc)}

    def _publish_archive(self, cfg, digests, limits, *, rebuild, update, ai_client=None):
        from .llm.review import proposal_issues

        package_count = len(digests)
        package_stage = 'Checking archive packages' if rebuild else 'Checking inbox packages'
        update(1, f'{package_stage} 0/{package_count}' if package_count else 'Preparing workspace')
        with writer_lock(self.registry.root):
            from .workspace_query import check_machine_tree
            check_machine_tree(self.registry.root)
            state, old = self.registry._state_and_revision()
            materials = state.setdefault('materials', {})
            state['workspace_id'] = cfg['workspace_id']
            tool_identity = extraction_tool_identity() if digests else None
            def fingerprint(material):
                tree = material.get('source_tree_hash')
                return hash_text(canonical({
                    'processor': PROCESSOR, 'semantics': extraction_semantics(tool_identity or {}),
                    'limits': cfg.get('limits', {}),
                    'entrypoint': cfg.get('entrypoints', {}).get(tree),
                    'source': cfg.get('sources', {}).get(tree, {}),
                }))
            proposal_map = state.setdefault('generated_research', {})
            manifest_hashes, verified_spans, staged_proposals = {}, {}, {}

            def needs_proposals(version):
                active = proposal_map.get(version['id'])
                return (not active or active['source_snapshot_id'] != version['snapshot_id']
                        or active['processor'] != PROCESSOR)

            def generate(graph, snapshot, version):
                verified_spans[snapshot, version['snapshot_id']] = source_span_index(graph)
                return proposals(graph, version)

            reused = {}
            ai_results = {(material.get('source_version_id'), material.get('source_snapshot_id')):
                          (self._english_ai_outcome(material)
                           if ai_client is not None and ai_client.config.extract_proposals else material['ai_extraction'])
                          for material in materials.values() if material.get('ai_extraction')}
            if digests:
                for prior in materials.values():
                    version = self._matching_extraction(state, prior, fingerprint(prior))
                    if version is not None:
                        reused[(version['id'], prior['entrypoint'], prior.get('normalization_sha256'))] = version
            names = self._archived_names()
            for index, digest in enumerate(track(sorted(digests), package_stage, unit='packages',
                    detail=lambda digest: next(iter(names.get(digest, [])), digest[:12]), detail_kind='package'), start=1):
                prior = materials.get(digest, {})
                version = self._matching_extraction(state, prior, fingerprint(prior))
                if rebuild or version is None:
                    captured = []
                    materials[digest] = self._prepare(cfg, state, digest, prior, reused, limits,
                                                       captured=captured, manifest_hashes=manifest_hashes,
                                                       tool_identity=tool_identity, ai_client=ai_client, progress=update)
                    materials[digest]['config_fingerprint'] = fingerprint(materials[digest])
                    if captured:
                        graph, snapshot, registered = captured.pop()
                        if needs_proposals(registered):
                            identity = (registered['id'], registered['snapshot_id'])
                            staged_proposals[identity] = generate(graph, snapshot, registered)
                update(index + 1, f'{package_stage} {index}/{package_count}')
            for digest, original_names in names.items():
                if digest in materials:
                    materials[digest]['original_names'] = original_names
            if ai_client is not None and ai_client.config.extract_proposals and digests:
                update(package_count + 1, 'Extracting AI proposals')
                self._complete_ai(ai_client, materials, digests, state['versions'], ai_results, limits)
            for material in materials.values():
                identity = material.get('source_version_id'), material.get('source_snapshot_id')
                if identity in ai_results and material.get('processing_completed'):
                    material['ai_extraction'] = ai_results[identity]
            # Also backfill pre-existing materials on an empty sync. Human
            # rendering reads this fixed release, never live archive receipts.
            update(package_count + 1, 'Publishing workspace')
            with task('Publishing workspace', retain=True):
                # Explicit version metadata, never inferred from filenames.
                parsed_versions = {m['source_version_id'] for m in materials.values() if m.get('source_version_id')}
                generated = []
                for identifier in sorted(parsed_versions):
                    version = state['versions'][identifier]
                    if not needs_proposals(version):
                        continue
                    records = staged_proposals.pop((identifier, version['snapshot_id']), None)
                    if records is None:
                        graph, snapshot, _ = self.registry.source_graph_from_state(
                            state, identifier, old, verify=True, manifest_hashes=manifest_hashes)
                        records = generate(graph, snapshot, version)
                    generated.extend(records)
                    proposal_map[identifier] = {'source_snapshot_id': version['snapshot_id'], 'processor': PROCESSOR,
                                                'bindings': [{'id': r['id'], 'revision': r['revision']} for r in records],
                                                'code_parameters_mentions': len(records) - 1}
                if generated:
                    stage_records(self.registry, state, generated, verified_spans=verified_spans)
                collisions = {}
                for material in materials.values():
                    if material.get('upstream_version') and material.get('source_tree_hash'):
                        pair = (material['work_id'], material['upstream_version'])
                        collisions.setdefault(pair, set()).add(material['source_tree_hash'])
                for material in materials.values():
                    pair = (material.get('work_id'), material.get('upstream_version'))
                    material['source_version_conflict'] = len(collisions.get(pair, ())) > 1
                from .retrieval import stage_index
                phase('Building retrieval index')
                stage_index(self.registry, state, cfg.get('retrieval', {}), repair=rebuild)
                phase('Preparing candidate release')
                candidate = self.registry.prepare_publication(state)
                # This verifies every registered snapshot, including reused ones,
                # before publishing the pointer or consuming any input claims.
                phase('Validating candidate release')
                validation = self.registry.validate(candidate, check_live_lean=False, manifest_hashes=manifest_hashes)
                if (not validation['passed'] or any(issue['severity'] == 'error'
                                                    for issue in self._normalization_issues(state, limits))
                        or next(proposal_issues(self.registry, state), None) is not None):
                    raise ValueError('Candidate machine release failed validation; CURRENT was retained')
                if cfg != self.config():
                    raise ValueError('Workspace configuration changed while preparing; retry')
                if tool_identity is not None and tool_identity != extraction_tool_identity():
                    raise ValueError('Extraction tools changed while preparing; retry')
                phase('Publishing workspace')
                release = self.registry.publish_prepared(candidate)
        return old, release, materials, proposal_map

    def _run(self, cfg, *, scan_inputs, rebuild, keep_inputs, progress=None, ai_client=None):
        if not self.path('machine/CURRENT.json').is_file() and (
                self.path('machine/operational/status.json').exists()
                or self.path('.qecgraph/migration.json').exists()):
            raise ValueError('Published workspace is missing its release pointer')
        run_id = uuid.uuid4().hex
        limits = Limits(**cfg.get('limits', {}))
        for path in ('inputs/.processing', 'archive/blobs/sha256', 'archive/receipts', 'sources', 'machine'):
            self.path(path).mkdir(parents=True, exist_ok=True)
        self._cleanup_empty_claims()
        claims, rows = [], []
        if scan_inputs:
            phase('Archiving inbox packages')
            if progress:
                progress(0, 1, 'Archiving inbox packages')
            claims, rows = self._archive_inbox(limits.input_bytes, keep_inputs)
        claimed_digests = {digest for _, _, digest in claims}
        digests = set(claimed_digests)
        if rebuild:
            phase('Scanning the archive')
            if progress:
                progress(0, 1, 'Scanning the archive')
            digests.update(self._archived_digests())
        elif ai_client is not None and ai_client.config.extract_proposals and self.path('machine/CURRENT.json').is_file():
            state, _ = self.registry.read()
            digests.update(digest for digest, material in state.get('materials', {}).items()
                           if material.get('processing_completed') and not _ai_complete(self._english_ai_outcome(material)))

        # Archiving, one check per distinct package, publication and final CLI work.
        steps = len(digests) + 3

        def update(done, message):
            phase(message)
            if progress:
                progress(done, steps, message)

        old, release, materials, proposal_map = self._publish_archive(
            cfg, digests, limits, rebuild=rebuild, update=update, ai_client=ai_client)
        update(steps - 1, 'Finalizing workspace')
        rows.extend(self._finish_claims(claims, materials, release, limits.input_bytes, keep_inputs))
        rows.extend(materials[digest] for digest in sorted(digests - claimed_digests))
        counts = {'registered': len(materials), 'processed': sum(x['processing_completed'] for x in materials.values()),
                  'conflicting': sum(x['source_version_conflict'] for x in materials.values()),
                  'code_mention_proposals': sum(p['code_parameters_mentions'] for p in proposal_map.values())}
        warning = None
        try:
            self._write_operational_status(release, counts)
        except (OSError, ValueError) as exc:
            # The machine release is already published and inputs may already be
            # consumed; a derived-status write must not turn that into a failure.
            warning = 'operational status could not be written: ' + str(exc).replace(str(self.root), '<workspace>')
        partial = any(not r.get('processing_completed') or r.get('cleanup_error') or r.get('retained_claim')
                      or r.get('source_version_conflict') or r.get('ai_extraction', {}).get('errors') for r in rows)
        result = {'status': 'partial_batch' if partial else 'unchanged' if old == release else 'published',
                  'run_id': run_id, 'workspace_id': cfg['workspace_id'], 'previous_release_id': old,
                  'release_id': release, 'counts': counts, 'inputs': rows}
        if warning is not None:
            result['warning'] = warning
        return result

    def status(self):
        cfg = self.config()
        state, release = self.registry.read()
        quarantined = self._quarantined_inputs()
        digests = {row['archive_sha256'] for row in quarantined}
        materials = [{**material, 'quarantined': digest in digests}
                     for digest, material in state.get('materials', {}).items()]
        partial = any((not material.get('processing_completed') or material.get('source_version_conflict')
                       or material.get('ai_extraction', {}).get('errors'))
                      and not material['quarantined']
                      for material in materials)
        pending_inputs = sum(1 for _ in self._inbox())
        pending_claims = sum(1 for _ in self._pending_jobs())
        counts = {'registered': len(materials), 'processed': sum(bool(m.get('processing_completed')) for m in materials),
                  'conflicting': sum(bool(m.get('source_version_conflict')) for m in materials),
                  'pending_inputs': pending_inputs, 'pending_claims': pending_claims, 'quarantined': len(quarantined)}
        try:
            observed = read_operational_status(self.path('machine/operational/status.json'))
        except (OSError, ValueError):
            observed = {}
        human = {'status': 'unknown', 'target_release_id': release, 'rendered_release_id': None}
        view = observed.get('human')
        if (observed.get('release_id') == release and isinstance(view, dict) and view.get('target_release_id') == release
                and view.get('status') in ('current', 'human_stale')):
            rendered = view.get('rendered_release_id')
            if rendered is None or isinstance(rendered, str) and HEX.fullmatch(rendered):
                human['rendered_release_id'] = rendered
                human['status'] = 'current' if rendered == release and view.get('status') == 'current' else 'human_stale'
        return {'status': 'partial_batch' if partial else 'ok',
                'workspace_id': cfg['workspace_id'], 'release_id': release, 'materials': materials,
                'counts': counts, 'human': human,
                'quarantined_inputs': quarantined,
                'pending_inputs': pending_inputs, 'pending_claims': pending_claims}

    def validate(self, *, progress=None):
        from .llm.review import proposal_issues

        cfg = self.config()
        from .workspace_query import check_machine_tree
        check_machine_tree(self.registry.root)
        phase('Checking the current release')
        if progress:
            progress(1, 3, 'Checking the current release')
        state, fixed = self.registry.read()
        verified_spans = {}
        result = self.registry._validate_state(state, fixed, check_live_lean=False, verified_spans=verified_spans)
        issues = result.setdefault('issues', [])
        if progress:
            progress(2, 3, 'Verifying archived packages')
        for digest in track(state.get('materials', {}), 'Verifying archived packages', unit='packages',
                            detail=lambda value: value[:12]):
            try:
                if not HEX.fullmatch(digest):
                    raise ValueError('Invalid archive hash')
                if _hash_regular(self.path('archive/blobs/sha256/' + digest), 128 << 20) != digest:
                    raise ValueError('Archive hash mismatch')
            except (OSError, ValueError) as exc:
                issues.append({'code': 'archive_invalid', 'archive_sha256': digest, 'message': str(exc)})
        phase('Verifying source mappings and AI proposal bindings')
        issues.extend(self._normalization_issues(state, Limits(**cfg.get('limits', {}))))
        issues.extend(proposal_issues(self.registry, state))
        passed = result.get('passed', False) and not any(i.get('severity') != 'warning' for i in issues)
        return {**result, 'valid': passed, 'passed': passed, 'suggested_exit_code': 0 if passed else 2, 'status': 'ok' if passed else 'invalid',
                'workspace_id': cfg['workspace_id'], 'release_id': fixed}
