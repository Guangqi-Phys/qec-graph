"""Content-checked per-file AST reuse, with full semantic discovery on every run.

Cache JSON decodes only an allowlist of pylatexenc node classes. No pickle,
dynamic imports, TeX execution, or semantic graph fragments are cached.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from pylatexenc import __version__ as PYLATEXENC_VERSION
from pylatexenc import latexwalker
from pylatexenc.macrospec import ParsedMacroArgs, ParsedVerbatimArgs

from ..core.graph import canonical, hash_text, read_json
from ..core.transactions import atomic_json

_NODE_TYPES = {name: getattr(latexwalker, name) for name in (
    'LatexCharsNode', 'LatexCommentNode', 'LatexGroupNode', 'LatexMacroNode',
    'LatexEnvironmentNode', 'LatexMathNode', 'LatexSpecialsNode')}
_STRUCTURAL = (b'\\newcommand', b'\\renewcommand', b'\\providecommand', b'\\Declare', b'\\newtheorem',
               b'\\newenvironment', b'\\renewenvironment', b'\\def', b'\\gdef', b'\\edef', b'\\xdef',
               b'\\newif', b'\\input', b'\\include')


def input_inventory(root, exclude=(), *, ignore_temporary=False):
    root = Path(root).resolve()
    excluded = [Path(path).resolve() for path in exclude]
    files, structural = {}, {}
    for directory, folders, names in os.walk(root, followlinks=False):
        directory = Path(directory)
        folders[:] = sorted(name for name in folders if name not in {'.git', '.venv', '__pycache__'}
                            and not (directory / name).is_symlink()
                            and not any((directory / name).resolve().is_relative_to(item) for item in excluded))
        for name in sorted(names):
            path = directory / name
            if not path.is_file() or not path.resolve().is_relative_to(root) or any(path.resolve().is_relative_to(item) for item in excluded):
                continue
            if ignore_temporary and (name.endswith(('~', '.swp', '.swo', '.tmp', '.temp')) or name.startswith(('.#', '.~lock.'))):
                continue
            relative = path.relative_to(root)
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            files[relative.as_posix()] = digest
            if path.suffix.lower() in {'.tex', '.sty', '.cls'} and any(token in raw for token in _STRUCTURAL):
                structural[relative.as_posix()] = digest
    return files, structural


def _encode(value):
    if isinstance(value, ParsedVerbatimArgs):
        return {'type': 'verbatim_args', 'chars': _encode(value.argnlist[0]), 'delimiters': value.verbatim_delimiters}
    if isinstance(value, ParsedMacroArgs):
        return {'type': 'args', 'argspec': value.argspec, 'argnlist': _encode(value.argnlist)}
    if type(value).__name__ in _NODE_TYPES and isinstance(value, tuple(_NODE_TYPES.values())):
        return {'type': type(value).__name__, 'fields': {key: _encode(getattr(value, key)) for key in value._fields}}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ValueError('Unsupported AST cache value')


def _decode(value, text_length):
    if isinstance(value, list):
        return [_decode(item, text_length) for item in value]
    if not isinstance(value, dict):
        if value is None or isinstance(value, (str, int, bool)):
            return value
        raise ValueError('Invalid AST cache primitive')
    kind = value['type']
    if kind == 'args':
        return ParsedMacroArgs(argspec=value['argspec'], argnlist=_decode(value['argnlist'], text_length))
    if kind == 'verbatim_args':
        delimiters = tuple(value['delimiters']) if value['delimiters'] else None
        return ParsedVerbatimArgs(_decode(value['chars'], text_length), verbatim_delimiters=delimiters)
    if kind not in _NODE_TYPES:
        raise ValueError('Unknown AST cache node kind')
    fields = {key: _decode(item, text_length) for key, item in value['fields'].items()}
    start, length = fields['pos'], fields['len']
    if type(start) is not int or type(length) is not int or not 0 <= start <= start + length <= text_length:
        raise ValueError('Invalid cached AST source range')
    if 'delimiters' in fields:
        fields['delimiters'] = tuple(fields['delimiters'])
    return _NODE_TYPES[kind](parsing_state=None, **fields)


class ParseCache:
    def __init__(self, store, root, config):
        self.store, self.root = Path(store).resolve(), Path(root).resolve()
        self.directory = self.store / 'cache/ast'
        if self.directory.is_symlink():
            raise ValueError('AST cache directory must be local, not a symlink')
        self.directory.mkdir(parents=True, exist_ok=True)
        files, structural = input_inventory(root, exclude=[self.store])
        package = Path(__file__).parent
        processor = {name: hashlib.sha256((package / name).read_bytes()).hexdigest()
                     for name in ('parser.py', 'incremental.py')}
        self.plan = {'format': 'qecgraph.incremental.v1', 'files': files, 'structural_inputs': structural,
                     'config': config, 'processor': processor, 'pylatexenc': PYLATEXENC_VERSION}
        self.stats = {'ast_hits': 0, 'ast_misses': 0, 'invalid_cache_entries': 0, 'fallback_reasons': []}
        state_path = self.store / 'cache/incremental-state.json'
        try:
            previous = read_json(state_path) if state_path.exists() else None
            if previous is not None and (not isinstance(previous, dict) or previous.get('format') != 'qecgraph.incremental.v1'
                                         or not isinstance(previous.get('files'), dict)
                                         or not isinstance(previous.get('structural_inputs'), dict)):
                raise ValueError('Invalid incremental state shape')
        except (OSError, ValueError):
            previous = None
            self.stats['fallback_reasons'].append('invalid_incremental_state')
        if previous:
            for key in ('structural_inputs', 'config', 'processor', 'pylatexenc'):
                if previous.get(key) != self.plan[key]:
                    self.stats['fallback_reasons'].append(key + '_changed')
            old_tex = {name for name in previous['files'] if name.endswith(('.tex', '.sty', '.cls'))}
            new_tex = {name for name in files if name.endswith(('.tex', '.sty', '.cls'))}
            if old_tex != new_tex:
                self.stats['fallback_reasons'].append('source_topology_changed')
            if previous.get('unresolved_dependencies'):
                self.stats['fallback_reasons'].append('previous_unresolved_dependencies')
            self.stats['changed_inputs'] = sorted(name for name in files.keys() | previous['files'].keys()
                                                 if files.get(name) != previous['files'].get(name))
        else:
            self.stats['fallback_reasons'].append('initial_full_parse')
            self.stats['changed_inputs'] = sorted(files)
        self.reuse = not self.stats['fallback_reasons']
        self.context_hash = hash_text(canonical({key: value for key, value in self.plan.items() if key != 'files'}))
        self.written = set()

    def key(self, path, text, context):
        return hash_text(canonical({'format': 'qecgraph.ast.v1', 'context': self.context_hash,
                                    'path': path, 'text_sha256': hash_text(text), 'parser_context': context}))

    def get(self, key, text):
        path = self.directory / (key + '.json')
        if (self.reuse or key in self.written) and path.exists():
            try:
                entry = read_json(path)
                if entry['format'] != 'qecgraph.ast.v1' or entry['key'] != key or entry['ast_sha256'] != hash_text(canonical(entry['ast'])):
                    raise ValueError('AST cache hash mismatch')
                nodes = _decode(entry['ast'], len(text))
                if not isinstance(nodes, list):
                    raise ValueError('AST cache root must be a list')
                self.stats['ast_hits'] += 1
                return nodes
            except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
                self.stats['invalid_cache_entries'] += 1
        self.stats['ast_misses'] += 1
        return None

    def put(self, key, nodes):
        try:
            ast = _encode(nodes)
        except (ValueError, TypeError, AttributeError):
            return
        atomic_json(self.directory / (key + '.json'), {'format': 'qecgraph.ast.v1', 'key': key,
                    'ast': ast, 'ast_sha256': hash_text(canonical(ast))})
        self.written.add(key)

    def finish(self, parsed, result):
        unresolved = {'missing_include', 'dynamic_path', 'path_outside_project', 'source_read_error', 'latex_parse_error'}
        self.plan['unresolved_dependencies'] = any(d['code'] in unresolved for d in parsed['diagnostics'])
        self.plan['snapshot_id'] = result['snapshot_id']
        self.plan['dependencies'] = {'sources': [f['path'] for f in parsed['files']],
                                     'resources': [r.get('path') for r in parsed['resources']], 'includes': parsed['includes']}
        atomic_json(self.store / 'cache/incremental-state.json', self.plan)
