"""Tests for scripts/rules/apply-skill-enforcement.rule.py."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_ase_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "apply-skill-enforcement.rule.py",
)
assert SPEC and SPEC.loader
_ase = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_ase)


def _fake_run(rc: int):
    def _r(cmd, **kw):
        return subprocess.CompletedProcess(cmd, rc, "", "")
    return _r


def test_validate_passes_when_marker_returns_0() -> None:
    with patch.object(_ase.subprocess, "run", side_effect=_fake_run(0)):
        assert _ase.validate("test-change") == 0


def test_validate_fails_when_marker_returns_nonzero(capsys) -> None:
    with patch.object(_ase.subprocess, "run", side_effect=_fake_run(2)):
        rc = _ase.validate("test-change")
    assert rc == 1
    assert "apply session marker" in capsys.readouterr().err


def test_validate_empty_change_id_is_noop() -> None:
    assert _ase.main(["validate", ""]) == 0


def test_validate_skip_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_APPLY_SKILL_SKIP", "1")
    assert _ase.validate("anything") == 0


def test_validate_missing_marker_script_returns_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_ase, "MARKER_SCRIPT", Path("/no/such/script.py"))
    assert _ase.validate("any") == 2


# ---------------------------------------------------------------------------
# validate-pr-diff (L3 PR gate) — fixture-based tests on a real git repo.
# ---------------------------------------------------------------------------


def _init_repo(repo: Path) -> None:
    """Initialize a tiny git repo with a single committed baseline."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True)
    (repo / "README.md").write_text("# initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def _seed_change_dir(repo: Path, change_id: str, write_paths: list[str], *, with_marker: bool = False) -> None:
    cdir = repo / "openspec" / "changes" / change_id
    cdir.mkdir(parents=True, exist_ok=True)
    bullets = "\n".join(f"* `{p}`" for p in write_paths)
    (cdir / "tasks.md").write_text(
        f"# tasks — {change_id}\n\n## Owns (write_paths)\n\n{bullets}\n\n## Reads\n\n* nothing\n",
        encoding="utf-8",
    )
    if with_marker:
        (cdir / ".apply_log.jsonl").write_text(
            f'{{"event":"start","change_id":"{change_id}","session_id":"x","ts":"2026-05-25T10:00:00Z","skill_version":"1.1"}}\n',
            encoding="utf-8",
        )


def _commit_files(repo: Path, files: dict[str, str], message: str) -> str:
    """Create/overwrite files and commit; return the commit sha."""
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True)
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    return out


def test_validate_pr_diff_clean_when_marker_present(tmp_path: Path) -> None:
    """Diff touches a write_path but `.apply_log.jsonl` has a start record → exit 0."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _seed_change_dir(repo, "demo-slice", ["backend/foo.py"], with_marker=True)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    # Commit the tasks.md + apply_log.jsonl + a write_path edit.
    head = _commit_files(
        repo,
        {
            "backend/foo.py": "x = 1\n",
        },
        "edit write_path with marker",
    )
    rc = _ase.validate_pr_diff(base, head, repo_root=repo)
    assert rc == 0


def test_validate_pr_diff_fails_when_marker_missing(tmp_path: Path) -> None:
    """Diff touches a write_path but no start record → exit 1."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _seed_change_dir(repo, "demo-slice", ["backend/foo.py"], with_marker=False)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    head = _commit_files(
        repo,
        {"backend/foo.py": "x = 2\n"},
        "edit write_path without marker",
    )
    rc = _ase.validate_pr_diff(base, head, repo_root=repo)
    assert rc == 1


def test_validate_pr_diff_clean_when_no_write_path_touched(tmp_path: Path) -> None:
    """Diff doesn't touch any declared write_path → exit 0."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _seed_change_dir(repo, "demo-slice", ["backend/foo.py"], with_marker=False)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    head = _commit_files(
        repo,
        {"docs/unrelated.md": "# unrelated\n"},
        "edit unrelated path",
    )
    rc = _ase.validate_pr_diff(base, head, repo_root=repo)
    assert rc == 0


def test_validate_pr_diff_skips_change_own_folder(tmp_path: Path) -> None:
    """Edits to openspec/changes/<id>/* are never gated → exit 0."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _seed_change_dir(repo, "demo-slice", ["backend/foo.py"], with_marker=False)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    head = _commit_files(
        repo,
        {"openspec/changes/demo-slice/notes.md": "# notes\n"},
        "edit change-own folder",
    )
    rc = _ase.validate_pr_diff(base, head, repo_root=repo)
    assert rc == 0


def test_validate_pr_diff_clean_when_no_openspec_dir(tmp_path: Path) -> None:
    """Repo without openspec/changes/ → exit 0."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    head = _commit_files(repo, {"backend/foo.py": "x\n"}, "no openspec")
    rc = _ase.validate_pr_diff(base, head, repo_root=repo)
    assert rc == 0


def test_validate_pr_diff_glob_matching(tmp_path: Path) -> None:
    """write_paths with glob (`backend/services/*.py`) match files inside that dir."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _seed_change_dir(repo, "demo-slice", ["backend/services/*.py"], with_marker=False)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    head = _commit_files(
        repo,
        {"backend/services/auth.py": "def login(): pass\n"},
        "edit glob-matched write_path",
    )
    rc = _ase.validate_pr_diff(base, head, repo_root=repo)
    assert rc == 1
    # And a non-matching path under a different dir → exit 0.
    head2 = _commit_files(
        repo,
        {"backend/handlers/auth.py": "def hdl(): pass\n"},
        "edit unrelated dir",
    )
    rc2 = _ase.validate_pr_diff(head, head2, repo_root=repo)
    assert rc2 == 0


def test_validate_pr_diff_via_main_cli(tmp_path: Path) -> None:
    """Smoke-test the CLI parsing path: main(['validate-pr-diff', '--base', ..., '--head', ...])."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _seed_change_dir(repo, "demo-slice", ["backend/foo.py"], with_marker=False)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    head = _commit_files(repo, {"backend/foo.py": "x\n"}, "violation")
    rc = _ase.main([
        "validate-pr-diff",
        "--base", base,
        "--head", head,
        "--repo-root", str(repo),
    ])
    assert rc == 1
