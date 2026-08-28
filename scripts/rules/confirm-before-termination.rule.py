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

# THE REMEDY MUST BE PERFORMABLE FROM THE GATED TOOL. Measured 2026-08-17: an
# agent with the user's explicit yes wrote `export OVERRIDE=...; Stop-Process`
# and was blocked AGAIN -- the hook evaluates BEFORE the shell runs, so an
# inline export can never reach the hook's os.environ. A gate whose documented
# remedy cannot be performed is the impossible-remedy shape of #166. Two
# performable channels, both leaving an audited reason:
#
#   1. Bash: the override ASSIGNMENT written inline in the gated command
#      itself (the transcript then carries the reason next to the kill).
#   2. Harness stop tools (no command string to carry anything): a ONE-SHOT
#      receipt file written by a prior command and consumed on use, so one
#      confirmation authorises exactly one stop.
#
# The hook-env path still works where a wrapper genuinely exports first.
_INLINE_OVERRIDE_RE = re.compile(
    re.escape(OVERRIDE_ENV) + r"=(?P<q>[\"']?)(?P<reason>[^\"'\s;|&]+)(?P=q)"
)

# Harness tools that stop/kill a running background task or shell.
_STOP_TOOLS = {"TaskStop", "KillShell", "BashOutputKill"}

# Process/job-control + irreversible verbs issued through Bash.
_KILL_PATTERNS = [
    r"\bkill\b", r"\bkillall\b", r"\bpkill\b", r"\btaskkill\b",
    r"\bStop-Process\b",
    r"\bdocker\s+(stop|kill|rm)\b",
    # Compose: both spellings, and the verb may sit behind global flags
    # (`-p proj`, `-f a.yml`). v2 is `docker compose` (space) — the hyphenated
    # v1 pattern never matched it, so `docker compose down -v`, which destroys
    # volumes, walked straight through the gate.
    r"\bdocker[-\s]+compose\s+(?:-{1,2}[\w-]+(?:[=\s]+[^\s]+)?\s+)*(down|stop|kill|rm)\b",
    # Deleting a live k8s workload is the cluster-native equivalent of
    # `docker rm`, and was ungated entirely.
    r"\bkubectl\s+delete\b",
    r"\bsystemctl\s+stop\b", r"\bservice\s+\S+\s+stop\b",
    r"\bsupervisorctl\s+stop\b", r"\bpm2\s+(stop|kill|delete)\b",
    r"\bscancel\b",
]
_KILL_RE = re.compile("|".join(_KILL_PATTERNS), re.IGNORECASE)


def _override_active() -> bool:
    return bool(os.environ.get(OVERRIDE_ENV, "").strip())


def _inline_override(cmd: str) -> bool:
    """True when the gated command itself carries a non-empty override reason."""
    return bool(_INLINE_OVERRIDE_RE.search(cmd))


def _receipt_path() -> "os.PathLike[str] | str":
    import tempfile
    from pathlib import Path

    return Path(tempfile.gettempdir()) / "aiplaybook-termination-receipt"


def _consume_receipt() -> bool:
    """One confirmation authorises exactly one stop: read AND delete.

    Fail closed on any surprise -- a receipt that cannot be read or removed
    must not authorise anything, or a stuck file becomes a standing override.
    """
    from pathlib import Path

    p = Path(_receipt_path())
    try:
        if not p.is_file() or not p.read_text(encoding="utf-8").strip():
            return False
        p.unlink()
        return True
    except OSError:
        return False


def pretooluse(event: dict):
    """In-process L1 hook: veto a termination tool call lacking user consent."""
    from scripts.rules._hook_contract import allow, bash_command, block, tool_name

    name = tool_name(event)

    # 1) Harness-level stop of a running background task / shell.
    if name in _STOP_TOOLS:
        if _override_active() or _consume_receipt():
            return allow()
        return block(
            f"Refusing to stop a running task/shell ({name}) without explicit user "
            "confirmation. A request to *check/investigate* is NOT authority to "
            "terminate. Report -> recommend -> ask the user; only after a yes, "
            f"write the one-shot receipt: echo <short reason> > "
            f"{_receipt_path()} (it authorises exactly one stop)."
        )

    # 2) Process/job termination issued through Bash.
    if name == "Bash":
        cmd = bash_command(event)
        if cmd and _KILL_RE.search(cmd):
            if _override_active() or _inline_override(cmd):
                return allow()
            return block(
                "Refusing a process/job-termination command without explicit user "
                f"confirmation: {cmd!r}. Ask the user first; only after a yes, "
                f"re-run with the reason INLINE in the same command: "
                f"{OVERRIDE_ENV}=<short-reason> <your command>. An `export` in a "
                "prior or same call cannot work -- this hook runs before the "
                "shell does."
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
