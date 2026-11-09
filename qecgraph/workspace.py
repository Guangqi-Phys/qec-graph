"""Local workspace, immutable archive receipts and one batch publication pointer."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
import tomllib
import uuid

from . import __version__
from .extraction import RULE_VERSION, proposals
from .research_store import load_records, stage_records, validate_sources
from .graph import canonical, hash_text, read_json
from .parser import PARSER_VERSION
from .registry import Registry
from .source_package import Limits, PackageError, read_bounded, unpack
from .store import ingest, validate_snapshot
from .transactions import atomic_bytes, atomic_json, immutable_json, writer_lock

CONFIG = 'qecgraph.toml'
FORMAT = 'qecgraph.workspace.v1'
PROCESSOR = f'qecgraph-{__version__}:archive-structure-v1:parser-{PARSER_VERSION}:{RULE_VERSION}'
HEX = re.compile(r'[0-9a-f]{64}')
JOB = re.compile(r'[0-9a-f]{32}')


def now():
    return datetime.now(timezone.utc).isoformat()


def _managed(root, relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Invalid managed path')
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f'Symlink is not allowed in managed path: {relative}')
    return current


def _read_regular(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError('Expected a regular unlinked source file')
        raw = read_bounded(stream, limit)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns) != (len(raw), after.st_mtime_ns):
            raise ValueError('Input changed while reading; retry after writing finishes')
    return raw


def locate(path=None, *, default=None):
    if path is not None:
        return Path(path).expanduser().resolve()
    start = Path.cwd()
    local = next((p for p in (start, *start.parents) if (p / CONFIG).is_file()), None)
    return local or (Path(default).expanduser().resolve() if default else start)


class Workspace:
    def __init__(self, root=None):
        self.root = locate(root)
        self.registry = Registry(self.path('machine'))

    def path(self, relative):
        return _managed(self.root, relative)

    def config(self):
        with self.path(CONFIG).open('rb') as source:
            cfg = tomllib.load(source)
        if cfg.get('format') != FORMAT or not isinstance(cfg.get('workspace_id'), str):
            raise ValueError('Invalid workspace configuration')
        if set(cfg) - {'format', 'workspace_id', 'limits', 'entrypoints', 'sources'}:
            raise ValueError('Unsupported workspace settings')
        for field in ('limits', 'entrypoints', 'sources'):
            if not isinstance(cfg.get(field, {}), dict):
                raise ValueError(f'{field} must be a table')
        try:
            Limits(**cfg.get('limits', {}))
        except TypeError as exc:
            raise ValueError('Unknown workspace limit') from exc
        for key, entry in cfg.get('entrypoints', {}).items():
            if not HEX.fullmatch(key) or not isinstance(entry, str) or not entry:
                raise ValueError('Entry overrides use source tree hashes and exact relative member names')
        for key, source in cfg.get('sources', {}).items():
            if (not HEX.fullmatch(key) or not isinstance(source, dict)
                    or set(source) - {'work_id', 'upstream_version', 'title'}
                    or not isinstance(source.get('work_id'), str) or not source['work_id'].strip()
                    or not all(isinstance(x, str) and x.strip() for x in source.values())):
                raise ValueError('Invalid explicit source metadata')
        return cfg

    def init(self, *, no_ingest=False, keep_inputs=False, progress=None):
        if progress:
            progress(0, 1, 'Initializing workspace')
        self.root.mkdir(parents=True, exist_ok=True)
        with writer_lock(self.path('.qecgraph')):
            target = self.path(CONFIG)
            if target.exists():
                cfg = self.config()
                return {'status': 'already_initialized', 'workspace_id': cfg['workspace_id'], 'next': 'qec-graph sync'}
            for path in ('inputs/.processing', 'archive/blobs/sha256', 'archive/receipts', 'sources', 'machine'):
                self.path(path).mkdir(parents=True, exist_ok=True)
            workspace_id = 'workspace:' + uuid.uuid4().hex
            atomic_bytes(target, f'format = "{FORMAT}"\nworkspace_id = "{workspace_id}"\n'.encode())
            return self._run(self.config(), scan_inputs=not no_ingest, rebuild=False,
                             keep_inputs=no_ingest or keep_inputs, progress=progress)

    def sync(self, *, dry_run=False, keep_inputs=False, progress=None):
        if dry_run:
            self.config()
            return {'status': 'planned', 'inputs': [p.name for p in self._inbox()],
                    'pending_claims': sum(1 for _ in self._jobs())}
        with writer_lock(self.path('.qecgraph')):
            return self._run(self.config(), scan_inputs=True, rebuild=False, keep_inputs=keep_inputs,
                             progress=progress)

    def rebuild(self, *, include_inputs=False, keep_inputs=False, progress=None):
        self.config()
        with writer_lock(self.path('.qecgraph')):
            cfg = self.config()
            before = None
            if include_inputs:
                before = self._run(cfg, scan_inputs=True, rebuild=False, keep_inputs=keep_inputs, progress=progress)
            result = self._run(cfg, scan_inputs=False, rebuild=True, keep_inputs=True, progress=progress)
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

    def _jobs(self):
        parent = self.path('inputs/.processing')
        for job in sorted(parent.iterdir()):
            if JOB.fullmatch(job.name):
                job = self.path('inputs/.processing/' + job.name)
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
        if Path(name).name != name or name in ('.', '..') or name.startswith('.'):
            raise ValueError('Invalid claim filename')
        original = self.root / 'inputs' / name
        # The destination creation is exclusive: an incoming replacement is never overwritten.
        if payload.is_symlink():
            try:
                original.symlink_to(os.readlink(payload))
            except FileExistsError:
                return False
        else:
            try:
                os.link(payload, original, follow_symlinks=False)
            except FileExistsError:
                if not os.path.samestat(payload.lstat(), original.lstat()):
                    return False
        payload.unlink()
        return True

    def _archive(self, job, meta, limit):
        raw = _read_regular(job / 'payload', limit)
        digest = hashlib.sha256(raw).hexdigest()
        blob = self.path('archive/blobs/sha256/' + digest)
        if blob.exists():
            if _read_regular(blob, max(limit, len(raw))) != raw:
                raise ValueError('Archived blob does not match claimed input')
        else:
            atomic_bytes(blob, raw)
        receipt = {'id': job.name, 'archive_sha256': digest, 'size_bytes': len(raw),
                   'original_name': meta['name'], 'claimed_at': meta['claimed_at']}
        immutable_json(self.path('archive/receipts/' + job.name + '.json'), receipt)
        return digest

    def _prepare(self, cfg, state, digest, prior, reused):
        limits = Limits(**cfg.get('limits', {}))
        result = {'archive_sha256': digest, 'status': 'archived_only', 'processing_completed': False,
                  'semantic_status': 'not_extracted', 'processor': PROCESSOR}
        try:
            raw = _read_regular(self.path('archive/blobs/sha256/' + digest), 128 << 20)
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError('Archived source hash mismatch')
            tree = unpack(raw, limits)
            tree_hash = tree.digest
            result.update(format=tree.format, source_tree_hash=tree_hash)
            metadata = cfg.get('sources', {}).get(tree_hash, {})
            work_id = metadata.get('work_id', 'work:local:' + tree_hash)
            upstream = metadata.get('upstream_version')
            result.update(work_id=work_id, upstream_version=upstream)
            candidates = tree.entrypoints()
            entry = cfg.get('entrypoints', {}).get(tree_hash)
            if entry is None and len(candidates) == 1:
                entry = candidates[0]
            if entry not in tree.files:
                result.update(status='needs_entrypoint', entrypoint_candidates=candidates)
                return self._keep_prior(result, prior)
            source_id = 'source:local:' + hash_text(canonical([tree_hash, work_id, upstream]))
            build_key = (source_id, entry)
            result['entrypoint'] = entry
            with tempfile.TemporaryDirectory(prefix='ingest-', dir=self.path('.qecgraph')) as temporary:
                temporary = Path(temporary)
                saved = self.path('sources/' + tree_hash)
                if not saved.exists():
                    expanded = temporary / 'expanded'
                    tree.materialize(expanded)
                    expanded.rename(saved)
                else:
                    for member in tree.manifest:
                        raw_member = _read_regular(self.path('sources/' + tree_hash + '/' + member['path']),
                                                   limits.member_bytes)
                        if hashlib.sha256(raw_member).hexdigest() != member['sha256']:
                            raise ValueError('Preserved source tree does not match archive')
                if build_key not in reused:
                    tree.materialize(temporary / 'project')
                    extraction = ingest(temporary / 'project' / entry, 'source-' + source_id.rsplit(':', 1)[-1],
                                        temporary / 'store',
                                        project_root=temporary / 'project', strict=True)
                    if not extraction.get('published'):
                        result.update(status='parse_failed', reason='Structural extraction is partial; see diagnostics',
                                      diagnostics=extraction.get('diagnostics', []))
                        return self._keep_prior(result, prior)
                    reused[build_key] = self.registry.stage_source(
                        state, work_id, source_id, temporary / 'store', title=metadata.get('title'),
                        upstream_version=upstream, replace_projection=True)
            version = reused[build_key]
            validate_snapshot(self.path('machine/' + version['snapshot_path']), version['snapshot_id'])
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
        if prior.get('source_version_id'):
            result.update(source_version_id=prior['source_version_id'], source_snapshot_id=prior['source_snapshot_id'],
                          retained_prior_extraction=True)
        return result

    def _run(self, cfg, *, scan_inputs, rebuild, keep_inputs, progress=None):
        run_id = uuid.uuid4().hex
        digests, rows, claims = set(), [], []
        if scan_inputs:
            if progress:
                progress(0, 1, 'Archiving inbox packages')
            for path in self._inbox():
                if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                    rows.append({'input': path.name, 'status': 'unsafe_input', 'input_consumed': False})
                    continue
                self._claim(path, keep_inputs)
            for job, meta in self._jobs():
                payload = job / 'payload'
                if not payload.exists() and not payload.is_symlink():
                    continue
                try:
                    digest = self._archive(job, meta, Limits(**cfg.get('limits', {})).input_bytes)
                except (OSError, ValueError) as exc:
                    rows.append({'input': meta['name'], 'status': 'archive_failed', 'reason': str(exc),
                                 'input_consumed': False, 'restored': self._restore(job, payload, meta['name'])})
                    continue
                digests.add(digest)
                claims.append((job, meta, digest))
        if rebuild:
            if progress:
                progress(0, 1, 'Scanning the archive')
            digests.update(p.name for p in self.path('archive/blobs/sha256').iterdir() if HEX.fullmatch(p.name))
            for receipt_path in self.path('archive/receipts').iterdir():
                if JOB.fullmatch(receipt_path.stem) and receipt_path.suffix == '.json':
                    receipt = read_json(self.path('archive/receipts/' + receipt_path.name))
                    digest = receipt['archive_sha256']
                    if not HEX.fullmatch(digest):
                        raise ValueError('Invalid archive receipt hash')
                    digests.add(digest)

        package_count = len(digests)
        # Stages are archiving, one check per distinct package, publication and final CLI work.
        steps = package_count + 3
        package_stage = 'Checking archive packages' if rebuild else 'Checking inbox packages'
        if progress:
            progress(1, steps, f'{package_stage} 0/{package_count}' if package_count else 'Preparing workspace')
        with writer_lock(self.registry.root):
            from .workspace_query import check_machine_tree
            check_machine_tree(self.registry.root)
            old = self.registry.read()[1] if self.path('machine/CURRENT.json').exists() else None
            state = self.registry._state_or_empty()
            previous = copy.deepcopy(state.get('materials', {}))
            materials = state.setdefault('materials', {})
            state['workspace_id'] = cfg['workspace_id']
            fingerprint = hash_text(canonical([PROCESSOR, cfg]))
            reused = {}
            if not rebuild:
                for prior in previous.values():
                    if prior.get('processing_completed') and prior.get('config_fingerprint') == fingerprint:
                        version = state['versions'].get(prior['source_version_id'])
                        if version and version['snapshot_id'] == prior['source_snapshot_id']:
                            reused[(prior['source_version_id'], prior['entrypoint'])] = version
            for index, digest in enumerate(sorted(digests), start=1):
                prior = previous.get(digest, {})
                if (not rebuild and prior.get('processing_completed') and prior.get('config_fingerprint') == fingerprint):
                    snapshot = self.path('machine/source_snapshots/' + prior['source_snapshot_id'])
                    validate_snapshot(snapshot, prior['source_snapshot_id'])
                else:
                    materials[digest] = self._prepare(cfg, state, digest, prior, reused)
                    materials[digest]['config_fingerprint'] = fingerprint
                if progress:
                    progress(index + 1, steps, f'{package_stage} {index}/{package_count}')
            if progress:
                progress(steps - 2, steps, 'Publishing workspace')
            # Explicit version metadata, never inferred from filenames.
            parsed_versions = {m['source_version_id'] for m in materials.values() if m.get('source_version_id')}
            proposal_map = state.setdefault('generated_research', {})
            generated = []
            for identifier in sorted(parsed_versions):
                version = state['versions'][identifier]
                active = proposal_map.get(identifier)
                if active and active['source_snapshot_id'] == version['snapshot_id'] and active['processor'] == PROCESSOR:
                    continue
                snapshot = self.path('machine/' + version['snapshot_path'])
                graph = read_json(snapshot / 'graph.json')
                records = proposals(graph, version)
                generated.extend(records)
                proposal_map[identifier] = {'source_snapshot_id': version['snapshot_id'], 'processor': PROCESSOR,
                                            'bindings': [{'id': r['id'], 'revision': r['revision']} for r in records],
                                            'code_mentions': len(records) - 1}
            if generated:
                stage_records(self.registry, state, generated)
            collisions = {}
            for material in materials.values():
                if material.get('upstream_version') and material.get('source_tree_hash'):
                    pair = (material['work_id'], material['upstream_version'])
                    collisions.setdefault(pair, set()).add(material['source_tree_hash'])
            for material in materials.values():
                pair = (material.get('work_id'), material.get('upstream_version'))
                material['source_version_conflict'] = len(collisions.get(pair, ())) > 1
            candidate = self.registry.prepare_publication(state)
            validation = self.registry.validate(candidate, check_live_lean=False)
            if not validation['passed']:
                raise ValueError('Candidate machine release failed validation; CURRENT was retained')
            if cfg != self.config():
                raise ValueError('Workspace configuration changed while preparing; retry')
            release = self.registry.publish_prepared(candidate)
        if progress:
            progress(steps - 1, steps, 'Finalizing workspace')
        # Recovery after a killed process replays the exact claim and verifies the published result.
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
                    raw = _read_regular(payload, Limits(**cfg.get('limits', {})).input_bytes)
                    if hashlib.sha256(raw).hexdigest() != digest:
                        raise ValueError('Claim changed after archiving')
                    payload.unlink()
                    row['input_consumed'] = True
                else:
                    row['restored'] = self._restore(job, payload, meta['name'])
                    if not row['restored']:
                        row['retained_claim'] = job.name
            except (OSError, ValueError) as exc:
                row['cleanup_error'] = str(exc)
                row['status'] = 'committed_pending_cleanup' if finished else material['status']
            rows.append(row)
        if rebuild:
            rows.extend(materials[digest] for digest in sorted(digests))
        counts = {'registered': len(materials), 'processed': sum(x['processing_completed'] for x in materials.values()),
                  'conflicting': sum(x['source_version_conflict'] for x in materials.values()),
                  'code_mention_proposals': sum(p['code_mentions'] for p in proposal_map.values())}
        self.path('machine/operational').mkdir(exist_ok=True)
        operational = self.path('machine/operational/status.json')
        earlier = read_json(operational) if operational.is_file() else {}
        prior_human = earlier.get('human') or {}
        rendered = prior_human.get('rendered_release_id')
        human_status = 'current' if rendered == release and prior_human.get('status') == 'current' else 'human_stale'
        atomic_json(operational, {'observed_at': now(), 'release_id': release, 'counts': counts,
                    'human': {'status': human_status, 'target_release_id': release, 'rendered_release_id': rendered}})
        partial = any(not r.get('processing_completed') or r.get('cleanup_error') or r.get('retained_claim')
                      or r.get('source_version_conflict') for r in rows)
        return {'status': 'partial_batch' if partial else 'unchanged' if old == release else 'published',
                'run_id': run_id, 'workspace_id': cfg['workspace_id'], 'previous_release_id': old,
                'release_id': release, 'counts': counts, 'inputs': rows}

    def status(self):
        cfg = self.config()
        state, release = self.registry.read()
        return {'status': 'ok', 'workspace_id': cfg['workspace_id'], 'release_id': release,
                'materials': list(state.get('materials', {}).values()),
                'pending_inputs': len(list(self._inbox())), 'pending_claims': sum(
                    (job / 'payload').exists() for job, _ in self._jobs())}

    def validate(self, *, progress=None):
        cfg = self.config()
        from .workspace_query import check_machine_tree
        check_machine_tree(self.registry.root)
        if progress:
            progress(1, 3, 'Checking the current release')
        state, fixed = self.registry.read()
        result = self.registry._validate_state(state, fixed, check_live_lean=False)
        issues = result.setdefault('issues', [])
        from .research import validate_bundle
        records = load_records(self.registry, state)
        validate_bundle(records)
        validate_sources(self.registry, state, records)
        if progress:
            progress(2, 3, 'Verifying archived packages')
        for digest in state.get('materials', {}):
            try:
                if not HEX.fullmatch(digest):
                    raise ValueError('Invalid archive hash')
                raw = _read_regular(self.path('archive/blobs/sha256/' + digest), 128 << 20)
                if hashlib.sha256(raw).hexdigest() != digest:
                    raise ValueError('Archive hash mismatch')
            except (OSError, ValueError) as exc:
                issues.append({'code': 'archive_invalid', 'archive_sha256': digest, 'message': str(exc)})
        passed = result.get('passed', False) and not any(i.get('severity') != 'warning' for i in issues)
        return {**result, 'valid': passed, 'passed': passed, 'suggested_exit_code': 0 if passed else 2, 'status': 'ok' if passed else 'invalid',
                'workspace_id': cfg['workspace_id'], 'release_id': fixed}
