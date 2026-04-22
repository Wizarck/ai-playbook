"""Emit a structured event to JSONL log + OTel span.

Populated in T07c (OTel bootstrap). v0.1.0 stub.

Usage (future):
    python -m scripts.log_event \
        --name "qa.verdict" \
        --attrs '{"severity":"S1","verdict":"issues-found"}' \
        --trace-id <otel-trace-id>
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    print("ai-playbook log_event — stub (populated in T07c).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
