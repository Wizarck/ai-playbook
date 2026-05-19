"""verify_board_state.py — assert a project item is in an expected Status.

Per project-board-sync.md L7: a tool-level reinforcer for the
`openspec-archive-change` skill. The skill's Step 0 invokes this script;
the skill's instruction is "refuse archive on non-zero exit", which the
script implements via exit-code semantics (rather than relying on the AI
to read a status string and decide).

Usage::

    python -m scripts.verify_board_state \\
        --change-id risk-engine-protections \\
        --owner Wizarck \\
        --project-number 2 \\
        --expected-status Done

Behaviour
---------
- Fetches the project item whose Title contains ``--change-id``.
- Reads the item's ``Status`` single-select value.
- Compares against ``--expected-status`` (default ``Done``).
- Exits ``0`` on match, ``1`` on mismatch, ``2`` on item-not-found, ``3``
  on GraphQL / network error.

Exit-code semantics
-------------------
- ``0`` — Status matches expected. Caller proceeds.
- ``1`` — Status does NOT match. Caller MUST refuse the gated action
  (e.g. archive). Stderr carries an actionable message.
- ``2`` — No project item found whose Title contains the change-id.
  Caller surfaces "board out of sync" and asks the human.
- ``3`` — GraphQL or network error talking to the project. Caller
  surfaces "transient error" and may retry once before giving up.

These are stable contract: never re-use the codes for other failure
modes. Callers grep on exit code, not on stderr text.

Cross-references
----------------
- ``docs/concepts/project-board-sync.md`` §2 L7
- ``docs/concepts/release-management.md`` §5 (project board schema)
- ``skills/openspec-archive-change/SKILL.md`` (caller)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

# Force UTF-8 on stdio so non-ASCII glyphs (✅ in the success line) don't
# blow up on Windows cp1252 consoles. Mirrors the pattern from notify.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

# Exit codes — stable contract.
EXIT_OK = 0
EXIT_STATUS_MISMATCH = 1
EXIT_ITEM_NOT_FOUND = 2
EXIT_GRAPHQL_ERROR = 3


def _gh_graphql(query: str, **variables: Any) -> dict[str, Any]:  # noqa: ANN401
    """Run a GraphQL query via ``gh api graphql`` and return the parsed ``data``.

    Mirrors the helper in ``scripts/bootstrap_gh_project.py`` (kept local
    to avoid a circular import with bootstrap_gh_project's own load order).
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
    return payload.get("data") or {}


def _fetch_item_status(*, owner: str, project_number: int, change_id: str) -> tuple[str | None, str | None]:
    """Return ``(status_value, item_title)`` for the matching project item.

    ``status_value`` is the Status single-select option name (e.g. "Done").
    ``item_title`` is the full Title of the matched item.
    Both are ``None`` when no matching item is found.

    Paginates over project items in 100-item pages (GitHub's GraphQL
    ``first`` connection limit). v0.10.0 used ``first: 200`` which exceeded
    the limit and produced ``HTTP 422: Requesting 200 records on the
    connection exceeds the 'first' limit of 100 records``. Fixed in v0.10.1.
    """
    query = """
    query($owner: String!, $number: Int!, $cursor: String) {
      user(login: $owner) {
        projectV2(number: $number) {
          items(first: 100, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            nodes {
              fieldValues(first: 30) {
                nodes {
                  ... on ProjectV2ItemFieldSingleSelectValue {
                    name
                    field { ... on ProjectV2SingleSelectField { name } }
                  }
                }
              }
              content {
                ... on Issue { title }
                ... on PullRequest { title }
                ... on DraftIssue { title }
              }
            }
          }
        }
      }
    }
    """
    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {"owner": owner, "number": project_number}
        if cursor is not None:
            kwargs["cursor"] = cursor
        data = _gh_graphql(query, **kwargs)
        user = data.get("user") or {}
        project = user.get("projectV2") or {}
        items_block = project.get("items") or {}
        items = items_block.get("nodes") or []

        for item in items:
            content = item.get("content") or {}
            title = content.get("title", "")
            if change_id not in title:
                continue
            # Found the matching item. Extract Status.
            for fv in (item.get("fieldValues") or {}).get("nodes") or []:
                field = fv.get("field") or {}
                if field.get("name") == "Status":
                    return fv.get("name"), title
            # Item found but no Status field value populated.
            return None, title

        page_info = items_block.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            return None, None
        cursor = page_info.get("endCursor")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a project item's Status matches an expected value.",
    )
    parser.add_argument(
        "--change-id",
        required=True,
        help="OpenSpec change-id (kebab-case). Matched against project item Title.",
    )
    parser.add_argument(
        "--owner",
        required=True,
        help="GitHub user/org login that owns the project.",
    )
    parser.add_argument(
        "--project-number",
        type=int,
        required=True,
        help="Numeric Project V2 ID.",
    )
    parser.add_argument(
        "--expected-status",
        default="Done",
        help="Expected Status value (default: Done).",
    )
    args = parser.parse_args(argv)

    try:
        status, title = _fetch_item_status(
            owner=args.owner,
            project_number=args.project_number,
            change_id=args.change_id,
        )
    except subprocess.CalledProcessError as exc:
        print(
            f"::error::gh api graphql failed (exit {exc.returncode}). "
            f"Check GH_TOKEN scope (project: read+write) and project-number value.",
            file=sys.stderr,
        )
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        return EXIT_GRAPHQL_ERROR
    except RuntimeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return EXIT_GRAPHQL_ERROR

    if title is None:
        print(
            f"::error::No project item found whose title contains "
            f"'{args.change_id}'. Either: (a) add the slice to the project "
            f"board, or (b) the title doesn't match the change-id.",
            file=sys.stderr,
        )
        return EXIT_ITEM_NOT_FOUND

    if status != args.expected_status:
        actual = status if status is not None else "(empty)"
        print(
            f"::error::Project item '{title}' has Status='{actual}'; "
            f"expected '{args.expected_status}'. "
            f"Likely cause: the gated action was invoked before the project "
            f"board reached the expected state. Check the L1/L2 workflows "
            f"fired correctly (project-status.yml, project-status-slice-progress.yml).",
            file=sys.stderr,
        )
        return EXIT_STATUS_MISMATCH

    print(
        f"✅ Project item '{title}' Status='{status}' matches expected.",
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
