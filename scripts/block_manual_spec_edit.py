"""Pre-commit hook: block manual edits to `openspec/specs/*.md`.

Populated in T11 + T09. v0.1.0 stub.

The OpenSpec workflow mandates that `specs/` are updated only via
`openspec archive`. Direct edits create drift between proposal → archive.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    print("ai-playbook block_manual_spec_edit — stub (populated in T09).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
