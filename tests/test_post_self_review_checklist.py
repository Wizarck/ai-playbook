"""Tests for scripts/post_self_review_checklist.py."""

from __future__ import annotations

from typing import Any

import pytest

from scripts import post_self_review_checklist as psrc

# ---------------------------------------------------------------------------
# is_section_45_populated
# ---------------------------------------------------------------------------


def test_section_unpopulated_when_body_empty() -> None:
    assert not psrc.is_section_45_populated("")


def test_section_unpopulated_when_no_markers() -> None:
    body = "## Summary\nLooks good."
    assert not psrc.is_section_45_populated(body)


def test_section_unpopulated_when_only_some_markers() -> None:
    body = "Profile: A\nReviewer: CodeRabbit\n"  # missing Self-review findings:
    assert not psrc.is_section_45_populated(body)


def test_section_unpopulated_when_marker_value_is_stub() -> None:
    body = "Profile: A\n" "Reviewer: CodeRabbit\n" "Self-review findings: TODO\n"
    assert not psrc.is_section_45_populated(body)


def test_section_unpopulated_when_placeholder_brackets() -> None:
    body = (
        "Profile: A\n"
        "Reviewer: CodeRabbit\n"
        "Self-review findings: <finding> stuff\n"
    )
    assert not psrc.is_section_45_populated(body)


def test_section_populated_canonical() -> None:
    body = (
        "## AI-reviewer signoff\n"
        "**Profile**: A\n"
        "**Reviewer**: CodeRabbit — rate-limited\n"
        "**Self-review findings**: 2 findings, both fixed in commits abc/def\n"
    )
    assert psrc.is_section_45_populated(body)


def test_section_populated_minimal_for_bump_pr() -> None:
    body = (
        "Profile: A.\n"
        "Reviewer: CodeRabbit rate-limited; self-review applied.\n"
        "Self-review findings: none, mechanical bump diff only.\n"
    )
    assert psrc.is_section_45_populated(body)


def test_section_unpopulated_when_marker_followed_by_blank() -> None:
    body = (
        "Profile: A\n"
        "Reviewer:\n"  # empty value, no following non-blank line for this marker
        "\n"
        "Self-review findings: 1 finding\n"
    )
    assert not psrc.is_section_45_populated(body)


def test_section_populated_when_marker_has_parenthetical_qualifier() -> None:
    """Regression for v0.9.0-rc1 dogfood bug.

    The PR body that introduced this contract had the form
    ``**Self-review findings** (this branch):`` with a parenthetical
    qualifier between the marker word and the colon. The naive
    ``find("Self-review findings:")`` substring check missed it,
    causing L2 to (incorrectly) post a redundant checklist on a PR that
    HAD §4.5 fully populated. Caught by dogfooding L2 against PR #25
    before the rc1 tag.
    """
    body = (
        "## AI-reviewer signoff (per release-management.md §4.5)\n"
        "\n"
        "**Profile**: A (active on this repo).\n"
        "\n"
        "**Reviewer**: self-review (Profile B fallback).\n"
        "\n"
        "**Self-review findings** (this branch):\n"
        "\n"
        "1. Real bug — fixed in commit `abc123`.\n"
        "2. Doc gap — fixed in commit `def456`.\n"
    )
    assert psrc.is_section_45_populated(body)


def test_section_populated_when_findings_on_next_line() -> None:
    """Marker line ends with `:` and findings start on the next line."""
    body = (
        "Profile: A\n"
        "Reviewer: CodeRabbit\n"
        "Self-review findings:\n"
        "  - first finding\n"
        "  - second finding\n"
    )
    assert psrc.is_section_45_populated(body)


# ---------------------------------------------------------------------------
# analyse_diff
# ---------------------------------------------------------------------------


_SAMPLE_DIFF = """\
diff --git a/apps/api/src/iguanatrader/shared/messagebus.py b/apps/api/src/iguanatrader/shared/messagebus.py
new file mode 100644
--- /dev/null
+++ b/apps/api/src/iguanatrader/shared/messagebus.py
@@ -0,0 +1,30 @@
+from __future__ import annotations
+
+import asyncio
+import contextlib
+from collections import deque
+
+class Event:
+    pass
+
+class MessageBus:
+    def __init__(self) -> None:
+        self._closed = False
+
+    async def publish(self, event: Event) -> None:
+        if self._closed:
+            raise RuntimeError("closed")
+        ...
+
+    async def aclose(self) -> None:
+        self._closed = True
+
+def _classify(events: list) -> str:
+    return "x"
"""


def test_analyse_diff_extracts_files_changed() -> None:
    signals = psrc.analyse_diff(_SAMPLE_DIFF)
    assert "apps/api/src/iguanatrader/shared/messagebus.py" in signals["files_changed"]


