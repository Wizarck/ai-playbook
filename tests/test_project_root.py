"""Tests for scripts._project_root — submodule-collision-safe project walk."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import _project_root


# ---------------------------------------------------------------------------
# is_inside_playbook_checkout — segment-based detection
# ---------------------------------------------------------------------------


def test_segment_dot_ai_playbook_flagged() -> None:
    assert _project_root.is_inside_playbook_checkout(
        Path("/home/dev/consumer/.ai-playbook")
    )
    assert _project_root.is_inside_playbook_checkout(
        Path("/home/dev/consumer/.ai-playbook/scripts/caveman")
    )


def test_segment_skills_sources_flagged() -> None:
    assert _project_root.is_inside_playbook_checkout(
        Path("/home/dev/consumer/.skills-sources/ai-playbook")
    )
    assert _project_root.is_inside_playbook_checkout(
        Path("/home/dev/consumer/.skills-sources/ai-playbook/scripts")
    )


def test_consumer_root_not_flagged() -> None:
    assert not _project_root.is_inside_playbook_checkout(
        Path("/home/dev/consumer")
    )


def test_playbook_repo_itself_not_flagged() -> None:
    # The playbook repo lives at a path NAMED 'ai-playbook' (no dot prefix),
    # so dogfooding caveman/rules_toggle on the playbook still works.
    assert not _project_root.is_inside_playbook_checkout(
        Path("/home/dev/Code/ai-playbook")
    )
    assert not _project_root.is_inside_playbook_checkout(
        Path("/home/dev/Code/ai-playbook/scripts")
    )


def test_substring_not_a_match() -> None:
    # A consumer dir merely containing the substring '.ai-playbook' (e.g.
    # '.ai-playbook-stuff') must NOT be flagged — we match exact segments.
    assert not _project_root.is_inside_playbook_checkout(
        Path("/home/dev/.ai-playbook-stuff/my-project")
    )


# ---------------------------------------------------------------------------
# find_project_root — the actual bug scenario
# ---------------------------------------------------------------------------


def _make_consumer(tmp_path: Path) -> Path:
    """Build a fake consumer that carries a playbook submodule mount.

    Layout::

        tmp_path/consumer/AGENTS.md                       <- consumer dispatcher
        tmp_path/consumer/.ai-playbook/AGENTS.md          <- submodule's own
        tmp_path/consumer/.ai-playbook/scripts/caveman/   <- where the bug fires
        tmp_path/consumer/.skills-sources/ai-playbook/AGENTS.md
    """
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "AGENTS.md").write_text("# consumer\n", encoding="utf-8")

    submodule = consumer / ".ai-playbook"
    (submodule / "scripts" / "caveman").mkdir(parents=True)
    (submodule / "AGENTS.md").write_text("# playbook self (submodule)\n", encoding="utf-8")

    mirror = consumer / ".skills-sources" / "ai-playbook"
    (mirror / "scripts").mkdir(parents=True)
    (mirror / "AGENTS.md").write_text("# playbook self (mirror)\n", encoding="utf-8")

    return consumer


def test_cwd_in_submodule_resolves_to_consumer(tmp_path: Path) -> None:
    consumer = _make_consumer(tmp_path)
    inside_submodule = consumer / ".ai-playbook" / "scripts" / "caveman"
    found = _project_root.find_project_root(inside_submodule)
    assert found == consumer


def test_cwd_at_submodule_root_resolves_to_consumer(tmp_path: Path) -> None:
    consumer = _make_consumer(tmp_path)
    found = _project_root.find_project_root(consumer / ".ai-playbook")
    assert found == consumer


def test_cwd_in_skills_sources_mirror_resolves_to_consumer(tmp_path: Path) -> None:
    consumer = _make_consumer(tmp_path)
    inside_mirror = consumer / ".skills-sources" / "ai-playbook" / "scripts"
    found = _project_root.find_project_root(inside_mirror)
    assert found == consumer


def test_cwd_at_consumer_root_resolves_to_consumer(tmp_path: Path) -> None:
    consumer = _make_consumer(tmp_path)
    found = _project_root.find_project_root(consumer)
    assert found == consumer


def test_no_agents_md_anywhere_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Walk a synthesized path with no AGENTS.md on the chain. Real OS chain
    # above tmp_path might or might not carry an AGENTS.md — we only verify
    # that tmp_path itself is not returned as a positive match.
    found = _project_root.find_project_root(tmp_path)
    assert found != tmp_path


def test_state_path_no_longer_nests(tmp_path: Path) -> None:
    """Regression: state file under consumer root, NOT under submodule.

    Before the fix, calling caveman from inside the submodule produced
    ``<consumer>/.ai-playbook/.ai-playbook/caveman.json``. After the fix
    the resolved project root is the consumer, so state lives at
    ``<consumer>/.ai-playbook/caveman.json`` — no nesting.
    """
    from scripts.caveman import toggle

    consumer = _make_consumer(tmp_path)
    inside_submodule = consumer / ".ai-playbook" / "scripts" / "caveman"
    found = toggle.find_project_root(inside_submodule)
    assert found == consumer

    state_p = toggle.state_path(found)
    # Exactly one '.ai-playbook' segment.
    assert state_p.parts.count(".ai-playbook") == 1
    assert state_p == consumer / ".ai-playbook" / "caveman.json"
