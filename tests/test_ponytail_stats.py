"""Tests for the ponytail discipline stats instrument (scripts/ponytail/stats.py).

Covers the rung-1 measurement: count `ponytail:` comment markers, mirroring the
/ponytail-debt harvest. Verifies the marker regex, SKIP_DIRS pruning, and
binary-file tolerance.
"""
from __future__ import annotations

import datetime as _dt
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.ponytail import stats

_GIT = shutil.which("git")
requires_git = pytest.mark.skipif(_GIT is None, reason="git not available")


def _git(args: list[str], cwd: Path) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e",
    }
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q"], path)


def test_counts_only_comment_markers(tmp_path: Path):
    (tmp_path / "a.py").write_text(
        "x = 1  # ponytail: global lock, shard later\n"
        "y = 2  #ponytail: no space variant counts too\n"
        "z = 3  // ponytail: c-style prefix counts\n"
        "print('mentions ponytail: in a string, no prefix')\n"
        "# a normal comment\n",
        encoding="utf-8",
    )
    s = stats.count_markers(tmp_path)
    assert s.markers == 3
    assert s.files_scanned == 1


def test_skips_skip_dirs(tmp_path: Path):
    (tmp_path / "src.py").write_text("# ponytail: real one\n", encoding="utf-8")
    vendored = tmp_path / "node_modules" / "pkg"
    vendored.mkdir(parents=True)
    (vendored / "dep.js").write_text("// ponytail: should be ignored\n", encoding="utf-8")
    s = stats.count_markers(tmp_path)
    assert s.markers == 1


def test_skips_binary_files(tmp_path: Path):
    (tmp_path / "ok.py").write_text("# ponytail: counted\n", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00\x01 ponytail: not decodable")
    s = stats.count_markers(tmp_path)
    assert s.markers == 1


def test_collect_shape(tmp_path: Path):
    (tmp_path / "f.py").write_text("# ponytail: x\n", encoding="utf-8")
    data = stats.collect(tmp_path)
    assert data == {"markers": 1, "files_scanned": 1}


def test_skips_vendored_playbook_dir(tmp_path: Path):
    (tmp_path / "own.py").write_text("# ponytail: mine\n", encoding="utf-8")
    vendored = tmp_path / ".ai-playbook" / "scripts"
    vendored.mkdir(parents=True)
    (vendored / "x.py").write_text("# ponytail: playbook's own, not the consumer's\n", encoding="utf-8")
    assert stats.count_markers(tmp_path).markers == 1


def test_collect_omits_window_without_since(tmp_path: Path):
    (tmp_path / "f.py").write_text("# ponytail: x\n", encoding="utf-8")
    assert "markers_window" not in stats.collect(tmp_path)


def test_markers_added_since_none_when_not_git(tmp_path: Path):
    assert stats.markers_added_since(tmp_path, "2000-01-01T00:00:00Z") is None


@requires_git
def test_markers_added_since_counts_window(tmp_path: Path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "a.py").write_text("# ponytail: one\n# ponytail: two\nx = 1\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-q", "-m", "add markers"], repo)
    # Window covering the commit -> both additions counted.
    assert stats.markers_added_since(repo, "2000-01-01T00:00:00Z") == 2
    # A window starting in the (near, realistic) future -> nothing added.
    future = (_dt.datetime.now(_dt.UTC) + _dt.timedelta(days=2)).isoformat().replace("+00:00", "Z")
    assert stats.markers_added_since(repo, future) == 0


@requires_git
def test_collect_includes_window_in_git_repo(tmp_path: Path):
    repo = tmp_path / "r2"
    _init_repo(repo)
    (repo / "m.py").write_text("// ponytail: x\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-q", "-m", "m"], repo)
    data = stats.collect(repo, since_iso="2000-01-01T00:00:00Z")
    assert data["markers"] == 1
    assert data["markers_window"] == 1
