"""Optional immutable retrieval projections; source records remain authoritative."""
from __future__ import annotations

from .core.progress import phase, task, track

from collections import Counter
import hashlib
import json
import math
import os
import re
from urllib.parse import urlsplit

from .core.graph import canonical, hash_text, read_json, strict_json_loads
from .core.transactions import atomic_bytes, immutable_json
from .core.errors import ToolError
from .core.fs import managed_path as _managed

from .retrieval_vectors import read_vector, vector_path, write_vector

FORMAT = 'qecgraph.retrieval.v2'


class RetrievalFormatError(ValueError):
    pass


DEFAULTS = {'enabled': False, 'provider': 'local', 'model': 'qecgraph-word-char-hash', 'model_revision': '1',
            'dimensions': 512, 'chunk_chars': 2048, 'max_chunks': 100000, 'max_total_chars': 20000000,
            'base_url': '', 'api_key_env': 'QECGRAPH_EMBEDDING_API_KEY', 'allow_source_upload': False,
            'timeout_seconds': 30}


def configuration(raw):
    if not isinstance(raw, dict) or set(raw) - set(DEFAULTS):
        raise ValueError('Unsupported retrieval configuration')
    cfg = {**DEFAULTS, **raw}
    for name in ('enabled', 'allow_source_upload'):
        if type(cfg[name]) is not bool:
            raise ValueError('Retrieval flags must be booleans')
    for name, lower, upper in [('dimensions', 8, 4096), ('chunk_chars', 128, 8192),
                                ('max_chunks', 1, 1000000), ('max_total_chars', 128, 1000000000),
                                ('timeout_seconds', 1, 120)]:
        if type(cfg[name]) is not int or not lower <= cfg[name] <= upper:
            raise ValueError('Invalid retrieval ' + name)
    if cfg['provider'] not in {'local', 'openai_compatible'}:
        raise ValueError('Unknown retrieval provider')
    for name in ('model', 'model_revision', 'api_key_env'):
        if not isinstance(cfg[name], str) or not cfg[name].strip() or len(cfg[name]) > 512:
            raise ValueError('Retrieval model identity and credential name are required')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', cfg['api_key_env']):
        raise ValueError('Invalid embedding credential environment name')
    if cfg['provider'] == 'local':
        if (cfg['model'], cfg['model_revision']) != ('qecgraph-word-char-hash', '1'):
            raise ValueError('Unknown local embedding model/revision')
    else:
        if not isinstance(cfg['base_url'], str):
            raise ValueError('Embedding endpoint must be HTTPS')
        url = urlsplit(cfg['base_url'])
        if url.scheme != 'https' or not url.hostname or url.username or url.query or url.fragment:
            raise ValueError('Embedding endpoint must be HTTPS without credentials/query/fragment')
        if cfg['enabled'] and not cfg['allow_source_upload']:
            raise ValueError('External embeddings require explicit allow_source_upload = true')
    return cfg


def identity(cfg):
    return {k: cfg[k] for k in ('provider', 'model', 'model_revision', 'dimensions', 'base_url')} | {
        'tokenizer': 'unicode-word-cjk-bigram-v1', 'normalization': 'l2', 'chunk_chars': cfg['chunk_chars']}


def terms(text):
    tokens = re.findall(r'[^\W_]+', text.casefold())
    result = []
    for token in tokens:
        if re.search(r'[\u3400-\u9fff]', token):
            result.extend(token[i:i+2] for i in range(max(1, len(token)-1)))
        else:
            result.append(token)
    return result


def local_vector(text, dimension):
    counts = Counter(terms(text))
    vector = {}
    for token, count in counts.items():
        features = [token, *('~'+token[i:i+3] for i in range(max(0, len(token)-2)))]
        for feature in features:
            index = str(int(hashlib.sha256(feature.encode()).hexdigest()[:16], 16) % dimension)
            vector[index] = vector.get(index, 0.0) + (1 + math.log(count)) / len(features)
    norm = math.sqrt(sum(x*x for x in vector.values()))
    return {i: x/norm for i, x in vector.items()} if norm else {}


