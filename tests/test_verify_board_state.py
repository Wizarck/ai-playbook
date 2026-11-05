"""Tests for scripts/verify_board_state.py — L7 board-state verifier.

Per project-board-sync.md §2 L7. Coverage targets:
- exit code 0 on Status match
- exit code 1 on Status mismatch
- exit code 2 on item-not-found
- exit code 3 on GraphQL/network error
- correct CLI argument parsing

The GraphQL transport (`subprocess.run(["gh", "api", "graphql", ...])`)
is mocked at the boundary — tests don't hit a real GH project.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from scripts import verify_board_state

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graphql_response(
    items: list[dict[str, Any]],
    *,
    has_next_page: bool = False,
    end_cursor: str | None = None,
) -> dict[str, Any]:
    """Build the shape `_gh_graphql` parses out of `gh api graphql`'s stdout.

    Includes ``pageInfo`` so the paginated implementation in
    `_fetch_item_status` can decide whether to follow the cursor.
    """
    return {
        "data": {
            "user": {
                "projectV2": {
                    "items": {
                        "nodes": items,
                        "pageInfo": {
                            "hasNextPage": has_next_page,
                            "endCursor": end_cursor,
                        },
                    },
                },
            },
        },
    }


def _item(*, title: str, status: str | None) -> dict[str, Any]:
    """Build one project-item node with optional Status field-value."""
    field_values: list[dict[str, Any]] = []
    if status is not None:
        field_values.append(
            {
                "name": status,
                "field": {"name": "Status"},
            }
        )
    return {
        "fieldValues": {"nodes": field_values},
        "content": {"title": title},
    }


def _mock_subprocess_run_returning(payload: dict[str, Any]):
    """Build a patcher that fakes `subprocess.run` to return the given payload."""
    completed = subprocess.CompletedProcess(
        args=["gh", "api", "graphql", "--input", "-"],
        returncode=0,
        stdout=json.dumps(payload),
        stderr="",
    )
    return patch("scripts.verify_board_state.subprocess.run", return_value=completed)


# ---------------------------------------------------------------------------
# Exit code 0 — Status matches expected
# ---------------------------------------------------------------------------


def test_status_matches_expected_returns_0() -> None:
    payload = _make_graphql_response([_item(title="risk-engine-protections", status="Done")])
    with _mock_subprocess_run_returning(payload):
        rc = verify_board_state.main(
            [
                "--change-id",
                "risk-engine-protections",
                "--owner",
                "Wizarck",
                "--project-number",
                "2",
                "--expected-status",
                "Done",
            ]
        )
    assert rc == verify_board_state.EXIT_OK == 0


def test_sibling_slice_with_longer_id_does_not_match() -> None:
    """'risk-engine-protections' (Done) must not satisfy the gate for 'risk-engine'."""
    payload = _make_graphql_response([
        _item(title="risk-engine-protections", status="Done"),
        _item(title="risk-engine", status="In Progress"),
    ])
    with _mock_subprocess_run_returning(payload):
        rc = verify_board_state.main(
            ["--change-id", "risk-engine", "--owner", "Wizarck", "--project-number", "2"]
        )
    assert rc == verify_board_state.EXIT_STATUS_MISMATCH


def test_issue_sync_consumer_prefix_matches() -> None:
    """issue_sync files board issues as '[<consumer>] <change-id>'; exact
    matching must not turn those boards into exit 2 (item not found)."""
    payload = _make_graphql_response([_item(title="[beta] risk-engine", status="Done")])
    with _mock_subprocess_run_returning(payload):
        rc = verify_board_state.main(
            ["--change-id", "risk-engine", "--owner", "Wizarck", "--project-number", "2"]
        )
    assert rc == verify_board_state.EXIT_OK


def test_consumer_prefixed_sibling_does_not_match() -> None:
    payload = _make_graphql_response([
        _item(title="[beta] risk-engine-protections", status="Done"),
        _item(title="[beta] risk-engine", status="In Progress"),
    ])
    with _mock_subprocess_run_returning(payload):
        rc = verify_board_state.main(
            ["--change-id", "risk-engine", "--owner", "Wizarck", "--project-number", "2"]
        )
    assert rc == verify_board_state.EXIT_STATUS_MISMATCH


# (title, matches "risk-engine"?) — shared by the Python matcher and the jq
# filter the consumer workflow templates carry.
TITLE_CASES = [
    ("risk-engine", True),
    ("  risk-engine  ", True),
    ("[beta] risk-engine", True),
    ("risk-engine-protections", False),
    ("[beta] risk-engine-protections", False),
    ("feat: risk-engine", False),
    ("[a] [b] risk-engine", False),
    ("", False),
]


@pytest.mark.parametrize("title,expected", TITLE_CASES)
def test_title_matches(title: str, expected: bool) -> None:
    assert verify_board_state.title_matches(title, "risk-engine") is expected


# ---------------------------------------------------------------------------
# The consumer workflow templates must match titles the same way
# ---------------------------------------------------------------------------

_WORKFLOWS = (
    Path(__file__).resolve().parents[1] / "templates" / "new-project" / ".github" / "workflows"
)
# The one jq title filter every board workflow template uses (exact as written
# between the template's single quotes).
TITLE_SELECT = (
    r'select((.content.title // "" | tostring | sub("^\\s+"; "") | sub("\\s+$"; "")'
    r' | sub("^\\[[^\\]]+\\]\\s+"; "")) == $cid)'
)


@pytest.mark.parametrize("name,uses", [
    ("project-board-synced-check.yml.tmpl", 1),
    ("project-status-slice-progress.yml.tmpl", 2),
])
def test_workflow_templates_match_titles_exactly(name: str, uses: int) -> None:
    """A substring match (`contains($cid)` + `head -1`) lets a sibling slice
    whose id contains this one answer for it in the PR gates."""
    text = (_WORKFLOWS / name).read_text(encoding="utf-8")
    assert "contains($cid)" not in text
    assert text.count(TITLE_SELECT) == uses


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not on PATH")
def test_workflow_title_filter_agrees_with_title_matches() -> None:
    nodes = [{"id": str(i), "content": {"title": t}} for i, (t, _) in enumerate(TITLE_CASES)]
    nodes.append({"id": "no-content", "content": None})
    out = subprocess.run(
        ["jq", "-c", "--arg", "cid", "risk-engine", f"[.[] | {TITLE_SELECT} | .id]"],
        input=json.dumps(nodes), capture_output=True, text=True, check=True,
    ).stdout
    assert json.loads(out) == [str(i) for i, (_, ok) in enumerate(TITLE_CASES) if ok]


def test_default_expected_status_is_done() -> None:
    payload = _make_graphql_response([_item(title="some-slice", status="Done")])
    with _mock_subprocess_run_returning(payload):
        # Don't pass --expected-status; should default to Done.
        rc = verify_board_state.main(
            [
                "--change-id",
                "some-slice",
                "--owner",
                "Wizarck",
                "--project-number",
                "2",
            ]
        )
    assert rc == 0


def test_status_match_with_in_progress_status() -> None:
    """L6 path uses --expected-status='In Progress'."""
    payload = _make_graphql_response([_item(title="risk-engine-protections", status="In Progress")])
    with _mock_subprocess_run_returning(payload):
        rc = verify_board_state.main(
            [
                "--change-id",
                "risk-engine-protections",
                "--owner",
                "Wizarck",
                "--project-number",
                "2",
                "--expected-status",
                "In Progress",
            ]
        )
    assert rc == 0


# ---------------------------------------------------------------------------
# Exit code 1 — Status mismatch
# ---------------------------------------------------------------------------


def test_status_mismatch_returns_1(capsys: pytest.CaptureFixture[str]) -> None:
    payload = _make_graphql_response([_item(title="risk-engine-protections", status="In Progress")])
    with _mock_subprocess_run_returning(payload):
        rc = verify_board_state.main(
            [
                "--change-id",
                "risk-engine-protections",
                "--owner",
                "Wizarck",
                "--project-number",
                "2",
                "--expected-status",
                "Done",
            ]
        )
    assert rc == verify_board_state.EXIT_STATUS_MISMATCH == 1
    captured = capsys.readouterr()
    assert "In Progress" in captured.err
    assert "Done" in captured.err


def test_status_field_empty_returns_1(capsys: pytest.CaptureFixture[str]) -> None:
    """Item exists but has no Status value populated → mismatch."""
    payload = _make_graphql_response([_item(title="risk-engine-protections", status=None)])
    with _mock_subprocess_run_returning(payload):
        rc = verify_board_state.main(
            [
                "--change-id",
                "risk-engine-protections",
                "--owner",
                "Wizarck",
                "--project-number",
                "2",
                "--expected-status",
                "Done",
            ]
        )
    assert rc == 1
    captured = capsys.readouterr()
    assert "(empty)" in captured.err


# ---------------------------------------------------------------------------
# Exit code 2 — Item not found
# ---------------------------------------------------------------------------


def test_change_id_not_in_any_title_returns_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _make_graphql_response(
        [
            _item(title="other-slice-1", status="Done"),
            _item(title="other-slice-2", status="In Progress"),
        ]
    )
    with _mock_subprocess_run_returning(payload):
        rc = verify_board_state.main(
            [
                "--change-id",
                "missing-slice",
                "--owner",
                "Wizarck",
                "--project-number",
                "2",
            ]
        )
    assert rc == verify_board_state.EXIT_ITEM_NOT_FOUND == 2
    captured = capsys.readouterr()
    assert "missing-slice" in captured.err


def test_empty_project_returns_2() -> None:
    payload = _make_graphql_response([])
    with _mock_subprocess_run_returning(payload):
        rc = verify_board_state.main(
            [
                "--change-id",
                "anything",
                "--owner",
                "Wizarck",
                "--project-number",
                "2",
            ]
        )
    assert rc == 2


# ---------------------------------------------------------------------------
# Exit code 3 — GraphQL / network error
# ---------------------------------------------------------------------------


def test_subprocess_failure_returns_3(capsys: pytest.CaptureFixture[str]) -> None:
    """gh api graphql exits non-zero (e.g. token scope issue) → exit 3."""
    failure = subprocess.CalledProcessError(
        returncode=1,
        cmd=["gh", "api", "graphql", "--input", "-"],
        output="",
        stderr="HTTP 401: Bad credentials",
    )
    with patch("scripts.verify_board_state.subprocess.run", side_effect=failure):
        rc = verify_board_state.main(
            [
                "--change-id",
                "anything",
                "--owner",
                "Wizarck",
                "--project-number",
                "2",
            ]
        )
    assert rc == verify_board_state.EXIT_GRAPHQL_ERROR == 3
    captured = capsys.readouterr()
    assert "gh api graphql failed" in captured.err


def test_graphql_errors_in_response_returns_3() -> None:
    """gh api succeeds but the GraphQL payload contains an `errors` block."""
    payload = {
        "data": None,
        "errors": [{"message": "Field 'projectV2' doesn't exist"}],
    }
    with _mock_subprocess_run_returning(payload):
        rc = verify_board_state.main(
            [
                "--change-id",
                "anything",
                "--owner",
                "Wizarck",
                "--project-number",
                "2",
            ]
        )
    assert rc == 3


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def test_missing_required_args_raises_systemexit() -> None:
    with pytest.raises(SystemExit) as exc:
        verify_board_state.main([])
    # argparse uses exit code 2 for argument errors; that's fine — the script's
    # own exit codes only apply once parsing succeeds.
    assert exc.value.code == 2


def test_help_flag_exits_0() -> None:
    with pytest.raises(SystemExit) as exc:
        verify_board_state.main(["--help"])
    assert exc.value.code == 0


# ---------------------------------------------------------------------------
# Pagination — issue surfaced 2026-05-06: GitHub GraphQL `first` connection
# limit is 100; v0.10.0's `items(first: 200)` produced HTTP 422. v0.10.1
# paginates over 100-item pages.
# ---------------------------------------------------------------------------


def test_pagination_walks_to_second_page() -> None:
    """When item is on page 2, the script must follow the cursor."""
    page1 = _make_graphql_response(
        [_item(title=f"item-{i}", status="Done") for i in range(5)],
        has_next_page=True,
        end_cursor="CURSOR_PAGE_2",
    )
    page2 = _make_graphql_response(
        [_item(title="target-slice", status="Done")],
        has_next_page=False,
        end_cursor=None,
    )
    completed_responses = [
        subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(page1), stderr=""),
        subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(page2), stderr=""),
    ]
    with patch("scripts.verify_board_state.subprocess.run", side_effect=completed_responses) as mock_run:
        rc = verify_board_state.main(
            [
                "--change-id",
                "target-slice",
                "--owner",
                "Wizarck",
                "--project-number",
                "2",
            ]
        )
    assert rc == 0
    assert mock_run.call_count == 2


def test_pagination_stops_after_last_page_when_not_found() -> None:
    """No item matches across all pages → exit 2 after walking to end."""
    page1 = _make_graphql_response(
        [_item(title="other-1", status="Done")],
        has_next_page=True,
        end_cursor="CURSOR_PAGE_2",
    )
    page2 = _make_graphql_response(
        [_item(title="other-2", status="Done")],
        has_next_page=False,
        end_cursor=None,
    )
    completed_responses = [
        subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(page1), stderr=""),
        subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(page2), stderr=""),
    ]
    with patch("scripts.verify_board_state.subprocess.run", side_effect=completed_responses) as mock_run:
        rc = verify_board_state.main(
            [
                "--change-id",
                "missing",
                "--owner",
                "Wizarck",
                "--project-number",
                "2",
            ]
        )
    assert rc == 2
    assert mock_run.call_count == 2
