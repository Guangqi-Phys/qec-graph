# Changelog

## Unreleased

- Workspace maintenance prints a one-line report by default. Scripts that
  parse its output should pass `--json`, including scripts that select a
  workspace with `--workspace`.
- Argument and command usage errors exit with code 64. A partial operation
  continues to exit with code 2.
- CLI errors returned with `--json` now have a versioned envelope on stdout
  (`mcp serve` startup errors stay on stderr). A missing required file exits
  with code 4. Successful JSON reports and partial workspace reports keep
  their existing fields.
- A writer lock held by another process exits with code 5. Damaged workspace
  configuration and CURRENT files report the path to inspect.
- An exact query target that is missing exits with code 4. Ambiguous labels
  report candidate IDs. With `--json`, fixed-scope query errors use the CLI
  envelope and keep the read tool's scope and error code.
- `qec-graph --version` and `qec-graph help <command>` report the installed
  version and available command options.
- Related commands have grouped names and examples. `qec-graph help aliases`
  lists supported older spellings and their replacements. Daily shortcuts
  remain supported without a notice.
- `--quiet` hides successful reports and progress; `--color` controls the
  color in workspace summaries.
- Workspace queries support fixed releases. Splitting a store with annotations
  or a catalog requires explicit `--force` to replace CURRENT.
- Generated Obsidian pages use readable filenames. Existing generated links
  remain usable through forwarding or archive pages. See the advanced guide
  before rolling back to an older renderer.
