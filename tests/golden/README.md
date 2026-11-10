# Pinned arXiv regression set

> **English** · [中文](README.zh-CN.md)

The [manifest](arxiv_sources.json) records six exact arXiv versions, the
SHA-256 of each source archive, the normalized source tree hash, and expected
entrypoints and graph labels. It links to the license listed for each version
on arXiv. The repository distributes the manifest and observed structural
results. Obtain source archives from the listed arXiv source URLs or use
existing content-addressed workspace copies.

Run with an installed QEC Graph environment from the repository root:

```sh
python tools/reproduce_golden.py \
  --archive-dir /path/to/workspace/archive/blobs/sha256 \
  --out build/golden-arxiv.json
```

The input directory can also contain one file named `<arxiv-id>.source`
per entry, with the exact bytes recorded in the manifest. The replay rejects
changed archive bytes. It imports copies into a temporary workspace, verifies
the release and archived bytes, and checks source paths and label kinds.

The supplement in [2308.07915v2](https://arxiv.org/abs/2308.07915v2)
also supports independent compilation. The replay checks that sync retains
this ambiguous package, then adds the pinned main entrypoint to the temporary
workspace config and checks a table from the included supplement.
[2009.03921v2](https://arxiv.org/abs/2009.03921v2) checks that references to
paragraph assumptions remain source references.

The inputs use either the [arXiv distribution license](https://arxiv.org/licenses/nonexclusive-distrib/1.0/)
or [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The replay measures structural extraction and evidence binding.
