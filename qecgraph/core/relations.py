"""Node kinds and edge contracts shared by graph construction and validation."""

STATEMENTS = {"lemma", "theorem", "proposition", "corollary", "conjecture", "claim", "statement_other"}
MATHEMATICS = STATEMENTS | {"definition", "assumption", "notation", "proof", "equation"}

KNOWN_RELATIONS = {
    "contains", "defined_in", "includes", "references", "cites", "cites_paper", "uses_resource",
    "depends_on_declared", "depends_on_candidate", "depends_on_reviewed",
    "proof_of", "proof_of_candidate", "describes", "about",
    "has_matrix", "has_check_matrix", "generated_by", "uses_circuit", "uses_noise",
    "uses_decoder", "supports", "contradicts", "reports", "instance_of",
}

ENDPOINTS = {
    'cites_paper': ({'bib_entry'}, {'document'}),
    'proof_of': ({'proof'}, STATEMENTS),
    'proof_of_candidate': ({'proof'}, STATEMENTS),
    'depends_on_declared': (MATHEMATICS, MATHEMATICS),
    'depends_on_candidate': (MATHEMATICS, MATHEMATICS),
    'depends_on_reviewed': (MATHEMATICS, MATHEMATICS),
    'supports': ({'evidence'}, {'claim'}),
    'contradicts': ({'evidence', 'claim'}, {'claim'}),
    'has_matrix': ({'quantum_code', 'check_matrix', 'classical_code'}, {'matrix', 'asset'}),
    'has_check_matrix': ({'quantum_code'}, {'check_matrix'}),
    'uses_circuit': ({'experiment', 'circuit', 'quantum_code', 'check_matrix'}, {'circuit'}),
    'uses_noise': ({'experiment', 'circuit'}, {'noise'}),
    'uses_decoder': ({'experiment'}, {'decoder'}),
    'normalizes_to': (MATHEMATICS | {'paragraph', 'table', 'remark'}, {'claim'}),
}
