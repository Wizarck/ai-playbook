"""Hard enforcement of slice dependency graph at PR merge time.

Per release-management.md §6.2: a PR for slice X cannot merge until every
change-id in X's `Depends on` column has Status: Done on the project
board. This script is the OPT-IN hard gate (the soft gate is the PR body's
"Dependency check" section, manually verified by reviewer).

CLI
---
    python -m scripts.check_slice_dependencies \\
        --owner Wizarck \\
        --project-number 2 \\
        --slicing-file docs/openspec-slice.md \\
        --change-id <slice-name>

Designed to be invoked by `.github/workflows/dep-check.yml` on every PR
to main targeting `slice/<change-id>`. The workflow extracts the slice
change-id from `github.head_ref` and passes it via `--change-id`.

Resolution
----------
For the given `<change-id>`:
  1. Look up the slicing-artefact row → list of dep change-ids.
  2. For each dep, look up its Status on the project board.
  3. If any dep has Status != Done: FAIL (exit 1) with a structured
     summary listing which deps are still Blocked / In Progress / Review.
  4. If all deps are Done OR the slice has no deps: PASS (exit 0).

Exit codes
----------
    0 — all deps Done; merge OK
    1 — at least one dep not yet Done; merge BLOCKED
    2 — setup error (gh unavailable, project not found, slicing file missing,
        change-id not in slicing artefact)
    3 — unrecoverable GraphQL error
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Force UTF-8 stdio.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.bootstrap_gh_project import (  # noqa: E402
    _emit,
    _gh_available,
    list_items,
    lookup_project,
    parse_slicing,
)


def run(
    *,
    owner: str,
    project_number: int,
    slicing_file: Path,
    change_id: str,
) -> int:
    if not _gh_available():
        print("error: gh CLI not authenticated; run `gh auth login` first", file=sys.stderr)
        return 2

    if not slicing_file.is_file():
        print(f"error: slicing file not found at {slicing_file}", file=sys.stderr)
        return 2

    _emit(
        "check_slice_dependencies.start",
        owner=owner,
        project_number=project_number,
        slicing_file=str(slicing_file),
        change_id=change_id,
    )

    try:
        proj = lookup_project(owner, project_number)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    try:
        rows = parse_slicing(slicing_file)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    by_change: dict[str, list[str]] = {row.change_id: list(row.depends_on) for row in rows}
    if change_id not in by_change:
        print(
            f"error: change-id {change_id!r} not found in {slicing_file}. "
            f"Either the branch name doesn't match a row, or the slice plan "
            f"hasn't been updated.",
            file=sys.stderr,
        )
        _emit(
            "check_slice_dependencies.failed",
            reason="change-id not in slicing",
            change_id=change_id,
        )
        return 2

    deps = by_change[change_id]
    if not deps:
        print(f"✓ {change_id}: no declared dependencies; merge OK")
        _emit("check_slice_dependencies.no_deps", change_id=change_id)
        return 0

    items = list_items(proj.id)
    status_by_title = {it.title: it.status for it in items}

    not_done: list[tuple[str, str | None]] = []  # [(dep_change_id, current_status)]
    for dep in deps:
        status = status_by_title.get(dep)
        if status != "Done":
            not_done.append((dep, status))

    if not not_done:
        print(f"✓ {change_id}: all {len(deps)} dependencies are Done; merge OK")
        for dep in deps:
            print(f"    {dep}: Done")
        _emit("check_slice_dependencies.pass", change_id=change_id, deps=len(deps))
        return 0

    # FAIL: structured output for CI annotations.
    print(f"❌ {change_id}: {len(not_done)} of {len(deps)} dependencies not yet Done")
    print("   Merge blocked until ALL dependencies reach Status: Done on project board.")
    print()
    print("   Dependency status:")
    for dep in deps:
        status = status_by_title.get(dep) or "<not-on-board>"
        marker = "✓" if status == "Done" else "✗"
        print(f"     {marker} {dep}: {status}")
    print()
    print("   FIX: wait for the upstream slice(s) to merge, OR re-slice if the")
    print("        dependency was incorrectly declared (Gate C re-open).")
    print()
    print("   See release-management.md §6.2 for the dependency-driven merge order.")

    _emit(
        "check_slice_dependencies.fail",
        change_id=change_id,
        not_done=[(d, s) for d, s in not_done],
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Check whether all dependencies of an OpenSpec change-id have "
            "Status: Done on the project board, per release-management.md §6.2."
        )
    )
    p.add_argument("--owner", required=True, help="GH user or org login")
    p.add_argument("--project-number", required=True, type=int)
    p.add_argument(
        "--slicing-file",
        type=Path,
        default=Path("docs/openspec-slice.md"),
        help="Path to the slicing artefact (default: docs/openspec-slice.md)",
    )
    p.add_argument(
        "--change-id",
        required=True,
        help="OpenSpec change-id (kebab-case folder name under openspec/changes/)",
    )
    args = p.parse_args(argv)

    try:
        return run(
            owner=args.owner,
            project_number=args.project_number,
            slicing_file=args.slicing_file,
            change_id=args.change_id,
        )
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        _emit("check_slice_dependencies.failed", reason=str(e))
        return 3


if __name__ == "__main__":
    sys.exit(main())
