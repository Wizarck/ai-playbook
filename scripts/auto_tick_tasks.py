"""auto_tick_tasks — auto-tick `tasks.md` checkboxes from a conventional-commit subject.

Implements Followup #4 Option 1 (recommended path per
docs/concepts/v0.9.0-roadmap.md): when a developer or agent commits with a
conventional-commit subject naming task identifiers (groups, sections,
or task numbers), the matching `- [ ]` checkboxes in
`openspec/changes/<active>/tasks.md` are flipped to `- [x]` and the
file is staged in the same commit.

Why
---
Filed as Followup #4 (consumer-e slice 3, PR #57): a slice was
merged with 0/55 boxes ticked despite being feature-complete (30
tests + 95% coverage + mypy strict + pre-commit clean). Soft
"remember to tick" guidance does not survive long runs of code+test
cycles. Auto-ticking from the commit subject lifts the discipline
into a determinist, auditable channel.

CLI
---
    python -m scripts.auto_tick_tasks <commit-msg-file> [--change-id <id>]

The script is invoked from `.git/hooks/prepare-commit-msg`. It reads
the commit message from <commit-msg-file>, parses the subject, locates
the active OpenSpec change (either via --change-id, or by inspecting
the current branch name `<type>/<change-id>`), opens
`openspec/changes/<change-id>/tasks.md`, ticks matching boxes, and
re-stages the file via `git add` (so it lands in the same commit).

Subject parsing rules
---------------------
The script extracts task identifiers from the commit subject in any
of these formats (case-insensitive, all may appear in the same
subject):

- `groups N-M`   → ticks all tasks in groups N..M (inclusive).
- `group N`      → ticks all tasks in group N.
- `§N`           → ticks all tasks in section §N.
- `§N.M`         → ticks all tasks in section §N.M (and sub-sections).
- `task N` or `task N.M` → ticks the named task only.
- `tasks N,M,O` or `tasks N-M` → ticks the named tasks (range or list).

If the subject contains none of these and no --change-id is supplied,
the script is a no-op (exit 0). Soft contract: missing task references
≠ failure; the hook never blocks commits.

Idempotent
----------
Running the script twice in the same commit pass leaves the file
unchanged after the first pass (already-ticked `- [x]` boxes are
skipped). Running it after the boxes were ticked manually is also
safe.

Exit codes
----------
    0  success (boxes ticked, or nothing to tick — both are OK)
    1  parse error in tasks.md
    2  setup error (commit-msg file missing, etc.)
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Force UTF-8 stdio.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


CONV_COMMIT_RE = re.compile(
    r"^(?P<type>feat|fix|chore|docs|refactor|test|release|build|ci|perf|style|revert)"
    r"(?:\((?P<scope>[^)]+)\))?"
    r"(?P<bang>!)?"
    r":\s*(?P<subject>.+)$",
    re.IGNORECASE,
)

GROUPS_RANGE_RE = re.compile(r"\bgroups?\s+(\d+)(?:[-–](\d+))?\b", re.IGNORECASE)
SECTION_RE = re.compile(r"§(\d+)(?:\.(\d+))?")
TASKS_RE = re.compile(r"\btasks?\s+(\d+(?:[\d,\s.-]*\d)?)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Subject parser
# ---------------------------------------------------------------------------


def parse_subject(subject: str) -> dict[str, set[str]]:
    """Extract task references from a commit subject.

    Returns a dict with keys:
      groups   — set of {"1", "2", ...} for `groups N-M` or `group N`
      sections — set of {"1", "1.2", ...} for `§N` or `§N.M`
      tasks    — set of {"1", "2.3", ...} for `task N` / `tasks N,M`

    Empty sets when no references are found.
    """
    found: dict[str, set[str]] = {"groups": set(), "sections": set(), "tasks": set()}

    # Groups
    for m in GROUPS_RANGE_RE.finditer(subject):
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        for n in range(start, end + 1):
            found["groups"].add(str(n))

    # Sections — `§N` adds section "N"; `§N.M` adds BOTH section "N.M" AND
    # task "N.M". Rationale: in markdown tasks.md files, `§3.1` is often a
    # task numbered 3.1 inside a `## §3` header rather than a `### §3.1`
    # subsection. Matching both surfaces makes the parser robust to either
    # convention.
    for m in SECTION_RE.finditer(subject):
        major, minor = m.group(1), m.group(2)
        if minor is not None:
            found["sections"].add(f"{major}.{minor}")
            found["tasks"].add(f"{major}.{minor}")
        else:
            found["sections"].add(major)

    # Tasks (comma / dash / mixed)
    for m in TASKS_RE.finditer(subject):
        raw = m.group(1)
        # Split by comma; each token may itself be a range "1-3".
        for token in raw.replace(" ", "").split(","):
            if not token:
                continue
            if "-" in token or "–" in token:
                # Range
                parts = re.split(r"[-–]", token, maxsplit=1)
                try:
                    start = int(parts[0])
                    end = int(parts[1]) if len(parts) > 1 else start
                    for n in range(start, end + 1):
                        found["tasks"].add(str(n))
                except ValueError:
                    pass
            else:
                # Single task ref (may be like "2.3" — keep as string)
                found["tasks"].add(token)

    return found


# ---------------------------------------------------------------------------
# Active change resolver
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


def get_current_branch(cwd: Path) -> str:
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)


def resolve_change_id(branch: str) -> str | None:
    """Extract change-id from `<type>/<change-id>` branch name."""
    if "/" not in branch:
        return None
    parts = branch.split("/", 1)
    if parts[0] not in {"feat", "fix", "chore", "docs", "refactor", "test", "release"}:
        return None
    return parts[1] or None


# ---------------------------------------------------------------------------
# tasks.md ticker
# ---------------------------------------------------------------------------


def tick_tasks_md(
    tasks_path: Path,
    *,
    refs: dict[str, set[str]],
) -> tuple[bool, list[str]]:
    """Tick boxes matching the refs in tasks.md.

    Returns (changed, ticked_descriptions). The function is conservative:
    it only ticks boxes whose enclosing section / group / task header
    matches a ref. Already-ticked boxes are no-ops.

    The matching strategy is heuristic by design — markdown structure in
    `tasks.md` varies. Rules:
      - Group headers (`## Group N` / `### Group N` / `## N. ...`) scope
        the boxes that follow until the next same-or-shallower header.
      - Section headers (`§N` / `§N.M` / `## N.M ...`) scope similarly.
      - Task lines (`- [ ] N. ...`) match individual task refs.
    """
    if not tasks_path.is_file():
        return False, []

    text = tasks_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    ticked: list[str] = []
    new_lines: list[str] = []

    # State: track current scope (active group or section) at each header depth.
    # Depth = number of leading `#` chars. A new heading at depth D resets all
    # sibling scopes (anything tracked at the same or shallower depth than D-1
    # stays valid; D itself replaces). For the MVP we treat group AND section
    # as mutually exclusive at the SAME depth: a new heading at depth D resets
    # whichever is tracked at depth ≥ D.
    current_group: str | None = None
    current_group_depth: int = 0
    current_section: str | None = None
    current_section_depth: int = 0
    in_matching_scope = False

    heading_depth_re = re.compile(r"^(#+)\s")
    group_header_re = re.compile(r"^#+\s*(?:group\s+)?(\d+)\b", re.IGNORECASE)
    section_header_re = re.compile(r"^#+\s*§?(\d+(?:\.\d+)?)\b")
    # Match `- [ ] N.M.K? <rest>` or `- [ ] N.M.K?. <rest>` capturing the
    # dotted task number when present. The trailing period is optional (some
    # files write `1.1 Task`, some `1.1. Task`).
    task_box_re = re.compile(
        r"^(\s*-\s*)\[ \](\s+(?:(\d+(?:\.\d+)*)\.?\s+)?.*)$"
    )

    for line in lines:
        # Header detection — re-evaluate scope.
        depth_m = heading_depth_re.match(line)
        if depth_m:
            depth = len(depth_m.group(1))
            # Any new heading at depth D invalidates same-or-shallower siblings.
            if current_group_depth and depth <= current_group_depth:
                current_group = None
                current_group_depth = 0
            if current_section_depth and depth <= current_section_depth:
                current_section = None
                current_section_depth = 0

            gh = group_header_re.match(line)
            sh = section_header_re.match(line)
            if gh:
                current_group = gh.group(1)
                current_group_depth = depth
            elif sh:
                current_section = sh.group(1)
                current_section_depth = depth

        # Compute whether current scope matches refs.
        in_matching_scope = False
        if current_group and current_group in refs["groups"]:
            in_matching_scope = True
        if current_section:
            # Section refs may match at any level (1.2 matches "1.2" or "1").
            if current_section in refs["sections"]:
                in_matching_scope = True
            else:
                # Check if any ref is a prefix of current_section (ref "1" matches "1.2").
                for ref_sec in refs["sections"]:
                    if current_section.startswith(ref_sec + ".") or current_section == ref_sec:
                        in_matching_scope = True
                        break

        # Box ticking.
        tb = task_box_re.match(line)
        if tb:
            prefix, suffix, task_num = tb.group(1), tb.group(2), tb.group(3)
            should_tick = False

            # Scope-based tick (group / section).
            if in_matching_scope:
                should_tick = True

            # Per-task ref tick.
            if task_num and task_num in refs["tasks"]:
                should_tick = True

            if should_tick:
                new_line = f"{prefix}[x]{suffix}"
                new_lines.append(new_line)
                ticked.append(new_line.strip())
                continue

        new_lines.append(line)

    new_text = "\n".join(new_lines)
    if text.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"

    if new_text == text:
        return False, ticked  # ticked may be empty

    tasks_path.write_text(new_text, encoding="utf-8")
    return True, ticked


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="auto_tick_tasks",
        description=(
            "Tick tasks.md checkboxes matching refs in a commit subject. "
            "Invoked from .git/hooks/prepare-commit-msg."
        ),
    )
    parser.add_argument(
        "commit_msg_file",
        type=Path,
        help="Path to the commit message file (passed by prepare-commit-msg hook).",
    )
    parser.add_argument(
        "--change-id",
        default=None,
        help="Override the active OpenSpec change-id (else inferred from branch).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root (defaults to git rev-parse --show-toplevel).",
    )
    parser.add_argument(
        "--no-stage",
        action="store_true",
        help="Do not `git add` the modified tasks.md (testing).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress informational output. Errors still print to stderr.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if not args.commit_msg_file.is_file():
        print(
            f"❌ commit-msg file not found: {args.commit_msg_file}",
            file=sys.stderr,
        )
        return 2

    try:
        subject_text = args.commit_msg_file.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"❌ cannot read commit-msg file: {exc}", file=sys.stderr)
        return 2

    # Subject = first non-empty, non-comment line.
    subject = ""
    for raw_line in subject_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        subject = line
        break

    if not subject:
        if not args.quiet:
            print("auto_tick_tasks: empty commit subject; nothing to do.")
        return 0

    m = CONV_COMMIT_RE.match(subject)
    if not m:
        if not args.quiet:
            print(
                f"auto_tick_tasks: subject '{subject[:60]}...' is not a "
                "conventional commit; nothing to do.",
            )
        return 0

    refs = parse_subject(m.group("subject"))
    has_refs = bool(refs["groups"] or refs["sections"] or refs["tasks"])
    if not has_refs:
        if not args.quiet:
            print(
                "auto_tick_tasks: no task / group / section refs in subject "
                "(skipping; not an error).",
            )
        return 0

    repo_root = args.repo_root or Path(_git(["rev-parse", "--show-toplevel"], Path.cwd()))
    if not repo_root or not repo_root.is_dir():
        print("❌ cannot determine repository root.", file=sys.stderr)
        return 2

    change_id = args.change_id
    if not change_id:
        branch = get_current_branch(repo_root)
        change_id = resolve_change_id(branch)

    if not change_id:
        if not args.quiet:
            print(
                "auto_tick_tasks: no --change-id and branch does not match "
                "<type>/<change-id>; nothing to tick.",
            )
        return 0

    tasks_path = repo_root / "openspec" / "changes" / change_id / "tasks.md"
    if not tasks_path.is_file():
        if not args.quiet:
            print(
                f"auto_tick_tasks: tasks.md not found at "
                f"{tasks_path.relative_to(repo_root)}; nothing to do.",
            )
        return 0

    try:
        changed, ticked = tick_tasks_md(tasks_path, refs=refs)
    except Exception as exc:  # noqa: BLE001 — defensive
        print(f"❌ tick_tasks_md failed: {exc}", file=sys.stderr)
        return 1

    if not changed:
        if not args.quiet:
            print(
                f"auto_tick_tasks: refs {refs} matched 0 unticked boxes in "
                f"{tasks_path.relative_to(repo_root)}; nothing changed.",
            )
        return 0

    if not args.no_stage:
        try:
            _git(["add", str(tasks_path.relative_to(repo_root))], repo_root)
        except Exception as exc:  # noqa: BLE001
            print(
                f"⚠️  auto_tick_tasks: ticked boxes but `git add` failed: {exc}. "
                "Stage the file manually before commit.",
                file=sys.stderr,
            )

    if not args.quiet:
        n = len(ticked)
        print(
            f"✅ auto_tick_tasks: ticked {n} checkbox{'es' if n != 1 else ''} "
            f"in {tasks_path.relative_to(repo_root)}.",
        )
        for entry in ticked:
            print(f"  - {entry}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
