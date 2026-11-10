# Reporting a vulnerability

Use the repository's [Security advisories](https://github.com/Guangqi-Phys/qec-graph/security/advisories)
page and choose **Report a vulnerability** if available. If the option is
unavailable, open an issue asking maintainers for a private contact channel.
Keep the vulnerability details out of the public issue. See
[GitHub's private reporting guide](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately).

In the private report, include the QEC Graph version, operating system,
affected command, and a minimal reproduction. Use a synthetic archive or
workspace where possible. Remove credentials, private notes, and any paper
source you are not permitted to share.

## AI providers and source upload

AI is optional. Before enabling it, decide whether paper excerpts may be sent to
the selected provider. `[ai].allow_source_upload = false` blocks uploads while
leaving local-only workflows available.

- Prefer `api_key_env` over an inline key. The generated `qecgraph.toml` is mode
  `0600`; do not commit it when it contains a key.
- Provider errors, logs and AI run metadata must not contain authorization
  headers or API keys.
- `human/notes/` is never included in an AI evidence pack.
- A model response is untrusted data; validate its JSON Schema before storing or
  displaying it. Never execute model-provided code or shell commands.
- Skills are code-adjacent instructions. Audit modified skills and bump their
  version; install skills only from trusted sources.
