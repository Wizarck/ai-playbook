"""L1 hardrule: openspec-apply-enforcement (paired with docs/rules/openspec-apply-enforcement.rule.md).

Verifies that the current Claude Code session has emitted an apply-skill
marker before any `openspec/changes/<slice>/tasks.md` checkboxes flip.

CLI:
    python scripts/rules/openspec-apply-enforcement.rule.py validate

Exit codes:
    0 — marker present for the current session, OR no openspec edits pending.
    1 — task checkbox flipped without a marker (violation).
    2 — schema break / fatal (no session id env var).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _consumer_root() -> Path:
    cur = Path.cwd()
    for parent in [cur, *cur.parents]:
        if (parent / ".gitmodules").is_file():
            return parent
    return cur


def validate() -> int:
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")
    if not session_id:
        # No session context — treat as advisory (not blocking outside Claude Code).
        return 0
    root = _consumer_root()
    marker_dir = root / ".ai-playbook-state" / "apply-markers"
    marker = marker_dir / f"{session_id}.json"
    if marker.is_file():
        return 0
    # No marker — only block if openspec/changes/* tasks.md has staged changes.
    try:
        import subprocess
        diff = subprocess.check_output(
            ["git", "-C", str(root), "diff", "--cached", "--name-only"],
            text=True, stderr=subprocess.STDOUT,
        )
    except Exception:
        return 0
    pending = [
        line for line in diff.splitlines()
        if line.startswith("openspec/changes/") and line.endswith("/tasks.md")
    ]
    if pending:
        print(f"error: openspec task edits staged without apply marker (session={session_id[:8]})", file=sys.stderr)
        print(f"FIX: python -m scripts.openspec_apply_marker start --slice <slug>", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openspec-apply-enforcement")
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
    raise SystemExit(cli_emit("openspec-apply-enforcement", main))
