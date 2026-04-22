"""Bootstrap a new consumer project with the ai-playbook submodule.

Populated in T14a. v0.1.0 is a runnable stub that prints intent and exits 0.

Usage (future):
    python -m scripts.bootstrap <project-name> [--from-template new-project]
"""
from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    print("ai-playbook bootstrap — stub (populated in T14a).")
    print(f"Received args: {argv}")
    print(f"Playbook root: {Path(__file__).resolve().parents[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
