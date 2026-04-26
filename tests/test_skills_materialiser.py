"""Tests for scripts/_skills_materialiser.py — RFC-0001 Phase 2a.

Mocks the git side of materialisation by faking `_add_submodule` so the suite
never touches the network. The merge / mirror logic is exercised end-to-end
against tmp_path filesystems.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Make scripts importable when running pytest from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import _skills_materialiser as sm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_agents_md(consumer_dir: Path, sources: list[str] | None) -> None:
    """Write a minimal AGENTS.md at consumer_dir/AGENTS.md with the given sources."""
    consumer_dir.mkdir(parents=True, exist_ok=True)
    fm_lines = ["---", "schema: agents-md/v1", "project: test-consumer"]
    if sources is not None:
        fm_lines.append("skills_sources:")
        for s in sources:
            fm_lines.append(f"  - {s}")
    fm_lines.append("---")
    fm_lines.append("body")
    (consumer_dir / "AGENTS.md").write_text(
        "\n".join(fm_lines) + "\n", encoding="utf-8"
    )


def _stub_submodule(
    consumer_dir: Path,
    relpath: str,
    skill_names: list[str],
) -> None:
    """Pre-populate a fake submodule checkout at relpath/skills/<name>/SKILL.md.

    Idempotent — callers (including re-runs in idempotency tests) may invoke it
    repeatedly with the same args.
    """
    skills_root = consumer_dir / relpath / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    for name in skill_names:
        sk = skills_root / name
        sk.mkdir(exist_ok=True)
        (sk / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# AGENTS.md frontmatter parsing
# ---------------------------------------------------------------------------


def test_read_frontmatter_returns_none_when_no_agents_md(tmp_path: Path) -> None:
    assert sm._read_agents_md_frontmatter(tmp_path) is None


def test_read_frontmatter_returns_none_when_no_block(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("just body, no frontmatter\n", encoding="utf-8")
    assert sm._read_agents_md_frontmatter(tmp_path) is None


def test_read_frontmatter_parses_skills_sources(tmp_path: Path) -> None:
    _write_agents_md(tmp_path, ["Wizarck/ai-playbook@v0.4.0"])
    fm = sm._read_agents_md_frontmatter(tmp_path)
    assert fm is not None
    assert fm["skills_sources"] == ["Wizarck/ai-playbook@v0.4.0"]


# ---------------------------------------------------------------------------
# Source ref parsing
# ---------------------------------------------------------------------------


def test_parse_source_ref_canonical() -> None:
    assert sm._parse_source_ref("Wizarck/ai-playbook@v0.4.0") == (
        "Wizarck", "ai-playbook", "v0.4.0",
    )


def test_parse_source_ref_with_github_prefix() -> None:
    assert sm._parse_source_ref("github.com/Wizarck/consumer-d-skills@v0.2.0") == (
        "Wizarck", "consumer-d-skills", "v0.2.0",
    )


def test_parse_source_ref_rejects_malformed() -> None:
    with pytest.raises(ValueError):
        sm._parse_source_ref("Wizarck/ai-playbook")  # missing @tag
    with pytest.raises(ValueError):
        sm._parse_source_ref("not-a-ref")


# ---------------------------------------------------------------------------
# materialise_skills — no-op paths (consumer not migrated)
# ---------------------------------------------------------------------------


def test_materialise_noop_when_no_agents_md(tmp_path: Path) -> None:
    result = sm.materialise_skills(tmp_path)
    assert result.noop is True
    assert result.ok
    assert result.skills_total == 0


def test_materialise_noop_when_no_skills_sources(tmp_path: Path) -> None:
    _write_agents_md(tmp_path, sources=None)
    result = sm.materialise_skills(tmp_path)
    assert result.noop is True
    assert result.ok


def test_materialise_errors_when_skills_sources_not_list(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "---\nschema: agents-md/v1\nskills_sources: not-a-list\n---\nbody\n",
        encoding="utf-8",
    )
    result = sm.materialise_skills(tmp_path)
    assert not result.ok
    assert any("not a list" in e for e in result.errors)


def test_materialise_errors_on_malformed_ref(tmp_path: Path) -> None:
    _write_agents_md(tmp_path, ["bogus-no-at-symbol"])
    result = sm.materialise_skills(tmp_path)
    assert not result.ok
    assert any("malformed" in e for e in result.errors)


# ---------------------------------------------------------------------------
# materialise_skills — happy path with stubbed submodules
# ---------------------------------------------------------------------------


def test_materialise_happy_path_single_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_md(tmp_path, ["Wizarck/ai-playbook@v0.4.0"])

    def fake_add_submodule(consumer_dir, *, url, relpath, tag):  # type: ignore[no-untyped-def]
        _stub_submodule(consumer_dir, relpath, ["alpha-skill", "beta-skill"])
        return True, "ok"

    monkeypatch.setattr(sm, "_git_available", lambda: True)
    monkeypatch.setattr(sm, "_ensure_consumer_repo", lambda d: None)
    monkeypatch.setattr(sm, "_add_submodule", fake_add_submodule)

    result = sm.materialise_skills(tmp_path)

    assert result.ok
    assert result.skills_total == 2
    assert result.sources_pinned == 1
    assert result.mirrors_generated == 2
    # Merged dir
    assert (tmp_path / "skills" / "alpha-skill" / "SKILL.md").is_file()
    assert (tmp_path / "skills" / "beta-skill" / "SKILL.md").is_file()
    # Mirrors
    assert (tmp_path / ".claude" / "skills" / "alpha-skill" / "SKILL.md").is_file()
    assert (tmp_path / ".gemini" / "skills" / "beta-skill" / "SKILL.md").is_file()


def test_materialise_two_sources_merged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_md(
        tmp_path,
        ["Wizarck/ai-playbook@v0.4.0", "Wizarck/consumer-d-skills@v0.2.0"],
    )

    def fake_add_submodule(consumer_dir, *, url, relpath, tag):  # type: ignore[no-untyped-def]
        if "ai-playbook" in relpath:
            _stub_submodule(consumer_dir, relpath, ["bmad-create-prd"])
        else:
            _stub_submodule(consumer_dir, relpath, ["code-reviewer"])
        return True, "ok"

    monkeypatch.setattr(sm, "_git_available", lambda: True)
    monkeypatch.setattr(sm, "_ensure_consumer_repo", lambda d: None)
    monkeypatch.setattr(sm, "_add_submodule", fake_add_submodule)

    result = sm.materialise_skills(tmp_path)

    assert result.ok
    assert result.skills_total == 2
    assert result.sources_pinned == 2
    assert (tmp_path / "skills" / "bmad-create-prd" / "SKILL.md").is_file()
    assert (tmp_path / "skills" / "code-reviewer" / "SKILL.md").is_file()


def test_materialise_collision_emits_clarification_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_md(
        tmp_path,
        ["Wizarck/ai-playbook@v0.4.0", "Wizarck/consumer-d-skills@v0.2.0"],
    )

    # Both sources expose the same skill name.
    def fake_add_submodule(consumer_dir, *, url, relpath, tag):  # type: ignore[no-untyped-def]
        _stub_submodule(consumer_dir, relpath, ["dup-skill"])
        return True, "ok"

    monkeypatch.setattr(sm, "_git_available", lambda: True)
    monkeypatch.setattr(sm, "_ensure_consumer_repo", lambda d: None)
    monkeypatch.setattr(sm, "_add_submodule", fake_add_submodule)

    result = sm.materialise_skills(tmp_path)

    assert not result.ok
    assert any("CLARIFICATION NEEDED" in e for e in result.errors)
    assert any("dup-skill" in e for e in result.errors)


def test_materialise_tag_not_found_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_md(tmp_path, ["Wizarck/ai-playbook@v9.9.9"])

    def fake_add_submodule(consumer_dir, *, url, relpath, tag):  # type: ignore[no-untyped-def]
        return False, "tag v9.9.9 not found in remote"

    monkeypatch.setattr(sm, "_git_available", lambda: True)
    monkeypatch.setattr(sm, "_ensure_consumer_repo", lambda d: None)
    monkeypatch.setattr(sm, "_add_submodule", fake_add_submodule)

    result = sm.materialise_skills(tmp_path)

    assert not result.ok
    assert any("tag v9.9.9" in e for e in result.errors)


def test_materialise_git_missing_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_md(tmp_path, ["Wizarck/ai-playbook@v0.4.0"])
    monkeypatch.setattr(sm, "_git_available", lambda: False)

    result = sm.materialise_skills(tmp_path)

    assert not result.ok
    assert any("git not on PATH" in e for e in result.errors)


def test_materialise_dry_run_no_filesystem_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agents_md(tmp_path, ["Wizarck/ai-playbook@v0.4.0"])
    # Even if git is missing, dry-run should succeed without invoking git.
    monkeypatch.setattr(sm, "_git_available", lambda: False)

    result = sm.materialise_skills(tmp_path, dry_run=True)

    assert result.ok
    assert not (tmp_path / "skills").exists()
    assert not (tmp_path / ".claude").exists()


def test_materialise_idempotent_rerun_same_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-invoking with same submodule state produces same merged content."""
    _write_agents_md(tmp_path, ["Wizarck/ai-playbook@v0.4.0"])

    def fake_add_submodule(consumer_dir, *, url, relpath, tag):  # type: ignore[no-untyped-def]
        _stub_submodule(consumer_dir, relpath, ["alpha", "beta"])
        return True, "ok"

    monkeypatch.setattr(sm, "_git_available", lambda: True)
    monkeypatch.setattr(sm, "_ensure_consumer_repo", lambda d: None)
    monkeypatch.setattr(sm, "_add_submodule", fake_add_submodule)

    r1 = sm.materialise_skills(tmp_path)
    # Snapshot file mtimes / contents.
    first_skill = (tmp_path / "skills" / "alpha" / "SKILL.md").read_text(encoding="utf-8")

    r2 = sm.materialise_skills(tmp_path)
    second_skill = (tmp_path / "skills" / "alpha" / "SKILL.md").read_text(encoding="utf-8")

    assert r1.ok and r2.ok
    assert first_skill == second_skill
    assert r1.skills_total == r2.skills_total == 2
