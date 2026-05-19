"""Auto-transition `Blocked` → `Todo` on dependency merge.

Per release-management.md §6.3: when a slice merges to main (Status: Done),
downstream slices whose entire `Depends on` set is now Done auto-transition
from Blocked to Todo. Without this, Wave 2+ slices stay Blocked long after
Wave 1 merged ("human-tracker-drift").

CLI
---
    python -m scripts.auto_transition_blocked_todo \\
        --owner Wizarck \\
        --project-number 2 \\
        --slicing-file docs/openspec-slice.md \\
        [--dry-run]

Reads the dependency graph from `docs/openspec-slice.md` (per
docs/concepts/bmad-openspec-bridge.md §3.1). Reuses `parse_slicing()` from
`bootstrap_gh_project.py` so the parser is one-source-of-truth.

For each item on the project board:
  - If Status == Blocked AND every item-id in its `Depends on` cell has
    Status == Done on the same project board:
        → transition Status: Blocked → Todo
  - Otherwise: skip (no-op).

Idempotent: re-running on an already-converged board is a no-op.
Designed to be invoked by `.github/workflows/project-status.yml` on every
push to main, but works equally well as a one-shot CLI.

Exit codes
----------
    0 — success (idempotent no-op or one or more transitions applied)
    2 — setup error (gh unavailable, project not found, slicing file missing)
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

# Reuse the parser + GraphQL helpers from bootstrap_gh_project so the
# slicing-file format and Status-field schema stay in lockstep.
from scripts.bootstrap_gh_project import (  # noqa: E402
    _emit,
    _gh_available,
    list_fields,
    list_items,
    lookup_project,
    parse_slicing,
    set_item_status,
)


def run(
    *,
    owner: str,
    project_number: int,
    slicing_file: Path,
    dry_run: bool,
) -> int:
    if not _gh_available():
        print("error: gh CLI not authenticated; run `gh auth login` first", file=sys.stderr)
        return 2

    if not slicing_file.is_file():
        print(f"error: slicing file not found at {slicing_file}", file=sys.stderr)
        return 2

    _emit(
        "auto_transition_blocked_todo.start",
        owner=owner,
        project_number=project_number,
        slicing_file=str(slicing_file),
        dry_run=dry_run,
    )

    try:
        proj = lookup_project(owner, project_number)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(f"→ Project: {proj.title} (#{proj.number}) under {proj.owner_login}")

    # Build dep graph: change-id → list of dep change-ids.
    try:
        rows = parse_slicing(slicing_file)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    deps: dict[str, list[str]] = {row.change_id: list(row.depends_on) for row in rows}
    print(f"→ Slicing artefact: {len(rows)} change rows parsed")

    # Read project state.
    fields = list_fields(proj.id)
    status_field = next((f for f in fields if f.name == "Status"), None)
    if status_field is None:
        print("error: project has no 'Status' field", file=sys.stderr)
        return 2

    items = list_items(proj.id)
    by_title = {it.title: it for it in items}
    status_by_title: dict[str, str | None] = {it.title: it.status for it in items}

    blocked_with_deps_done: list[tuple[str, str]] = []  # [(change_id, item_id)]
    skipped_blocked_unmet: list[tuple[str, list[str]]] = []
    skipped_other: list[str] = []

    for change_id, dep_list in deps.items():
        item = by_title.get(change_id)
        if item is None:
            # Not on the board (yet) — bootstrap will add it on next run.
            continue
        current = status_by_title.get(change_id)
        if current != "Blocked":
            skipped_other.append(change_id)
            continue
        # Walk deps: every one must be Done.
        unmet = [d for d in dep_list if status_by_title.get(d) != "Done"]
        if unmet:
            skipped_blocked_unmet.append((change_id, unmet))
            continue
        blocked_with_deps_done.append((change_id, item.id))

    # Apply transitions.
    transitioned = 0
    todo_option_id = status_field.options.get("Todo")
    if todo_option_id is None:
        print(
            "error: 'Todo' option not present in Status field; run bootstrap_gh_project first",
            file=sys.stderr,
        )
        return 2

    for change_id, item_id in blocked_with_deps_done:
        if dry_run:
            print(f"→ would transition {change_id}: Blocked → Todo (dry-run)")
        else:
            set_item_status(
                proj.id,
                item_id,
                status_field.id,
                todo_option_id,
                dry_run=dry_run,
            )
            print(f"→ {change_id}: Blocked → Todo")
        transitioned += 1
        _emit(
            "auto_transition_blocked_todo.transitioned",
            change_id=change_id,
            dry_run=dry_run,
        )

    # Diagnostics.
    print(
        f"✓ done — transitioned:+{transitioned}  "
        f"still-blocked:{len(skipped_blocked_unmet)}  "
        f"other-status:{len(skipped_other)}"
    )
    if skipped_blocked_unmet:
        print("→ Still Blocked (deps not yet Done):")
        for change_id, unmet in skipped_blocked_unmet[:10]:  # cap output
            print(f"    {change_id}: waiting on {', '.join(unmet)}")
        if len(skipped_blocked_unmet) > 10:
            print(f"    ... and {len(skipped_blocked_unmet) - 10} more")

    _emit(
        "auto_transition_blocked_todo.complete",
        transitioned=transitioned,
        still_blocked=len(skipped_blocked_unmet),
        other=len(skipped_other),
        dry_run=dry_run,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Auto-transition Blocked → Todo on dependency merge. "
            "Per release-management.md §6.3."
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
        "--dry-run",
        action="store_true",
        help="Print intended transitions without applying them",
    )
    args = p.parse_args(argv)

    try:
        return run(
            owner=args.owner,
            project_number=args.project_number,
            slicing_file=args.slicing_file,
            dry_run=args.dry_run,
        )
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        _emit("auto_transition_blocked_todo.failed", reason=str(e))
        return 3


if __name__ == "__main__":
    sys.exit(main())
