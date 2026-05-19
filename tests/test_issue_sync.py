"""Tests for scripts/issue_sync.py — zero-touch tracker sync."""
from __future__ import annotations

import json
import subprocess
from datetime import UTC
from pathlib import Path
from typing import Any

import pytest

from scripts import issue_sync
from scripts import notify as notify_mod

PROPOSAL_WITHOUT = """\
---
change_id: demo-change
project: demo
---
# Proposal

Body goes here.
"""

PROPOSAL_WITH_TRACKER_ID = """\
---
change_id: demo-change
tracker_id: PROJ-42
project: demo
---
# Proposal

Body.
"""

AGENTS_MD = """\
---
schema: agents-md/v1
version: 1.0.0
project: {project}
personal: {personal}
{tracker_block}---
# body
"""


@pytest.fixture(autouse=True)
def _reset_notify() -> None:
    notify_mod._reset_state_for_tests()


@pytest.fixture
def jsonl_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / ".ai-playbook" / "notifications.jsonl"
    monkeypatch.setenv("AIPLAYBOOK_NOTIFICATIONS_FILE", str(path))
    for var in ("SMTP_USER", "SMTP_PASSWORD",
                "ATLASSIAN_URL", "ATLASSIAN_USERNAME", "ATLASSIAN_API_TOKEN",
                "AIPLAYBOOK_GH_PROJECT_NUMBER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "tester@example.com")
    return path


def _make_consumer(
    tmp_path: Path, *, project: str = "acme", personal: bool = False,
    tracker_kind: str | None = None, jira_project: str | None = None,
    proposals: dict[str, str] | None = None,
) -> Path:
    root = tmp_path / project
    root.mkdir()
    tracker_lines: list[str] = []
    if tracker_kind is not None:
        tracker_lines.append(f"tracker_kind: {tracker_kind}")
    if jira_project is not None:
        tracker_lines.append(f"jira_project: {jira_project}")
    tracker_block = ("\n".join(tracker_lines) + "\n") if tracker_lines else ""
    (root / "AGENTS.md").write_text(
        AGENTS_MD.format(
            project=project, personal=str(personal).lower(),
            tracker_block=tracker_block,
        ),
        encoding="utf-8",
    )
    changes = root / "openspec" / "changes"
    changes.mkdir(parents=True)
    for slug, content in (proposals or {}).items():
        c = changes / slug
        c.mkdir()
        (c / "proposal.md").write_text(content, encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


def test_parse_frontmatter_extracts_keys() -> None:
    fm, body = issue_sync.parse_frontmatter(PROPOSAL_WITH_TRACKER_ID)
    assert fm["tracker_id"] == "PROJ-42"
    assert fm["change_id"] == "demo-change"
    assert "Body." in body


def test_parse_frontmatter_missing_fm() -> None:
    fm, body = issue_sync.parse_frontmatter("# plain\n")
    assert fm == {}
    assert body.startswith("# plain")


def test_render_with_frontmatter_roundtrips() -> None:
    fm = {"tracker_id": "PROJ-42", "change_id": "x"}
    out = issue_sync.render_with_frontmatter(fm, "body\n")
    parsed, body = issue_sync.parse_frontmatter(out)
    assert parsed["tracker_id"] == "PROJ-42"
    assert "body" in body


# ---------------------------------------------------------------------------
# Scan proposals
# ---------------------------------------------------------------------------


def test_scan_finds_proposals(tmp_path: Path) -> None:
    root = _make_consumer(
        tmp_path,
        proposals={"a": PROPOSAL_WITHOUT, "b": PROPOSAL_WITH_TRACKER_ID},
    )
    props = issue_sync.scan_proposals(root)
    slugs = sorted(p.change_id for p in props)
    assert slugs == ["a", "b"]


def test_scan_ignores_archive_dir(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path, proposals={"active": PROPOSAL_WITHOUT})
    archive = root / "openspec" / "changes" / "archive" / "old"
    archive.mkdir(parents=True)
    (archive / "proposal.md").write_text(PROPOSAL_WITH_TRACKER_ID, encoding="utf-8")
    props = issue_sync.scan_proposals(root)
    assert [p.change_id for p in props] == ["active"]


def test_proposal_has_tracker() -> None:
    assert issue_sync.proposal_has_tracker({"tracker_id": "X"}) is True
    assert issue_sync.proposal_has_tracker({"tracker_issue": "5"}) is True
    assert issue_sync.proposal_has_tracker({}) is False


# ---------------------------------------------------------------------------
# Surface decision  (v0.19.0+: tracker_kind read from AGENTS.md frontmatter)
# ---------------------------------------------------------------------------


def test_decide_surface_personal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # personal flag in AGENTS.md wins over tracker_kind — personal repos never
    # publish externally regardless of tracker_kind.
    root = _make_consumer(
        tmp_path, project="ai-playbook", personal=True, tracker_kind="github",
    )
    monkeypatch.setattr(issue_sync, "_gh_available", lambda: True)
    monkeypatch.setattr(issue_sync, "_gh_repo_nwo", lambda p: "Wizarck/ai-playbook")
    decision = issue_sync.decide_surface(root)
    assert decision.kind == "github-personal"
    assert decision.gh_repo == "Wizarck/ai-playbook"


def test_decide_surface_github_from_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_consumer(
        tmp_path, project="consumer-c", personal=False, tracker_kind="github",
    )
    monkeypatch.setattr(issue_sync, "_gh_available", lambda: True)
    monkeypatch.setattr(issue_sync, "_gh_repo_nwo", lambda p: "Wizarck/consumer-c")
    monkeypatch.setenv("AIPLAYBOOK_GH_PROJECT_NUMBER", "42")
    decision = issue_sync.decide_surface(root)
    assert decision.kind == "github"
    assert decision.gh_project_number == "42"
    assert "tracker_kind=github" in decision.reason


def test_decide_surface_jira_from_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_consumer(
        tmp_path, project="future-jira-consumer", personal=False,
        tracker_kind="jira", jira_project="consumer-c-legacy",
    )
    monkeypatch.setattr(issue_sync, "_gh_available", lambda: False)
    decision = issue_sync.decide_surface(root)
    assert decision.kind == "jira"
    assert decision.jira_project == "consumer-c-legacy"
    assert "tracker_kind=jira" in decision.reason


def test_decide_surface_missing_tracker_kind_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_consumer(tmp_path, project="undeclared", personal=False)
    monkeypatch.setattr(issue_sync, "_gh_available", lambda: False)
    with pytest.raises(RuntimeError, match=r"no tracker_kind"):
        issue_sync.decide_surface(root)


def test_decide_surface_invalid_tracker_kind_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_consumer(
        tmp_path, project="bad-config", personal=False, tracker_kind="atlassian",
    )
    monkeypatch.setattr(issue_sync, "_gh_available", lambda: False)
    with pytest.raises(RuntimeError, match=r"invalid tracker_kind"):
        issue_sync.decide_surface(root)


def test_decide_surface_jira_without_project_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_consumer(
        tmp_path, project="missing-jira-key", personal=False, tracker_kind="jira",
    )
    monkeypatch.setattr(issue_sync, "_gh_available", lambda: False)
    with pytest.raises(RuntimeError, match=r"no jira_project"):
        issue_sync.decide_surface(root)


def test_jira_project_for_returns_none_for_github(tmp_path: Path) -> None:
    root = _make_consumer(
        tmp_path, project="consumer-c", personal=False, tracker_kind="github",
    )
    assert issue_sync.jira_project_for(root) is None


def test_jira_project_for_returns_key_for_jira(tmp_path: Path) -> None:
    root = _make_consumer(
        tmp_path, project="some-jira-consumer", personal=False,
        tracker_kind="jira", jira_project="FOO",
    )
    assert issue_sync.jira_project_for(root) == "FOO"


# ---------------------------------------------------------------------------
# Jira client
# ---------------------------------------------------------------------------


def _fake_urlopen_success(body: dict) -> Any:
    def _opener(req, timeout=10.0):
        class _R:
            def __enter__(self): return self
            def __exit__(self, *a): return None
            def read(self): return json.dumps(body).encode("utf-8")
        return _R()
    return _opener


def test_create_jira_issue_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        issue_sync.urlrequest, "urlopen",
        _fake_urlopen_success({"key": "PROJ-123", "id": "10001"}),
    )
    creds = issue_sync.JiraCreds(url="https://x", username="u", api_token="t")
    key, reason = issue_sync.create_jira_issue(
        creds=creds, project_key="PROJ", summary="s", description="d",
    )
    assert key == "PROJ-123"
    assert reason == "ok"


def test_create_jira_issue_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from urllib import error as urlerror

    def _boom(req, timeout=10.0):
        raise urlerror.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(issue_sync.urlrequest, "urlopen", _boom)
    creds = issue_sync.JiraCreds(url="https://x", username="u", api_token="t")
    key, reason = issue_sync.create_jira_issue(
        creds=creds, project_key="P", summary="s", description="d",
    )
    assert key is None
    assert "http-401" in reason


def test_load_jira_creds_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATLASSIAN_URL", raising=False)
    assert issue_sync._load_jira_creds() is None


def test_load_jira_creds_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLASSIAN_URL", "https://x")
    monkeypatch.setenv("ATLASSIAN_USERNAME", "u")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "t")
    creds = issue_sync._load_jira_creds()
    assert creds and creds.url == "https://x"