def test_analyse_diff_extracts_classes() -> None:
    signals = psrc.analyse_diff(_SAMPLE_DIFF)
    assert "Event" in signals["new_classes"]
    assert "MessageBus" in signals["new_classes"]


def test_analyse_diff_extracts_functions() -> None:
    signals = psrc.analyse_diff(_SAMPLE_DIFF)
    assert "__init__" in signals["new_functions"]
    assert "_classify" in signals["new_functions"]


def test_analyse_diff_extracts_async_functions() -> None:
    signals = psrc.analyse_diff(_SAMPLE_DIFF)
    assert "publish" in signals["new_async"]
    assert "aclose" in signals["new_async"]


def test_analyse_diff_extracts_raise_sites() -> None:
    signals = psrc.analyse_diff(_SAMPLE_DIFF)
    assert any("RuntimeError" in line for line in signals["new_raises"])


def test_analyse_diff_extracts_imports() -> None:
    signals = psrc.analyse_diff(_SAMPLE_DIFF)
    assert any("import asyncio" in i for i in signals["new_imports"])
    assert any("from collections import deque" in i for i in signals["new_imports"])


def test_analyse_diff_empty_diff_returns_empty_signals() -> None:
    signals = psrc.analyse_diff("")
    assert signals["files_changed"] == []
    assert signals["new_functions"] == []
    assert signals["new_classes"] == []


def test_analyse_diff_ignores_removed_lines() -> None:
    diff = """\
diff --git a/x.py b/x.py
--- a/x.py
+++ b/x.py
@@ -1,3 +1,2 @@
-def removed_fn(): pass
-class RemovedClass: pass
 def kept_fn(): pass
"""
    signals = psrc.analyse_diff(diff)
    # Only the unchanged "def kept_fn" line is present, but it's not added (no `+`).
    assert "removed_fn" not in signals["new_functions"]
    assert "RemovedClass" not in signals["new_classes"]
    assert "kept_fn" not in signals["new_functions"]


# ---------------------------------------------------------------------------
# render_checklist
# ---------------------------------------------------------------------------


def test_render_checklist_includes_diff_signals() -> None:
    signals = psrc.analyse_diff(_SAMPLE_DIFF)
    body = psrc.render_checklist(
        pr=1, repo="x/y", signals=signals, reason="rate-limited"
    )
    assert "Self-review checklist" in body
    assert "Files changed" in body
    assert "MessageBus" in body or "Event" in body


def test_render_checklist_lists_seven_categories() -> None:
    signals = psrc.analyse_diff(_SAMPLE_DIFF)
    body = psrc.render_checklist(pr=1, repo="x/y", signals=signals, reason="silent")
    # 7 checklist items per coderabbit-fallback.md §2.
    for cat in (
        "Type safety",
        "Async + concurrency",
        "Error handling",
        "Security",
        "Edge cases",
        "Public API",
        "Spec / runbook compliance",
    ):
        assert cat in body, f"missing category: {cat}"


def test_render_checklist_explains_how_to_resolve() -> None:
    body = psrc.render_checklist(
        pr=1, repo="x/y", signals=psrc.analyse_diff(""), reason="rate-limited"
    )
    assert "Profile:" in body
    assert "Reviewer:" in body
    assert "Self-review findings:" in body


# ---------------------------------------------------------------------------
# run() — end-to-end behavior
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_gh_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(psrc, "_gh_available", lambda: True)


