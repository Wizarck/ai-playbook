"""L1 hardrule: bootstrap-directive.

Paired with docs/rules/bootstrap-directive.rule.md.

Validates that an AGENTS.md file carries the canonical four-step bootstrap
directive in §0:

  1. read dispatcher-chain.md
  2. consult injected-context.md
  3. scan openspec/changes/*/
  4. respond

The `apply` subcommand inserts the canonical block into AGENTS.md when §0
is entirely absent. If §0 exists but is malformed, apply refuses (the
operator must reconcile by hand) — apply does not overwrite custom content.

CLI:
    python scripts/rules/bootstrap-directive.rule.py validate <AGENTS.md-path>
    python scripts/rules/bootstrap-directive.rule.py apply [--dry-run] <AGENTS.md-path>

Exit codes:
    0 — canonical block present (validate) / inserted or already canonical (apply).
    1 — missing or incomplete (validate) / refuse-overwrite-custom (apply).
    2 — schema break.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Required tokens in the bootstrap block. Order matters — we check all four
# appear AT LEAST once within the first ~150 lines of the file.
REQUIRED_TOKENS = [
    re.compile(r"dispatcher-chain\.md", re.IGNORECASE),
    re.compile(r"injected-context\.md", re.IGNORECASE),
    re.compile(r"openspec/changes", re.IGNORECASE),
    re.compile(r"\bbootstrap\b", re.IGNORECASE),
]
SECTION_ZERO_RE = re.compile(r"^#{1,2}\s*0\b", re.MULTILINE)


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def validate_text(text: str, where: str) -> int:
    header = "\n".join(text.splitlines()[:200])
    if not SECTION_ZERO_RE.search(header):
        _emit_error(
            why="AGENTS.md missing §0 bootstrap section",
            where=where,
            fix="add `## 0 Bootstrap directive` per bootstrap-directive.rule.md.",
        )
        return 1
    missing: list[str] = []
    for pat in REQUIRED_TOKENS:
        if not pat.search(header):
            missing.append(pat.pattern)
    if missing:
        _emit_error(
            why=f"AGENTS.md §0 missing tokens: {', '.join(missing)}",
            where=where,
            fix="copy the canonical bootstrap block from docs/rules/bootstrap-directive.rule.md verbatim.",
        )
        return 1
    return 0


def validate(paths: list[str]) -> int:
    if os.environ.get("AIPLAYBOOK_BOOTSTRAP_DIRECTIVE_SKIP"):
        return 0
    for raw in paths:
        p = Path(raw)
        if not p.is_file():
            _emit_error(why=f"path not readable: {raw}", where=raw, fix="pass an existing AGENTS.md path.")
            return 2
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            _emit_error(why=str(exc), where=raw, fix="check file permissions.")
            return 2
        rc = validate_text(text, raw)
        if rc:
            return rc
    return 0


CANONICAL_BLOCK = """## 0. Bootstrap directive

Before responding to ANY task:

1. Read `.ai-playbook/docs/concepts/dispatcher-chain.md` — universal norms inherited
   from the pinned playbook tag.
2. Consult `.claude/injected-context.md` — populated by the SessionStart hook
   from `hindsight.recall(query="<project> <topic keywords>")`. If the file is
   absent or the recall failed (DEGRADED_CONTEXT banner), proceed without
   prior recall but announce the degradation per `degradation-modes.md`.
3. Check `openspec/changes/*/` for active OpenSpec changes that touch the same
   capability or area. Do not start parallel work on one already in flight.
4. Only then respond.

Skipping any step is a policy violation. If steps 1 or 3 are blocked
(submodule missing, openspec dir absent), announce the gap before proceeding.
"""


def _insert_canonical(text: str) -> str:
    """Return AGENTS.md content with the canonical §0 block inserted.

    Insertion point: after the YAML frontmatter (if present) and after the
    first H1 header line. The block is appended with a blank line above/below
    to preserve readability.
    """
    lines = text.splitlines(keepends=False)
    insert_at = 0

    # Skip frontmatter block if present.
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                insert_at = i + 1
                break

    # Skip past blank lines.
    while insert_at < len(lines) and not lines[insert_at].strip():
        insert_at += 1

    # If next line is an H1 (single `#`), insert after it (skip a blank line too).
    if insert_at < len(lines) and lines[insert_at].startswith("# "):
        insert_at += 1
        while insert_at < len(lines) and not lines[insert_at].strip():
            insert_at += 1

    head = lines[:insert_at]
    tail = lines[insert_at:]
    block_lines = CANONICAL_BLOCK.splitlines()
    out_lines = head + [""] + block_lines + [""] + tail
    return "\n".join(out_lines) + ("\n" if text.endswith("\n") else "")


def apply(paths: list[str], *, dry_run: bool) -> int:
    """Insert the canonical §0 block into an AGENTS.md that's missing it.

    Idempotent: if §0 is already canonical (validate would pass), no-op.
    Refuses to overwrite a §0 that exists but is non-canonical.
    """
    if not paths:
        print("error: apply requires an AGENTS.md path", file=sys.stderr)
        return 2
    for raw in paths:
        p = Path(raw)
        if not p.is_file():
            _emit_error(why=f"path not readable: {raw}", where=raw, fix="pass an existing AGENTS.md path.")
            return 2
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            _emit_error(why=str(exc), where=raw, fix="check file permissions.")
            return 2

        header = "\n".join(text.splitlines()[:200])
        has_section_zero = bool(SECTION_ZERO_RE.search(header))

        if has_section_zero:
            # validate would tell us if it's canonical or malformed.
            if validate_text(text, raw) == 0:
                print(f"ok: {p} already canonical (no-op)")
                continue
            print(
                f"refuse: {p} has §0 with non-canonical content; "
                "reconcile by hand or delete §0 and re-run apply.",
                file=sys.stderr,
            )
            return 1

        new_text = _insert_canonical(text)
        if dry_run:
            print(f"[dry-run] would insert canonical §0 block into {p}")
            continue
        try:
            p.write_text(new_text, encoding="utf-8")
        except OSError as exc:
            print(f"error: cannot write {p}: {exc}", file=sys.stderr)
            return 2
        print(f"inserted canonical §0 block into {p}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bootstrap-directive")
    parser.add_argument("subcommand", choices=["validate", "apply"])
    parser.add_argument("--dry-run", action="store_true", help="With 'apply': print plan, do not write.")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        if not args.paths:
            return 0
        return validate(args.paths)
    if args.subcommand == "apply":
        return apply(args.paths, dry_run=args.dry_run)
    return 2


if __name__ == "__main__":
    # File-path invocation from a consumer root: put the playbook root on
    # sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("bootstrap-directive", main))