@task('Waiting for embedding provider')
def external_embeddings(texts, cfg):
    from .llm.providers.http import UrllibTransport
    secret = os.environ.get(cfg['api_key_env'])
    if not secret:
        raise ValueError('Embedding credential environment variable is not set')
    try:
        response = UrllibTransport().request('POST', cfg['base_url'].rstrip('/') + '/embeddings',
            headers={'Authorization': 'Bearer ' + secret, 'Content-Type': 'application/json'},
            body=json.dumps({'model': cfg['model'], 'input': texts, 'encoding_format': 'float',
                             'dimensions': cfg['dimensions']}).encode(), timeout=cfg['timeout_seconds'])
        if response.status != 200:
            raise ValueError('Embedding request failed')
        data = strict_json_loads(response.body.decode('utf-8'))
        if not isinstance(data, dict) or data.get('model') != cfg['model']:
            raise ValueError('Embedding response model mismatch')
        rows = data.get('data')
        if not isinstance(rows, list) or len(rows) != len(texts):
            raise ValueError('Embedding response count mismatch')
        if any(not isinstance(row, dict) or type(row.get('index')) is not int for row in rows):
            raise ValueError('Embedding response index mismatch')
        rows = sorted(rows, key=lambda row: row['index'])
        if [row['index'] for row in rows] != list(range(len(texts))):
            raise ValueError('Embedding response index mismatch')
        vectors = []
        for row in rows:
            values = row.get('embedding')
            if (not isinstance(values, list) or len(values) != cfg['dimensions'] or
                    any(type(x) not in (int, float) or not math.isfinite(x) for x in values)):
                raise ValueError('Embedding response vector mismatch')
            norm = math.sqrt(sum(x*x for x in values))
            if not norm or not math.isfinite(norm):
                raise ValueError('Embedding response vector norm invalid')
            vectors.append({str(i): x/norm for i, x in enumerate(values) if x})
        return vectors
    except Exception:
        # Never include a credential, provider response body or source text in errors.
        raise ValueError('Embedding provider failed validation or transport; prior release retained') from None


def unit_key(unit):
    return hash_text(canonical([unit['id'], unit.get('revision')]))


def corpus_binding(units):
    return hash_text(canonical([(unit_key(u), hash_text(u['search_text'])) for u in units]))


def read_index(machine, binding, *, verify_vectors=False):
    digest = binding.get('sha256', '')
    if not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('Invalid retrieval index binding')
    data = read_json(_managed(machine, 'retrieval/indexes/' + digest + '.json'))
    if hash_text(canonical(data)) != digest:
        raise ValueError('Retrieval index hash mismatch')
    if data.get('format') != FORMAT:
        raise RetrievalFormatError('Retrieval format changed; rebuild the optional index')
    cfg = configuration(data['configuration'])
    if data['identity'] != identity(cfg) or binding.get('identity') != data['identity'] or binding.get('corpus_sha256') != data['corpus_sha256']:
        raise ValueError('Retrieval model or corpus binding mismatch')
    if not isinstance(data['chunks'], list) or len(data['chunks']) > cfg['max_chunks']:
        raise ValueError('Retrieval index exceeds chunk budget')
    vector_digests = {chunk.get('vector_sha256') for chunk in data['chunks']}
    for vector_digest in vector_digests:
        if verify_vectors:
            read_vector(machine, vector_digest, cfg['dimensions'])
        else:
            vector_path(machine, vector_digest)
    return data


def _store_vectors(machine, cfg, pending, *, repair):
    dimensions = cfg['dimensions']
    items = list(pending.items())
    stored = {}
    for start in track(range(0, len(items), 16), 'Generating embeddings', unit='batches'):
        batch = items[start:start + 16]
        texts = [text for _, text in batch]
        vectors = ([local_vector(text, dimensions) for text in texts]
                   if cfg['provider'] == 'local' else external_embeddings(texts, cfg))
        for (digest, _), vector in zip(batch, vectors, strict=True):
            stored[digest] = write_vector(machine, vector, dimensions, repair=repair)
    return stored


