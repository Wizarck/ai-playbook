"""Helper to emit an OTel span with `gen_ai.*` attributes.

Populated in T07c. v0.1.0 stub.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    print("ai-playbook tracing/trace_emit — stub (populated in T07c).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
