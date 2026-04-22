"""Recall project context from Hindsight MCP and inject it into the agent session.

Populated in T12. v0.1.0 stub.

Reads Hindsight creds from SOPS-decrypted env (see `specs/env-vars.md`).
Calls `hindsight.recall(query, bank_id=<project>, top_k=5)`.
Writes results to `.claude/injected-context.md` (consumed by SessionStart hook).
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    print("ai-playbook inject_context — stub (populated in T12).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
