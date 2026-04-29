"""Bootstrap a consumer project's GitHub Project board with the canonical schema.

Per ``specs/release-management.md`` §5 + §7, every consumer project that adopts
the BMAD+OpenSpec hybrid flow needs a GitHub Project (V2) board with:

- A ``Status`` field with **exactly five options** in canonical order:
  ``Todo``, ``Blocked``, ``In Progress``, ``Review``, ``Done``.
- Optionally two custom single-select fields ``Risk`` (Low/Medium/High) and
  ``P&L impact`` (None/Low/Medium/High) for prioritisation visibility.

This script is the one-command bootstrap that ensures a project board conforms
to the schema before ``/opsx:propose`` runs. It is **idempotent**: re-running
on a board that already conforms is a no-op (notifications emit ``skipped``).

Optional content seed
---------------------
If ``--slicing-file docs/openspec-slice.md`` is passed, the script also reads
the slicing artefact (per ``specs/bmad-openspec-bridge.md`` §3.1) and creates
**one draft project item per change row** with title = ``<change-id>`` and
body = the scope note paragraph. Initial Status assignment follows the dep
graph: the foundation slice (Wave 0 row 1, no ``Depends on``) gets ``Todo``;
all others get ``Blocked``.

Without ``--slicing-file``, the script only sets up the schema. Items are then
created by ``scripts/issue_sync.py`` as ``openspec/changes/*/proposal.md``
files land per ``/opsx:propose`` runs.

CLI
---
    python -m scripts.bootstrap_gh_project \\
        --owner <gh-user-or-org> \\
        --project-number <existing-id> \\
        [--slicing-file docs/openspec-slice.md] \\
        [--no-custom-fields] \\
        [--dry-run]

Exit codes
----------
    0 — success (idempotent no-op or schema/items aligned)
    1 — schema rename divergence detected (manual cleanup required)
    2 — setup error (gh unavailable, project not found, slicing file unparseable)
    3 — unrecoverable GraphQL error

Notifications
-------------
    bootstrap_gh_project.start            info  before any mutation
    bootstrap_gh_project.option_added     info  per Status option created
    bootstrap_gh_project.option_skipped   silent already present
    bootstrap_gh_project.field_added      info  per custom field created
    bootstrap_gh_project.field_skipped    silent already present
    bootstrap_gh_project.item_added       info  per draft item created
    bootstrap_gh_project.item_skipped     silent existing item with same title
    bootstrap_gh_project.diverged         warn  Status option name mismatch
    bootstrap_gh_project.complete         info  summary
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from scripts.notify import notify as _notify_raw
except ImportError:  # pragma: no cover — dev-loop fallback
    def _notify_raw(**kw: Any) -> None:  # noqa: ANN401
        print(f"[notify] {kw}", file=sys.stderr)


def _emit(event: str, severity: str = "info", summary: str = "", **attrs: Any) -> None:  # noqa: ANN401
    """Thin wrapper around `scripts.notify.notify` with a kwargs-friendly shape."""
    try:
        _notify_raw(
            event=event,
            severity=severity,
            summary=summary or event,
            attrs=attrs or {},
        )
    except Exception:  # pragma: no cover — notification must never break the script
        pass


# ---------------------------------------------------------------------------
# Canonical schema (per specs/release-management.md §5)
# ---------------------------------------------------------------------------

CANONICAL_STATUS_OPTIONS = ["Todo", "Blocked", "In Progress", "Review", "Done"]

CUSTOM_FIELDS = [
    {
        "name": "Risk",
        "options": ["Low", "Medium", "High"],
    },
    {
        "name": "P&L impact",
        "options": ["None", "Low", "Medium", "High"],
    },
]


# ---------------------------------------------------------------------------
# gh CLI helpers
# ---------------------------------------------------------------------------


def _gh_available() -> bool:
    try:
        subprocess.run(
            ["gh", "auth", "status"],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _gh(args: list[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args],
        check=True,
        capture_output=capture,
        text=True,
    )


def _gh_graphql(query: str, **variables: Any) -> dict:  # noqa: ANN401
    """Run a GraphQL query via `gh api graphql` and return the parsed `data`.

    Variables are passed via -F (typed) so booleans/ints/lists are forwarded
    without quoting issues.
    """
    cmd = ["api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        if isinstance(v, bool):
            cmd += ["-F", f"{k}={'true' if v else 'false'}"]
        elif isinstance(v, (int, float)):
            cmd += ["-F", f"{k}={v}"]
        elif isinstance(v, list):
            cmd += ["-F", f"{k}={json.dumps(v)}"]
        else:
            cmd += ["-f", f"{k}={v}"]
    result = _gh(cmd)
    payload = json.loads(result.stdout)
    if "errors" in payload:
        raise RuntimeError(f"GraphQL error: {payload['errors']}")
    return payload.get("data", {})


# ---------------------------------------------------------------------------
# Project lookup
# ---------------------------------------------------------------------------


@dataclass
class Project:
    id: str
    number: int
    title: str
    owner_login: str


def lookup_project(owner: str, project_number: int) -> Project:
    # Try user scope first, then organization. Each scope errors if the owner
    # is the wrong type, so we run them sequentially and swallow NOT_FOUND.
    for scope in ("user", "organization"):
        query = f"""
        query($owner: String!, $number: Int!) {{
          {scope}(login: $owner) {{
            projectV2(number: $number) {{ id number title }}
          }}
        }}
        """
        try:
            data = _gh_graphql(query, owner=owner, number=project_number)
        except RuntimeError:
            continue
        proj = (data.get(scope) or {}).get("projectV2")
        if proj:
            return Project(
                id=proj["id"],
                number=proj["number"],
                title=proj["title"],
                owner_login=owner,
            )
    raise RuntimeError(
        f"project #{project_number} not found under owner {owner!r} "
        f"(checked both user and organization scopes)"
    )


# ---------------------------------------------------------------------------
# Field + option discovery / creation
# ---------------------------------------------------------------------------


@dataclass
class FieldInfo:
    id: str
    name: str
    data_type: str  # "SINGLE_SELECT", "TEXT", etc.
    options: dict[str, str]  # name → option_id (for single-select)


def list_fields(project_id: str) -> list[FieldInfo]:
    query = """
    query($id: ID!) {
      node(id: $id) {
        ... on ProjectV2 {
          fields(first: 50) {
            nodes {
              ... on ProjectV2FieldCommon {
                id
                name
                dataType
              }
              ... on ProjectV2SingleSelectField {
                id
                name
                dataType
                options { id name }
              }
            }
          }
        }
      }
    }
    """
    data = _gh_graphql(query, id=project_id)
    nodes = data["node"]["fields"]["nodes"]
    out: list[FieldInfo] = []
    for n in nodes:
        if not n:
            continue
        opts = {o["name"]: o["id"] for o in n.get("options", [])} if "options" in n else {}
        out.append(
            FieldInfo(
                id=n["id"],
                name=n["name"],
                data_type=n.get("dataType", ""),
                options=opts,
            )
        )
    return out


def add_status_options(
    project_id: str,
    status_field: FieldInfo,
    *,
    dry_run: bool,
) -> tuple[int, int, list[str]]:
    """Add canonical Status options that are missing.

    Returns (added_count, skipped_count, divergent_names).
    """
    added = 0
    skipped = 0
    divergent: list[str] = []
    existing_lower = {n.lower(): n for n in status_field.options}
    for canonical in CANONICAL_STATUS_OPTIONS:
        if canonical in status_field.options:
            _emit("bootstrap_gh_project.option_skipped", option=canonical)
            skipped += 1
            continue
        # Detect rename divergence (e.g. "In review" vs canonical "Review").
        if canonical.lower() in existing_lower and existing_lower[canonical.lower()] != canonical:
            divergent.append(f"{existing_lower[canonical.lower()]!r} (expected {canonical!r})")
            continue
        # Add the option.
        if dry_run:
            _emit("bootstrap_gh_project.option_added", option=canonical, dry_run=True)
            added += 1
            continue
        # GitHub's `updateProjectV2Field` REPLACES the full option list, so we
        # re-pass existing + the new one to add non-destructively.
        all_options = list(status_field.options.keys()) + [canonical]
        _replace_status_options(project_id, status_field.id, all_options)
        added += 1
        _emit("bootstrap_gh_project.option_added", option=canonical)
    return added, skipped, divergent


def _replace_status_options(project_id: str, field_id: str, all_names: list[str]) -> None:
    """Replace the full option set on a single-select field, preserving order.

    GitHub's ``updateProjectV2Field`` mutation REPLACES all options when
    ``singleSelectOptions`` is provided. To add an option non-destructively we
    re-list existing + the new one and assign sensible colors.
    """
    color_for = {
        "Todo": "GRAY",
        "Blocked": "RED",
        "In Progress": "YELLOW",
        "Review": "BLUE",
        "Done": "GREEN",
    }
    options_payload = []
    for name in all_names:
        options_payload.append(
            {
                "name": name,
                "color": color_for.get(name, "GRAY"),
                "description": "",
            }
        )
    mutation = """
    mutation($field_id: ID!, $opts: [ProjectV2SingleSelectFieldOptionInput!]!) {
      updateProjectV2Field(input: {
        fieldId: $field_id,
        singleSelectOptions: $opts
      }) {
        projectV2Field { ... on ProjectV2SingleSelectField { id } }
      }
    }
    """
    _gh_graphql(mutation, field_id=field_id, opts=options_payload)


def ensure_custom_fields(
    project_id: str,
    fields_now: list[FieldInfo],
    *,
    dry_run: bool,
) -> int:
    """Create the recommended custom single-select fields if absent.

    Returns the count of fields created.
    """
    existing_names = {f.name for f in fields_now}
    created = 0
    for spec in CUSTOM_FIELDS:
        if spec["name"] in existing_names:
            _emit("bootstrap_gh_project.field_skipped", field=spec["name"])
            continue
        if dry_run:
            _emit("bootstrap_gh_project.field_added", field=spec["name"], dry_run=True)
            created += 1
            continue
        options_payload = [
            {"name": opt, "color": "GRAY", "description": ""} for opt in spec["options"]
        ]
        mutation = """
        mutation($project_id: ID!, $name: String!, $opts: [ProjectV2SingleSelectFieldOptionInput!]!) {
          createProjectV2Field(input: {
            projectId: $project_id,
            dataType: SINGLE_SELECT,
            name: $name,
            singleSelectOptions: $opts
          }) {
            projectV2Field { ... on ProjectV2SingleSelectField { id name } }
          }
        }
        """
        _gh_graphql(
            mutation,
            project_id=project_id,
            name=spec["name"],
            opts=options_payload,
        )
        created += 1
        _emit("bootstrap_gh_project.field_added", field=spec["name"])
    return created


# ---------------------------------------------------------------------------
# Slicing artefact parsing
# ---------------------------------------------------------------------------


@dataclass
class SliceRow:
    change_id: str
    bounded_context: str
    depends_on: list[str]
    scope_note: str  # full paragraph text, possibly multiline


def parse_slicing(path: Path) -> list[SliceRow]:
    """Parse `docs/openspec-slice.md` per `bmad-openspec-bridge.md` §3.1.

    Returns one SliceRow per row in the "Approved change list" table.
    """
    if not path.exists():
        raise RuntimeError(f"slicing file not found: {path}")
    text = path.read_text(encoding="utf-8")

    # Locate the "Approved change list" table.
    m = re.search(
        r"##\s+Approved change list\s*\n(?P<table>(?:\|[^\n]+\n)+)",
        text,
    )
    if not m:
        raise RuntimeError(
            f"no 'Approved change list' table found in {path}; "
            f"slicing file does not conform to bmad-openspec-bridge.md §3.1"
        )
    table = m.group("table").strip().splitlines()
    # First two lines are header + separator; rest are rows.
    if len(table) < 3:
        raise RuntimeError(f"approved change list table too short in {path}")
    rows = table[2:]

    # Locate the "Scope notes" section to extract per-change paragraphs.
    notes_block = ""
    n = re.search(r"##\s+Scope notes\s*\n(?P<body>.+?)(?=\n##\s+|\Z)", text, re.DOTALL)
    if n:
        notes_block = n.group("body")

    # Map ### N. `<change-id>` → paragraph until next ###.
    notes_map: dict[str, str] = {}
    for sm in re.finditer(
        r"###\s+\d+\.\s+`(?P<id>[^`]+)`\s*\n(?P<body>.+?)(?=\n###\s+|\Z)",
        notes_block,
        re.DOTALL,
    ):
        notes_map[sm.group("id").strip()] = sm.group("body").strip()

    out: list[SliceRow] = []
    for line in rows:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 7:
            continue
        # Schema: # | Change ID | Bounded context | FRs | Journeys | Components | Depends on
        change_id_raw = cells[1].strip().strip("`")
        if not change_id_raw or change_id_raw.startswith("..."):
            continue
        depends_raw = cells[6].strip()
        depends: list[str] = []
        if depends_raw and depends_raw not in {"—", "-", ""}:
            for tok in re.split(r"[,;]", depends_raw):
                tok = tok.strip().strip("`").strip()
                if tok and tok != "—":
                    depends.append(tok)
        scope = notes_map.get(change_id_raw, "(scope note missing — re-run slicing per Gate C)")
        out.append(
            SliceRow(
                change_id=change_id_raw,
                bounded_context=cells[2].strip(),
                depends_on=depends,
                scope_note=scope,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Project items
# ---------------------------------------------------------------------------


@dataclass
class ProjectItem:
    id: str
    title: str


def list_items(project_id: str) -> list[ProjectItem]:
    query = """
    query($id: ID!, $cursor: String) {
      node(id: $id) {
        ... on ProjectV2 {
          items(first: 100, after: $cursor) {
            nodes {
              id
              fieldValues(first: 20) {
                nodes {
                  ... on ProjectV2ItemFieldTextValue { text field { ... on ProjectV2FieldCommon { name } } }
                }
              }
            }
            pageInfo { hasNextPage endCursor }
          }
        }
      }
    }
    """
    out: list[ProjectItem] = []
    cursor: str | None = None
    while True:
        data = _gh_graphql(query, id=project_id, cursor=cursor or "")
        items = data["node"]["items"]
        for n in items["nodes"]:
            title = ""
            for fv in n["fieldValues"]["nodes"]:
                if fv and fv.get("field", {}).get("name") == "Title":
                    title = fv.get("text", "")
                    break
            out.append(ProjectItem(id=n["id"], title=title))
        page = items["pageInfo"]
        if not page["hasNextPage"]:
            break
        cursor = page["endCursor"]
    return out


def add_draft_item(project_id: str, title: str, body: str, *, dry_run: bool) -> str | None:
    if dry_run:
        _emit("bootstrap_gh_project.item_added", title=title, dry_run=True)
        return None
    mutation = """
    mutation($project_id: ID!, $title: String!, $body: String!) {
      addProjectV2DraftIssue(input: {
        projectId: $project_id,
        title: $title,
        body: $body
      }) {
        projectItem { id }
      }
    }
    """
    data = _gh_graphql(mutation, project_id=project_id, title=title, body=body)
    _emit("bootstrap_gh_project.item_added", title=title)
    return data["addProjectV2DraftIssue"]["projectItem"]["id"]


def set_item_status(
    project_id: str,
    item_id: str,
    status_field_id: str,
    option_id: str,
    *,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    mutation = """
    mutation($project_id: ID!, $item_id: ID!, $field_id: ID!, $option_id: String!) {
      updateProjectV2ItemFieldValue(input: {
        projectId: $project_id,
        itemId: $item_id,
        fieldId: $field_id,
        value: { singleSelectOptionId: $option_id }
      }) {
        projectV2Item { id }
      }
    }
    """
    _gh_graphql(
        mutation,
        project_id=project_id,
        item_id=item_id,
        field_id=status_field_id,
        option_id=option_id,
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run(
    *,
    owner: str,
    project_number: int,
    slicing_file: Path | None,
    no_custom_fields: bool,
    dry_run: bool,
) -> int:
    if not _gh_available():
        _emit("bootstrap_gh_project.failed", reason="gh not authenticated")
        print("error: gh CLI not authenticated; run `gh auth login` first", file=sys.stderr)
        return 2

    _emit(
        "bootstrap_gh_project.start",
        owner=owner,
        project_number=project_number,
        slicing_file=str(slicing_file) if slicing_file else None,
        dry_run=dry_run,
    )

    try:
        proj = lookup_project(owner, project_number)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(f"→ Project: {proj.title} (#{proj.number}) under {proj.owner_login}")

    fields = list_fields(proj.id)
    status_field = next((f for f in fields if f.name == "Status"), None)
    if status_field is None:
        print(
            "error: project has no 'Status' field; create it manually in the project UI first",
            file=sys.stderr,
        )
        return 2
    if status_field.data_type != "SINGLE_SELECT":
        print(
            f"error: 'Status' field is type {status_field.data_type}, expected SINGLE_SELECT",
            file=sys.stderr,
        )
        return 2

    added, skipped, divergent = add_status_options(proj.id, status_field, dry_run=dry_run)
    print(f"→ Status options: {added} added, {skipped} already present")
    if divergent:
        for d in divergent:
            print(f"  ⚠ name divergence: {d}", file=sys.stderr)
            _emit("bootstrap_gh_project.diverged", divergence=d)
        print(
            "  Resolve manually: rename in the project UI to match the canonical option name.",
            file=sys.stderr,
        )
        return 1

    fields_now = list_fields(proj.id) if not dry_run else fields
    custom_added = 0
    if not no_custom_fields:
        custom_added = ensure_custom_fields(proj.id, fields_now, dry_run=dry_run)
        print(f"→ Custom fields: {custom_added} added (Risk, P&L impact)")

    items_added = 0
    items_skipped = 0
    if slicing_file is not None:
        try:
            rows = parse_slicing(slicing_file)
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(f"→ Slicing artefact: {len(rows)} change rows parsed")

        # Refresh status field after option addition.
        fields_now = list_fields(proj.id) if not dry_run else fields
        status_field_now = next((f for f in fields_now if f.name == "Status"), status_field)
        existing_titles = (
            {it.title for it in list_items(proj.id)} if not dry_run else set()
        )

        for i, row in enumerate(rows):
            if row.change_id in existing_titles:
                items_skipped += 1
                _emit("bootstrap_gh_project.item_skipped", title=row.change_id)
                continue
            body = (
                f"**Bounded context**: {row.bounded_context}\n"
                f"**Depends on**: {', '.join(row.depends_on) if row.depends_on else '—'}\n\n"
                f"---\n\n{row.scope_note}\n"
            )
            item_id = add_draft_item(proj.id, row.change_id, body, dry_run=dry_run)
            items_added += 1
            # Initial status: foundation slice (i=0, no deps) → Todo; rest → Blocked.
            initial = "Todo" if i == 0 and not row.depends_on else "Blocked"
            if item_id is not None and initial in status_field_now.options:
                set_item_status(
                    proj.id,
                    item_id,
                    status_field_now.id,
                    status_field_now.options[initial],
                    dry_run=dry_run,
                )
        print(f"→ Items: {items_added} added, {items_skipped} already present")

    _emit(
        "bootstrap_gh_project.complete",
        added_options=added,
        added_fields=custom_added,
        added_items=items_added,
        skipped_items=items_skipped,
        dry_run=dry_run,
    )
    print(
        f"✓ done — options:+{added}/={skipped}  fields:+{custom_added}  "
        f"items:+{items_added}/={items_skipped}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Bootstrap a consumer's GitHub Project board with the canonical "
            "schema per specs/release-management.md."
        )
    )
    p.add_argument("--owner", required=True, help="GH user or org login (e.g. 'Wizarck')")
    p.add_argument(
        "--project-number",
        required=True,
        type=int,
        help="Existing GH Project number (visible in the project URL)",
    )
    p.add_argument(
        "--slicing-file",
        type=Path,
        default=None,
        help=(
            "Path to docs/openspec-slice.md; if provided, also creates one draft "
            "project item per change row with initial Status set per dep graph"
        ),
    )
    p.add_argument(
        "--no-custom-fields",
        action="store_true",
        help="Skip creating the recommended Risk + P&L impact custom fields",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print intended mutations without applying them",
    )
    args = p.parse_args(argv)

    try:
        return run(
            owner=args.owner,
            project_number=args.project_number,
            slicing_file=args.slicing_file,
            no_custom_fields=args.no_custom_fields,
            dry_run=args.dry_run,
        )
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        _emit("bootstrap_gh_project.failed", reason=str(e))
        return 3


if __name__ == "__main__":
    sys.exit(main())
