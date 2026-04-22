"""Lint an artifact (review, readiness check, proposal) for verdict + severity compliance.

Populated in T05 + T09 (pre-commit). v0.1.0 stub.

Enforces:
- Exactly one of ✅ APPROVED / ⚠️ ISSUES FOUND / ❓ CLARIFICATION NEEDED.
- If ⚠️, every issue carries an explicit severity S1..S4.
- S0 rejected unless caller passes --audit.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    print("ai-playbook verdict_lint — stub (populated in T05).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
