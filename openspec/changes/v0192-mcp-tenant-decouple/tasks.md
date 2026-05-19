# v0192-mcp-tenant-decouple — Tasks

- [x] 1. Remove `rag` entry from `templates/rendered/mcp-servers-base.yaml.tmpl` (add inline NOTE pointing at the migration)
- [x] 2. Drop legacy `~/Projects/consumer-d/mcp-servers.yaml` + `C:/Projects/consumer-d/mcp-servers.yaml` fallback paths from `scripts/mcp/validate.py::resolve_personal_file()`
- [x] 3. Update module-level docstring of `scripts/mcp/validate.py` to reflect the simplified search order
- [x] 4. Add `docs/concepts/mcp-servers-schema.md` §3.1 "Tenant-specific servers"
- [x] 5. Update `tests/test_mcp_render.py` mock data: `python -m consumer-d.rag` -> `python -m vault_rag`
- [x] 6. `python -m pytest tests/test_mcp_render.py tests/test_mcp_validate.py -q` -> 28 passed
- [x] 7. `python -m pytest tests/ -q` -> 990 passed / 2 skipped
- [x] 8. `python -m ruff check .` -> All checks passed
- [x] 9. Bump `VERSION` 0.19.1 -> 0.19.2
- [x] 10. Prepend CHANGELOG v0.19.2 entry with migration notes
- [ ] 11. Open PR; merge after CI green
- [ ] 12. Tag v0.19.2
