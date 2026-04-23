"""Tests for scripts.upstream_sync (T23a).

All git subprocess calls are mocked; no real fork is required. Registry
files are written to `tmp_path` and loaded via the public CLI path.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Make "scripts.upstream_sync" importable when tests run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts import upstream_sync  # noqa: E402


VALID_REGISTRY_YAML = """\
schema: ai-playbook/forks-registry/v1
forks:
  hindsight:
    path: {path}
    upstream: https://github.com/upstream/hindsight-repo
    owner: arturo6ramirez@gmail.com
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_fork(tmp_path: Path) -> Path:
    """Create a fake fork directory with a minimal PATCHES.md."""
    fork = tmp_path / "hindsight"
    fork.mkdir()
    (fork / "PATCHES.md").write_text(
        "# PATCHES.md — hindsight\n\n"
        "Upstream: https://example.invalid\n"
        "Last refresh: 2026-04-23\n\n"
        "## Active patches\n\n"
        "| ID | Title | Branch | Upstream PR | Status | Last rebase | Notes |\n"
        "|---|---|---|---|---|---|---|\n"
        "| P01 | demo patch | eligia/demo | — | staged | 2026-04-23 | — |\n"
        "| P02 | second patch | eligia/second | #42 | submitted | 2026-04-20 | — |\n"
        "\n"
        "## Merged upstream (archive)\n\n"
        "| ID | Title | Upstream commit | Merged on |\n"
        "|---|---|---|---|\n",
        encoding="utf-8",
    )
    return fork


@pytest.fixture
def registry_file(tmp_path: Path, tmp_fork: Path) -> Path:
    reg = tmp_path / "forks.yaml"
    reg.write_text(
        VALID_REGISTRY_YAML.format(path=str(tmp_fork).replace("\\", "/")),
        encoding="utf-8",
    )
    return reg


