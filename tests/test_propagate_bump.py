"""Tests for scripts/propagate_bump.py — CI-side propagation script.

Mocks `subprocess.run` so the suite never touches network or git. Covers:
- consumers.yaml loading + active-status filtering
- _configure_git_credentials installs `insteadOf` rewrite
- idempotency: skip if PR already open
- skip when consumer has no submodule
- error path on clone/checkout failure
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Force-import the module fresh to pick up consumers.yaml from the repo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import propagate_bump as pb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _make_consumers_yaml(path: Path, *, status_per_repo: dict[str, str]) -> None:
    body = ["schema: ai-playbook/consumers/v1", "version: 1", "consumers:"]
    for name, status in status_per_repo.items():
        body.append(f"  {name}:")
        body.append(f"    repo: Wizarck/{name}")
        body.append(f"    default_branch: master")
        body.append(f"    status: {status}")
    path.write_text("\n".join(body), encoding="utf-8")


# ---------------------------------------------------------------------------
# _load_consumers — registry parsing + filtering
# ---------------------------------------------------------------------------


def test_load_consumers_filters_inactive(tmp_path: Path) -> None:
    cf = tmp_path / "consumers.yaml"
    _make_consumers_yaml(cf, status_per_repo={
        "alpha": "active", "beta": "paused", "gamma": "active", "delta": "archived",
    })
    out = pb._load_consumers(cf)
    names = {c["name"] for c in out}
    assert names == {"alpha", "gamma"}


def test_load_consumers_rejects_wrong_schema(tmp_path: Path) -> None:
    cf = tmp_path / "consumers.yaml"
    cf.write_text("schema: bogus/v1\nconsumers: {}", encoding="utf-8")
    with pytest.raises(SystemExit):
        pb._load_consumers(cf)


# ---------------------------------------------------------------------------
# _configure_git_credentials — installs insteadOf rewrite + disables helper
# ---------------------------------------------------------------------------


def test_configure_git_credentials_runs_two_git_configs() -> None:
    runs: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        runs.append(cmd)
        return _completed()

    with patch.object(pb, "_run", _fake_run):
        pb._configure_git_credentials("test-token")

    assert any("insteadOf" in " ".join(c) for c in runs)
    assert any("credential.helper" in " ".join(c) for c in runs)
    # Token is embedded in the rewrite — never logged stand-alone.
    rewrite = next(c for c in runs if "insteadOf" in " ".join(c))
    assert "test-token" in " ".join(rewrite)


# ---------------------------------------------------------------------------
# _propagate_one — happy path + edge cases
# ---------------------------------------------------------------------------


def test_propagate_skips_when_no_submodule(tmp_path: Path) -> None:
    consumer = {"name": "alpha", "repo": "Wizarck/alpha"}
    workdir = tmp_path

    def _fake_run(cmd, cwd=None, **kwargs):
        # `git clone` succeeds with no submodule dir.
        if cmd[:2] == ["git", "clone"]:
            (workdir / "alpha").mkdir()
            return _completed()
        return _completed()

    with patch.object(pb, "_run", _fake_run):
        result = pb._propagate_one(consumer, "v0.3.0", "tok", workdir, open_pr=False)

    assert result.status == "skipped"
    assert ".ai-playbook" in result.detail


def test_propagate_skips_when_pr_already_open(tmp_path: Path) -> None:
    consumer = {"name": "beta", "repo": "Wizarck/beta", "default_branch": "master"}
    workdir = tmp_path

    def _fake_run(cmd, cwd=None, **kwargs):
        if cmd[:2] == ["git", "clone"]:
            sub = workdir / "beta" / ".ai-playbook"
            sub.mkdir(parents=True)
            return _completed()
        # gh pr list returns an existing PR.
        if cmd[:3] == ["gh", "pr", "list"]:
            return _completed(stdout=json.dumps([{"url": "https://gh/pr/123"}]))
        return _completed()

    with patch.object(pb, "_run", _fake_run):
        result = pb._propagate_one(consumer, "v0.3.0", "tok", workdir, open_pr=True)

    assert result.status == "pr-exists"
    assert "https://gh/pr/123" in result.detail
    assert result.pr_url == "https://gh/pr/123"


def test_propagate_happy_path_opens_pr(tmp_path: Path) -> None:
    consumer = {"name": "gamma", "repo": "Wizarck/gamma", "default_branch": "main"}
    workdir = tmp_path
    calls: list[list[str]] = []

    def _fake_run(cmd, cwd=None, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["git", "clone"]:
            sub = workdir / "gamma" / ".ai-playbook"
            sub.mkdir(parents=True)
            return _completed()
        if cmd[:3] == ["gh", "pr", "list"]:
            return _completed(stdout="[]")  # no existing PR
        if cmd[:3] == ["git", "rev-parse", "refs/tags/v0.3.0^{commit}"]:
            return _completed(stdout="newsha1234abcd\n")
        if cmd[:3] == ["git", "rev-parse", "HEAD:.ai-playbook"]:
            return _completed(stdout="oldsha5678efgh\n")
        if cmd[:3] == ["gh", "pr", "create"]:
            return _completed(stdout="https://gh/pr/new\n")
        return _completed()

    with patch.object(pb, "_run", _fake_run):
        result = pb._propagate_one(consumer, "v0.3.0", "tok", workdir, open_pr=True)

    assert result.status == "pr-opened"
    assert "newsha12" in result.detail
    assert result.pr_url == "https://gh/pr/new"
    # Verify the right git commands ran in order.
    cmd_strs = [" ".join(c) for c in calls]
    assert any("git clone" in s for s in cmd_strs)
    assert any("git checkout -b chore/bump-playbook-v0.3.0" in s for s in cmd_strs)
    assert any("git push -u origin chore/bump-playbook-v0.3.0" in s for s in cmd_strs)
    assert any("gh pr create" in s for s in cmd_strs)


def test_propagate_skips_when_already_at_target(tmp_path: Path) -> None:
    """If consumer's submodule already points at the target SHA, no PR opens."""
    consumer = {"name": "delta", "repo": "Wizarck/delta", "default_branch": "master"}
    workdir = tmp_path

    def _fake_run(cmd, cwd=None, **kwargs):
        if cmd[:2] == ["git", "clone"]:
            (workdir / "delta" / ".ai-playbook").mkdir(parents=True)
            return _completed()
        if cmd[:3] == ["gh", "pr", "list"]:
            return _completed(stdout="[]")
        if cmd[:2] == ["git", "rev-parse"]:
            # Same SHA on both ends.
            return _completed(stdout="samesha000000\n")
        return _completed()

    with patch.object(pb, "_run", _fake_run):
        result = pb._propagate_one(consumer, "v0.3.0", "tok", workdir, open_pr=True)

    assert result.status == "up-to-date"


def test_propagate_error_on_clone_failure(tmp_path: Path) -> None:
    consumer = {"name": "epsilon", "repo": "Wizarck/epsilon"}

    def _fake_run(cmd, cwd=None, **kwargs):
        if cmd[:2] == ["git", "clone"]:
            raise subprocess.CalledProcessError(128, cmd, stderr="fatal: not found")
        return _completed()

    with patch.object(pb, "_run", _fake_run):
        result = pb._propagate_one(consumer, "v0.3.0", "tok", tmp_path, open_pr=False)

    assert result.status == "error"
    assert "clone failed" in result.detail
