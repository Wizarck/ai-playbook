"""L1 hardrule: dispatcher-gemini (paired with docs/rules/dispatcher-gemini.rule.md).

Verifies that a consumer repository configured for Gemini CLI ships a top-level
`GEMINI.md` whose body delegates to `AGENTS.md` as the canonical dispatcher.

The rule honours the LLM-agnostic invariant from `development-flow.md` §4:
CLI-specific routers (`CLAUDE.md`, `GEMINI.md`, `.cursor/rules/`) are pointers,
not content carriers.

CLI:
    python scripts/rules/dispatcher-gemini.rule.py validate
    python scripts/rules/dispatcher-gemini.rule.py apply [--dry-run]

Exit codes:
    0 — pointer present and well-formed, OR Gemini not in use here.
    1 — missing / oversized / content-carrier drift.
    2 — fatal (no readable consumer root).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

MAX_CONTENT_LINES = 30
SKIP_ENV = "AIPLAYBOOK_DISPATCHER_GEMINI_SKIP"

CANONICAL_GEMINI_MD = """# GEMINI.md — Gemini CLI dispatcher

This file is read by Gemini CLI sessions. The canonical dispatcher is
[AGENTS.md](AGENTS.md) — follow its §0 bootstrap directive before any task.

For universal norms, this repo inherits from `.ai-playbook/docs/` (the
playbook submodule pinned to a semver tag).
"""


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: AIPLAYBOOK_DISPATCHER_GEMINI_SKIP=1", file=sys.stderr)


def _consumer_root(cwd: Path | None = None) -> Path | None:
    """Locate the consumer root: directory containing AGENTS.md and (typically) .gitmodules."""
    cur = (cwd or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / "AGENTS.md").is_file():
            return p
    return None


def _gemini_in_use(root: Path) -> bool:
    """Heuristic: is this repo configured for Gemini CLI?

    True iff any of the following holds:
      - `.gemini/` directory exists at root.
      - `mcp-servers.yaml` mentions `gemini`.
      - `GEMINI.md` already exists (an existing pointer means the repo opted in).
    """
    if (root / ".gemini").is_dir():
        return True
    if (root / "GEMINI.md").is_file():
        return True
    mcp = root / "mcp-servers.yaml"
    if mcp.is_file():
        try:
            if "gemini" in mcp.read_text(encoding="utf-8", errors="replace").lower():
                return True
        except OSError:
            pass
    return False


def _content_line_count(text: str) -> int:
    """Count non-empty, non-whitespace-only lines."""
    return sum(1 for ln in text.splitlines() if ln.strip())


def validate(cwd: Path | None = None) -> int:
    if os.environ.get(SKIP_ENV):
        return 0
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2
    if not _gemini_in_use(root):
        return 0  # not applicable for this consumer

    gemini_md = root / "GEMINI.md"
    if not gemini_md.is_file():
        _emit_error(
            why="GEMINI.md missing",
            where=str(gemini_md),
            fix="run `python .ai-playbook/scripts/rules/dispatcher-gemini.rule.py apply`.",
        )
        return 1

    try:
        text = gemini_md.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _emit_error(why=str(exc), where=str(gemini_md), fix="check file permissions.")
        return 2

    if "AGENTS.md" not in text:
        _emit_error(
            why="GEMINI.md does not reference AGENTS.md",
            where=str(gemini_md),
            fix="add a pointer line: `[AGENTS.md](AGENTS.md)`.",
        )
        return 1

    if _content_line_count(text) > MAX_CONTENT_LINES:
        _emit_error(
            why=f"GEMINI.md exceeds {MAX_CONTENT_LINES} content lines (content-carrier drift)",
            where=str(gemini_md),
            fix="trim to a thin pointer; move content to AGENTS.md.",
        )
        return 1

    return 0


def apply(*, dry_run: bool, cwd: Path | None = None) -> int:
    """Write a canonical `GEMINI.md` when missing. Idempotent.

    If `GEMINI.md` already exists but is malformed, the rule refuses to
    overwrite — the operator must reconcile by hand. This prevents the
    `apply` from clobbering hand-edited customisations.
    """
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2
    gemini_md = root / "GEMINI.md"

    if gemini_md.is_file():
        # Idempotency: existing canonical content → no-op success.
        try:
            current = gemini_md.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"error: cannot read {gemini_md}: {exc}", file=sys.stderr)
            return 2
        if current.strip() == CANONICAL_GEMINI_MD.strip():
            print(f"ok: {gemini_md} already canonical (no-op)")
            return 0
        print(
            f"refuse: {gemini_md} exists with non-canonical content; "
            "reconcile by hand or delete and re-run apply.",
            file=sys.stderr,
        )
        return 1

    if dry_run:
        print(f"[dry-run] would write {gemini_md} ({_content_line_count(CANONICAL_GEMINI_MD)} content lines)")
        return 0

    try:
        gemini_md.write_text(CANONICAL_GEMINI_MD, encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write {gemini_md}: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {gemini_md}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dispatcher-gemini")
    parser.add_argument("subcommand", choices=["validate", "apply"])
    parser.add_argument("--dry-run", action="store_true", help="With 'apply': print plan, mutate nothing.")
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    if args.subcommand == "apply":
        return apply(dry_run=args.dry_run)
    return 2


if __name__ == "__main__":
    # File-path invocation from a consumer root: put the playbook root on
    # sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("dispatcher-gemini", main))
