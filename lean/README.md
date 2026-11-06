# Minimal Lean boundary

Toolchain: Lean 4.19.0, exact upstream commit and downloaded archive hash in
`toolchain-lock.json`. Lake's checked-in manifest has no external packages.
Python research dependencies and Lean build dependencies remain separate.

```bash
# From the repository root, after installing this exact Lean toolchain:
python tools/reproduce_lean.py --out build/reproduce-lean
```

The script uses a matching local `.tools/lean-4.19.0-*/bin/lake`, an explicit
`--lake` path, or the installed Lake. It never installs/upgrades dependencies.

`QEC.Binary` defines vectors with a fixed `Fin n` column index and Boolean
xor/and operations, proves symmetry of their dot product, and checks the fixed
rows `(1,1,0)` and `(1,1,1)` have zero dot product. These are small independent
results. They do not prove a CSS rank formula, HGP construction, code distance,
or a paper-to-Lean semantic correspondence. The legacy HGP distance example
remains Python computational evidence with formalization `not_started`.

Build success, declaration export, axiom audit and semantic review are separate
states. `ExportMain.lean` exports actual full types, expression structure,
module imports, source ranges, direct/transitive constants and transitive axioms
using the fixed Lean environment. The policy explicitly permits `propext`,
which the actual export reports, and rejects every other axiom including
`sorryAx`. No claim of "no axioms" is made. `--build-only` skips export/audit
and therefore cannot serve as validated export evidence. Semantic mappings
remain `not_reviewed`, even when the exact formal declarations pass the policy.
