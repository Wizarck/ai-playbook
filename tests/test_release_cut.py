"""Tests for scripts/release_cut.py — zero-touch release automation."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import issue_sync, release_cut
from scripts import notify as notify_mod

CHANGELOG = """\
# Changelog

## v1.2.3
- Added feature X
- Fixed bug Y

## v1.2.2
- Earlier release

## 1.0.0
- Ancient
"""


@pytest.fixture(autouse=True)
def _reset_notify() -> None:
    notify_mod._reset_state_for_tests()


@pytest.fixture
def jsonl_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / ".ai-playbook" / "notifications.jsonl"
    monkeypatch.setenv("AIPLAYBOOK_NOTIFICATIONS_FILE", str(path))
    for var in ("SMTP_USER", "SMTP_PASSWORD",
                "ATLASSIAN_URL", "ATLASSIAN_USERNAME", "ATLASSIAN_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "tester@example.com")
    return path


def _make_repo(tmp_path: Path, *, changelog: str = CHANGELOG) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# CHANGELOG parsing
# ---------------------------------------------------------------------------


def test_extract_changelog_section_with_v_prefix(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    out = release_cut.extract_changelog_section(root / "CHANGELOG.md", "v1.2.3")
    assert out and "Added feature X" in out and "Earlier release" not in out


def test_extract_changelog_section_without_v(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    out = release_cut.extract_changelog_section(root / "CHANGELOG.md", "1.2.3")
    assert out and "Added feature X" in out


def test_extract_changelog_section_missing(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    out = release_cut.extract_changelog_section(root / "CHANGELOG.md", "v9.9.9")
    assert out is None


def test_extract_changelog_section_no_file(tmp_path: Path) -> None:
    out = release_cut.extract_changelog_section(tmp_path / "missing.md", "v1.0.0")
    assert out is None


# ---------------------------------------------------------------------------
# Tag resolution (mocked git)
# ---------------------------------------------------------------------------


def test_resolve_tag_explicit_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _run(cmd, **kw):
        if cmd[:3] == ["git", "tag", "-l"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="v1.2.3\n", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
    monkeypatch.setattr(release_cut.subprocess, "run", _run)
    assert release_cut.resolve_tag(tmp_path, explicit="v1.2.3") == "v1.2.3"


def test_resolve_tag_explicit_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    monkeypatch.setattr(release_cut.subprocess, "run", _run)
    assert release_cut.resolve_tag(tmp_path, explicit="v1.2.3") is None


def test_resolve_tag_exact_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout="v2.0.0\n", stderr="")
    monkeypatch.setattr(release_cut.subprocess, "run", _run)
    assert release_cut.resolve_tag(tmp_path) == "v2.0.0"


def test_resolve_previous_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout="v1.2.2\n", stderr="")
    monkeypatch.setattr(release_cut.subprocess, "run", _run)
    assert release_cut.resolve_previous_tag(tmp_path, "v1.2.3") == "v1.2.2"


def test_archived_change_proposals_parses_git_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _run(cmd, **kw):
        out = "\n".join([
            "",
            "openspec/changes/archive/x/proposal.md",
            "openspec/changes/archive/x/tasks.md",
            "openspec/changes/archive/y/proposal.md",
            "openspec/changes/archive/x/proposal.md",  # dupe
        ])
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
    monkeypatch.setattr(release_cut.subprocess, "run", _run)
    props = release_cut.archived_change_proposals(
        tmp_path, since_tag="v1.0.0", current_tag="v1.1.0",
    )
    assert len(props) == 2
    assert all(p.name == "proposal.md" for p in props)


def test_tracker_ids_from_proposals_extracts(tmp_path: Path) -> None:
    p1 = tmp_path / "p1.md"
    p2 = tmp_path / "p2.md"
    p1.write_text("---\ntracker_id: PROJ-1\n---\nbody\n", encoding="utf-8")
    p2.write_text("---\ntracker_issue: 7\n---\nbody\n", encoding="utf-8")
    ids = release_cut.tracker_ids_from_proposals([p1, p2, tmp_path / "missing.md"])
    assert sorted(ids) == ["7", "PROJ-1"]


# ---------------------------------------------------------------------------
# GH release helpers
# ---------------------------------------------------------------------------


def test_gh_release_exists_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        release_cut.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""),
    )
    assert release_cut.gh_release_exists("v1.0.0", tmp_path) is True


def test_gh_release_exists_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        release_cut.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not found"),
    )
    assert release_cut.gh_release_exists("v9", tmp_path) is False


def test_gh_release_create_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        release_cut.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""),
    )
    notes = tmp_path / "notes.md"
    notes.write_text("release!", encoding="utf-8")
    ok, reason = release_cut.gh_release_create(
        tag="v1", notes_file=notes, cwd=tmp_path,
    )
    assert ok is True and reason == "ok"


def test_gh_release_create_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*a, **kw):
        raise AssertionError("subprocess should not run in dry-run")
    monkeypatch.setattr(release_cut.subprocess, "run", _boom)
    ok, reason = release_cut.gh_release_create(
        tag="v1", notes_file=tmp_path / "x", cwd=tmp_path, dry_run=True,
    )
    assert ok is True and reason == "dry-run"


# ---------------------------------------------------------------------------
# Jira fixVersion
# ---------------------------------------------------------------------------


def _fake_jira(responses: list[tuple[int, dict | list | None]]) -> Any:
    """Return a fake urlopen that emits a queue of (status, payload) tuples."""
    iter_responses = iter(responses)

    def _opener(req, timeout=10.0):
        status, payload = next(iter_responses)
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        class _R:
            def __init__(self):
                self.status = status
            def __enter__(self): return self
            def __exit__(self, *a): return None
            def read(self): return body
        return _R()
    return _opener


def test_jira_find_fixversion_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        release_cut.urlrequest, "urlopen",
        _fake_jira([(200, [{"id": "10001", "name": "repo-1.2.3"}])]),
    )
    creds = issue_sync.JiraCreds(url="https://x", username="u", api_token="t")
    vid, reason = release_cut.jira_find_or_create_fixversion(
        creds=creds, project_key="PROJ", name="repo-1.2.3",
    )
    assert vid == "10001" and reason == "exists"


def test_jira_create_fixversion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        release_cut.urlrequest, "urlopen",
        _fake_jira([
            (200, []),  # GET versions → empty
            (201, {"id": "20002", "name": "repo-1.2.3"}),  # POST create
        ]),
    )
    creds = issue_sync.JiraCreds(url="https://x", username="u", api_token="t")
    vid, reason = release_cut.jira_find_or_create_fixversion(
        creds=creds, project_key="PROJ", name="repo-1.2.3",
    )
    assert vid == "20002" and reason == "created"


def test_jira_mark_released_updates_and_transitions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        release_cut.urlrequest, "urlopen",
        _fake_jira([
            (204, None),  # PUT issue update
            (200, {"transitions": [{"id": "31", "name": "Released"}]}),
            (204, None),  # POST transition
        ]),
    )
    creds = issue_sync.JiraCreds(url="https://x", username="u", api_token="t")
    ok, reason = release_cut.jira_mark_released(
        creds=creds, tracker_id="PROJ-1", fixversion_name="repo-1.2.3",
    )
    assert ok is True and reason == "ok"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def test_build_context_returns_none_when_tag_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_repo(tmp_path)
    monkeypatch.setattr(release_cut, "resolve_tag", lambda p, explicit=None: None)
    ctx, reason = release_cut.build_context(repo_root=root, tag_override=None)
    assert ctx is None
    assert reason == "tag-not-found"


def test_build_context_returns_none_when_changelog_section_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_repo(tmp_path)
    monkeypatch.setattr(release_cut, "resolve_tag", lambda p, explicit=None: "v9.9.9")
    monkeypatch.setattr(release_cut, "resolve_previous_tag", lambda p, t: None)
    monkeypatch.setattr(issue_sync, "_gh_repo_visibility", lambda p: "PUBLIC")
    monkeypatch.setattr(issue_sync, "_gh_repo_nwo", lambda p: "w/r")
    ctx, reason = release_cut.build_context(repo_root=root, tag_override=None)
    assert ctx is None
    assert reason == "changelog-section-missing"


def test_run_release_public_happy(
    tmp_path: Path, jsonl_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_repo(tmp_path)
    monkeypatch.setattr(release_cut, "resolve_tag", lambda p, explicit=None: "v1.2.3")
    monkeypatch.setattr(release_cut, "resolve_previous_tag", lambda p, t: "v1.2.2")
    monkeypatch.setattr(
        release_cut, "archived_change_proposals",
        lambda p, since_tag, current_tag: [],
    )
    monkeypatch.setattr(issue_sync, "_gh_repo_visibility", lambda p: "PUBLIC")
    monkeypatch.setattr(issue_sync, "_gh_repo_nwo", lambda p: "Wizarck/repo")
    monkeypatch.setattr(release_cut, "gh_release_exists", lambda tag, cwd: False)
    monkeypatch.setattr(
        release_cut, "gh_release_create",
        lambda **kw: (True, "ok"),
    )
    rc, outcome = release_cut.run_release(repo_root=root, tag_override="v1.2.3")
    assert rc == 0
    assert outcome.ok is True
    assert "github_released" in outcome.steps


def test_run_release_refuses_to_overwrite(
    tmp_path: Path, jsonl_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_repo(tmp_path)
    monkeypatch.setattr(release_cut, "resolve_tag", lambda p, explicit=None: "v1.2.3")
    monkeypatch.setattr(release_cut, "resolve_previous_tag", lambda p, t: None)
    monkeypatch.setattr(
        release_cut, "archived_change_proposals",
        lambda p, since_tag, current_tag: [],
    )
    monkeypatch.setattr(issue_sync, "_gh_repo_visibility", lambda p: "PUBLIC")
    monkeypatch.setattr(issue_sync, "_gh_repo_nwo", lambda p: "w/r")
    monkeypatch.setattr(release_cut, "gh_release_exists", lambda tag, cwd: True)
    rc, outcome = release_cut.run_release(repo_root=root, tag_override="v1.2.3")
    assert rc == 1
    assert "gh-release-exists" in outcome.errors


def test_run_release_private_requires_jira_creds(
    tmp_path: Path, jsonl_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_repo(tmp_path)
    monkeypatch.setattr(release_cut, "resolve_tag", lambda p, explicit=None: "v1.2.3")
    monkeypatch.setattr(release_cut, "resolve_previous_tag", lambda p, t: None)
    monkeypatch.setattr(
        release_cut, "archived_change_proposals",
        lambda p, since_tag, current_tag: [],
    )
    monkeypatch.setattr(issue_sync, "_gh_repo_visibility", lambda p: "PRIVATE")
    monkeypatch.setattr(issue_sync, "_gh_repo_nwo", lambda p: None)
    monkeypatch.setattr(issue_sync, "_load_jira_creds", lambda: None)
    rc, outcome = release_cut.run_release(repo_root=root, tag_override="v1.2.3")
    assert rc == 2
    assert "jira-creds" in outcome.errors


def test_run_release_private_dry_run_skips_api(
    tmp_path: Path, jsonl_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_repo(tmp_path)
    monkeypatch.setattr(release_cut, "resolve_tag", lambda p, explicit=None: "v1.2.3")
    monkeypatch.setattr(release_cut, "resolve_previous_tag", lambda p, t: None)
    monkeypatch.setattr(
        release_cut, "archived_change_proposals",
        lambda p, since_tag, current_tag: [],
    )
    monkeypatch.setattr(issue_sync, "_gh_repo_visibility", lambda p: "PRIVATE")
    monkeypatch.setattr(issue_sync, "_gh_repo_nwo", lambda p: None)
    monkeypatch.setattr(
        issue_sync, "_load_jira_creds",
        lambda: issue_sync.JiraCreds(url="https://x", username="u", api_token="t"),
    )
    # Ensure no real http call happens.
    def _boom(*a, **kw):
        raise AssertionError("HTTP must not fire in dry-run private path")
    monkeypatch.setattr(release_cut.urlrequest, "urlopen", _boom)
    rc, outcome = release_cut.run_release(
        repo_root=root, tag_override="v1.2.3", dry_run=True,
    )
    assert rc == 0
    assert "jira_fixversion_created" in outcome.steps


def test_run_release_emits_complete_notification(
    tmp_path: Path, jsonl_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_repo(tmp_path)
    monkeypatch.setattr(release_cut, "resolve_tag", lambda p, explicit=None: "v1.2.3")
    monkeypatch.setattr(release_cut, "resolve_previous_tag", lambda p, t: None)
    monkeypatch.setattr(
        release_cut, "archived_change_proposals",
        lambda p, since_tag, current_tag: [],
    )
    monkeypatch.setattr(issue_sync, "_gh_repo_visibility", lambda p: "PUBLIC")
    monkeypatch.setattr(issue_sync, "_gh_repo_nwo", lambda p: "w/r")
    monkeypatch.setattr(release_cut, "gh_release_exists", lambda tag, cwd: False)
    monkeypatch.setattr(release_cut, "gh_release_create", lambda **kw: (True, "ok"))

    rc, _ = release_cut.run_release(repo_root=root, tag_override="v1.2.3")
    assert rc == 0
    lines = [json.loads(l) for l in jsonl_path.read_text(encoding="utf-8").splitlines()]
    events = [l["event"] for l in lines]
    assert "release_cut.start" in events
    assert "release_cut.changes_collected" in events
    assert "release_cut.github_released" in events
    assert "release_cut.complete" in events


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_errors_when_not_git_repo(
    jsonl_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = release_cut.main(["--repo-root", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "not a git repository" in err
    assert "OVERRIDE:" in err


def test_cli_force_with_reason_bypasses_git_check(
    jsonl_path: Path, tmp_path: Path,
) -> None:
    rc = release_cut.main([
        "--repo-root", str(tmp_path),
        "--force-with-reason", "bootstrapping release harness on CI",
    ])
    assert rc == 0


def test_cli_dry_run_public_path(
    jsonl_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_repo(tmp_path)
    monkeypatch.setattr(release_cut, "resolve_tag", lambda p, explicit=None: "v1.2.3")
    monkeypatch.setattr(release_cut, "resolve_previous_tag", lambda p, t: None)
    monkeypatch.setattr(
        release_cut, "archived_change_proposals",
        lambda p, since_tag, current_tag: [],
    )
    monkeypatch.setattr(issue_sync, "_gh_repo_visibility", lambda p: "PUBLIC")
    monkeypatch.setattr(issue_sync, "_gh_repo_nwo", lambda p: "w/r")
    monkeypatch.setattr(release_cut, "gh_release_exists", lambda tag, cwd: False)
    monkeypatch.setattr(release_cut, "gh_release_create", lambda **kw: (True, "dry-run"))
    rc = release_cut.main(["--repo-root", str(root), "--tag", "v1.2.3", "--dry-run"])
    assert rc == 0


def test_cli_tag_not_found_exits_1(
    jsonl_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_repo(tmp_path)
    monkeypatch.setattr(release_cut, "resolve_tag", lambda p, explicit=None: None)
    rc = release_cut.main(["--repo-root", str(root), "--tag", "v9.9.9"])
    assert rc == 1
