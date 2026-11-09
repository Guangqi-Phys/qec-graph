# Schema paths

Current JSON Schema files live in the [packaged schema directory](../qecgraph/validators/schemas/).
Checkout consumers can replace the old `schemas/<name>.schema.json` path with
`qecgraph/validators/schemas/<name>.schema.json`. Installed Python consumers
can read the same file using `importlib.resources`.

Schema names and record versions stay the same. Semantic checks such as
source coordinates, content hashes, and cross-record bindings also require
the package validator.
