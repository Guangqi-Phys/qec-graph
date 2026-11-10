"""Canonical typed-relation names shared by graph building and validation.

This module is deliberately dependency-free so ``graph`` and ``validators`` can
both use it without importing each other at module load time.
"""

KNOWN_RELATIONS = {
    "contains", "defined_in", "includes", "references", "cites", "uses_resource",
    "depends_on_declared", "depends_on_candidate", "depends_on_reviewed",
    "proof_of", "proof_of_candidate", "formalizes", "describes", "about",
    "has_matrix", "has_presentation", "generated_by", "uses_circuit", "uses_noise",
    "uses_decoder", "supports", "contradicts", "reports", "instance_of",
}
