# Changelog

## Unreleased

- Workspace maintenance prints a one-line report by default. Scripts that
  parse its output should pass `--json`, including scripts that select a
  workspace with `--workspace`.
- Argument and command usage errors exit with code 64. A partial operation
  continues to exit with code 2.
- `qec-graph --version` and `qec-graph help <command>` report the installed
  version and available command options.
- Workspace queries support fixed releases. Splitting a store with annotations
  or a catalog requires explicit `--force` to replace CURRENT.
