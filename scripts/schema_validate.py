"""Validate an AGENTS.md frontmatter against specs/agents-md-v1.schema.json.

Populated in T03a + T03b (migration path for v0 files). v0.1.0 stub.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    print("ai-playbook schema_validate — stub (populated in T03a).")
    if argv:
        print(f"Would validate: {argv[0]}")
    else:
        print("Usage: python -m scripts.schema_validate <path/to/AGENTS.md>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
