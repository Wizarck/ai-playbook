"""Cost report aggregator (token spend by project / model / task class).

Populated in T14f. v0.1.0 stub.

Reads from Langfuse + OTel Collector backends (T07c), joins spans by trace_id,
rolls up by project → model → task_class per day/week/month.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    print("ai-playbook cost_report — stub (populated in T14f).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
