"""L1 hardrule: openspec-scaffold (paired with docs/rules/openspec-scaffold.rule.md).

Verifies that a consumer using the openspec workflow keeps the canonical
scaffold (`openspec/changes/` and `openspec/specs/`) present at the root,
even when empty. The rule is structural only — it does NOT inspect file
content (that is the job of sibling rules like `openspec-apply-enforcement`
and `block_manual_spec_edit.py`).

CLI:
    python scripts/rules/openspec-scaffold.rule.py validate
    python scripts/rules/openspec-scaffold.rule.py apply [--dry-run]

Exit codes:
    0 — both canonical subdirectories present, OR openspec not in use.
    1 — one or both canonical subdirectories missing.
    2 — fatal (no consumer root, path-type drift, unwritable filesystem).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SKIP_ENV = "AIPLAYBOOK_OPENSPEC_SCAFFOLD_SKIP"
OPENSPEC_REL = Path("openspec")
CANONICAL_SUBDIRS = (Path("changes"), Path("specs"))


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(f"   OVERRIDE: {SKIP_ENV}=1", file=sys.stderr)


def _consumer_root(cwd: Path | None = None) -> Path | None:
    """Locate the consumer root: nearest ancestor containing AGENTS.md."""
    cur = (cwd or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / "AGENTS.md").is_file():
            return p
    return None


def _openspec_in_use(root: Path) -> bool:
    """Heuristic: is this repo using the openspec workflow?

    True iff:
      - `openspec/` directory exists at root, OR
      - `AGENTS.md` references `openspec/changes/`.
    """
    if (root / OPENSPEC_REL).is_dir():
        return True
    agents = root / "AGENTS.md"
    if agents.is_file():
        try:
            if "openspec/changes" in agents.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            pass
    return False


def _missing_subdirs(root: Path) -> list[Path]:
    """Return canonical subdirs that are NOT present as directories."""
    base = root / OPENSPEC_REL
    out: list[Path] = []
    for sub in CANONICAL_SUBDIRS:
        if not (base / sub).is_dir():
            out.append(sub)
    return out


def _path_type_drift(root: Path) -> Path | None:
    """Return the first canonical path that exists as a non-directory (e.g. a file)."""
    base = root / OPENSPEC_REL
    if base.exists() and not base.is_dir():
        return base
    for sub in CANONICAL_SUBDIRS:
        p = base / sub
        if p.exists() and not p.is_dir():
            return p
    return None


def validate(cwd: Path | None = None) -> int:
    if os.environ.get(SKIP_ENV):
        return 0
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2

    if not _openspec_in_use(root):
        return 0  # not applicable for this consumer

    drift = _path_type_drift(root)
    if drift is not None:
        _emit_error(
            why=f"path exists but is not a directory: {drift}",
            where=str(drift),
            fix="remove or rename the conflicting file, then re-run apply.",
        )
        return 2

    missing = _missing_subdirs(root)
    if missing:
        listed = ", ".join(f"openspec/{m.as_posix()}/" for m in missing)
        _emit_error(
            why=f"canonical openspec subdirectories missing: {listed}",
            where=str(root / OPENSPEC_REL),
            fix="run `python .ai-playbook/scripts/rules/openspec-scaffold.rule.py apply`.",
        )
        return 1

    return 0


def apply(*, dry_run: bool, cwd: Path | None = None) -> int:
    """Create any missing canonical subdirectories. Idempotent.

    Uses `Path.mkdir(parents=True, exist_ok=True)` so a converged state is
    a true no-op (no FS mutation, exit 0). Refuses to proceed on path-type
    drift (a canonical name occupied by a non-directory).
    """
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2

    drift = _path_type_drift(root)
    if drift is not None:
        print(
            f"refuse: {drift} exists and is not a directory; "
            "remove or rename it by hand before re-running apply.",
            file=sys.stderr,
        )
        return 2

    base = root / OPENSPEC_REL
    targets = [base / sub for sub in CANONICAL_SUBDIRS]
    to_create = [t for t in targets if not t.is_dir()]

    if not to_create:
        print(f"ok: {base} already canonical (no-op)")
        return 0

    if dry_run:
        for t in to_create:
            print(f"[dry-run] would mkdir -p {t}")
        return 0

    for t in to_create:
        try:
            t.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"error: cannot create {t}: {exc}", file=sys.stderr)
            return 2
        print(f"created {t}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openspec-scaffold")
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
    raise SystemExit(cli_emit("openspec-scaffold", main))
