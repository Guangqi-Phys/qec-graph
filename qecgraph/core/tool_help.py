"""Shared agent-facing help for the fixed-scope read interfaces."""

DESCRIPTIONS = {
    'qec_list_papers': 'Locate papers by title, author, topic or year. Returns a paginated library inventory; use qec_fetch(view=card) to inspect a paper.',
    'qec_search': 'Discover ranked source passages, records and proposed extractions. Use natural keywords before exact reading; similarity does not satisfy numeric code conditions. Returns handles, excerpts and locations.',
    'qec_fetch': 'Read an exact paper, file, section, node, proposal or record by ID or handle. Use card/outline for navigation, raw/reading for evidence; explicit ranges paginate long text.',
    'qec_get_context': 'Expand one source or record with bounded structural and evidence context. Select a purpose for missing-component reporting. Proximity and references are not proof dependencies.',
    'qec_query_codes': 'Enumerate registered quantum codes with exact parameter and evidence filters. Does not search prose: when empty, use qec_search. Returns parameters, evidence states and source bindings.',
    'qec_query_performance': 'Enumerate explicitly registered performance points with experiment, decoder, noise and metric bindings. No interpolation or cross-experiment ranking. Empty results require source search.',
    'qec_trace': 'Traverse typed relations from an exact entity or occurrence in either direction. Returns complete selected nodes, edges and truncation; candidate links require explicit opt-in.',
    'qec_status': 'Inspect fixed-release coverage, missing fields, extraction and retrieval status before interpreting empty queries. Counts describe this library, not the literature.',
    'search': 'Find citable source evidence with confirmed public URLs for generic search clients. Local-only papers remain available through qec_search.',
    'fetch': 'Fetch one complete citable source unit from generic search results. Oversize units require the research profile and exact ranges; no silent text truncation.',
    'qec_get_entity': 'Compatibility entity lookup by exact identity and optional revision. Returns the registered record or source node with evidence.',
    'qec_get_source': 'Read an exact registered source occurrence or codepoint range. Returns verbatim TeX and source coordinates; no filesystem paths are accepted.',
    'qec_get_asset': 'Read paginated bytes of an asset referenced by an eligible record. Returns base64 bytes, hash and byte offsets; does not execute the asset.',
    'qec_find_software': 'Enumerate registered software names, roles and reported usage. Does not inspect local installations or infer current versions.',
}

PARAMETERS = {
    'query': 'Search terms or a natural-language query; not SQL, code or a filesystem path.',
    'identifier': 'Exact registered identity or a short handle returned in this pinned release. Duplicate labels require an exact ID.',
    'id': 'Exact ID returned by generic search.',
    'kind': 'Exact node, record or proposal kind; filter is applied before ranking.',
    'revision': 'Exact record revision; unavailable revisions never fall back to another version.',
    'source_version_id': 'Restrict to this exact registered source version, never a guessed latest version.',
    'release_id': 'Optional assertion of this session release; cannot switch the pinned scope.',
    'view': 'raw preserves TeX; reading is derived display text; outline lists structure; card previews one paper.',
    'detail': 'concise reduces discovery rows to handles and excerpts; full retains hashes and provenance.',
    'max_chars': 'Maximum serialized response characters within the session cap. Truncation is explicit.',
    'max_nodes': 'Maximum complete nodes in a traversal or context result, including its root.',
    'depth': 'Traversal hop limit; for qec_fetch outline use sections or blocks.',
    'limit': 'Maximum result rows in this page, within the session cap.',
    'offset': 'Zero-based result row offset; for assets this is a byte offset.',
    'length': 'Maximum asset bytes to return, before base64 encoding.',
    'char_start': 'Inclusive Unicode codepoint offset in the registered source file, not a byte offset.',
    'char_end': 'Exclusive Unicode codepoint offset; must remain inside the selected source unit.',
    'include_proposals': 'Include unreviewed AI proposals (default true); each retains proposed status.',
    'include_candidates': 'Opt into candidate/proposed relationships; never promotes them to verified dependencies.',
    'purpose': 'Select theorem, performance, construction, thought or Lean preparation context; missing evidence stays explicit.',
    'mode': 'keyword uses BM25; hybrid adds optional vectors; vector requires an index; literal normalizes whitespace only.',
    'relations': 'Exact relation names to traverse; citations and references are not proof dependencies.',
    'direction': 'outgoing follows source to target; incoming finds predecessors; both traverses either direction.',
    'evidence_policy': 'verified requires qualifying computational/certificate evidence; source_reported accepts located paper claims.',
    'distance_at_least': 'Minimum qualifying distance lower bound. An upper bound never satisfies this condition.',
    'sector': 'X, Z or joint distance sector; code and circuit distance remain distinct.',
    'metric_id': 'Exact metric identity; units and definitions must match, not just its display name.',
    'metric_revision': 'Exact metric revision associated with the evidence filter.',
    'complete_only': 'Exclude points with incomplete recorded experiment conditions; does not infer missing values.',
    'selection': 'exact selects reported coordinates only; nearest_reported selects an existing point without interpolation.',
    'coordinate': 'Requested numeric value of coordinate_name, in the recorded coordinate units.',
    'coordinate_name': 'Recorded axis/parameter name for selecting performance points.',
    'source_query': 'Optional source-search fallback returned separately; cannot satisfy structured hard filters.',
    'year': 'Exact source-reported publication year; unknown years do not match.',
    'topic': 'Filter recorded topic labels; absence is not proof of irrelevance.',
    'idle': 'Require an explicitly included/excluded idle-noise condition; unknown does not match.',
    'loss': 'Require an explicitly included/excluded loss condition; unknown does not match.',
}


def describe(tool):
    name = tool['name']
    aliases = {'qec_find_codes': 'qec_query_codes', 'qec_find_performance': 'qec_query_performance',
               'qec_workspace_status': 'qec_status'}
    if name in aliases:
        tool['description'] = 'Compatibility alias: ' + name + '. ' + DESCRIPTIONS[aliases[name]]
    elif name.startswith('qecgraph_'):
        action = name.removeprefix('qecgraph_')
        tool['description'] = ('Compatibility ' + action + ' over a pinned store/corpus graph. '
                               'Returns source nodes with evidence states and explicit truncation. '
                               'Workspace research tools provide paper navigation and ranked discovery.')
    else:
        tool['description'] = DESCRIPTIONS[name]
    for field, schema in tool['inputSchema']['properties'].items():
        description = PARAMETERS.get(field)
        if description is None:
            description = ('Exact ' + field.removesuffix('_id').replace('_', ' ') + ' identity.' if field.endswith('_id')
                           else 'Filter the recorded ' + field.replace('_', ' ') + '; unknown values do not satisfy this filter.')
        if 'enum' in schema:
            description += ' Allowed values: ' + ', '.join(str(v) for v in schema['enum']) + '.'
        schema['description'] = description
    return tool
