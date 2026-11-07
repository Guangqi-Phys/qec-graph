"""Bind actual Lean artifacts to revisioned records without claiming semantic review."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import quote

from .graph import LEAN_DEPENDENCIES, canonical, hash_text, read_json, strict_json_loads
from .lean import audit_export, producer_manifest, source_manifest
from .records import RECORD_SCHEMA, prepare_record
from .registry import Registry
from .store import safe_relative, validate_snapshot
from .transactions import writer_lock


def declaration_id(project_id, name):
    return 'lean:' + project_id + ':' + quote(name, safe='._-')


def _build_id(raw_report):
    # One execution's immutable report, not a mathematical object's identity.
    return 'lean-build:' + hashlib.sha256(raw_report).hexdigest()


def _verify_artifacts(report, load):
    if report.get('schema_version') != 'qecgraph.lean-build.v1' or report.get('status') != 'validated_build':
        raise ValueError('Only an actual validated build/export/audit may be imported; build-only or rejected logs are insufficient')
    if report.get('build_status') != 'build_passed' or report.get('declaration_export') != 'exported' or report.get('axiom_audit') != 'allowed':
        raise ValueError('Build/export/axiom states are incomplete')
    files = {'report.json': None}
    commands = {item['name']: item for item in report['commands']}
    if any(name not in commands or commands[name]['exit_code'] != 0 for name in ('build', 'export', 'lean_version', 'lake_version')):
        raise ValueError('Actual build/export command results are missing or failed')
    for item in report['commands']:
        for key in ('stdout', 'stderr'):
            raw = load(item[key])
            expected = item.get(key + '_sha256')
            if (expected is not None or 'tool_binaries' in report) and hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError('Lean command log hash mismatch: ' + item[key])
            files[item[key]] = raw
    for ref_key in ('export_ref', 'audit_ref'):
        ref = report[ref_key]
        if ref['path'] != ('export.json' if ref_key == 'export_ref' else 'audit.json'):
            raise ValueError('Unknown Lean evidence artifact layout')
        raw = load(ref['path'])
        if hashlib.sha256(raw).hexdigest() != ref['sha256']:
            raise ValueError('Lean artifact hash mismatch: ' + ref_key)
        files[ref['path']] = raw
    export = strict_json_loads(files[report['export_ref']['path']].decode('utf-8'))
    audit = strict_json_loads(files[report['audit_ref']['path']].decode('utf-8'))
    raw_stdout = files[commands['export']['stdout']]
    if hashlib.sha256(raw_stdout).hexdigest() != report['export_ref']['raw_stdout_sha256'] or strict_json_loads(raw_stdout.decode('utf-8')) != export:
        raise ValueError('Lean export does not match the actual command stdout')
    for relative, digest in report['input_manifest'].items():
        raw = load('inputs/' + relative)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('Archived Lean input changed: ' + relative)
        files['inputs/' + relative] = raw
    policy = strict_json_loads(files['inputs/axiom-policy.json'].decode('utf-8'))
    targets = strict_json_loads(files['inputs/targets.json'].decode('utf-8'))
    if hashlib.sha256(files['inputs/axiom-policy.json']).hexdigest() != report['axiom_policy_sha256']:
        raise ValueError('Axiom policy binding mismatch')
    actual_audit = audit_export(export, policy, targets)
    if actual_audit != audit or audit['status'] != 'allowed' or audit['declaration_bindings'] != report['declaration_bindings']:
        raise ValueError('Lean audit is not bound to this exact export and policy')
    return export, audit, files


def _current_reasons(report, project):
    reasons = []
    if project is None:
        reasons.append({'code': 'missing_project_inputs'})
    else:
        try:
            if source_manifest(Path(project).resolve()) != report['input_manifest']:
                reasons.append({'code': 'lean_inputs_changed'})
        except (OSError, ValueError) as exc:
            reasons.append({'code': 'missing_project_inputs', 'message': str(exc)})
    if report.get('producer_inputs') != producer_manifest():
        reasons.append({'code': 'lean_producer_changed'})
    try:
        binaries = report.get('tool_binaries')
        if binaries is None:
            executable = Path(next(item for item in report['commands'] if item['name'] == 'lake_version')['command'][0])
            binaries = {'lake': executable, 'lean': executable.parent / 'lean'}
        for name in ('lake', 'lean'):
            path = Path(binaries[name])
            if hashlib.sha256(path.read_bytes()).hexdigest() != report[name + '_binary_sha256']:
                reasons.append({'code': 'lean_tool_binary_changed', 'tool': name})
    except (OSError, KeyError, StopIteration) as exc:
        reasons.append({'code': 'missing_lean_toolchain', 'message': str(exc)})
    return reasons


def inspect_build(report_path, project=None):
    report_path = Path(report_path).resolve()
    raw_report = report_path.read_bytes()
    report = strict_json_loads(raw_report.decode('utf-8'))
    export, audit, artifacts = _verify_artifacts(report, lambda relative: safe_relative(report_path.parent, relative).read_bytes())
    artifacts['report.json'] = raw_report
    reasons = _current_reasons(report, project)
    return {'report': report, 'export': export, 'audit': audit, 'artifacts': artifacts,
            'build_id': _build_id(artifacts['report.json']), 'current': not reasons, 'reasons': reasons}


def _record(identifier, kind, revision, data, *, refs=(), assets=(), provenance=None, evidence_ids=()):
    return prepare_record({'schema_version': RECORD_SCHEMA, 'id': identifier, 'kind': kind, 'revision': revision,
                           'title': data.get('declaration_name', identifier), 'data': data, 'refs': list(refs),
                           'assets': list(assets), 'provenance': provenance or {}, 'review': {'status': 'proposed'},
                           'evidence_ids': list(evidence_ids)})


def import_build(corpus, report_path, *, project_id, project=None, mappings=None, historical=False):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', project_id):
        raise ValueError('Lean project-id must be a stable safe namespace')
    if mappings is not None and (not isinstance(mappings, list) or not all(isinstance(item, dict) for item in mappings)):
        raise ValueError('Lean mappings must be a list of explicit mapping objects')
    inspected = inspect_build(report_path, project)
    if not historical and not inspected['current']:
        raise ValueError('Lean build is stale or inputs unavailable: ' + canonical(inspected['reasons']))
    report, export, audit = inspected['report'], inspected['export'], inspected['audit']
    build_id = inspected['build_id']
    revision = build_id.removeprefix('lean-build:')
    evidence_id = 'evidence:' + build_id
    registry = Registry(corpus)
    with writer_lock(registry.root):
        state = registry._state_or_empty()
        assets = {}
        for relative, raw in inspected['artifacts'].items():
            media = 'application/json' if relative.endswith('.json') else 'text/plain'
            assets[relative] = registry._put_asset(raw, media, 'lean-build/' + revision + '/' + relative)
        common = {'method': 'actual_lean_environment_export', 'lean_project_id': project_id, 'build_id': build_id,
                  'export_asset_uri': assets[report['export_ref']['path']]['uri'],
                  'field_ownership': 'Actual type/dependencies belong to the immutable Lean export, not handwritten metadata'}
        evidence = _record(evidence_id, 'evidence', revision, {
            'evidence_kind': 'lean_build', 'method': 'Lean build plus actual checked-environment export', 'inputs': [],
            'checker': report['lean_version'], 'outputs': [assets[key]['uri'] for key in ('report.json', 'export.json', 'audit.json')],
            'scope': 'Exact exported formal declarations; paper/claim correspondence has not been reviewed',
            'limitations': ['Axioms are restricted to the recorded policy', 'No automatic Bool/ZMod bridge or distance verification'],
            'status': 'build_passed', 'axiom_policy_status': 'allowed', 'semantic_review': 'not_reviewed',
            'input_manifest': report['input_manifest'], 'project_commit': report['git']['project_commit'],
            'input_revision': hash_text(canonical(report['input_manifest'])),
            'project_worktree_dirty': report['git'].get('project_worktree_dirty'), 'build_id': build_id,
            'axioms_observed': audit['axioms_observed'], 'mathlib_commit': report['mathlib_commit'],
            'mathlib_status': report['mathlib_status']}, assets=list(assets.values()), provenance=common)
        records = [evidence]
        declarations = {item['name']: item for item in export['declarations']}
        names = set(declarations)
        for declaration in declarations.values():
            for field in ('type_constants_direct', 'proof_constants_direct', 'type_constants_transitive', 'proof_constants_transitive'):
                names.update(declaration[field])
        for name in sorted(names):
            declaration = declarations.get(name)
            data = {'declaration_name': name, 'module': None, 'type': None, 'type_expr_sha256': None,
                    'build_evidence_id': evidence_id, 'build_id': build_id, 'proof_progress': 'referenced_name_only',
                    'axiom_audit': 'not_exported', 'semantic_review': 'not_reviewed',
                    'unknown_reason': 'Only a referenced constant name is exported; its complete type was not selected'}
            refs = [{'relation': 'has_build_evidence', 'target': evidence_id, 'revision': revision, 'status': 'observed'}]
            record_assets = []
            if declaration:
                data.update({key: declaration[key] for key in ('module', 'type', 'kind', 'source_range', 'imports', 'type_expr',
                            'type_constants_direct', 'proof_constants_direct', 'type_constants_transitive', 'proof_constants_transitive', 'axioms_transitive')})
                data['declaration_kind'] = data.pop('kind')
                data.update(type_expr_sha256=audit['declaration_bindings'][name]['type_expr_sha256'],
                            proof_progress='build_passed', axiom_audit='allowed')
                data.pop('unknown_reason')
                for field, relation in [('type_constants_direct', 'lean_type_depends_on'), ('proof_constants_direct', 'lean_proof_depends_on'),
                                        ('type_constants_transitive', 'lean_type_depends_on_transitive'), ('proof_constants_transitive', 'lean_proof_depends_on_transitive')]:
                    refs.extend({'relation': relation, 'target': declaration_id(project_id, dependency), 'revision': revision,
                                 'status': 'observed', 'evidence': {'method': 'actual_Lean_constant', 'scope': field,
                                                                'filtered': False, 'build_id': build_id}}
                                for dependency in declaration[field])
                record_assets = [assets['export.json']]
                source_path = declaration['module'].replace('.', '/') + '.lean'
                if source_path in report['input_manifest'] and declaration['source_range']:
                    source_asset = assets['inputs/' + source_path]
                    record_assets.append(source_asset)
                    data['source_locator'] = {'path': source_path, 'file_sha256': report['input_manifest'][source_path],
                                               'asset_uri': source_asset['uri'], 'source_kind': 'lean', 'build_id': build_id,
                                               **declaration['source_range']}
            records.append(_record(declaration_id(project_id, name), 'lean_declaration', revision, data,
                                   refs=refs, assets=record_assets, provenance=common, evidence_ids=[evidence_id]))
        mapping_records = []
        for mapping in mappings or []:
            if mapping.get('schema_version') != 'qecgraph.lean-mapping.v1':
                raise ValueError('Unknown Lean mapping schema')
            claim = registry.record_from_state(state, mapping['claim_id'], mapping['claim_revision'])
            if claim['kind'] != 'claim' or claim['content_sha256'] != mapping['expected_claim_content_sha256']:
                raise ValueError('Lean mapping claim revision/hash mismatch')
            if state['records'][claim['id']]['current_revision'] != claim['revision']:
                raise ValueError('Lean mapping targets a stale claim revision; inspect and propose the current correspondence')
            declaration = declarations.get(mapping['declaration'])
            if declaration is None or declaration['kind'] != 'theorem':
                raise ValueError('Lean mapping requires an actually exported theorem')
            actual_hash = audit['declaration_bindings'][mapping['declaration']]['type_expr_sha256']
            if actual_hash != mapping['expected_type_expr_sha256']:
                raise ValueError('Lean mapping type mismatch; name existence cannot establish correspondence')
            if mapping.get('semantic_review', 'not_reviewed') != 'not_reviewed':
                raise ValueError('Importer cannot grant semantic review; use an independent bound human review')
            source_refs = []
            for source in mapping.get('source_refs', []):
                from .query import resolve
                from .validators import validate_endpoint
                graph, snapshot, version = registry.source_graph(source['source_version_id'])
                validate_snapshot(snapshot, expected_snapshot_id=version['snapshot_id'])
                node_id = resolve(graph, source['selector'])
                node = next(node for node in graph['nodes'] if node['id'] == node_id)
                validate_endpoint('formalization', node['kind'], 'maps_source_occurrence')
                if node['origin'] != 'parser' or not node.get('source') or node['content_sha256'] != source['expected_content_sha256']:
                    raise ValueError('Lean mapping original statement hash mismatch')
                source_refs.append({**source, 'node_id': node_id, 'snapshot_id': version['snapshot_id']})
            identifier = mapping['id']
            data = {'claim_id': claim['id'], 'claim_revision': claim['revision'], 'claim_content_sha256': claim['content_sha256'],
                    'lean_declaration': mapping['declaration'], 'declaration_id': declaration_id(project_id, mapping['declaration']),
                    'build_evidence_id': evidence_id, 'build_id': build_id, 'semantic_review': 'not_reviewed',
                    'proof_progress': 'build_passed', 'axiom_audit': 'allowed', 'type_expr_sha256': actual_hash,
                    'lean_project_id': project_id, 'project_commit': report['git']['project_commit'], 'module': declaration['module'],
                    'statement_relation': mapping.get('statement_relation', 'not_established'),
                    'extra_assumptions': mapping.get('extra_assumptions', []), 'notation_map': mapping.get('notation_map', {}),
                    'source_refs': source_refs, 'definition_refs': mapping.get('definition_refs', []),
                    'planned_dependencies': mapping.get('planned_dependencies', [])}
            refs = [{'relation': 'formalizes', 'target': claim['id'], 'revision': claim['revision'], 'status': 'candidate'},
                    {'relation': 'maps_declaration', 'target': data['declaration_id'], 'revision': revision, 'status': 'observed'},
                    {'relation': 'has_build_evidence', 'target': evidence_id, 'revision': revision, 'status': 'observed'}]
            mapped = _record(identifier, 'formalization', revision, data, refs=refs, provenance=common, evidence_ids=[evidence_id])
            records.append(mapped)
            mapping_records.append(identifier)
        for record in records:
            registry._put_record(state, record)
        if not historical:
            reasons = _current_reasons(report, project)
            if reasons:
                raise ValueError('Lean build inputs changed during import: ' + canonical(reasons))
        state.setdefault('lean_projects', {})[project_id] = {'project_id': project_id, 'root': str(Path(project).resolve()) if project else None,
            'current_build_id': build_id, 'evidence_id': evidence_id, 'historical': bool(historical), 'artifacts': assets}
        published = registry._publish(state)
    return {'registry_revision': published, 'build_id': build_id, 'evidence_id': evidence_id, 'imported_records': len(records),
            'full_declarations': len(declarations), 'referenced_name_only': len(names) - len(declarations),
            'formalization_ids': mapping_records, 'freshness': 'historical' if historical else 'current', 'semantic_review': 'not_reviewed'}


def lean_record_states(registry, state, records, reviews):
    """Recompute freshness by reading pinned artifacts/explicit project inputs; never execute Lean."""
    projects = {}
    for project_id, entry in state.get('lean_projects', {}).items():
        reasons, exported, observed_names, report = [], {}, set(), None
        try:
            assets = entry['artifacts']
            raw_report = registry.asset_bytes(assets['report.json']['uri'])
            report = strict_json_loads(raw_report.decode('utf-8'))
            export, audit, _ = _verify_artifacts(report, lambda relative: registry.asset_bytes(assets[relative]['uri']))
            if _build_id(raw_report) != entry['current_build_id']:
                raise ValueError('Registered Lean build identity mismatch')
            reasons.extend(_current_reasons(report, entry['root']))
            if entry['historical']:
                reasons.append({'code': 'imported_as_history'})
            exported = {declaration['name']: declaration for declaration in export['declarations']}
            observed_names = set(exported)
            for declaration in exported.values():
                for field in ('type_constants_direct', 'proof_constants_direct', 'type_constants_transitive', 'proof_constants_transitive'):
                    observed_names.update(declaration[field])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            reasons.append({'code': 'lean_artifact_unavailable', 'message': str(exc)})
        projects[project_id] = {'entry': entry, 'reasons': reasons, 'declarations': exported,
                                'observed_names': observed_names, 'report': report}
    result = {}
    for identifier, record in records.items():
        if record['provenance'].get('method') != 'actual_lean_environment_export' and record['kind'] != 'lean_declaration' and not (
                record['kind'] == 'evidence' and record['data'].get('evidence_kind') == 'lean_build'):
            continue
        data = record['data']
        project_id = record['provenance'].get('lean_project_id')
        project = projects.get(project_id)
        reasons = list(project['reasons']) if project else [{'code': 'unbound_lean_project'}]
        if project:
            entry = project['entry']
            if record['provenance'].get('build_id') != entry['current_build_id'] or data.get('build_id') != entry['current_build_id']:
                reasons.append({'code': 'not_the_selected_lean_build'})
            if record['kind'] == 'lean_declaration':
                name = data['declaration_name']
                if identifier != declaration_id(project_id, name):
                    reasons.append({'code': 'lean_declaration_identity_mismatch'})
                actual = project['declarations'].get(name)
                if actual:
                    fields = ('module', 'type', 'type_expr', 'imports', 'source_range', 'type_constants_direct', 'proof_constants_direct',
                              'type_constants_transitive', 'proof_constants_transitive', 'axioms_transitive')
                    mismatch = any(data.get(field) != actual[field] for field in fields)
                    mismatch |= data.get('type_expr_sha256') != hash_text(canonical(actual['type_expr']))
                    mismatch |= data.get('declaration_kind') != actual['kind']
                    mismatch |= data.get('proof_progress') != 'build_passed' or data.get('axiom_audit') != 'allowed'
                    source_path = actual['module'].replace('.', '/') + '.lean'
                    manifest = project['report']['input_manifest']
                    locator = None
                    if source_path in manifest and actual['source_range']:
                        locator = {'path': source_path, 'file_sha256': manifest[source_path],
                                   'asset_uri': entry['artifacts']['inputs/' + source_path]['uri'], 'source_kind': 'lean',
                                   'build_id': entry['current_build_id'], **actual['source_range']}
                    mismatch |= data.get('source_locator') != locator
                    expected_edges = set()
                    for field, relation in [('type_constants_direct', 'lean_type_depends_on'), ('proof_constants_direct', 'lean_proof_depends_on'),
                                            ('type_constants_transitive', 'lean_type_depends_on_transitive'), ('proof_constants_transitive', 'lean_proof_depends_on_transitive')]:
                        expected_edges.update((relation, declaration_id(project_id, name), 'observed', entry['current_build_id'].removeprefix('lean-build:'))
                                              for name in actual[field])
                    actual_edges = {(ref['relation'], ref['target'], ref.get('status'), ref.get('revision'))
                                    for ref in record['refs'] if ref['relation'] in LEAN_DEPENDENCIES}
                    mismatch |= expected_edges != actual_edges
                    if mismatch:
                        reasons.append({'code': 'lean_export_projection_mismatch'})
                elif (name not in project['observed_names'] or data.get('type') is not None or data.get('module') is not None
                      or data.get('type_expr_sha256') is not None or data['proof_progress'] != 'referenced_name_only'
                      or data['axiom_audit'] != 'not_exported' or any(ref['relation'] in LEAN_DEPENDENCIES for ref in record['refs'])):
                    reasons.append({'code': 'lean_reference_name_unbound'})
            elif record['kind'] == 'formalization':
                claim = records.get(data.get('claim_id'))
                if claim is None or claim['revision'] != data.get('claim_revision') or claim['content_sha256'] != data.get('claim_content_sha256'):
                    reasons.append({'code': 'lean_mapping_claim_changed'})
                actual = project['declarations'].get(data.get('lean_declaration'))
                if actual is None or data.get('type_expr_sha256') != hash_text(canonical(actual['type_expr'])):
                    reasons.append({'code': 'lean_mapping_type_changed'})
                for source in data.get('source_refs', []):
                    try:
                        version = state['versions'][source['source_version_id']]
                        snapshot = safe_relative(registry.root, version['snapshot_path'])
                        validate_snapshot(snapshot, expected_snapshot_id=source['snapshot_id'])
                        graph = read_json(snapshot / 'graph.json')
                        if not any(node['id'] == source['node_id'] and node['content_sha256'] == source['expected_content_sha256']
                                   for node in graph['nodes']):
                            raise ValueError('Original statement no longer matches')
                    except (OSError, ValueError, KeyError) as exc:
                        reasons.append({'code': 'lean_mapping_source_changed', 'message': str(exc)})
        declared_review = data.get('semantic_review', 'not_reviewed')
        semantic_review = declared_review if not reasons and reviews[identifier]['effective_status'] == 'reviewed' else 'not_reviewed'
        result[identifier] = {'effective_status': 'stale' if reasons else 'current', 'reasons': reasons,
                              'build_id': data.get('build_id'), 'semantic_review': semantic_review,
                              'declared_semantic_review': declared_review}
    return result
