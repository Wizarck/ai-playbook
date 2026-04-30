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

# Visibility choices for `--visibility` (per release-management.md §5.1).
VISIBILITY_CHOICES = ("private", "public", "keep")

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
            encoding="utf-8",
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
        encoding="utf-8",
    )


def _gh_graphql(query: str, **variables: Any) -> dict:  # noqa: ANN401
    """Run a GraphQL query via `gh api graphql` and return the parsed `data`.

    The full request body (query + variables) is sent on stdin as JSON via
    `--input -`, so complex types (lists, dicts) survive without quoting
    games. ``gh``'s `-F` only handles scalars (bool / int / null / @file);
    JSON arrays via `-F` get rejected as unparseable.

    `encoding="utf-8"` is required on Windows because the default is
    cp1252, which silently drops the response body when GH returns
    non-ASCII bytes (e.g. accented characters in card body markdown
    persisted by previous bootstrap runs).
    """
    body = json.dumps({"query": query, "variables": variables})
    result = subprocess.run(
        ["gh", "api", "graphql", "--input", "-"],
        input=body,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
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
# Repo linking + visibility
# ---------------------------------------------------------------------------


def lookup_repo(owner: str, name: str) -> str:
    """Return the GraphQL node id for ``<owner>/<name>``."""
    query = """
    query($owner: String!, $name: String!) {
      repository(owner: $owner, name: $name) { id }
    }
    """
    data = _gh_graphql(query, owner=owner, name=name)
    repo = data.get("repository")
    if not repo:
        raise RuntimeError(f"repo {owner!r}/{name!r} not found")
    return repo["id"]


def list_linked_repos(project_id: str) -> list[str]:
    """Return the GraphQL node ids of repositories already linked to the project."""
    query = """
    query($id: ID!) {
      node(id: $id) {
        ... on ProjectV2 {
          repositories(first: 50) { nodes { id nameWithOwner } }
        }
      }
    }
    """
    data = _gh_graphql(query, id=project_id)
    nodes = (data.get("node") or {}).get("repositories", {}).get("nodes", [])
    return [n["id"] for n in nodes]


def link_project_to_repo(project_id: str, repo_id: str, *, dry_run: bool) -> bool:
    """Link the project to the repo. Returns True if linked (False if already linked).

    Idempotent: pre-checks `list_linked_repos` (a read-only query) and skips
    if the link exists. Safe to call in dry-run mode — the read-only check
    runs but the link mutation does not.
    """
    if repo_id in list_linked_repos(project_id):
        return False
    if dry_run:
        return True
    mutation = """
    mutation($project_id: ID!, $repo_id: ID!) {
      linkProjectV2ToRepository(input: {projectId: $project_id, repositoryId: $repo_id}) {
        repository { id }
      }
    }
    """
    _gh_graphql(mutation, project_id=project_id, repo_id=repo_id)
    return True


def set_project_visibility(project_id: str, public: bool, *, dry_run: bool) -> None:
    """Set the project's `public` flag (true → public on the web; false → private)."""
    if dry_run:
        return
    mutation = """
    mutation($project_id: ID!, $public: Boolean!) {
      updateProjectV2(input: {projectId: $project_id, public: $public}) {
        projectV2 { id public }
      }
    }
    """
    _gh_graphql(mutation, project_id=project_id, public=public)


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
        # re-pass existing + the new one to add non-destructively. Mutate the
        # in-memory dict so subsequent iterations include this newly-added
        # option in their full-list send (otherwise iteration N+1 would drop
        # iteration N's addition because the local dict is stale).
        all_options = list(status_field.options.keys()) + [canonical]
        _replace_status_options(project_id, status_field.id, all_options)
        status_field.options[canonical] = ""  # placeholder; real id reloaded later
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
    frs: str  # raw FRs/NFRs cell content (e.g. "FR1-FR5, FR11" or "(foundation: NFR-S1)")
    depends_on: list[str]
    scope_note: str  # full paragraph text, possibly multiline


def _render_item_body(row: SliceRow, *, repo: str | None, slice_index: int) -> str:
    """Render the markdown body for a project item card.

    Per release-management.md §5.4: cards reference the source artefacts in
    the repo so a reader can back-track to the proposal / spec / ADRs without
    duplicating content (DRY). Each card carries:
    - Header line with bounded context, deps, FRs.
    - The scope note from `docs/openspec-slice.md` verbatim (single source
      of truth — never edit the card body manually; re-run bootstrap).
    - References block linking to the canonical artefacts.

    ``repo`` is "owner/name" when known (from --repo); if None, the references
    use relative paths only (won't resolve from the project page). ``slice_index``
    is the 1-based row number from the slicing table, used for the deep-link
    anchor into Scope notes.
    """
    base = f"https://github.com/{repo}/blob/main" if repo else ""

    deps_md = (
        ", ".join(
            f"[`{d}`]({base}/openspec/changes/{d}/)" if base else f"`{d}`"
            for d in row.depends_on
        )
        if row.depends_on
        else "—"
    )

    refs_lines = []
    if base:
        anchor = f"#-{slice_index}-{row.change_id}"
        refs_lines.append(
            f"- 📋 [Slice plan row {slice_index}]({base}/docs/openspec-slice.md{anchor}) — canonical scope note"
        )
        refs_lines.append(
            f"- 📄 [Proposal]({base}/openspec/changes/{row.change_id}/proposal.md) "
            f"(landed after `/opsx:propose {row.change_id}`)"
        )
        refs_lines.append(
            f"- 🏛️ [Architecture decisions]({base}/docs/architecture-decisions.md) "
            f"· 🗃️ [Data model]({base}/docs/data-model.md) "
            f"· 📁 [Project structure]({base}/docs/project-structure.md)"
        )
        refs_lines.append(
            f"- ⚖️ [HITL gates log]({base}/docs/hitl-gates-log.md) — Gates A/B/C approvals"
        )
    else:
        refs_lines.append(
            "- 📋 `docs/openspec-slice.md` row " f"{slice_index} — canonical scope note"
        )
        refs_lines.append(
            f"- 📄 `openspec/changes/{row.change_id}/proposal.md` "
            f"(after `/opsx:propose {row.change_id}`)"
        )
        refs_lines.append(
            "- 🏛️ `docs/architecture-decisions.md` · 🗃️ `docs/data-model.md` "
            "· 📁 `docs/project-structure.md`"
        )

    return (
        f"**Bounded context**: {row.bounded_context}  \n"
        f"**Depends on**: {deps_md}  \n"
        f"**FRs / NFRs**: {row.frs}\n"
        "\n"
        "---\n"
        "\n"
        f"{row.scope_note.strip()}\n"
        "\n"
        "---\n"
        "\n"
        "**References** (back-track to source):\n"
        + "\n".join(refs_lines)
        + "\n"
    )


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
        frs_raw = cells[3].strip() if len(cells) > 3 else ""
        out.append(
            SliceRow(
                change_id=change_id_raw,
                bounded_context=cells[2].strip(),
                frs=frs_raw or "—",
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
    status: str  # current Status field value; "" if unset
    body: str = ""  # current draft-issue body markdown; "" if not a draft or no body
    content_id: str = ""  # GraphQL id of the underlying DraftIssue (for body updates)


def list_items(project_id: str) -> list[ProjectItem]:
    query = """
    query($id: ID!, $cursor: String) {
      node(id: $id) {
        ... on ProjectV2 {
          items(first: 100, after: $cursor) {
            nodes {
              id
              content {
                ... on DraftIssue { id title body }
              }
              fieldValues(first: 20) {
                nodes {
                  ... on ProjectV2ItemFieldTextValue { text field { ... on ProjectV2FieldCommon { name } } }
                  ... on ProjectV2ItemFieldSingleSelectValue { name field { ... on ProjectV2FieldCommon { name } } }
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
            status = ""
            body = ""
            content_id = ""
            content = n.get("content") or {}
            if content.get("title"):
                title = content["title"]
                body = content.get("body", "") or ""
                content_id = content.get("id", "") or ""
            for fv in n["fieldValues"]["nodes"]:
                if fv and fv.get("field", {}).get("name") == "Status":
                    status = fv.get("name", "") or ""
                if fv and fv.get("field", {}).get("name") == "Title" and not title:
                    title = fv.get("text", "")
            out.append(
                ProjectItem(
                    id=n["id"], title=title, status=status, body=body, content_id=content_id
                )
            )
        page = items["pageInfo"]
        if not page["hasNextPage"]:
            break
        cursor = page["endCursor"]
    return out


def update_draft_item_body(content_id: str, body: str, *, dry_run: bool) -> None:
    """Update a DraftIssue's body markdown via the updateProjectV2DraftIssue mutation."""
    if dry_run or not content_id:
        return
    mutation = """
    mutation($draft_id: ID!, $body: String!) {
      updateProjectV2DraftIssue(input: {draftIssueId: $draft_id, body: $body}) {
        draftIssue { id }
      }
    }
    """
    _gh_graphql(mutation, draft_id=content_id, body=body)


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
    repo: str | None,
    visibility: str,
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
        repo=repo,
        visibility=visibility,
        dry_run=dry_run,
    )

    try:
        proj = lookup_project(owner, project_number)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(f"→ Project: {proj.title} (#{proj.number}) under {proj.owner_login}")

    # Link to repo if requested. Per release-management.md §5.3 — Projects v2
    # live at user/org scope; the repo's Projects tab is just a link surface,
    # so this step is what makes the project visible inside the repo.
    if repo:
        if "/" not in repo:
            print(f"error: --repo must be 'owner/name' (got {repo!r})", file=sys.stderr)
            return 2
        repo_owner, repo_name = repo.split("/", 1)
        try:
            repo_id = lookup_repo(repo_owner, repo_name)
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        try:
            linked_now = link_project_to_repo(proj.id, repo_id, dry_run=dry_run)
        except RuntimeError as e:
            print(f"error: failed to link project to repo: {e}", file=sys.stderr)
            return 3
        if linked_now:
            _emit("bootstrap_gh_project.repo_linked", repo=repo, dry_run=dry_run)
            print(f"→ Linked to repo {repo}")
        else:
            _emit("bootstrap_gh_project.repo_link_skipped", repo=repo)
            print(f"→ Repo {repo} already linked")

    # Set visibility if requested. "keep" leaves the existing setting alone.
    if visibility != "keep":
        if dry_run:
            print(f"→ Visibility: would set to '{visibility}' (dry-run)")
        else:
            try:
                set_project_visibility(proj.id, public=(visibility == "public"), dry_run=dry_run)
                print(f"→ Visibility: set to '{visibility}'")
                _emit("bootstrap_gh_project.visibility_set", visibility=visibility)
            except RuntimeError as e:
                print(f"error: failed to update visibility: {e}", file=sys.stderr)
                return 3

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
        # list_items is read-only — safe to call in dry-run; gives accurate diff.
        existing_items = list_items(proj.id)
        existing_by_title: dict[str, ProjectItem] = {it.title: it for it in existing_items}

        items_status_set = 0
        items_body_refreshed = 0
        for i, row in enumerate(rows):
            existing = existing_by_title.get(row.change_id)
            slice_index = i + 1  # 1-based for human-readable references
            expected_body = _render_item_body(row, repo=repo, slice_index=slice_index)
            # Initial status: foundation slice (i=0, no deps) → Todo; rest → Blocked.
            initial = "Todo" if i == 0 and not row.depends_on else "Blocked"

            if existing is not None:
                items_skipped += 1
                _emit("bootstrap_gh_project.item_skipped", title=row.change_id)
                # Recovery 1: if the item was created earlier without a Status
                # (e.g. the option didn't yet exist due to v0.8.0-rc1's
                # in-memory option-list bug), set the canonical initial Status
                # now. Items with an already-populated Status are left alone.
                if (
                    not existing.status
                    and initial in status_field_now.options
                    and not dry_run
                ):
                    set_item_status(
                        proj.id,
                        existing.id,
                        status_field_now.id,
                        status_field_now.options[initial],
                        dry_run=dry_run,
                    )
                    items_status_set += 1
                # Recovery 2: if the item's body diverges from the rendered
                # template (e.g. the template was upgraded in a later
                # bootstrap_gh_project version), refresh it. The slicing
                # artefact is the single source of truth — never edit the
                # card body manually.
                if existing.content_id and existing.body.strip() != expected_body.strip():
                    if not dry_run:
                        update_draft_item_body(
                            existing.content_id, expected_body, dry_run=dry_run
                        )
                    items_body_refreshed += 1
                    _emit("bootstrap_gh_project.item_body_refreshed", title=row.change_id)
                continue

            item_id = add_draft_item(proj.id, row.change_id, expected_body, dry_run=dry_run)
            items_added += 1
            if item_id is not None and initial in status_field_now.options:
                set_item_status(
                    proj.id,
                    item_id,
                    status_field_now.id,
                    status_field_now.options[initial],
                    dry_run=dry_run,
                )
                items_status_set += 1

        summary_parts = [f"{items_added} added", f"{items_skipped} already present"]
        if items_status_set:
            summary_parts.append(f"{items_status_set} status-set")
        if items_body_refreshed:
            summary_parts.append(f"{items_body_refreshed} body-refreshed")
        print(f"→ Items: {', '.join(summary_parts)}")

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
        "--repo",
        default=None,
        metavar="owner/name",
        help=(
            "Link the project to this repo so it appears in the repo's Projects "
            "tab (idempotent). Projects v2 live at user/org scope; the repo's "
            "Projects tab is purely a link surface — this step is what makes the "
            "project visible inside the repo."
        ),
    )
    p.add_argument(
        "--visibility",
        choices=VISIBILITY_CHOICES,
        default="keep",
        help=(
            "Project visibility on the web: 'private' (default for new projects), "
            "'public', or 'keep' to leave whatever is already set (default: keep)"
        ),
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
            repo=args.repo,
            visibility=args.visibility,
            dry_run=args.dry_run,
        )
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        _emit("bootstrap_gh_project.failed", reason=str(e))
        return 3


if __name__ == "__main__":
    sys.exit(main())
