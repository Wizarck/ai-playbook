"""L1 hardrule: alembic-single-head.

Paired with docs/rules/alembic-single-head.rule.md.

Validates that an Alembic migrations directory resolves to EXACTLY ONE head.
A forked chain with two or more heads makes ``alembic upgrade head`` abort
with "Multiple head revisions are present", which breaks deploys, the CI
migrate step, and any container entrypoint that runs ``alembic upgrade head``
(e.g. ``sh -c "alembic upgrade head && uvicorn ..."``).

Static analysis only — no live database and no ``alembic`` install required,
so it runs in pre-commit and CI without a DB. Each migration file is parsed
with the ``ast`` module to extract the ``revision`` and ``down_revision``
literals; a head is any revision that no other migration names as a parent.

A file argument is resolved to its parent directory and the WHOLE directory is
checked, so editing a single migration triggers a full single-head check of
its ``versions/`` folder.

CLI:
    python scripts/rules/alembic-single-head.rule.py validate [<dir-or-file> ...]

With no path arguments it auto-discovers migration directories under the cwd
(``alembic/versions``, ``**/migrations/versions``, ``**/migrations``).

Exit codes:
    0 — every checked directory has exactly one head (or holds no migrations).
    1 — a directory has multiple heads, OR a file in a migrations directory has
        no parsable ``revision`` (an empty/orphaned migration also aborts
        ``alembic heads`` with "Could not determine revision id from filename").
    2 — schema break (a passed path is not readable).
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
from pathlib import Path

OVERRIDE_ENV = "AIPLAYBOOK_ALEMBIC_SINGLE_HEAD_SKIP"


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(f"   OVERRIDE: {OVERRIDE_ENV}=1 (audited)", file=sys.stderr)


def _literal(node: ast.expr | None) -> object:
    """Best-effort literal eval of a revision/down_revision RHS.

    Handles ``"x"``, ``None``, and tuples/lists of strings (merge nodes). Any
    non-literal (a name, call, f-string) yields ``...`` (Ellipsis) meaning
    "present but undeterminable" — treated as no constraint.
    """
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.Tuple, ast.List)):
        out: list[object] = []
        for elt in node.elts:
            if isinstance(elt, ast.Constant):
                out.append(elt.value)
            else:
                return ...  # undeterminable element
        return tuple(out)
    return ...


def _extract(text: str) -> tuple[object, object, bool]:
    """Return (revision, down_revision, is_migration_shaped).

    ``revision`` / ``down_revision`` are ``...`` when the assignment is absent.
    ``is_migration_shaped`` is True when EITHER name is assigned at module level
    — i.e. the file looks like an Alembic migration even if a value is missing
    (an empty/orphaned file assigns neither and is NOT migration-shaped).
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ..., ..., False
    revision: object = ...
    down: object = ...
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        for tgt in targets:
            if isinstance(tgt, ast.Name) and tgt.id == "revision":
                revision = _literal(value)
            elif isinstance(tgt, ast.Name) and tgt.id == "down_revision":
                down = _literal(value)
    shaped = revision is not ... or down is not ...
    return revision, down, shaped


def _migration_files(directory: Path) -> list[Path]:
    return [p for p in sorted(directory.glob("*.py")) if p.name != "__init__.py"]


def check_dir(directory: Path) -> int:
    """Single-head check over every migration file directly in ``directory``."""
    files = _migration_files(directory)
    if not files:
        return 0

    revisions: dict[str, Path] = {}
    parents: set[str] = set()
    rc = 0

    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            _emit_error(why=str(exc), where=str(p), fix="check file permissions.")
            rc = max(rc, 2)
            continue
        revision, down, shaped = _extract(text)
        if not shaped:
            # A .py file in a migrations dir with neither revision nor
            # down_revision is either a non-migration helper (harmless) or an
            # empty/orphaned migration. We can only distinguish by emptiness:
            # a 0-byte / whitespace-only file is the orphan that breaks
            # `alembic heads`.
            if not text.strip():
                _emit_error(
                    why=f"empty/orphaned migration file {p.name} (no revision id)",
                    where=str(p),
                    fix="delete the orphaned file or restore its revision/down_revision.",
                )
                rc = max(rc, 1)
            continue
        if isinstance(revision, str):
            revisions[revision] = p
        if isinstance(down, str):
            parents.add(down)
        elif isinstance(down, tuple):
            parents.update(d for d in down if isinstance(d, str))

    if not revisions:
        return rc

    heads = sorted(rev for rev in revisions if rev not in parents)
    if len(heads) > 1:
        head_list = ", ".join(heads)
        _emit_error(
            why=f"{len(heads)} alembic heads present ({head_list})",
            where=str(directory),
            fix=(
                'add a no-op merge node — `alembic merge -m "merge heads" '
                f"{heads[0]} {heads[1]}` — so `alembic upgrade head` resolves "
                "to one head."
            ),
        )
        rc = max(rc, 1)
    return rc


def _discover_dirs(root: Path) -> list[Path]:
    seen: set[Path] = set()
    for pattern in ("**/alembic/versions", "**/migrations/versions", "**/migrations"):
        for d in root.glob(pattern):
            if d.is_dir() and _migration_files(d):
                seen.add(d.resolve())
    return sorted(seen)


def validate(paths: list[str]) -> int:
    targets: list[Path] = []
    if not paths:
        targets = _discover_dirs(Path.cwd())
    else:
        dirs: set[Path] = set()
        for raw in paths:
            p = Path(raw)
            if p.is_dir():
                dirs.add(p)
            elif p.is_file():
                dirs.add(p.parent)
            else:
                _emit_error(
                    why=f"path not readable: {p}",
                    where=str(p),
                    fix="pass an existing migrations directory or file.",
                )
                return 2
        targets = sorted(dirs)

    rc = 0
    for d in targets:
        rc = max(rc, check_dir(d))
    return rc


def main(argv: list[str] | None = None) -> int:
    if os.environ.get(OVERRIDE_ENV):
        return 0
    parser = argparse.ArgumentParser(prog="alembic-single-head")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    return validate(args.paths)


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit

    raise SystemExit(cli_emit("alembic-single-head", main))
