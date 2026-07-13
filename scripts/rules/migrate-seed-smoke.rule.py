"""L1 hardrule: migrate-seed-smoke (paired with docs/rules/migrate-seed-smoke.rule.md).

Verifies the migrate→seed contract: a consumer repo that has BOTH an alembic
migrations tree AND a DB seed script (e2e fixtures) must exercise them together
in CI — a job that applies migrations to a FRESH database and then runs the
seed (twice, for idempotency). Without it, a migration that adds a NOT NULL
column the seeder never learned about explodes days later in the e2e job of an
unrelated PR (geeplo 2026-07-13: 0070/0072 vs bootstrap-test-db.py), instead of
failing the schema-changing PR itself in one minute.

Validate-only: workflows are too heterogeneous for a safe auto-append. A
drop-in job lives at `templates/ci/migrate-seed-smoke.yml`.

CLI:
    python scripts/rules/migrate-seed-smoke.rule.py validate

Exit codes:
    0 — contract exercised in CI, OR rule not applicable (no alembic tree,
        or no seed script).
    1 — alembic + seed exist but no workflow runs `alembic upgrade head`
        together with the seed script.
    2 — fatal (no consumer root).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SKIP_ENV = "AIPLAYBOOK_MIGRATE_SEED_SMOKE_SKIP"
_SKIP_DIRS = {"node_modules", ".venv", "venv", ".git", "__pycache__", ".next"}
_SEED_GLOBS = ("bootstrap*db*.py", "seed*db*.py", "*seed*.py")


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(f"   OVERRIDE: {SKIP_ENV}=1", file=sys.stderr)


def _consumer_root(cwd: Path | None = None) -> Path | None:
    """Locate the consumer root: directory containing AGENTS.md."""
    cur = (cwd or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / "AGENTS.md").is_file():
            return p
    return None


def _has_alembic_tree(root: Path) -> bool:
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        p = Path(dirpath)
        if p.name == "versions" and p.parent.name in ("alembic", "migrations"):
            return True
    return False


def _seed_scripts(root: Path) -> list[Path]:
    """Seed candidates: scripts/ dirs at root or one level down (backend/scripts)."""
    found: list[Path] = []
    candidates = [root / "scripts"]
    for child in root.iterdir() if root.is_dir() else []:
        if child.is_dir() and child.name not in _SKIP_DIRS:
            candidates.append(child / "scripts")
    for scripts_dir in candidates:
        if not scripts_dir.is_dir():
            continue
        for pattern in _SEED_GLOBS:
            found.extend(scripts_dir.glob(pattern))
    # de-dup, stable order
    return sorted(set(found))


def _workflow_texts(root: Path) -> list[tuple[Path, str]]:
    wf_dir = root / ".github" / "workflows"
    if not wf_dir.is_dir():
        return []
    out: list[tuple[Path, str]] = []
    for path in sorted(wf_dir.glob("*.y*ml")):
        try:
            out.append((path, path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return out


def validate(cwd: Path | None = None) -> int:
    if os.environ.get(SKIP_ENV) == "1":
        print(f"skip: {SKIP_ENV}=1")
        return 0

    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2

    if not _has_alembic_tree(root):
        print("ok: no alembic migrations tree (rule not applicable)")
        return 0

    seeds = _seed_scripts(root)
    if not seeds:
        print("ok: no DB seed script found (rule not applicable)")
        return 0

    workflows = _workflow_texts(root)
    seed_names = [s.name for s in seeds]
    for path, text in workflows:
        if "alembic upgrade head" in text and any(name in text for name in seed_names):
            print(f"ok: migrate→seed contract exercised in {path.name}")
            return 0

    _emit_error(
        why=(
            "alembic migrations + seed script "
            f"({', '.join(seed_names)}) exist, but no CI workflow applies "
            "migrations to a fresh DB and runs the seed"
        ),
        where=str(root / ".github" / "workflows"),
        fix=(
            "add the smoke job from "
            ".ai-playbook/templates/ci/migrate-seed-smoke.yml (fresh postgres "
            "service → alembic upgrade head → seed twice)."
        ),
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="migrate-seed-smoke")
    parser.add_argument("subcommand", choices=["validate"])
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    return 2


if __name__ == "__main__":
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("migrate-seed-smoke", main))
