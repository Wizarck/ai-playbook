# v0192-mcp-tenant-decouple — Move tenant-specific MCP literals out of the public base template

## Why

When bumping geeplo (a real consumer) to v0.19.1, two latent issues from the v0.18.x public-flip surfaced:

1. **`mcp-servers-base.yaml.tmpl` `rag` server** carries `command: "python -m consumer-d.rag"`. The literal `consumer-d` is the redacted form of the real upstream module name. On any actual consumer machine the real Python module is named differently (e.g. `eligia.rag`), so the rendered `.mcp.json` doesn't work — the `rag` server fails to start. The redaction kept the public repo private-safe but broke the contract for real consumers.

2. **`scripts/mcp/validate.py::resolve_personal_file()`** falls back to `~/Projects/consumer-d/mcp-servers.yaml` and `C:/Projects/consumer-d/mcp-servers.yaml`. Pre-flip those paths pointed at the maintainer's real personal-layer file. Post-flip the path uses a redacted name that no longer matches any real local checkout — the personal layer is silently never loaded, so all servers declared there (`atlassian-geeplo`, `camoufox`, `context7`, ~7 more) drop out of the rendered `.mcp.json` and the consumer's pre-commit `mcp-validate` check fails on every commit.

## What Changes

- **Remove `rag` from `templates/rendered/mcp-servers-base.yaml.tmpl`.** Tenant-specific server entries belong in the project or personal layer. The base template is reserved for servers whose every field is parametric (env vars, null commands, well-known public endpoints).
- **Drop legacy `consumer-d/` fallback paths from `resolve_personal_file()`.** Search order is now: explicit `--personal-file` -> `$AIPLAYBOOK_PERSONAL_MCP_FILE` -> `~/.config/mcp-servers.yaml`. Returns `None` if none resolve (silently skip personal layer, as before).
- **Add `docs/concepts/mcp-servers-schema.md` §3.1 "Tenant-specific servers"** explaining the rule and pointing future contributors at the project/personal layers for any `command`/`endpoint` that carries a tenant literal.
- **Update the module-level docstring of `validate.py`** and the `resolve_personal_file()` docstring to reflect the search order.
- **Update tests**: `tests/test_mcp_render.py` mock data uses `python -m vault_rag` instead of `python -m consumer-d.rag` — the tests exercise plumbing, not the real template content.

## Impact

- **Non-breaking for consumers using the XDG personal-layer path** (`~/.config/mcp-servers.yaml`). They were already on the canonical path.
- **BREAKING for maintainers who relied on the legacy `~/Projects/consumer-d/mcp-servers.yaml` fallback.** They must set `AIPLAYBOOK_PERSONAL_MCP_FILE=<absolute-path>` in their shell profile (or symlink the real file into `~/.config/mcp-servers.yaml`). Migration documented in CHANGELOG v0.19.2.
- **BREAKING for consumers whose existing `.mcp.json` includes the `rag` server**: they must add the server to their own `mcp-servers.project.yaml` (with the real `command` for their stack) and re-run `scripts/mcp/render.py` to regenerate `.mcp.json` and `.gemini/settings.json`.

## Versioning

`VERSION` bumps 0.19.1 -> **0.19.2**. Third fix iteration in the v0.19.x stream; v0.20.0 remains gated on explicit user OK.
