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
import subprocess
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


def _record(revisions: dict[str, object], parents: set[str], revision: object, down: object, src: object) -> None:
    """Fold one migration's (revision, down_revision) into the maps."""
    if isinstance(revision, str):
        revisions.setdefault(revision, src)
    if isinstance(down, str):
        parents.add(down)
    elif isinstance(down, tuple):
        parents.update(d for d in down if isinstance(d, str))


def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError) as exc:
        return 1, str(exc)
    return proc.returncode, proc.stdout if proc.returncode == 0 else proc.stderr


def _resolve_auto_base(directory: Path) -> str | None:
    """Auto-detect the base ref to union against — no `main`/`origin` assumption.

    Remote: ``origin`` if present, else the sole remote, else None. Branch: the
    remote's published default via ``symbolic-ref .../HEAD`` (handles
    main/master/trunk/develop), falling back to probing those names when
    ``<remote>/HEAD`` is unset (common in shallow CI clones). Returns e.g.
    ``origin/master`` or None when nothing resolves.
    """
    rc, top = _git(["rev-parse", "--show-toplevel"], cwd=directory)
    if rc != 0:
        return None
    root = Path(top.strip())
    rc, remotes_out = _git(["remote"], cwd=root)
    if rc != 0:
        return None
    remotes = [r.strip() for r in remotes_out.splitlines() if r.strip()]
    if not remotes:
        return None
    remote = "origin" if "origin" in remotes else (remotes[0] if len(remotes) == 1 else None)
    if remote is None:
        return None
    rc, head = _git(["symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD"], cwd=root)
    if rc == 0 and head.strip():
        # refs/remotes/<remote>/<branch> -> <remote>/<branch>
        return head.strip().removeprefix("refs/remotes/")
    for branch in ("main", "master", "trunk", "develop"):
        rc, _ = _git(["rev-parse", "--verify", "--quiet", f"{remote}/{branch}"], cwd=root)
        if rc == 0:
            return f"{remote}/{branch}"
    return None


def _base_dir_entries(directory: Path, ref: str) -> list[tuple[object, object]]:
    """Read the directory's migrations AS THEY EXIST ON ``ref`` (e.g. origin/main).

    Returns a list of (revision, down_revision) for every migration file under
    ``directory`` in ``ref``. Lets the head computation union the base's chain
    with the working tree's — so a fork created by ANOTHER branch that already
    merged into ``ref`` is caught WITHOUT a local rebase. Degrades to ``[]`` (with
    a stderr notice) when ``directory`` is not in a git work tree or ``ref`` is
    unknown — the check then falls back to working-tree-only.
    """
    rc, top = _git(["rev-parse", "--show-toplevel"], cwd=directory)
    if rc != 0:
        print(f"⚠ alembic-single-head: --base skipped — not a git work tree ({directory})", file=sys.stderr)
        return []
    root = Path(top.strip())
    try:
        rel = directory.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return []
    rc, listing = _git(["ls-tree", "-r", "--name-only", ref, "--", rel], cwd=root)
    if rc != 0:
        print(f"⚠ alembic-single-head: --base skipped — ref '{ref}' not resolvable", file=sys.stderr)
        return []
    entries: list[tuple[object, object]] = []
    for line in listing.splitlines():
        name = line.strip()
        if not name.endswith(".py") or name.rsplit("/", 1)[-1] == "__init__.py":
            continue
        # Only files DIRECTLY in the dir (migrations are flat under versions/).
        if name.rsplit("/", 1)[0] != rel:
            continue
        frc, text = _git(["show", f"{ref}:{name}"], cwd=root)
        if frc != 0:
            continue
        revision, down, shaped = _extract(text)
        if shaped:
            entries.append((revision, down))
    return entries


def check_dir(directory: Path, base_ref: str | None = None) -> int:
    """Single-head check over the migrations in ``directory``.

    When ``base_ref`` is given, the working tree's migrations are UNIONED with
    the same directory's migrations on ``base_ref`` before computing heads —
    modelling "what ``base_ref`` looks like after merging this branch". This is
    what catches a fork introduced by a sibling branch that already merged into
    the base, which a working-tree-only check on a non-rebased branch misses.
    """
    files = _migration_files(directory)
    if not files and base_ref is None:
        return 0

    revisions: dict[str, object] = {}
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
        _record(revisions, parents, revision, down, p)

    resolved_ref: str | None = None
    if base_ref is not None:
        resolved_ref = _resolve_auto_base(directory) if base_ref == "auto" else base_ref
        if resolved_ref is None:
            print(
                "⚠ alembic-single-head: --base auto could not resolve a base "
                f"branch for {directory}; falling back to working-tree-only",
                file=sys.stderr,
            )
        else:
            for revision, down in _base_dir_entries(directory, resolved_ref):
                _record(revisions, parents, revision, down, None)

    if not revisions:
        return rc

    heads = sorted(rev for rev in revisions if rev not in parents)
    if len(heads) > 1:
        head_list = ", ".join(heads)
        scope = f"{directory} (unioned with {resolved_ref})" if resolved_ref else str(directory)
        _emit_error(
            why=f"{len(heads)} alembic heads present ({head_list})",
            where=scope,
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


def validate(paths: list[str], base_ref: str | None = None) -> int:
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
        rc = max(rc, check_dir(d, base_ref=base_ref))
    return rc


def main(argv: list[str] | None = None) -> int:
    if os.environ.get(OVERRIDE_ENV):
        return 0
    parser = argparse.ArgumentParser(prog="alembic-single-head")
    # Subparser (not a bare choices-positional + nargs="*" sibling): on CPython
    # 3.11/3.12 a single positional followed by a `nargs="*"` positional fails to
    # consume the trailing args ("unrecognized arguments: <path>"); 3.13 fixed it.
    # A subparser is the version-robust shape (matches scripts/caveman/cli.py).
    sub = parser.add_subparsers(dest="subcommand", required=True)
    v = sub.add_parser("validate", help="Verify the migration chain resolves to one head.")
    v.add_argument(
        "--base",
        default=None,
        metavar="GITREF",
        help=(
            "Union the working tree's migrations with the same directory's "
            "migrations on GITREF before computing heads, so a fork already "
            "merged into the base is caught without a local rebase. The special "
            "value `auto` resolves the remote's default branch (origin or the "
            "sole remote; main/master/trunk/develop) — no `main`/`origin` "
            "assumption. Or pin a ref explicitly (e.g. `--base upstream/release`). "
            "Run `git fetch` first."
        ),
    )
    v.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    return validate(args.paths, base_ref=args.base)


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit

    raise SystemExit(cli_emit("alembic-single-head", main))
