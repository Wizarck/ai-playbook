"""Tests for scripts/rules/alembic-single-head.rule.py."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_ash_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "alembic-single-head.rule.py",
)
assert SPEC and SPEC.loader
_ash = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_ash)


def _mk(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / name
    p.write_text(body, encoding="utf-8")
    return p


def _linear(directory: Path) -> None:
    _mk(directory, "0001_init.py", 'revision = "0001_init"\ndown_revision = None\n')
    _mk(
        directory,
        "0002_add_users.py",
        'revision = "0002_add_users"\ndown_revision = "0001_init"\n',
    )


def test_single_head_passes(tmp_path: Path) -> None:
    _linear(tmp_path)
    assert _ash.main(["validate", str(tmp_path)]) == 0


def test_two_heads_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _linear(tmp_path)
    # two siblings both off 0002 → two heads
    _mk(tmp_path, "0003_a.py", 'revision = "0003_a"\ndown_revision = "0002_add_users"\n')
    _mk(tmp_path, "0003_b.py", 'revision = "0003_b"\ndown_revision = "0002_add_users"\n')
    rc = _ash.main(["validate", str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err.lower()
    assert "2 alembic heads" in err
    assert "0003_a" in err and "0003_b" in err


def test_merge_node_collapses_to_single_head(tmp_path: Path) -> None:
    _linear(tmp_path)
    _mk(tmp_path, "0003_a.py", 'revision = "0003_a"\ndown_revision = "0002_add_users"\n')
    _mk(tmp_path, "0003_b.py", 'revision = "0003_b"\ndown_revision = "0002_add_users"\n')
    # merge node names both forks as parents (tuple down_revision)
    _mk(
        tmp_path,
        "0004_merge.py",
        'revision = "0004_merge"\ndown_revision = ("0003_a", "0003_b")\n',
    )
    assert _ash.main(["validate", str(tmp_path)]) == 0


def test_empty_orphan_file_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _linear(tmp_path)
    _mk(tmp_path, "0003_orphan.py", "")  # 0-byte orphan
    rc = _ash.main(["validate", str(tmp_path)])
    assert rc == 1
    assert "empty/orphaned" in capsys.readouterr().err.lower()


def test_non_migration_helper_skipped(tmp_path: Path) -> None:
    _linear(tmp_path)
    _mk(tmp_path, "helpers.py", "def foo():\n    return 1\n")  # not migration-shaped
    assert _ash.main(["validate", str(tmp_path)]) == 0


def test_file_arg_resolves_to_parent_dir(tmp_path: Path) -> None:
    _linear(tmp_path)
    _mk(tmp_path, "0003_a.py", 'revision = "0003_a"\ndown_revision = "0002_add_users"\n')
    one = _mk(tmp_path, "0003_b.py", 'revision = "0003_b"\ndown_revision = "0002_add_users"\n')
    # passing a single file still checks the whole directory → detects 2 heads
    assert _ash.main(["validate", str(one)]) == 1


def test_annotated_assignment_handled(tmp_path: Path) -> None:
    _mk(tmp_path, "0001_init.py", 'revision: str = "0001_init"\ndown_revision = None\n')
    _mk(
        tmp_path,
        "0002_next.py",
        'revision: str = "0002_next"\ndown_revision: str = "0001_init"\n',
    )
    assert _ash.main(["validate", str(tmp_path)]) == 0


def test_missing_path_returns_two(tmp_path: Path) -> None:
    assert _ash.main(["validate", str(tmp_path / "nope.py")]) == 2


def test_empty_dir_passes(tmp_path: Path) -> None:
    assert _ash.main(["validate", str(tmp_path)]) == 0


# ─── --base (union with a git ref) ──────────────────────────────────────────


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


def _git_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Return (repo_root, versions_dir) with a linear base chain on `main`."""
    repo = tmp_path / "repo"
    versions = repo / "alembic" / "versions"
    versions.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t.test")
    _git(repo, "config", "user.name", "t")
    _mk(versions, "0001_init.py", 'revision = "0001_init"\ndown_revision = None\n')
    _mk(versions, "0002_users.py", 'revision = "0002_users"\ndown_revision = "0001_init"\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "--no-verify", "-m", "base chain")
    return repo, versions


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_base_union_detects_fork_merged_into_base(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, versions = _git_repo(tmp_path)
    # feature branch adds 0003_a off 0002
    _git(repo, "checkout", "-b", "feature")
    _mk(versions, "0003_a.py", 'revision = "0003_a"\ndown_revision = "0002_users"\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "--no-verify", "-m", "feature head a")
    # meanwhile main gains a sibling head 0003_b, then feature does NOT rebase
    _git(repo, "checkout", "main")
    _mk(versions, "0003_b.py", 'revision = "0003_b"\ndown_revision = "0002_users"\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "--no-verify", "-m", "main head b")
    _git(repo, "checkout", "feature")
    # working tree (feature) has only 0003_a → looks single-head in isolation …
    assert _ash.main(["validate", str(versions)]) == 0
    # … but unioned with main it is a 2-head fork.
    rc = _ash.main(["validate", "--base", "main", str(versions)])
    assert rc == 1
    err = capsys.readouterr().err.lower()
    assert "2 alembic heads" in err
    assert "0003_a" in err and "0003_b" in err


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_base_union_merge_node_passes(tmp_path: Path) -> None:
    repo, versions = _git_repo(tmp_path)
    _git(repo, "checkout", "-b", "feature")
    _mk(versions, "0003_a.py", 'revision = "0003_a"\ndown_revision = "0002_users"\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "--no-verify", "-m", "feature head a")
    _git(repo, "checkout", "main")
    _mk(versions, "0003_b.py", 'revision = "0003_b"\ndown_revision = "0002_users"\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "--no-verify", "-m", "main head b")
    _git(repo, "checkout", "feature")
    # feature fetches/sees the other head and adds a merge node naming both
    _mk(
        versions,
        "0004_merge.py",
        'revision = "0004_merge"\ndown_revision = ("0003_a", "0003_b")\n',
    )
    assert _ash.main(["validate", "--base", "main", str(versions)]) == 0


def test_base_unknown_ref_degrades_to_worktree(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Not a git repo → --base degrades gracefully to working-tree-only (exit 0).
    _linear(tmp_path)
    assert _ash.main(["validate", "--base", "origin/main", str(tmp_path)]) == 0
    assert "--base skipped" in capsys.readouterr().err.lower()