@pytest.fixture(autouse=True)
def _mock_git(monkeypatch: pytest.MonkeyPatch):
    """Default: git subprocess calls return success with plausible stdout."""
    def _fake_run(cmd, **kwargs):
        assert cmd[0] == "git", f"unexpected subprocess call: {cmd!r}"
        sub = cmd[1]
        if sub == "fetch":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if sub == "rev-list":
            # ahead then behind — return 1, 2 alternating; tests override as needed.
            return SimpleNamespace(returncode=0, stdout="1\n", stderr="")
        if sub == "for-each-ref":
            return SimpleNamespace(
                returncode=0,
                stdout="main\neligia/demo\neligia/second\neligia/orphan\n",
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(upstream_sync.subprocess, "run", _fake_run)


# ---------------------------------------------------------------------------
# Registry loading
# ---------------------------------------------------------------------------

def test_load_registry_parses_valid_yaml(registry_file: Path) -> None:
    reg = upstream_sync.load_registry(registry_file)
    assert "hindsight" in reg
    assert reg["hindsight"].upstream.startswith("https://")


def test_load_registry_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        upstream_sync.load_registry(tmp_path / "nope.yaml")


def test_load_registry_bad_schema_raises(tmp_path: Path) -> None:
    f = tmp_path / "forks.yaml"
    f.write_text("schema: wrong/schema\nforks: {}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        upstream_sync.load_registry(f)


# ---------------------------------------------------------------------------
# PATCHES.md parsing
# ---------------------------------------------------------------------------

def test_parse_patches_md_extracts_active_rows(tmp_fork: Path) -> None:
    text = (tmp_fork / "PATCHES.md").read_text(encoding="utf-8")
    rows = upstream_sync.parse_patches_md(text)
    assert len(rows) == 2
    assert rows[0].id == "P01"
    assert rows[0].branch == "eligia/demo"
    assert rows[1].status == "submitted"


def test_rewrite_patch_status_updates_only_active_row(tmp_fork: Path) -> None:
    text = (tmp_fork / "PATCHES.md").read_text(encoding="utf-8")
    new_text = upstream_sync.rewrite_patch_status(text, "P01", "merged")
    assert "| P01 | demo patch | eligia/demo | — | merged |" in new_text
    # Other row untouched.
    assert "| P02 | second patch | eligia/second | #42 | submitted |" in new_text


def test_rewrite_patch_status_raises_on_missing_id(tmp_fork: Path) -> None:
    text = (tmp_fork / "PATCHES.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        upstream_sync.rewrite_patch_status(text, "P99", "merged")


# ---------------------------------------------------------------------------
# list command
# ---------------------------------------------------------------------------

def test_list_empty_registry(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    reg = tmp_path / "forks.yaml"
    reg.write_text("schema: ai-playbook/forks-registry/v1\nforks: {}\n", encoding="utf-8")
    rc = upstream_sync.main(["--registry", str(reg), "list"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "no forks registered" in captured.out


def test_list_populated_registry(registry_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = upstream_sync.main(["--registry", str(registry_file), "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "hindsight" in out


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------

def test_status_reports_ahead_behind(
    registry_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = upstream_sync.main(["--registry", str(registry_file), "status", "hindsight"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ahead=" in out and "behind=" in out
    assert "patches_total=2" in out


def test_status_detects_orphan_branch(
    registry_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = upstream_sync.main(["--registry", str(registry_file), "status", "hindsight"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "orphan_branches" in out
    assert "eligia/orphan" in out


def test_status_detects_missing_branch(
    tmp_path: Path, tmp_fork: Path, registry_file: Path,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    # Override for-each-ref to NOT list eligia/second (so it's "missing" from git
    # but still listed in PATCHES.md).
    def _fake_run(cmd, **kwargs):
        if cmd[1] == "for-each-ref":
            return SimpleNamespace(returncode=0, stdout="main\neligia/demo\n", stderr="")
        if cmd[1] == "rev-list":
            return SimpleNamespace(returncode=0, stdout="0\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(upstream_sync.subprocess, "run", _fake_run)
    rc = upstream_sync.main(["--registry", str(registry_file), "status", "hindsight"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "missing_branches" in out
    assert "eligia/second" in out


def test_status_missing_patches_md_errors(
    tmp_path: Path, registry_file: Path, tmp_fork: Path,
) -> None:
    (tmp_fork / "PATCHES.md").unlink()
    rc = upstream_sync.main(["--registry", str(registry_file), "status", "hindsight"])
    assert rc == 1


# ---------------------------------------------------------------------------
# refresh command — NEVER merges
# ---------------------------------------------------------------------------

def test_refresh_only_fetches_no_merge(
    registry_file: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[list[str]] = []
    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "rev-list":
            return SimpleNamespace(returncode=0, stdout="0\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(upstream_sync.subprocess, "run", _fake_run)

    rc = upstream_sync.main(["--registry", str(registry_file), "refresh", "hindsight"])
    assert rc == 0
    # No git merge or rebase or pull ever called.
    for cmd in calls:
        assert cmd[1] not in {"merge", "rebase", "pull", "push"}, f"forbidden git: {cmd!r}"
    out = capsys.readouterr().out
    assert "read-only" in out.lower()


def test_refresh_fetch_failure_returns_1(
    registry_file: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_run(cmd, **kwargs):
        if cmd[1] == "fetch":
            return SimpleNamespace(returncode=1, stdout="", stderr="network down")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(upstream_sync.subprocess, "run", _fake_run)
    rc = upstream_sync.main(["--registry", str(registry_file), "refresh", "hindsight"])
    assert rc == 1


def test_refresh_force_with_reason_bypasses_unreachable(
    registry_file: Path, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _fake_run(cmd, **kwargs):
        if cmd[1] == "fetch":
            return SimpleNamespace(returncode=1, stdout="", stderr="offline")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(upstream_sync.subprocess, "run", _fake_run)
    # Redirect overrides.log to tmp_path so we don't pollute the repo.
    monkeypatch.chdir(tmp_path)
    rc = upstream_sync.main([
        "--registry", str(registry_file),
        "--force-with-reason=offline during weekend triage",
        "refresh", "hindsight",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OVERRIDE APPLIED" in out


# ---------------------------------------------------------------------------
# mark-merged command
# ---------------------------------------------------------------------------

def test_mark_merged_rewrites_row(registry_file: Path, tmp_fork: Path) -> None:
    rc = upstream_sync.main([
        "--registry", str(registry_file),
        "mark-merged", "hindsight", "P01",
    ])
    assert rc == 0
    body = (tmp_fork / "PATCHES.md").read_text(encoding="utf-8")
    assert "| P01 | demo patch | eligia/demo | — | merged |" in body


def test_mark_merged_unknown_patch_returns_1(registry_file: Path, tmp_fork: Path) -> None:
    rc = upstream_sync.main([
        "--registry", str(registry_file),
        "mark-merged", "hindsight", "P99",
    ])
    assert rc == 1


# ---------------------------------------------------------------------------
# Exit code matrix
# ---------------------------------------------------------------------------

def test_missing_registry_exits_2(tmp_path: Path) -> None:
    rc = upstream_sync.main(["--registry", str(tmp_path / "nope.yaml"), "list"])
    assert rc == 2


def test_unknown_fork_exits_1(registry_file: Path) -> None:
    rc = upstream_sync.main(["--registry", str(registry_file), "status", "nonexistent"])
    assert rc == 1


def test_invalid_schema_exits_2(tmp_path: Path) -> None:
    reg = tmp_path / "forks.yaml"
    reg.write_text("schema: wrong\nforks: {}\n", encoding="utf-8")
    rc = upstream_sync.main(["--registry", str(reg), "list"])
    assert rc == 2
