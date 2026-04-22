"""Check prerequisites + context budget for a consuming project.

Populated in T14a. v0.1.0 stub: prints intent and exits 0.

Checks planned (T14a):
- Python >= 3.11, git, pre-commit, gh CLI, npx.
- `.ai-playbook/` submodule present and pinned to a semver tag.
- `AGENTS.md` parses against `specs/agents-md-v1.schema.json`.
- `mcp-servers.yaml` layers render without drift.
- Required env vars per `specs/env-vars.md` are set.
- Context budget: total tokens of always-loaded files < 20000.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    print("ai-playbook doctor — stub (populated in T14a).")
    print("No checks run. Exit 0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