def test_run_skips_silently_when_section_populated(
    stub_gh_available: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    body = (
        "Profile: A\n"
        "Reviewer: self-review applied per §4.5\n"
        "Self-review findings: 2 issues fixed in commits abc/def\n"
    )
    monkeypatch.setattr(psrc, "_gh_pr_body", lambda pr, repo: body)
    monkeypatch.setattr(
        psrc,
        "_gh_pr_diff",
        lambda *a, **kw: pytest.fail("should not call _gh_pr_diff when populated"),
    )
    posted: list[str] = []
    monkeypatch.setattr(
        psrc,
        "_gh_pr_comment",
        lambda pr, repo, body, dry_run: posted.append(body),
    )
    set_check_calls: list[dict[str, str]] = []
    monkeypatch.setattr(
        psrc,
        "_set_status_check",
        lambda *, repo, sha, state, description, dry_run: set_check_calls.append(
            {"state": state, "sha": sha}
        ),
    )

    rc = psrc.run(pr=1, repo="x/y", head_sha="abc123", dry_run=False)
    assert rc == 0
    assert posted == []  # no comment posted
    assert len(set_check_calls) == 1
    assert set_check_calls[0]["state"] == "success"
    assert "no checklist posted" in capsys.readouterr().out


def test_run_posts_checklist_when_section_unpopulated(
    stub_gh_available: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "## Summary\nNothing here."  # no §4.5 markers
    monkeypatch.setattr(psrc, "_gh_pr_body", lambda pr, repo: body)
    monkeypatch.setattr(psrc, "_gh_pr_diff", lambda pr, repo: _SAMPLE_DIFF)
    posted: list[str] = []
    monkeypatch.setattr(
        psrc,
        "_gh_pr_comment",
        lambda pr, repo, body, dry_run: posted.append(body),
    )
    set_check_calls: list[dict[str, str]] = []
    monkeypatch.setattr(
        psrc,
        "_set_status_check",
        lambda *, repo, sha, state, description, dry_run: set_check_calls.append(
            {"state": state}
        ),
    )

    rc = psrc.run(pr=1, repo="x/y", head_sha="abc123", dry_run=False)
    assert rc == 0
    assert len(posted) == 1
    assert "Self-review checklist" in posted[0]
    assert set_check_calls == [{"state": "failure"}]


def test_run_posts_without_status_check_when_no_head_sha(
    stub_gh_available: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(psrc, "_gh_pr_body", lambda pr, repo: "")
    monkeypatch.setattr(psrc, "_gh_pr_diff", lambda pr, repo: _SAMPLE_DIFF)
    posted: list[str] = []
    monkeypatch.setattr(
        psrc,
        "_gh_pr_comment",
        lambda pr, repo, body, dry_run: posted.append(body),
    )
    monkeypatch.setattr(
        psrc,
        "_set_status_check",
        lambda *, repo, sha, state, description, dry_run: pytest.fail(
            "should not set check without head_sha"
        ),
    )

    rc = psrc.run(pr=1, repo="x/y", head_sha=None, dry_run=False)
    assert rc == 0
    assert len(posted) == 1


def test_run_returns_2_when_gh_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(psrc, "_gh_available", lambda: False)
    rc = psrc.run(pr=1, repo="x/y", head_sha=None, dry_run=False)
    assert rc == 2


def test_run_returns_2_on_pr_body_fetch_error(
    stub_gh_available: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(pr: int, repo: str) -> str:
        raise RuntimeError("PR not found")

    monkeypatch.setattr(psrc, "_gh_pr_body", boom)
    rc = psrc.run(pr=99999, repo="x/y", head_sha=None, dry_run=False)
    assert rc == 2


def test_run_returns_3_on_diff_fetch_error(
    stub_gh_available: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(psrc, "_gh_pr_body", lambda pr, repo: "")  # unpopulated

    def boom(pr: int, repo: str) -> str:
        raise RuntimeError("network")

    monkeypatch.setattr(psrc, "_gh_pr_diff", boom)
    rc = psrc.run(pr=1, repo="x/y", head_sha=None, dry_run=False)
    assert rc == 3


def test_run_dry_run_does_not_post(
    stub_gh_available: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(psrc, "_gh_pr_body", lambda pr, repo: "")
    monkeypatch.setattr(psrc, "_gh_pr_diff", lambda pr, repo: _SAMPLE_DIFF)

    # Catch ONLY the side-effect helpers (gh pr comment + check API).
    # Telemetry (_emit) may call git/gh internally — that's fine.
    def fail_post(*a: Any, **kw: Any) -> None:
        raise AssertionError(
            "_gh_pr_comment must not be called via subprocess in dry-run"
        )

    def fail_check(*a: Any, **kw: Any) -> None:
        raise AssertionError("_set_status_check must not call gh api in dry-run")

    real_post_calls: list[tuple[Any, ...]] = []

    original_post = psrc._gh_pr_comment
    original_check = psrc._set_status_check

    def wrapped_post(pr: int, repo: str, body: str, *, dry_run: bool) -> None:
        real_post_calls.append((pr, dry_run))
        return original_post(pr, repo, body, dry_run=dry_run)

    def wrapped_check(
        *, repo: str, sha: str, state: str, description: str, dry_run: bool
    ) -> None:
        real_post_calls.append((sha, state, dry_run))
        return original_check(
            repo=repo, sha=sha, state=state, description=description, dry_run=dry_run
        )

    monkeypatch.setattr(psrc, "_gh_pr_comment", wrapped_post)
    monkeypatch.setattr(psrc, "_set_status_check", wrapped_check)

    rc = psrc.run(pr=1, repo="x/y", head_sha="abc123", dry_run=True)
    assert rc == 0
    # Both helpers were called WITH dry_run=True, so the actual subprocess
    # invocations inside them are short-circuited (per their dry_run guard).
    assert any(call[-1] is True for call in real_post_calls)
    out = capsys.readouterr().out
    assert "would post comment" in out
    assert "would set status check" in out
