"""Drift detection across playbook, consumer-d add-on, and consumer AGENTS.md files.

Populated in T17 (live docs) + T22 (governance). v0.1.0 stub.

Checks:
- `inherits_from` pin is at or above playbook's minimum supported version.
- No duplicate rules between playbook `specs/` and consumer `AGENTS.md`
  (consumer should point, not copy).
- Auto-managed sections (BEGIN/END markers) match their source.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    print("ai-playbook drift_check — stub (populated in T17).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
