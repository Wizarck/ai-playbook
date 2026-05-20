"""L1 hardrule: mcp-render (paired with docs/rules/mcp-render.rule.md).

Verifies that the consumer's rendered MCP configs (`.mcp.json`,
`.gemini/settings.json`) are fresh relative to `mcp-servers.yaml` (the SSOT).
Detection is mtime-based — `apply` delegates to the existing renderer at
`scripts/mcp/render.py`.

CLI:
    python scripts/rules/mcp-render.rule.py validate
    python scripts/rules/mcp-render.rule.py apply [--dry-run]

Exit codes:
    0 — renders fresh, or no SSOT here (not applicable).
    1 — renders missing or stale (drift).
    2 — fatal (renderer crashed, filesystem error).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SKIP_ENV = "AIPLAYBOOK_MCP_RENDER_SKIP"

# Files maintained by the renderer.
CLAUDE_TARGET = ".mcp.json"
GEMINI_TARGET = ".gemini/settings.json"
SSOT_NAME = "mcp-servers.yaml"


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(f"   OVERRIDE: {SKIP_ENV}=1", file=sys.stderr)


def _consumer_root(cwd: Path | None = None) -> Path | None:
    """Locate the consumer root: walk up for AGENTS.md."""
    cur = (cwd or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / "AGENTS.md").is_file():
            return p
    return None


def _is_stale(ssot: Path, render: Path) -> bool:
    """True if SSOT is newer than the render, or the render is missing."""
    if not render.is_file():
        return True
    try:
        return ssot.stat().st_mtime > render.stat().st_mtime
    except OSError:
        return True


def _uses_gemini(root: Path) -> bool:
    """Heuristic: does the consumer use Gemini? `.gemini/` dir or GEMINI.md exists."""
    return (root / ".gemini").is_dir() or (root / "GEMINI.md").is_file()


def validate(cwd: Path | None = None) -> int:
    if os.environ.get(SKIP_ENV):
        return 0
    root = _consumer_root(cwd)
    if root is None:
        return 0  # not a consumer here
    ssot = root / SSOT_NAME
    if not ssot.is_file():
        return 0  # no MCP servers configured — not applicable

    claude_target = root / CLAUDE_TARGET
    drift_targets: list[str] = []
    if _is_stale(ssot, claude_target):
        drift_targets.append(CLAUDE_TARGET)
    if _uses_gemini(root):
        gemini_target = root / GEMINI_TARGET
        if _is_stale(ssot, gemini_target):
            drift_targets.append(GEMINI_TARGET)

    if not drift_targets:
        return 0

    _emit_error(
        why=f"rendered MCP config stale or missing: {', '.join(drift_targets)}",
        where=str(root),
        fix="run `python .ai-playbook/scripts/rules/mcp-render.rule.py apply`.",
    )
    return 1


def apply(*, dry_run: bool, cwd: Path | None = None) -> int:
    """Delegate to scripts.mcp.render, optionally with --dry-run."""
    root = _consumer_root(cwd)
    if root is None:
        print("ok: no consumer root here (not applicable)")
        return 0
    ssot = root / SSOT_NAME
    if not ssot.is_file():
        print(f"ok: no {SSOT_NAME} found at {root} (not applicable)")
        return 0

    # Discover the playbook root: prefer the submodule, fall back to the
    # script's own location (dogfood mode when running inside ai-playbook).
    submodule = root / ".ai-playbook"
    if submodule.is_dir():
        playbook_root = submodule
    else:
        playbook_root = Path(__file__).resolve().parent.parent.parent

    cmd = [sys.executable, "-m", "scripts.mcp.render"]
    if dry_run:
        cmd.append("--dry-run")

    env = {**os.environ, "PYTHONPATH": str(playbook_root)}
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            env=env,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        print("error: renderer timed out after 60s", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: invoking renderer: {exc}", file=sys.stderr)
        return 2
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mcp-render")
    parser.add_argument("subcommand", choices=["validate", "apply"])
    parser.add_argument("--dry-run", action="store_true", help="With 'apply': print rendered output, do not write.")
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    if args.subcommand == "apply":
        return apply(dry_run=args.dry_run)
    return 2


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("mcp-render", main))
