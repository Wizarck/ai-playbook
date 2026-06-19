"""L1 hardrule: gitignore-entries (paired with docs/rules/gitignore-entries.rule.md).

Verifies the consumer's root `.gitignore` contains the playbook-managed entries
for break-glass audit state, notification queue, and hindsight queue. These
files are per-consumer/per-developer runtime state and MUST NOT be committed.

CLI:
    python scripts/rules/gitignore-entries.rule.py validate
    python scripts/rules/gitignore-entries.rule.py apply [--dry-run]

Exit codes:
    0 — `.gitignore` contains all required entries.
    1 — missing file or one+ required entries.
    2 — fatal (no readable consumer root).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SKIP_ENV = "AIPLAYBOOK_GITIGNORE_ENTRIES_SKIP"

REQUIRED_ENTRIES: tuple[str, ...] = (
    ".ai-playbook/.ai-playbook-state/",
    "notifications.jsonl",
    "hindsight-queue.jsonl",
)

MANAGED_HEADER = "# === ai-playbook managed entries (do not remove) ==="


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: AIPLAYBOOK_GITIGNORE_ENTRIES_SKIP=1", file=sys.stderr)


def _consumer_root(cwd: Path | None = None) -> Path | None:
    """Locate the consumer root: directory containing AGENTS.md."""
    cur = (cwd or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / "AGENTS.md").is_file():
            return p
    return None


def _read_gitignore(gitignore: Path) -> str | None:
    if not gitignore.is_file():
        return None
    try:
        return gitignore.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _missing_entries(text: str) -> list[str]:
    """Return required entries that do NOT appear as a line in `text`.

    Matches against trimmed lines; ignores comment lines (leading '#').
    """
    present: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        present.add(line)
    return [e for e in REQUIRED_ENTRIES if e not in present]


def validate(cwd: Path | None = None) -> int:
    if os.environ.get(SKIP_ENV):
        return 0
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2
    gitignore = root / ".gitignore"
    text = _read_gitignore(gitignore)
    if text is None:
        _emit_error(
            why=".gitignore missing or unreadable",
            where=str(gitignore),
            fix="run `python .ai-playbook/scripts/rules/gitignore-entries.rule.py apply`.",
        )
        return 1

    missing = _missing_entries(text)
    if missing:
        _emit_error(
            why=f".gitignore missing required entries: {', '.join(missing)}",
            where=str(gitignore),
            fix="run `python .ai-playbook/scripts/rules/gitignore-entries.rule.py apply`.",
        )
        return 1
    return 0


def apply(*, dry_run: bool, cwd: Path | None = None) -> int:
    """Append missing playbook-managed entries to `.gitignore`. Idempotent.

    Existing content is preserved verbatim; missing entries are appended at
    the END under a managed comment header. Running `apply` twice on a
    converged state is a no-op.
    """
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2
    gitignore = root / ".gitignore"

    existing = _read_gitignore(gitignore)
    if existing is None:
        existing = ""

    missing = _missing_entries(existing)
    if not missing:
        print(f"ok: {gitignore} already contains all required entries (no-op)")
        return 0

    # Build the appended block.
    sep = "" if (existing == "" or existing.endswith("\n")) else "\n"
    block_lines = [MANAGED_HEADER, *missing]
    appended = sep + ("\n" if existing else "") + "\n".join(block_lines) + "\n"
    new_text = existing + appended

    if dry_run:
        print(f"[dry-run] would append {len(missing)} entry(ies) to {gitignore}:")
        for e in missing:
            print(f"           + {e}")
        return 0

    try:
        gitignore.write_text(new_text, encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write {gitignore}: {exc}", file=sys.stderr)
        return 2
    print(f"appended {len(missing)} entry(ies) to {gitignore}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gitignore-entries")
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
    raise SystemExit(cli_emit("gitignore-entries", main))
