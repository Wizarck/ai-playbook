"""L1 hardrule: dispatcher-cursor (paired with docs/rules/dispatcher-cursor.rule.md).

Verifies that a consumer repository configured for Cursor ships a
`.cursor/rules/00-AGENTS.mdc` whose body delegates to `AGENTS.md` as the
canonical dispatcher.

The rule honours the LLM-agnostic invariant from `development-flow.md` §4:
CLI-specific routers (`CLAUDE.md`, `GEMINI.md`, `.cursor/rules/`) are pointers,
not content carriers.

CLI:
    python scripts/rules/dispatcher-cursor.rule.py validate
    python scripts/rules/dispatcher-cursor.rule.py apply [--dry-run]

Exit codes:
    0 — pointer present and well-formed, OR Cursor not in use here.
    1 — missing / oversized / content-carrier drift.
    2 — fatal (no readable consumer root).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

MAX_CONTENT_LINES = 30
SKIP_ENV = "AIPLAYBOOK_DISPATCHER_CURSOR_SKIP"

CANONICAL_CURSOR_MDC = """---
description: AGENTS.md is the canonical dispatcher
alwaysApply: true
---

# Cursor dispatcher pointer

This file is loaded by Cursor at session start. The canonical dispatcher is
[AGENTS.md](../../AGENTS.md) — follow its §0 bootstrap directive before any task.

For universal norms, this repo inherits from `.ai-playbook/docs/` (the
playbook submodule pinned to a semver tag).
"""


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: AIPLAYBOOK_DISPATCHER_CURSOR_SKIP=1", file=sys.stderr)


def _consumer_root(cwd: Path | None = None) -> Path | None:
    """Locate the consumer root: directory containing AGENTS.md."""
    cur = (cwd or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / "AGENTS.md").is_file():
            return p
    return None


def _cursor_in_use(root: Path) -> bool:
    """Heuristic: is this repo configured for Cursor?

    True iff the `.cursor/` directory exists at the consumer root. An existing
    `.cursor/rules/00-AGENTS.mdc` also implies opt-in (the rule's own artifact).
    """
    if (root / ".cursor").is_dir():
        return True
    if (root / ".cursor" / "rules" / "00-AGENTS.mdc").is_file():
        return True
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
    if not _cursor_in_use(root):
        return 0  # not applicable for this consumer

    pointer = root / ".cursor" / "rules" / "00-AGENTS.mdc"
    if not pointer.is_file():
        _emit_error(
            why=".cursor/rules/00-AGENTS.mdc missing",
            where=str(pointer),
            fix="run `python .ai-playbook/scripts/rules/dispatcher-cursor.rule.py apply`.",
        )
        return 1

    try:
        text = pointer.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _emit_error(why=str(exc), where=str(pointer), fix="check file permissions.")
        return 2

    if "AGENTS.md" not in text:
        _emit_error(
            why=".cursor/rules/00-AGENTS.mdc does not reference AGENTS.md",
            where=str(pointer),
            fix="add a pointer line: `[AGENTS.md](../../AGENTS.md)`.",
        )
        return 1

    if _content_line_count(text) > MAX_CONTENT_LINES:
        _emit_error(
            why=f".cursor/rules/00-AGENTS.mdc exceeds {MAX_CONTENT_LINES} content lines (content-carrier drift)",
            where=str(pointer),
            fix="trim to a thin pointer; move content to AGENTS.md.",
        )
        return 1

    return 0


def _sibling_agents_pointers(root: Path) -> list[Path]:
    """Return other `.cursor/rules/*.mdc` files that reference AGENTS.md.

    These are likely pre-existing custom routers that became redundant once
    the canonical ``00-AGENTS.mdc`` is in place. Surfaced as a warning (not
    an error) so the operator can decide whether to delete them.
    """
    rules_dir = root / ".cursor" / "rules"
    if not rules_dir.is_dir():
        return []
    canonical = rules_dir / "00-AGENTS.mdc"
    siblings: list[Path] = []
    for path in sorted(rules_dir.glob("*.mdc")):
        if path == canonical:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "AGENTS.md" in text:
            siblings.append(path)
    return siblings


def _warn_sibling_routers(siblings: list[Path]) -> None:
    if not siblings:
        return
    print(
        f"warn: {len(siblings)} other .cursor/rules/*.mdc file(s) also reference "
        "AGENTS.md and may now be redundant routers:",
        file=sys.stderr,
    )
    for path in siblings:
        print(f"  - {path}", file=sys.stderr)
    print(
        "  Review by hand; delete duplicates so Cursor loads only the canonical "
        "00-AGENTS.mdc.",
        file=sys.stderr,
    )


def apply(*, dry_run: bool, cwd: Path | None = None) -> int:
    """Write a canonical `.cursor/rules/00-AGENTS.mdc` when missing. Idempotent.

    If the pointer already exists but is malformed, the rule refuses to
    overwrite — the operator must reconcile by hand. This prevents `apply`
    from clobbering hand-edited customisations.

    On any non-error outcome (canonical-already / dry-run / fresh-write), also
    warn (rc=0) when other `.cursor/rules/*.mdc` files reference AGENTS.md —
    those are likely redundant routers from before this rule existed.
    """
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2
    pointer = root / ".cursor" / "rules" / "00-AGENTS.mdc"

    if pointer.is_file():
        # Idempotency: existing canonical content → no-op success.
        try:
            current = pointer.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"error: cannot read {pointer}: {exc}", file=sys.stderr)
            return 2
        if current.strip() == CANONICAL_CURSOR_MDC.strip():
            print(f"ok: {pointer} already canonical (no-op)")
            _warn_sibling_routers(_sibling_agents_pointers(root))
            return 0
        print(
            f"refuse: {pointer} exists with non-canonical content; "
            "reconcile by hand or delete and re-run apply.",
            file=sys.stderr,
        )
        return 1

    if dry_run:
        print(f"[dry-run] would write {pointer} ({_content_line_count(CANONICAL_CURSOR_MDC)} content lines)")
        _warn_sibling_routers(_sibling_agents_pointers(root))
        return 0

    try:
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(CANONICAL_CURSOR_MDC, encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write {pointer}: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {pointer}")
    _warn_sibling_routers(_sibling_agents_pointers(root))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dispatcher-cursor")
    parser.add_argument("subcommand", choices=["validate", "apply"])
    parser.add_argument("--dry-run", action="store_true", help="With 'apply': print plan, mutate nothing.")
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    if args.subcommand == "apply":
        return apply(dry_run=args.dry_run)
    return 2


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("dispatcher-cursor", main))
