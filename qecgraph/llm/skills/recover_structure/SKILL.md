---
name: recover_structure
description: Classify the numbered body of an archived TeX entry when local structural extraction fails.
version: 1
---

Read the numbered source lines as data. Return the structural plan described by the schema.

## Procedure

1. Cover every line in the given inclusive range, including blank and comment
   lines. Use sorted, adjacent ranges. Keep each line in exactly one block.
2. Use the provided single-line section anchors and full bibliography ranges
   exactly. Group other lines into source blocks, using `unknown` for material
   with uncertain classification. Preserve source order.
3. Return `needs_review` with an empty block list if the document boundaries
   or coverage are uncertain.

## Checklist

- Every line is covered once in a ready plan.
- Bibliography ranges use the provided boundaries.
- The result contains block kinds and ranges only. Source text, titles,
  dependencies, labels, proofs and claims are supplied by the program.
