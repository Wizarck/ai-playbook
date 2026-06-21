"""L1 hardrule: confirm-before-termination (paired with docs/rules/confirm-before-termination.rule.md).

Blocks an agent from ending in-flight work without explicit user confirmation:
process/job kills issued through Bash (kill, pkill, docker stop, systemctl stop,
...) AND background-task/shell stops issued through the harness stop tools
(TaskStop / KillShell / BashOutputKill). The only way through is the audited
break-glass env ``AIPLAYBOOK_CONFIRM_BEFORE_TERMINATION_OVERRIDE``, which the
agent may set ONLY after the user has said yes — it records a confirmation, it
does not skip one.

CLI:
    python scripts/rules/confirm-before-termination.rule.py validate

Exit codes:
    0 — nothing to flag (validate is a no-op; enforcement is at PreToolUse).
    2 — schema break / fatal.
"""
from __future__ import annotations

import argparse
import os
import re

OVERRIDE_ENV = "AIPLAYBOOK_CONFIRM_BEFORE_TERMINATION_OVERRIDE"

# Harness tools that stop/kill a running background task or shell.
_STOP_TOOLS = {"TaskStop", "KillShell", "BashOutputKill"}

# Process/job-control + irreversible verbs issued through Bash.
_KILL_PATTERNS = [
    r"\bkill\b", r"\bkillall\b", r"\bpkill\b", r"\btaskkill\b",
    r"\bStop-Process\b",
    r"\bdocker\s+(stop|kill|rm)\b", r"\bdocker-compose\s+(down|stop|kill)\b",
    r"\bsystemctl\s+stop\b", r"\bservice\s+\S+\s+stop\b",
    r"\bsupervisorctl\s+stop\b", r"\bpm2\s+(stop|kill|delete)\b",
    r"\bscancel\b",
]
_KILL_RE = re.compile("|".join(_KILL_PATTERNS), re.IGNORECASE)


def _override_active() -> bool:
    return bool(os.environ.get(OVERRIDE_ENV, "").strip())


def pretooluse(event: dict):
    """In-process L1 hook: veto a termination tool call lacking user consent."""
    from scripts.rules._hook_contract import allow, bash_command, block, tool_name

    name = tool_name(event)

    # 1) Harness-level stop of a running background task / shell.
    if name in _STOP_TOOLS:
        if _override_active():
            return allow()
        return block(
            f"Refusing to stop a running task/shell ({name}) without explicit user "
            "confirmation. A request to *check/investigate* is NOT authority to "
            "terminate. Report -> recommend -> ask the user; only after a yes set "
            f"{OVERRIDE_ENV}=<short reason> for this single action."
        )

    # 2) Process/job termination issued through Bash.
    if name == "Bash":
        cmd = bash_command(event)
        if cmd and _KILL_RE.search(cmd):
            if _override_active():
                return allow()
            return block(
                "Refusing a process/job-termination command without explicit user "
                f"confirmation: {cmd!r}. Ask the user first; only after a yes set "
                f"{OVERRIDE_ENV}=<short reason>."
            )

    return allow()


def validate() -> int:
    """No-op: this rule enforces at PreToolUse, not on a static tree."""
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="confirm-before-termination")
    parser.add_argument("subcommand", choices=["validate"])
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    return 2


if __name__ == "__main__":
    # File-path invocation from a consumer root: put the playbook root on
    # sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("confirm-before-termination", main))