@task('Preparing retrieval index')
def _stage_index(registry, state, raw_config, *, repair=False):
    """Called under the existing writer lock, before release validation/publication."""
    cfg = configuration(raw_config)
    if not cfg['enabled']:
        state.pop('retrieval_index', None)
        return
    from .workspace_query import WorkspaceSession
    session = WorkspaceSession(registry.root, _candidate_state=state)
    units = session.knowledge.search_units
    model = identity(cfg)
    binding = corpus_binding(units)
    try:
        previous = read_index(registry.root, state['retrieval_index'], verify_vectors=repair) if state.get('retrieval_index', {}).get('sha256') else None
    except RetrievalFormatError:
        previous = None
    except (OSError, ValueError, KeyError, TypeError):
        if not repair:
            raise
        previous = None
    if previous and previous['corpus_sha256'] == binding and previous['configuration'] == cfg:
        return
    chunks, pending, total_chars = [], {}, 0
    reusable = {c['text_sha256']: c['vector_sha256'] for c in previous['chunks']} if previous and previous['identity'] == model else {}
    for unit in track(units, 'Indexing searchable source text', unit='passages'):
        text = unit['search_text']
        total_chars += len(text)
        if total_chars > cfg['max_total_chars']:
            raise ValueError('Retrieval character budget exceeded; prior release retained')
        for start in range(0, len(text), cfg['chunk_chars']):
            if len(chunks) >= cfg['max_chunks']:
                raise ValueError('Retrieval chunk budget exceeded; prior release retained')
            part = text[start:start + cfg['chunk_chars']]
            digest = hash_text(part)
            if digest not in reusable:
                pending[digest] = part
            chunks.append({'unit_key': unit_key(unit), 'char_start': start, 'char_end': start + len(part),
                           'text_sha256': digest})
    reusable.update(_store_vectors(registry.root, cfg, pending, repair=repair))
    for chunk in chunks:
        chunk['vector_sha256'] = reusable[chunk['text_sha256']]
    phase('Writing retrieval index')
    projection = {'format': FORMAT, 'identity': model, 'configuration': cfg,
                  'corpus_sha256': binding, 'unit_count': len(units), 'chunks': chunks,
                  'coverage': 'Complete registered search text; chunk offsets address derived search text, not source'}
    digest = hash_text(canonical(projection))
    path = _managed(registry.root, 'retrieval/indexes/' + digest + '.json')
    if repair and path.exists():
        # Restore only this derived, content-addressed projection under the writer lock.
        atomic_bytes(path, (canonical(projection) + '\n').encode('utf-8'))
    else:
        immutable_json(path, projection, compact=True)
    state['retrieval_index'] = {'sha256': digest, 'corpus_sha256': binding, 'identity': model}


def stage_index(registry, state, raw_config, *, repair=False):
    """Optional projection failures cannot veto a valid source publication."""
    try:
        _stage_index(registry, state, raw_config, repair=repair)
    except (OSError, ValueError) as exc:
        state['retrieval_index'] = {'status': 'stale',
            'reason': 'Optional retrieval projection unavailable (' + type(exc).__name__ + '); rebuild to retry'}


class RetrievalIndex:
    def __init__(self, view):
        self.view = view
        binding = view.session.state.get('retrieval_index')
        self.stale = bool(binding and binding.get('status') == 'stale')
        try:
            self.data = read_index(view.session.machine, binding) if binding and not self.stale else None
        except RetrievalFormatError:
            self.stale, self.data = True, None
        self.current = self.data is not None and self.data['corpus_sha256'] == corpus_binding(view.search_units)

    def status(self):
        return {'status': 'current' if self.current else 'stale' if self.data or self.stale else 'not_built',
                'identity': self.data['identity'] if self.data else None,
                'units': self.data['unit_count'] if self.data else 0,
                'quality': 'Local vectors are a lexical baseline; external semantic quality requires evaluation'}

    def _vector(self, digest, dimensions):
        try:
            return read_vector(self.view.session.machine, digest, dimensions)
        except (OSError, ValueError):
            raise ToolError('EMBEDDING_UNAVAILABLE', 'Stored vector unavailable; rebuild or use mode=keyword') from None

    def rank(self, query, allowed):
        if not self.current:
            raise ToolError('INDEX_UNAVAILABLE', 'Build a current retrieval index with sync/rebuild; source search remains available')
        cfg = configuration(self.data['configuration'])
        if len(query) > cfg['chunk_chars']:
            raise ToolError('INVALID_ARGUMENT', 'Query exceeds embedding character budget')
        try:
            vector = (local_vector(query, cfg['dimensions']) if cfg['provider'] == 'local'
                      else external_embeddings([query], cfg)[0])
        except ValueError:
            raise ToolError('EMBEDDING_UNAVAILABLE', 'Query embedding unavailable; retry with mode=keyword') from None
        similarity = {}
        vectors = {}
        for chunk in self.data['chunks']:
            key = chunk['unit_key']
            if not vector or key not in allowed:
                continue
            digest = chunk['vector_sha256']
            if digest not in vectors:
                vectors[digest] = self._vector(digest, cfg['dimensions'])
            score = sum(x * vectors[digest].get(i, 0) for i, x in vector.items())
            if score > 0:
                similarity[key] = max(similarity.get(key, 0), score)
        return sorted(similarity, key=lambda key: (-similarity[key], key)), self.status()
