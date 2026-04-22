"""Thin wrapper around `npx openspec validate` so consumers can call a single
Python entry point regardless of platform.

Populated in T11 + T09 (pre-commit integration). v0.1.0 stub.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    print("ai-playbook openspec_validate — stub (populated in T11).")
    print(f"Would run: npx @fission-ai/openspec@latest validate {' '.join(argv)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
