#!/usr/bin/env python3
"""budget_disable_check.py — sentinel-flag check for agentic budget gate.

Used by hermes-wrapper.sh and other agentic LLM callers to decide whether
to refuse a call because a provider's monthly budget has been exhausted.

The flag is created by:
  - langgraph-aiops/workflows/cost_reporter.py (node_evaluate_thresholds) when
    a provider crosses the 100% (fatal) tier with agentic_disable_on=fatal
  - eligia-core/scripts/litellm-alert-drainer.py when LiteLLM reports a
    "credit balance is too low" error for a provider

The flag is cleared by:
  - dashboard/backend/routes/cost.py DELETE /cost/budget/flags/{provider}
    (admin-token gated)
  - manual `rm /var/lib/eligia/budget-disabled-{provider}.flag` on VPS

Usage as a library:
    from budget_disable_check import is_disabled
    if is_disabled("anthropic"):
        ...

Usage as a CLI (for shell scripts like hermes-wrapper.sh):
    python3 budget_disable_check.py anthropic
    # exit 0 if disabled, exit 1 if enabled (idiomatic shell test inversion)
"""

from __future__ import annotations

import os
import sys

FLAG_DIR_DEFAULT = "/var/lib/eligia"


def flag_path(provider: str, flag_dir: str | None = None) -> str:
    """Return the canonical sentinel-flag path for a provider."""
    base = flag_dir or os.environ.get("ELIGIA_FLAG_DIR", FLAG_DIR_DEFAULT)
    return os.path.join(base, f"budget-disabled-{provider}.flag")


def is_disabled(provider: str, flag_dir: str | None = None) -> bool:
    """Return True if the agentic gate is closed for this provider."""
    return os.path.isfile(flag_path(provider, flag_dir))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: budget_disable_check.py <provider>", file=sys.stderr)
        return 2
    return 0 if is_disabled(args[0]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
