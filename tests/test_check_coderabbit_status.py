"""Tests for scripts/check_coderabbit_status.py."""

from __future__ import annotations

import json
from typing import Any

import pytest

from scripts import check_coderabbit_status as ccs

# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------


def _comment(login: str, body: str) -> dict[str, Any]:
    return {"author": {"login": login}, "body": body}


def test_classify_silent_when_no_comments() -> None:
    status, excerpt = ccs._classify([])
    assert status == "silent"
    assert excerpt is None


def test_classify_silent_when_no_coderabbit_comments() -> None:
    comments = [
        _comment("Wizarck", "Looks good!"),
        _comment("github-actions[bot]", "Lint passed."),
    ]
    status, excerpt = ccs._classify(comments)
    assert status == "silent"
    assert excerpt is None


def test_classify_rate_limited_on_marker_match() -> None:
    body = (
        "<!-- This is an auto-generated comment: rate limited by coderabbit.ai -->\n"
        "> [!WARNING]\n> ## Rate limit exceeded\n"
        "> @Wizarck has exceeded the limit for the number of commits..."
    )
    status, excerpt = ccs._classify([_comment(ccs.CODERABBIT_LOGIN, body)])
    assert status == "rate-limited"
    assert excerpt is not None
    assert "Rate limit" in excerpt or "rate limited" in excerpt


def test_classify_available_on_real_review() -> None:
    body = (
        "<!-- This is an auto-generated comment: summarize by coderabbit.ai -->\n"
        "## Summary by CodeRabbit\n\n"
        "* Added MessageBus with FIFO per subscriber.\n"
        "* Added Money value object.\n"
    )
    status, excerpt = ccs._classify([_comment(ccs.CODERABBIT_LOGIN, body)])
    assert status == "available"
    assert excerpt is not None
    assert "Summary by CodeRabbit" in excerpt


def test_classify_uses_latest_comment() -> None:
    """If CodeRabbit posted rate-limit then later a real review, the latter wins."""
    comments = [
        _comment(ccs.CODERABBIT_LOGIN, "Rate limit exceeded"),
        _comment(ccs.CODERABBIT_LOGIN, "## Summary by CodeRabbit\n* great work"),
    ]
    status, _ = ccs._classify(comments)
    assert status == "available"


def test_classify_ignores_other_authors() -> None:
    comments = [
        _comment("not-coderabbit", "## Summary by CodeRabbit\nfake!"),
    ]
    status, excerpt = ccs._classify(comments)
    assert status == "silent"
    assert excerpt is None


# ---------------------------------------------------------------------------
# _is_rate_limit_body
# ---------------------------------------------------------------------------


def test_rate_limit_marker_canonical() -> None:
    assert ccs._is_rate_limit_body("> ## Rate limit exceeded")


def test_rate_limit_marker_lowercase() -> None:
    assert ccs._is_rate_limit_body("rate limited by coderabbit.ai")


def test_rate_limit_marker_absent() -> None:
    assert not ccs._is_rate_limit_body("Looks good to me!")


# ---------------------------------------------------------------------------
# _seconds_since
# ---------------------------------------------------------------------------


def test_seconds_since_handles_z_suffix() -> None:
    # Far past — must return a large positive integer.
    delta = ccs._seconds_since("2020-01-01T00:00:00Z")
    assert delta > 60 * 60 * 24 * 365 * 4  # >4 years


def test_seconds_since_handles_explicit_offset() -> None:
    # Same as above but with explicit offset.
    delta = ccs._seconds_since("2020-01-01T00:00:00+00:00")
    assert delta > 60 * 60 * 24 * 365 * 4


def test_seconds_since_invalid_returns_minus_one() -> None:
    assert ccs._seconds_since("not-a-date") == -1


# ---------------------------------------------------------------------------
# run() — end-to-end with monkeypatched gh helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_gh_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ccs, "_gh_available", lambda: True)


def test_run_returns_0_when_available(
    stub_gh_available: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        ccs,
        "_gh_pr_meta",
        lambda pr, repo: {"createdAt": "2026-05-01T03:00:00Z", "number": pr},
    )
    monkeypatch.setattr(
        ccs,
        "_gh_pr_comments",
        lambda pr, repo: [
            _comment(ccs.CODERABBIT_LOGIN, "## Summary by CodeRabbit\nlgtm")
        ],
    )

    rc = ccs.run(pr=1, repo="x/y", wait_seconds=0, poll_interval=1, output_json=True)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "available"
    assert out["comments_checked"] == 1
    assert "polled_at" in out
    assert out["polled_at"].endswith("Z")


def test_run_returns_1_when_rate_limited(
    stub_gh_available: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        ccs,
        "_gh_pr_meta",
        lambda pr, repo: {"createdAt": "2026-05-01T03:00:00Z", "number": pr},
    )
    monkeypatch.setattr(
        ccs,
        "_gh_pr_comments",
        lambda pr, repo: [_comment(ccs.CODERABBIT_LOGIN, "## Rate limit exceeded\n")],
    )

    rc = ccs.run(pr=1, repo="x/y", wait_seconds=0, poll_interval=1, output_json=True)
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "rate-limited"


def test_run_returns_1_when_silent_after_wait(
    stub_gh_available: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        ccs,
        "_gh_pr_meta",
        lambda pr, repo: {"createdAt": "2026-05-01T03:00:00Z", "number": pr},
    )
    monkeypatch.setattr(ccs, "_gh_pr_comments", lambda pr, repo: [])
    # Don't actually sleep during the test — wait_seconds=0 short-circuits.
    rc = ccs.run(pr=1, repo="x/y", wait_seconds=0, poll_interval=1, output_json=True)
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "silent"
    assert out["comments_checked"] == 0


def test_run_returns_2_when_gh_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(ccs, "_gh_available", lambda: False)
    rc = ccs.run(pr=1, repo="x/y", wait_seconds=0, poll_interval=1, output_json=True)
    assert rc == 2
    err = capsys.readouterr().err
    assert "gh CLI not authenticated" in err


def test_run_returns_2_when_pr_not_found(
    stub_gh_available: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def boom(pr: int, repo: str) -> dict[str, Any]:
        raise RuntimeError("gh pr view failed (exit 1): no such PR")

    monkeypatch.setattr(ccs, "_gh_pr_meta", boom)
    rc = ccs.run(
        pr=99999, repo="x/y", wait_seconds=0, poll_interval=1, output_json=True
    )
    assert rc == 2


def test_run_returns_3_on_polling_error(
    stub_gh_available: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        ccs,
        "_gh_pr_meta",
        lambda pr, repo: {"createdAt": "2026-05-01T03:00:00Z", "number": pr},
    )

    def boom(pr: int, repo: str) -> list[dict[str, Any]]:
        raise RuntimeError("gh: network error")

    monkeypatch.setattr(ccs, "_gh_pr_comments", boom)
    rc = ccs.run(pr=1, repo="x/y", wait_seconds=0, poll_interval=1, output_json=True)
    assert rc == 3


# ---------------------------------------------------------------------------
# main() — argparse + arg validation
# ---------------------------------------------------------------------------


def test_main_negative_wait_returns_2(capsys: pytest.CaptureFixture[str]) -> None:
    rc = ccs.main(["--pr", "1", "--repo", "x/y", "--wait", "-1"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "must be >= 0" in err


def test_main_zero_poll_interval_returns_2(capsys: pytest.CaptureFixture[str]) -> None:
    rc = ccs.main(["--pr", "1", "--repo", "x/y", "--wait", "0", "--poll-interval", "0"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "must be > 0" in err
