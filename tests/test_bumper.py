"""Tests for scripts/_bumper.py — shared helpers used by both propagation
scripts (CI-side) and bump_consumers.py (manual).

Covers the v0.9.1 followups:

* Followup #1: ``bump_agents_md_pin`` rewrites both ``inherits_from:`` and
  ``skills_sources:`` items with the same regex; preserves comments,
  ordering, and quoting style; refreshes ``updated:`` to today; idempotent
  when already at-target.
* Followup #2: ``supersede_open_bump_prs`` is semver-aware — it only closes
  open PRs whose parsed branch version is ``<=`` the new bump's version.
  Out-of-order tag pushes don't corrupt the cascade.
* ``_parse_branch_version`` orders stable releases above their rcs and
  older series below newer.

Mocks ``subprocess.run`` so the suite never touches network or git.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

# Force-import the module fresh.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import _bumper  # noqa: I001, E402


# ---------------------------------------------------------------------------
# bump_agents_md_pin (followup #1)
# ---------------------------------------------------------------------------


def _agents_md(content: str, tmp_path: Path) -> Path:
    p = tmp_path / "AGENTS.md"
    p.write_text(content, encoding="utf-8", newline="\n")
    return p


def test_bump_agents_md_pin_rewrites_inherits_from(tmp_path: Path) -> None:
    """`inherits_from:` items use the `github.com/` prefix and must be rewritten."""
    src = """\
---
schema: agents-md/v1
version: 0.1.0
inherits_from:
  - github.com/Wizarck/ai-playbook@v0.9.0-rc2
updated: 2026-04-30
project: livekit
---

# AGENTS.md
"""
    p = _agents_md(src, tmp_path)
    changed, detail = _bumper.bump_agents_md_pin(p, "ai-playbook", "v0.9.1")
    assert changed is True
    assert detail == "rewrote"
    out = p.read_text(encoding="utf-8")
    assert "github.com/Wizarck/ai-playbook@v0.9.1" in out
    assert "v0.9.0-rc2" not in out
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    assert f"updated: {today}" in out


def test_bump_agents_md_pin_rewrites_skills_sources(tmp_path: Path) -> None:
    """`skills_sources:` items lack the prefix; same regex covers both."""
    src = """\
---
schema: agents-md/v1
version: 0.1.0
skills_sources:
  - Wizarck/ai-playbook@v0.9.0
  - Wizarck/consumer-d-skills@v0.3.0
updated: 2026-04-30
---
"""
    p = _agents_md(src, tmp_path)
    changed, detail = _bumper.bump_agents_md_pin(p, "ai-playbook", "v0.9.1")
    assert changed is True
    out = p.read_text(encoding="utf-8")
    assert "- Wizarck/ai-playbook@v0.9.1" in out
    assert "- Wizarck/consumer-d-skills@v0.3.0" in out, "non-target source must not be touched"


def test_bump_agents_md_pin_rewrites_both_blocks_in_one_pass(tmp_path: Path) -> None:
    """A consumer with BOTH inherits_from and skills_sources gets both bumped."""
    src = """\
---
schema: agents-md/v1
inherits_from:
  - github.com/Wizarck/ai-playbook@v0.8.6
skills_sources:
  - Wizarck/ai-playbook@v0.8.6
  - Wizarck/consumer-d-skills@v0.3.0
updated: 2026-04-30
---
"""
    p = _agents_md(src, tmp_path)
    changed, detail = _bumper.bump_agents_md_pin(p, "ai-playbook", "v0.9.1")
    assert changed is True
    out = p.read_text(encoding="utf-8")
    assert out.count("ai-playbook@v0.9.1") == 2
    assert "v0.8.6" not in out


def test_bump_agents_md_pin_already_at_target_returns_up_to_date(tmp_path: Path) -> None:
    src = """\
---
inherits_from:
  - github.com/Wizarck/ai-playbook@v0.9.1
---
"""
    p = _agents_md(src, tmp_path)
    changed, detail = _bumper.bump_agents_md_pin(p, "ai-playbook", "v0.9.1")
    assert changed is False
    assert detail == "up-to-date"


def test_bump_agents_md_pin_not_found_returns_not_found(tmp_path: Path) -> None:
    src = """\