# ---------------------------------------------------------------------------
# GH client
# ---------------------------------------------------------------------------


def test_create_gh_issue_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def _run(cmd, **kw):
        return subprocess.CompletedProcess(
            cmd, 0, stdout="https://github.com/Wizarck/x/issues/42\n", stderr="",
        )
    monkeypatch.setattr(issue_sync.subprocess, "run", _run)
    number, reason = issue_sync.create_gh_issue(
        repo="Wizarck/x", title="t", body="b",
    )
    assert number == "42"
    assert reason == "ok"


def test_create_gh_issue_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")
    monkeypatch.setattr(issue_sync.subprocess, "run", _run)
    number, reason = issue_sync.create_gh_issue(repo="X/Y", title="t", body="b")
    assert number is None
    assert "gh-create-rc-1" in reason


# ---------------------------------------------------------------------------
# Retry queue
# ---------------------------------------------------------------------------


def test_queue_entry_and_read(tmp_path: Path) -> None:
    issue_sync.queue_entry(tmp_path, change_id="cc", reason="x")
    entries = issue_sync.read_queue(tmp_path)
    assert entries[0]["change_id"] == "cc"
    assert entries[0]["reason"] == "x"


def test_prune_queue_drops_old(tmp_path: Path) -> None:
    from datetime import datetime, timedelta

    old = (datetime.now(UTC).astimezone() - timedelta(days=10)).isoformat(timespec="seconds")
    recent = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
    path = issue_sync._queue_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"ts": old, "change_id": "old", "reason": "x"}) + "\n" +
        json.dumps({"ts": recent, "change_id": "new", "reason": "y"}) + "\n",
        encoding="utf-8",
    )
    dropped = issue_sync.prune_queue(tmp_path)
    assert len(dropped) == 1
    assert dropped[0]["change_id"] == "old"
    remaining = issue_sync.read_queue(tmp_path)
    assert [e["change_id"] for e in remaining] == ["new"]


