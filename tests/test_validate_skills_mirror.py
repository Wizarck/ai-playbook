"""Tests for scripts/validate_skills_mirror.py — RFC-0001 Phase 2c."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import validate_skills_mirror as vsm

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill_tree(consumer: Path, names: list[str], body: str = "x") -> None:
    """Populate <consumer>/skills/<name>/SKILL.md for each name."""
    skills = consumer / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    for n in names:
        sk = skills / n
        sk.mkdir(exist_ok=True)
        (sk / "SKILL.md").write_text(f"# {n}\n{body}\n", encoding="utf-8")


def _mirror_from_skills(consumer: Path) -> None:
    """Copy skills/ to both mirror dirs (the materialiser's behaviour)."""
    src = consumer / "skills"
    for rel in vsm.MIRROR_SUBDIRS:
        dst = consumer / rel
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst)


# ---------------------------------------------------------------------------
# No-op paths (pre-migration consumers)
# ---------------------------------------------------------------------------


def test_noop_when_no_skills_dir(tmp_path: Path) -> None:
    rc = vsm.validate_consumer(tmp_path)
    assert rc == 0


def test_noop_when_no_mirrors_yet(tmp_path: Path) -> None:
    _make_skill_tree(tmp_path, ["alpha"])
    rc = vsm.validate_consumer(tmp_path)
    assert rc == 0  # mirror dirs absent → script defers to first materialise run


def test_invalid_consumer_path_returns_2(tmp_path: Path) -> None:
    rc = vsm.validate_consumer(tmp_path / "does-not-exist")
    assert rc == 2


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


def test_in_sync_returns_0(tmp_path: Path) -> None:
    _make_skill_tree(tmp_path, ["alpha", "beta"])
    _mirror_from_skills(tmp_path)
    rc = vsm.validate_consumer(tmp_path)
    assert rc == 0


def test_drift_when_mirror_modified_returns_1(tmp_path: Path, capsys) -> None:
    _make_skill_tree(tmp_path, ["alpha"])
    _mirror_from_skills(tmp_path)
    # Tamper with .claude/skills/alpha/SKILL.md.
    tampered = tmp_path / ".claude" / "skills" / "alpha" / "SKILL.md"
    tampered.write_text("DRIFTED\n", encoding="utf-8")
    rc = vsm.validate_consumer(tmp_path)
    assert rc == 1
    captured = capsys.readouterr()
    assert "drift detected" in captured.err
    assert "alpha/SKILL.md" in captured.err


def test_drift_when_mirror_has_extra_file_returns_1(tmp_path: Path) -> None:
    _make_skill_tree(tmp_path, ["alpha"])
    _mirror_from_skills(tmp_path)
    # Add a stray file only in the mirror.
    extra = tmp_path / ".claude" / "skills" / "alpha" / "EXTRA.md"
    extra.write_text("not in canonical\n", encoding="utf-8")
    rc = vsm.validate_consumer(tmp_path)
    assert rc == 1


def test_drift_when_canonical_has_extra_file_returns_1(tmp_path: Path) -> None:
    _make_skill_tree(tmp_path, ["alpha"])
    _mirror_from_skills(tmp_path)
    # Add a stray file only in canonical (would be missing from mirror).
    (tmp_path / "skills" / "alpha" / "NEW.md").write_text("only here\n", encoding="utf-8")
    rc = vsm.validate_consumer(tmp_path)
    assert rc == 1


def test_drift_when_one_mirror_dir_missing(tmp_path: Path) -> None:
    _make_skill_tree(tmp_path, ["alpha"])
    _mirror_from_skills(tmp_path)
    # Remove just the .gemini side.
    shutil.rmtree(tmp_path / ".gemini" / "skills")
    rc = vsm.validate_consumer(tmp_path)
    assert rc == 1


# ---------------------------------------------------------------------------
# --fix regenerates mirrors
# ---------------------------------------------------------------------------


def test_fix_regenerates_drift_to_zero(tmp_path: Path) -> None:
    _make_skill_tree(tmp_path, ["alpha", "beta"])
    _mirror_from_skills(tmp_path)
    # Drift the mirror.
    (tmp_path / ".claude" / "skills" / "alpha" / "SKILL.md").write_text("BAD\n", encoding="utf-8")

    rc_dirty = vsm.validate_consumer(tmp_path, fix=False)
    assert rc_dirty == 1

    rc_fix = vsm.validate_consumer(tmp_path, fix=True)
    assert rc_fix == 0

    rc_clean = vsm.validate_consumer(tmp_path, fix=False)
    assert rc_clean == 0
    # Re-copied content matches canonical.
    mirror_path = tmp_path / ".claude" / "skills" / "alpha" / "SKILL.md"
    assert "DRIFTED" not in mirror_path.read_text(encoding="utf-8")


def test_fix_regenerates_missing_mirror(tmp_path: Path) -> None:
    _make_skill_tree(tmp_path, ["alpha"])
    _mirror_from_skills(tmp_path)
    shutil.rmtree(tmp_path / ".gemini" / "skills")

    rc = vsm.validate_consumer(tmp_path, fix=True)
    assert rc == 0
    assert (tmp_path / ".gemini" / "skills" / "alpha" / "SKILL.md").is_file()


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def test_main_default_consumer_is_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    _make_skill_tree(tmp_path, ["alpha"])
    _mirror_from_skills(tmp_path)
    monkeypatch.chdir(tmp_path)
    rc = vsm.main([])
    assert rc == 0


def test_main_passes_through_paths_arg(
    tmp_path: Path, monkeypatch
) -> None:
    """Pre-commit invokes hooks with file paths — we accept + ignore them."""
    _make_skill_tree(tmp_path, ["alpha"])
    _mirror_from_skills(tmp_path)
    monkeypatch.chdir(tmp_path)
    rc = vsm.main(["skills/alpha/SKILL.md"])
    assert rc == 0
