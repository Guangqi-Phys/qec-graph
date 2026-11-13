# Workspace maintenance

> Status: Current.

> **English** · [中文](maintenance.zh-CN.md)

Run these commands in the workspace to inspect the archive and publication status, then rebuild when needed.

```sh
qec-graph doctor
qec-graph validate
qec-graph rebuild
```

Rebuild regenerates a machine release from the registered archive. Original materials live in `archive/`. Research tools read a pinned machine release.

For a release from the retired format, prepare an empty workspace with
`qec-graph init`. Copy the original `archive/blobs/` and `archive/receipts/`
into the new workspace, reapply any explicit source metadata or encoding
settings, then run `qec-graph rebuild --no-human` and `qec-graph validate`.
Update the MCP configuration to pin the new release.