---
schema: agents-md/v1
inherits_from:
  - github.com/Wizarck/consumer-d-skills@v0.3.0
---
"""
    p = _agents_md(src, tmp_path)
    changed, detail = _bumper.bump_agents_md_pin(p, "ai-playbook", "v0.9.1")
    assert changed is False
    assert detail == "not-found"


def test_bump_agents_md_pin_missing_file(tmp_path: Path) -> None:
    p = tmp_path / "missing.md"
    changed, detail = _bumper.bump_agents_md_pin(p, "ai-playbook", "v0.9.1")
    assert changed is False
    assert detail == "agents-md-missing"


def test_bump_agents_md_pin_no_frontmatter_returns_no_frontmatter(tmp_path: Path) -> None:
    src = "# AGENTS.md\n\nNo frontmatter at all.\n"
    p = _agents_md(src, tmp_path)
    changed, detail = _bumper.bump_agents_md_pin(p, "ai-playbook", "v0.9.1")
    assert changed is False
    assert detail == "no-frontmatter"


def test_bump_agents_md_pin_preserves_comments_and_indentation(tmp_path: Path) -> None:
    src = """\
---
schema: agents-md/v1
inherits_from:
  -   github.com/Wizarck/ai-playbook@v0.8.6   # legacy pin
updated: 2026-04-30
---
"""
    p = _agents_md(src, tmp_path)
    _bumper.bump_agents_md_pin(p, "ai-playbook", "v0.9.1")
    out = p.read_text(encoding="utf-8")
    assert "  -   github.com/Wizarck/ai-playbook@v0.9.1   # legacy pin" in out


# ---------------------------------------------------------------------------
# _parse_branch_version (followup #2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "branch,expected_present",
    [
        ("chore/bump-playbook-v0.9.0", True),
        ("chore/bump-playbook-v0.9.0-rc2", True),
        ("chore/bump-playbook-v0.10.5", True),
        ("chore/bump-skills-ai-playbook-v0.9.0", True),
        ("chore/bump-skills-consumer-d-skills-v0.3.0-rc1", True),
        ("chore/something-else-v1.0.0", False),
        ("feat/persistence-tenant-enforcement", False),
        ("chore/bump-playbook-not-a-version", False),
    ],
)
def test_parse_branch_version_recognises_bump_branches(
    branch: str, expected_present: bool
) -> None:
    result = _bumper._parse_branch_version(branch)
    assert (result is not None) == expected_present


def test_parse_branch_version_orders_rcs_below_stable() -> None:
    """v0.9.0-rc3 < v0.9.0 (stable releases sort above their rcs)."""
    rc = _bumper._parse_branch_version("chore/bump-playbook-v0.9.0-rc3")
    stable = _bumper._parse_branch_version("chore/bump-playbook-v0.9.0")
    assert rc is not None and stable is not None
    assert rc < stable


def test_parse_branch_version_orders_rcs_by_number() -> None:
    """v0.9.0-rc2 < v0.9.0-rc3."""
    rc2 = _bumper._parse_branch_version("chore/bump-playbook-v0.9.0-rc2")
    rc3 = _bumper._parse_branch_version("chore/bump-playbook-v0.9.0-rc3")
    assert rc2 is not None and rc3 is not None
    assert rc2 < rc3


def test_parse_branch_version_orders_series() -> None:
    """v0.8.8 < v0.9.0-rc1 < v0.9.0 < v0.10.0 (series ordering across major-minor-patch)."""
    keys = [
        _bumper._parse_branch_version("chore/bump-playbook-v0.8.8"),
        _bumper._parse_branch_version("chore/bump-playbook-v0.9.0-rc1"),
        _bumper._parse_branch_version("chore/bump-playbook-v0.9.0"),
        _bumper._parse_branch_version("chore/bump-playbook-v0.10.0"),
    ]
    assert all(k is not None for k in keys)
    for a, b in zip(keys, keys[1:], strict=False):
        assert a is not None and b is not None
        assert a < b


# ---------------------------------------------------------------------------
# supersede_open_bump_prs semver-aware behaviour (followup #2)
# ---------------------------------------------------------------------------


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _make_prs(*entries: tuple[int, str]) -> str:
    return json.dumps(
        [
            {
                "number": num,
                "headRefName": branch,
                "url": f"https://github.com/example/repo/pull/{num}",
            }
            for num, branch in entries
        ]
    )


def test_supersede_only_closes_older_versions_when_new_branch_supplied(
    tmp_path: Path,
) -> None:
    """Out-of-order tag push: pushing v0.8.7 LAST must NOT close v0.9.0-rc2 PR."""
    list_stdout = _make_prs(
        (101, "chore/bump-playbook-v0.9.0-rc2"),  # newer, should NOT close
        (100, "chore/bump-playbook-v0.8.6"),  # older, should close
    )
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess:
        calls.append(cmd)
        if cmd[:3] == ["gh", "pr", "list"]:
            return _completed(stdout=list_stdout)
        return _completed()

    with patch.object(_bumper.subprocess, "run", side_effect=fake_run):
        closed = _bumper.supersede_open_bump_prs(
            tmp_path,
            "chore/bump-playbook-",
            new_pr_number=200,
            new_branch="chore/bump-playbook-v0.8.7",
        )

    assert closed == ["100"], "v0.8.7 closes v0.8.6 but NOT v0.9.0-rc2"
    pr_close_cmds = [c for c in calls if c[:3] == ["gh", "pr", "close"]]
    assert len(pr_close_cmds) == 1
    assert "100" in pr_close_cmds[0]


def test_supersede_closes_all_when_new_branch_is_newest(tmp_path: Path) -> None:
    """Pushing v0.9.0 stable closes every prior bump PR (rc1, rc2, rc3, v0.8.8)."""
    list_stdout = _make_prs(
        (101, "chore/bump-playbook-v0.9.0-rc3"),
        (102, "chore/bump-playbook-v0.9.0-rc2"),
        (103, "chore/bump-playbook-v0.8.8"),
    )

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "pr", "list"]:
            return _completed(stdout=list_stdout)
        return _completed()

    with patch.object(_bumper.subprocess, "run", side_effect=fake_run):
        closed = _bumper.supersede_open_bump_prs(
            tmp_path,
            "chore/bump-playbook-",
            new_pr_number=200,
            new_branch="chore/bump-playbook-v0.9.0",
        )

    assert sorted(closed) == ["101", "102", "103"]


def test_supersede_falls_back_to_chronological_when_new_branch_absent(
    tmp_path: Path,
) -> None:
    """Backward compatibility: callers that don't pass new_branch still close all."""
    list_stdout = _make_prs(
        (101, "chore/bump-playbook-v0.9.0-rc2"),
        (102, "chore/bump-playbook-v0.8.6"),
    )

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "pr", "list"]:
            return _completed(stdout=list_stdout)
        return _completed()

    with patch.object(_bumper.subprocess, "run", side_effect=fake_run):
        closed = _bumper.supersede_open_bump_prs(
            tmp_path,
            "chore/bump-playbook-",
            new_pr_number=200,
        )

    assert sorted(closed) == ["101", "102"]


def test_supersede_skips_unparseable_open_branches(tmp_path: Path) -> None:
    """Open PRs with non-standard branch names are skipped (no close)."""
    list_stdout = _make_prs(
        (101, "chore/bump-playbook-v0.8.6"),
        (102, "chore/bump-playbook-not-a-version"),  # unparseable; don't close
    )

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "pr", "list"]:
            return _completed(stdout=list_stdout)
        return _completed()

    with patch.object(_bumper.subprocess, "run", side_effect=fake_run):
        closed = _bumper.supersede_open_bump_prs(
            tmp_path,
            "chore/bump-playbook-",
            new_pr_number=200,
            new_branch="chore/bump-playbook-v0.9.0",
        )

    assert closed == ["101"]


def test_supersede_idempotent_when_no_open_prs(tmp_path: Path) -> None:
    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "pr", "list"]:
            return _completed(stdout="[]")
        return _completed()

    with patch.object(_bumper.subprocess, "run", side_effect=fake_run):
        closed = _bumper.supersede_open_bump_prs(
            tmp_path,
            "chore/bump-playbook-",
            new_pr_number=None,
            new_branch="chore/bump-playbook-v0.9.0",
        )

    assert closed == []
