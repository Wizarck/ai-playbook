"""Tests for scripts/wt_sweep.py.

Covers BranchEntry classification, plan rendering, dry-run vs --apply behavior,
PR state filtering, and the --include-worktrees / --remote toggles.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import wt_sweep as ws


class _FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ---------------------------------------------------------------------------
# BranchEntry
# ---------------------------------------------------------------------------


def test_branch_entry_merged_is_safe() -> None:
    e = ws.BranchEntry("slice/x", "abc1234", False, 42, "MERGED")
    assert e.is_safe_to_delete is True
    assert "DELETE branch" in e.action


def test_branch_entry_closed_is_safe() -> None:
    e = ws.BranchEntry("slice/x", "abc1234", False, 42, "CLOSED")
    assert e.is_safe_to_delete is True


def test_branch_entry_open_is_not_safe() -> None:
    e = ws.BranchEntry("slice/x", "abc1234", False, 42, "OPEN")
    assert e.is_safe_to_delete is False
    assert "PR OPEN" in e.action


def test_branch_entry_no_pr_is_not_safe() -> None:
    e = ws.BranchEntry("slice/x", "abc1234", False, None, None)
    assert e.is_safe_to_delete is False
    assert "no PR found" in e.action


def test_branch_entry_worktree_signal_in_action() -> None:
    e = ws.BranchEntry("slice/x", "abc1234", True, 42, "MERGED")
    assert "worktree" in e.action


# ---------------------------------------------------------------------------
# require_gh
# ---------------------------------------------------------------------------


def test_require_gh_missing_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws.shutil, "which", lambda _name: None)
    with pytest.raises(SystemExit) as exc:
        ws.require_gh()
    assert exc.value.code == 2


def test_require_gh_unauthenticated_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(ws.subprocess, "run", lambda *a, **k: _FakeProc(returncode=1))
    with pytest.raises(SystemExit) as exc:
        ws.require_gh()
    assert exc.value.code == 2


def test_require_gh_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(ws.subprocess, "run", lambda *a, **k: _FakeProc(returncode=0))
    ws.require_gh()  # must not raise


# ---------------------------------------------------------------------------
# lookup_pr
# ---------------------------------------------------------------------------


def test_lookup_pr_returns_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = json.dumps([{"number": 42, "state": "MERGED"}])
    monkeypatch.setattr(
        ws.subprocess,
        "run",
        lambda *a, **k: _FakeProc(returncode=0, stdout=payload),
    )
    num, state = ws.lookup_pr("slice/x", tmp_path)
    assert num == 42 and state == "MERGED"


def test_lookup_pr_no_match_returns_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        ws.subprocess,
        "run",
        lambda *a, **k: _FakeProc(returncode=0, stdout="[]"),
    )
    num, state = ws.lookup_pr("slice/x", tmp_path)
    assert num is None and state is None


# ---------------------------------------------------------------------------
# gather_entries (integration with stubbed git/gh)
# ---------------------------------------------------------------------------


def test_gather_entries_full_pipeline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".bare").mkdir()
    (tmp_path / "slice-a").mkdir()

    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[:2] == ["git", "for-each-ref"]:
            return _FakeProc(
                returncode=0,
                stdout="slice/a\tabc1234\nslice/b\tdef5678\n",
            )
        if cmd[:3] == ["git", "worktree", "list"]:
            return _FakeProc(
                returncode=0,
                stdout=f"worktree {tmp_path / 'slice-a'}\nHEAD abc\n",
            )
        if cmd[:1] == ["gh"]:
            if "slice/a" in cmd:
                return _FakeProc(
                    returncode=0,
                    stdout=json.dumps([{"number": 1, "state": "MERGED"}]),
                )
            if "slice/b" in cmd:
                return _FakeProc(
                    returncode=0,
                    stdout=json.dumps([{"number": 2, "state": "OPEN"}]),
                )
        return _FakeProc(returncode=0, stdout="[]")

    monkeypatch.setattr(ws.subprocess, "run", fake_run)
    entries = ws.gather_entries(tmp_path, tmp_path / ".bare", "slice/")
    by_name = {e.name: e for e in entries}
    assert by_name["slice/a"].pr_state == "MERGED"
    assert by_name["slice/a"].is_safe_to_delete is True
    assert by_name["slice/b"].pr_state == "OPEN"
    assert by_name["slice/b"].is_safe_to_delete is False


# ---------------------------------------------------------------------------
# apply_deletes
# ---------------------------------------------------------------------------


def test_apply_deletes_skips_unsafe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".bare").mkdir()
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return _FakeProc(returncode=0)

    monkeypatch.setattr(ws.subprocess, "run", fake_run)
    entries = [
        ws.BranchEntry("slice/open", "aaa", False, 1, "OPEN"),
        ws.BranchEntry("slice/closed", "bbb", False, 2, "CLOSED"),
    ]
    deleted = ws.apply_deletes(
        entries,
        repo_root=tmp_path,
        bare_dir=tmp_path / ".bare",
        include_worktrees=False,
        delete_remote=False,
    )
    assert deleted == 1  # only slice/closed
    assert any(cmd[:3] == ["git", "branch", "-D"] and cmd[3] == "slice/closed" for cmd in calls)
    assert not any(cmd[3:] == ["slice/open"] for cmd in calls if cmd[:3] == ["git", "branch", "-D"])


def test_apply_deletes_skips_with_worktree_without_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".bare").mkdir()
    monkeypatch.setattr(ws.subprocess, "run", lambda *a, **k: _FakeProc(returncode=0))
    entries = [ws.BranchEntry("slice/a", "aaa", True, 1, "MERGED")]
    deleted = ws.apply_deletes(
        entries,
        repo_root=tmp_path,
        bare_dir=tmp_path / ".bare",
        include_worktrees=False,
        delete_remote=False,
    )
    assert deleted == 0
    assert "has worktree" in capsys.readouterr().out


def test_apply_deletes_removes_worktree_with_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".bare").mkdir()
    calls: list[list[str]] = []
    monkeypatch.setattr(
        ws.subprocess,
        "run",
        lambda cmd, *a, **k: (calls.append(list(cmd)) or _FakeProc(returncode=0)),
    )
    entries = [ws.BranchEntry("slice/a", "aaa", True, 1, "MERGED")]
    deleted = ws.apply_deletes(
        entries,
        repo_root=tmp_path,
        bare_dir=tmp_path / ".bare",
        include_worktrees=True,
        delete_remote=False,
    )
    assert deleted == 1
    assert any(cmd[:3] == ["git", "worktree", "remove"] for cmd in calls)
    assert any(cmd[:3] == ["git", "branch", "-D"] for cmd in calls)


def test_apply_deletes_remote_pushes_delete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".bare").mkdir()
    calls: list[list[str]] = []
    monkeypatch.setattr(
        ws.subprocess,
        "run",
        lambda cmd, *a, **k: (calls.append(list(cmd)) or _FakeProc(returncode=0)),
    )
    entries = [ws.BranchEntry("slice/a", "aaa", False, 1, "MERGED")]
    ws.apply_deletes(
        entries,
        repo_root=tmp_path,
        bare_dir=tmp_path / ".bare",
        include_worktrees=False,
        delete_remote=True,
    )
    assert any(cmd[:4] == ["git", "push", "origin", "--delete"] for cmd in calls)