# ---------------------------------------------------------------------------
# End-to-end sync
# ---------------------------------------------------------------------------


def test_sync_all_skips_when_tracker_present(
    tmp_path: Path, jsonl_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_consumer(
        tmp_path, project="demo",
        proposals={"a": PROPOSAL_WITH_TRACKER_ID},
    )
    monkeypatch.setattr(
        issue_sync, "decide_surface",
        lambda p: issue_sync.SurfaceDecision(kind="jira", jira_project="consumer-a"),
    )
    outcome = issue_sync.sync_all(consumer_root=root)
    assert outcome.skipped == 1
    assert outcome.created == 0


def test_sync_all_creates_jira_issue_and_writes_back(
    tmp_path: Path, jsonl_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_consumer(
        tmp_path, project="consumer-b",
        proposals={"new-feature": PROPOSAL_WITHOUT},
    )
    monkeypatch.setenv("ATLASSIAN_URL", "https://x")
    monkeypatch.setenv("ATLASSIAN_USERNAME", "u")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "t")
    monkeypatch.setattr(
        issue_sync, "decide_surface",
        lambda p: issue_sync.SurfaceDecision(kind="jira", jira_project="consumer-b"),
    )
    monkeypatch.setattr(
        issue_sync.urlrequest, "urlopen",
        _fake_urlopen_success({"key": "consumer-b-7"}),
    )
    outcome = issue_sync.sync_all(consumer_root=root)
    assert outcome.created == 1
    # Verify proposal now carries the tracker_id.
    prop = (root / "openspec" / "changes" / "new-feature" / "proposal.md").read_text(encoding="utf-8")
    assert "tracker_id: consumer-b-7" in prop


def test_sync_all_queues_on_failure(
    tmp_path: Path, jsonl_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_consumer(
        tmp_path, project="consumer-b",
        proposals={"fails": PROPOSAL_WITHOUT},
    )
    monkeypatch.setattr(
        issue_sync, "decide_surface",
        lambda p: issue_sync.SurfaceDecision(kind="jira", jira_project="consumer-b"),
    )
    monkeypatch.setattr(issue_sync, "_load_jira_creds", lambda: None)
    outcome = issue_sync.sync_all(consumer_root=root)
    assert outcome.failed == 1
    queue = issue_sync.read_queue(root)
    assert queue[0]["change_id"] == "fails"
    # Emits warn notification.
    lines = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert any(line["event"] == "issue_sync.failed" for line in lines)


def test_sync_all_dry_run_does_not_write(
    tmp_path: Path, jsonl_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_consumer(
        tmp_path, project="acme",
        proposals={"c": PROPOSAL_WITHOUT},
    )
    monkeypatch.setattr(
        issue_sync, "decide_surface",
        lambda p: issue_sync.SurfaceDecision(kind="jira", jira_project="consumer-a"),
    )
    outcome = issue_sync.sync_all(consumer_root=root, dry_run=True)
    assert outcome.created == 1
    prop = (root / "openspec" / "changes" / "c" / "proposal.md").read_text(encoding="utf-8")
    # Proposal frontmatter untouched in dry-run.
    assert "tracker_id" not in prop


def test_sync_all_idempotent_on_second_run(
    tmp_path: Path, jsonl_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_consumer(
        tmp_path, project="consumer-b",
        proposals={"once": PROPOSAL_WITHOUT},
    )
    monkeypatch.setenv("ATLASSIAN_URL", "https://x")
    monkeypatch.setenv("ATLASSIAN_USERNAME", "u")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "t")
    monkeypatch.setattr(
        issue_sync, "decide_surface",
        lambda p: issue_sync.SurfaceDecision(kind="jira", jira_project="consumer-b"),
    )
    monkeypatch.setattr(
        issue_sync.urlrequest, "urlopen",
        _fake_urlopen_success({"key": "consumer-b-1"}),
    )
    first = issue_sync.sync_all(consumer_root=root)
    assert first.created == 1
    second = issue_sync.sync_all(consumer_root=root)
    assert second.created == 0
    assert second.skipped == 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_errors_when_consumer_root_missing(jsonl_path: Path, tmp_path: Path) -> None:
    fake = tmp_path / "does-not-exist"
    rc = issue_sync.main(["--consumer-root", str(fake)])
    assert rc == 2


def test_cli_errors_when_no_openspec_dir(
    jsonl_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "AGENTS.md").write_text(
        AGENTS_MD.format(project="x", personal="false", tracker_block=""),
        encoding="utf-8",
    )
    rc = issue_sync.main(["--consumer-root", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "no openspec/changes" in err
    assert "FIX:" in err
    assert "OVERRIDE:" in err


def test_cli_break_glass_accepts_missing_openspec(
    jsonl_path: Path, tmp_path: Path,
) -> None:
    (tmp_path / "AGENTS.md").write_text(
        AGENTS_MD.format(project="x", personal="false", tracker_block=""),
        encoding="utf-8",
    )
    rc = issue_sync.main([
        "--consumer-root", str(tmp_path),
        "--force-with-reason", "bootstrapping repo without openspec yet",
    ])
    assert rc == 0


def test_cli_dry_run_succeeds(
    jsonl_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_consumer(
        tmp_path, project="acme",
        proposals={"c": PROPOSAL_WITHOUT},
    )
    monkeypatch.setattr(
        issue_sync, "decide_surface",
        lambda p: issue_sync.SurfaceDecision(kind="jira", jira_project="consumer-a"),
    )
    rc = issue_sync.main(["--consumer-root", str(root), "--dry-run"])
    assert rc == 0
