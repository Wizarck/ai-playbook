"""Tests for scripts/propagate_skills_bump.py — RFC-0001 Phase 2b.

Mocks `subprocess.run` so the suite never touches network or git. Covers:
- consumers.yaml loading + skills_pins filtering
- AGENTS.md frontmatter line-level rewrite
- idempotency: skip if pin already at target
- skip when AGENTS.md missing or has no entry for the source repo
- happy path: branch + commit + PR
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import propagate_skills_bump as psb

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _make_consumers_yaml(path: Path, entries: dict) -> None:
    body = ["schema: ai-playbook/consumers/v1", "version: 1", "consumers:"]
    for name, meta in entries.items():
        body.append(f"  {name}:")
        body.append(f"    repo: Wizarck/{name}")
        body.append("    default_branch: main")
        body.append(f"    status: {meta.get('status', 'active')}")
        if "skills_pins" in meta:
            body.append("    skills_pins:")
            for k, v in meta["skills_pins"].items():
                body.append(f"      {k}: {v}")
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


def _write_agents_md(path: Path, sources: list[str]) -> None:
    body = ["---", "schema: agents-md/v1", "skills_sources:"]
    for s in sources:
        body.append(f"  - {s}")
    body.append("---")
    body.append("body")
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# _load_consumers — filtering
# ---------------------------------------------------------------------------


def test_load_consumers_filters_to_skills_pins(tmp_path: Path) -> None:
    cf = tmp_path / "consumers.yaml"
    _make_consumers_yaml(cf, {
        "alpha": {"skills_pins": {"ai-playbook": "v0.3.0"}},
        "beta": {},  # no skills_pins
        "gamma": {"skills_pins": {"consumer-d-skills": "v0.1.0"}},  # different source
        "delta": {"skills_pins": {"ai-playbook": "v0.3.0"}},
    })
    out = psb._load_consumers(cf, "ai-playbook")
    names = {c["name"] for c in out}
    assert names == {"alpha", "delta"}


def test_load_consumers_filters_inactive(tmp_path: Path) -> None:
    cf = tmp_path / "consumers.yaml"
    _make_consumers_yaml(cf, {
        "alpha": {"status": "paused", "skills_pins": {"ai-playbook": "v0.3.0"}},
        "beta": {"status": "active", "skills_pins": {"ai-playbook": "v0.3.0"}},
    })
    out = psb._load_consumers(cf, "ai-playbook")
    names = {c["name"] for c in out}
    assert names == {"beta"}


def test_load_consumers_rejects_wrong_schema(tmp_path: Path) -> None:
    cf = tmp_path / "consumers.yaml"
    cf.write_text("schema: bogus/v1\nconsumers: {}", encoding="utf-8")
    with pytest.raises(SystemExit):
        psb._load_consumers(cf, "ai-playbook")


# ---------------------------------------------------------------------------
# _edit_frontmatter_skills_source — surgical line-level rewrite
# ---------------------------------------------------------------------------


def test_edit_frontmatter_rewrites_matching_entry(tmp_path: Path) -> None:
    am = tmp_path / "AGENTS.md"
    _write_agents_md(am, [
        "Wizarck/ai-playbook@v0.3.0",
        "Wizarck/consumer-d-skills@v0.1.0",
    ])
    changed, detail = psb._edit_frontmatter_skills_source(am, "ai-playbook", "v0.4.0")
    assert changed is True
    assert detail == "rewrote"
    text = am.read_text(encoding="utf-8")
    assert "Wizarck/ai-playbook@v0.4.0" in text
    # Other source untouched.
    assert "Wizarck/consumer-d-skills@v0.1.0" in text


def test_edit_frontmatter_idempotent_when_at_target(tmp_path: Path) -> None:
    am = tmp_path / "AGENTS.md"
    _write_agents_md(am, ["Wizarck/ai-playbook@v0.4.0"])
    before = am.read_text(encoding="utf-8")
    changed, detail = psb._edit_frontmatter_skills_source(am, "ai-playbook", "v0.4.0")
    assert changed is False
    assert detail == "up-to-date"
    assert am.read_text(encoding="utf-8") == before


def test_edit_frontmatter_returns_not_found_when_source_absent(tmp_path: Path) -> None:
    am = tmp_path / "AGENTS.md"
    _write_agents_md(am, ["Wizarck/consumer-d-skills@v0.1.0"])
    changed, detail = psb._edit_frontmatter_skills_source(am, "ai-playbook", "v0.4.0")
    assert changed is False
    assert detail == "not-found"


def test_edit_frontmatter_handles_github_prefix(tmp_path: Path) -> None:
    am = tmp_path / "AGENTS.md"
    _write_agents_md(am, ["github.com/Wizarck/ai-playbook@v0.3.0"])
    changed, detail = psb._edit_frontmatter_skills_source(am, "ai-playbook", "v0.4.0")
    assert changed is True
    assert detail == "rewrote"
    text = am.read_text(encoding="utf-8")
    assert "github.com/Wizarck/ai-playbook@v0.4.0" in text


def test_edit_frontmatter_no_frontmatter_returns_no_frontmatter(tmp_path: Path) -> None:
    am = tmp_path / "AGENTS.md"
    am.write_text("just body\n", encoding="utf-8")
    changed, detail = psb._edit_frontmatter_skills_source(am, "ai-playbook", "v0.4.0")
    assert changed is False
    assert detail == "no-frontmatter"


# ---------------------------------------------------------------------------
# _propagate_one — happy + edge paths
# ---------------------------------------------------------------------------


def test_propagate_skips_when_no_agents_md(tmp_path: Path) -> None:
    consumer = {"name": "alpha", "repo": "Wizarck/alpha", "default_branch": "main"}
    workdir = tmp_path

    def fake_run(cmd, cwd=None, **kwargs):
        if cmd[:2] == ["git", "clone"]:
            (workdir / "alpha").mkdir()
            return _completed()
        return _completed()

    with patch.object(psb, "_run", fake_run):
        result = psb._propagate_one(
            consumer, source_repo="ai-playbook", tag="v0.4.0",
            workdir=workdir, open_pr=False,
        )
    assert result.status == "skipped"
    assert "AGENTS.md" in result.detail


def test_propagate_skips_when_pr_already_open(tmp_path: Path) -> None:
    consumer = {"name": "beta", "repo": "Wizarck/beta", "default_branch": "main"}
    workdir = tmp_path

    def fake_run(cmd, cwd=None, **kwargs):
        if cmd[:2] == ["git", "clone"]:
            (workdir / "beta").mkdir()
            _write_agents_md(workdir / "beta" / "AGENTS.md", ["Wizarck/ai-playbook@v0.3.0"])
            return _completed()
        if cmd[:3] == ["gh", "pr", "list"]:
            return _completed(stdout=json.dumps([{"url": "https://gh/pr/9"}]))
        return _completed()

    with patch.object(psb, "_run", fake_run):
        result = psb._propagate_one(
            consumer, source_repo="ai-playbook", tag="v0.4.0",
            workdir=workdir, open_pr=True,
        )
    assert result.status == "pr-exists"
    assert result.pr_url == "https://gh/pr/9"


def test_propagate_skipped_when_already_at_target(tmp_path: Path) -> None:
    consumer = {"name": "gamma", "repo": "Wizarck/gamma", "default_branch": "main"}
    workdir = tmp_path

    def fake_run(cmd, cwd=None, **kwargs):
        if cmd[:2] == ["git", "clone"]:
            (workdir / "gamma").mkdir()
            _write_agents_md(workdir / "gamma" / "AGENTS.md", ["Wizarck/ai-playbook@v0.4.0"])
            return _completed()
        if cmd[:3] == ["gh", "pr", "list"]:
            return _completed(stdout="[]")
        return _completed()

    with patch.object(psb, "_run", fake_run):
        result = psb._propagate_one(
            consumer, source_repo="ai-playbook", tag="v0.4.0",
            workdir=workdir, open_pr=True,
        )
    assert result.status == "up-to-date"


def test_propagate_happy_path_opens_pr(tmp_path: Path) -> None:
    consumer = {"name": "delta", "repo": "Wizarck/delta", "default_branch": "main"}
    workdir = tmp_path
    calls: list[list[str]] = []

    def fake_run(cmd, cwd=None, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["git", "clone"]:
            (workdir / "delta").mkdir()
            _write_agents_md(workdir / "delta" / "AGENTS.md", ["Wizarck/ai-playbook@v0.3.0"])
            return _completed()
        if cmd[:3] == ["gh", "pr", "list"]:
            return _completed(stdout="[]")
        if cmd[:3] == ["gh", "pr", "create"]:
            return _completed(stdout="https://gh/pr/new\n")
        return _completed()

    with patch.object(psb, "_run", fake_run):
        result = psb._propagate_one(
            consumer, source_repo="ai-playbook", tag="v0.4.0",
            workdir=workdir, open_pr=True,
        )
    assert result.status == "pr-opened"
    assert result.pr_url == "https://gh/pr/new"

    cmd_strs = [" ".join(c) for c in calls]
    assert any("git checkout -b chore/bump-skills-ai-playbook-v0.4.0" in s for s in cmd_strs)
    assert any("git push -u origin chore/bump-skills-ai-playbook-v0.4.0" in s for s in cmd_strs)
    assert any("gh pr create" in s for s in cmd_strs)


def test_propagate_skipped_when_source_not_in_agents_md(tmp_path: Path) -> None:
    consumer = {"name": "eps", "repo": "Wizarck/eps", "default_branch": "main"}
    workdir = tmp_path

    def fake_run(cmd, cwd=None, **kwargs):
        if cmd[:2] == ["git", "clone"]:
            (workdir / "eps").mkdir()
            _write_agents_md(workdir / "eps" / "AGENTS.md", ["Wizarck/consumer-d-skills@v0.1.0"])
            return _completed()
        if cmd[:3] == ["gh", "pr", "list"]:
            return _completed(stdout="[]")
        return _completed()

    with patch.object(psb, "_run", fake_run):
        result = psb._propagate_one(
            consumer, source_repo="ai-playbook", tag="v0.4.0",
            workdir=workdir, open_pr=True,
        )
    assert result.status == "skipped"
    assert "no skills_sources entry" in result.detail


def test_propagate_error_on_clone_failure(tmp_path: Path) -> None:
    consumer = {"name": "zeta", "repo": "Wizarck/zeta"}

    def fake_run(cmd, cwd=None, **kwargs):
        if cmd[:2] == ["git", "clone"]:
            raise subprocess.CalledProcessError(128, cmd, stderr="fatal: not found")
        return _completed()

    with patch.object(psb, "_run", fake_run):
        result = psb._propagate_one(
            consumer, source_repo="ai-playbook", tag="v0.4.0",
            workdir=tmp_path, open_pr=False,
        )
    assert result.status == "error"
    assert "clone failed" in result.detail


# ---------------------------------------------------------------------------
# Branch + commit naming
# ---------------------------------------------------------------------------


def test_bump_branch_format() -> None:
    assert psb.bump_branch("ai-playbook", "v0.4.0") == "chore/bump-skills-ai-playbook-v0.4.0"
    assert psb.bump_branch("consumer-d-skills", "v0.2.0") == "chore/bump-skills-consumer-d-skills-v0.2.0"


def test_commit_message_format() -> None:
    expected = "chore(skills): bump ai-playbook to v0.4.0"
    assert psb.commit_message("ai-playbook", "v0.4.0") == expected
