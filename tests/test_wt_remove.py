"""Tests for scripts/wt_remove.py.

Mocks subprocess.run + filesystem so tests never touch a real git repo.
Covers: layout discovery, PR state gating, --force override, --keep-branch,
--dry-run, exit codes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import wt_remove as wr

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _stub_layout(tmp_path: Path, change_id: str = "fix-bug") -> Path:
    """Create a minimal bare-layout fixture and return repo_root."""
    (tmp_path / ".bare").mkdir()
    (tmp_path / change_id).mkdir()  # worktree dir
    return tmp_path


def _patch_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pr_state: str | None = "MERGED",
    branch_exists_rc: int = 0,
    has_gh: bool = True,
) -> list[list[str]]:
    """Patch subprocess.run + shutil.which. Return a `calls` list."""
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        # gh pr list returns a JSON array
        if "gh" in cmd[:1] and "pr" in cmd[:2]:
            if pr_state is None:
                return _FakeProc(returncode=0, stdout="[]")
            return _FakeProc(
                returncode=0,
                stdout=json.dumps([{"state": pr_state}]),
            )
        # git show-ref --verify refs/heads/<branch>
        if cmd[:3] == ["git", "show-ref", "--verify"]:
            return _FakeProc(returncode=branch_exists_rc)
        # Anything else: succeed silently.
        return _FakeProc(returncode=0)

    monkeypatch.setattr(wr.subprocess, "run", fake_run)
    monkeypatch.setattr(wr.shutil, "which", lambda name: "/usr/bin/gh" if has_gh else None)
    return calls


# ---------------------------------------------------------------------------
# find_repo_root
# ---------------------------------------------------------------------------


def test_find_repo_root_walks_up(tmp_path: Path) -> None:
    repo = _stub_layout(tmp_path)
    deep = repo / "fix-bug" / "frontend" / "src"
    deep.mkdir(parents=True)
    assert wr.find_repo_root(deep) == repo


def test_find_repo_root_missing_aborts(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        wr.find_repo_root(tmp_path)
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# assert_worktree_exists
# ---------------------------------------------------------------------------


def test_assert_worktree_exists_missing(tmp_path: Path) -> None:
    repo = _stub_layout(tmp_path)
    ctx = wr.RemoveContext(
        repo_root=repo,
        bare_dir=repo / ".bare",
        change_id="nonexistent",
        branch="slice/nonexistent",
        worktree_dir=repo / "nonexistent",
    )
    with pytest.raises(SystemExit) as exc:
        wr.assert_worktree_exists(ctx)
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# PR-state gating
# ---------------------------------------------------------------------------


def test_assert_pr_resolved_merged_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _stub_layout(tmp_path)
    _patch_run(monkeypatch, pr_state="MERGED")
    ctx = wr.RemoveContext(repo, repo / ".bare", "fix-bug", "slice/fix-bug", repo / "fix-bug")
    wr.assert_pr_resolved(ctx, force=False)  # should not raise
    assert "MERGED" in capsys.readouterr().out


def test_assert_pr_resolved_closed_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _stub_layout(tmp_path)
    _patch_run(monkeypatch, pr_state="CLOSED")
    ctx = wr.RemoveContext(repo, repo / ".bare", "fix-bug", "slice/fix-bug", repo / "fix-bug")
    wr.assert_pr_resolved(ctx, force=False)


def test_assert_pr_resolved_open_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _stub_layout(tmp_path)
    _patch_run(monkeypatch, pr_state="OPEN")
    ctx = wr.RemoveContext(repo, repo / ".bare", "fix-bug", "slice/fix-bug", repo / "fix-bug")
    with pytest.raises(SystemExit) as exc:
        wr.assert_pr_resolved(ctx, force=False)
    assert exc.value.code == 2


def test_assert_pr_resolved_open_overridden_by_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _stub_layout(tmp_path)
    _patch_run(monkeypatch, pr_state="OPEN")
    ctx = wr.RemoveContext(repo, repo / ".bare", "fix-bug", "slice/fix-bug", repo / "fix-bug")
    wr.assert_pr_resolved(ctx, force=True)  # should not raise


def test_assert_pr_resolved_no_pr_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _stub_layout(tmp_path)
    _patch_run(monkeypatch, pr_state=None)
    ctx = wr.RemoveContext(repo, repo / ".bare", "fix-bug", "slice/fix-bug", repo / "fix-bug")
    with pytest.raises(SystemExit) as exc:
        wr.assert_pr_resolved(ctx, force=False)
    assert exc.value.code == 2


def test_assert_pr_resolved_no_pr_overridden_by_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _stub_layout(tmp_path)
    _patch_run(monkeypatch, pr_state=None)
    ctx = wr.RemoveContext(repo, repo / ".bare", "fix-bug", "slice/fix-bug", repo / "fix-bug")
    wr.assert_pr_resolved(ctx, force=True)


# ---------------------------------------------------------------------------
# End-to-end main()
# ---------------------------------------------------------------------------


def test_main_dry_run_records_actions_without_executing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _stub_layout(tmp_path)
    _patch_run(monkeypatch, pr_state="MERGED")
    rc = wr.main(["fix-bug", "--repo-root", str(repo), "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[dry-run]" in out
    assert (repo / "fix-bug").exists()  # not actually removed


def test_main_keep_branch_skips_branch_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _stub_layout(tmp_path)
    calls = _patch_run(monkeypatch, pr_state="MERGED")
    rc = wr.main(["fix-bug", "--repo-root", str(repo), "--keep-branch"])
    assert rc == 0
    # No `git branch -D` call should have been emitted.
    assert not any(cmd[:3] == ["git", "branch", "-D"] for cmd in calls)


def test_main_normal_flow_runs_remove_and_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _stub_layout(tmp_path)
    calls = _patch_run(monkeypatch, pr_state="MERGED")
    rc = wr.main(["fix-bug", "--repo-root", str(repo)])
    assert rc == 0
    assert any(cmd[:3] == ["git", "worktree", "remove"] for cmd in calls)
    assert any(cmd[:3] == ["git", "branch", "-D"] for cmd in calls)


# ---------------------------------------------------------------------------
# Real git: unsaved-work guard (uncommitted files / unpushed commits)
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.test", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()


def make_bare_layout(tmp_path: Path, change_id: str = "feat-x") -> Path:
    """Real bare layout: ``proj/.bare`` cloned from a local origin, with a
    ``slice/<change_id>`` worktree whose tip is pushed. Returns ``proj``."""
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-q", "-b", "master")
    (seed / "a.txt").write_text("a\n", encoding="utf-8")
    _git(seed, "add", "a.txt")
    _git(seed, "commit", "-q", "-m", "base")
    origin = tmp_path / "origin.git"
    _git(tmp_path, "clone", "-q", "--bare", str(seed), str(origin))
    proj = tmp_path / "proj"
    proj.mkdir()
    _git(proj, "clone", "-q", "--bare", str(origin), ".bare")
    (proj / ".git").write_text("gitdir: ./.bare\n", encoding="utf-8")
    bare = proj / ".bare"
    _git(bare, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
    _git(bare, "fetch", "-q", "origin")
    wt = proj / change_id
    _git(bare, "worktree", "add", "-q", "-b", f"slice/{change_id}", str(wt), "origin/master")
    (wt / "pushed.txt").write_text("p\n", encoding="utf-8")
    _git(wt, "add", "pushed.txt")
    _git(wt, "commit", "-q", "-m", "pushed")
    _git(wt, "push", "-q", "origin", f"slice/{change_id}")
    _git(bare, "fetch", "-q", "origin")
    return proj


def _merged(monkeypatch: pytest.MonkeyPatch, head: str | None = None) -> None:
    monkeypatch.setattr(wr, "lookup_pr", lambda *_a: {"state": "MERGED", "headRefOid": head})


def test_real_git_refuses_uncommitted_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proj = make_bare_layout(tmp_path)
    _merged(monkeypatch)
    (proj / "feat-x" / "untracked-notes.txt").write_text("keep me\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        wr.main(["feat-x", "--repo-root", str(proj)])
    assert exc.value.code == 2
    assert (proj / "feat-x" / "untracked-notes.txt").exists()


def test_real_git_refuses_unpushed_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proj = make_bare_layout(tmp_path)
    wt = proj / "feat-x"
    (wt / "follow-up.txt").write_text("f\n", encoding="utf-8")
    _git(wt, "add", "follow-up.txt")
    _git(wt, "commit", "-q", "-m", "follow-up not pushed")
    tip = _git(wt, "rev-parse", "HEAD")
    _merged(monkeypatch, head=_git(wt, "rev-parse", "HEAD~1"))  # PR head = the pushed commit
    with pytest.raises(SystemExit) as exc:
        wr.main(["feat-x", "--repo-root", str(proj)])
    assert exc.value.code == 2
    assert _git(proj / ".bare", "rev-parse", "slice/feat-x") == tip


def test_real_git_force_discards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proj = make_bare_layout(tmp_path)
    _merged(monkeypatch)
    (proj / "feat-x" / "untracked-notes.txt").write_text("x\n", encoding="utf-8")
    assert wr.main(["feat-x", "--repo-root", str(proj), "--force"]) == 0
    assert not (proj / "feat-x").exists()


def test_real_git_pruned_remote_branch_trusts_pr_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Remote branch deleted + pruned after merge: the PR head proves nothing is lost."""
    proj = make_bare_layout(tmp_path)
    bare = proj / ".bare"
    head = _git(bare, "rev-parse", "slice/feat-x")
    _git(bare, "push", "-q", "origin", "--delete", "slice/feat-x")
    _git(bare, "fetch", "-q", "--prune", "origin")
    _merged(monkeypatch, head=None)
    with pytest.raises(SystemExit):
        wr.main(["feat-x", "--repo-root", str(proj)])
    _merged(monkeypatch, head=head)
    assert wr.main(["feat-x", "--repo-root", str(proj)]) == 0
    assert not (proj / "feat-x").exists()
    assert _git(bare, "branch", "--list", "slice/feat-x") == ""
