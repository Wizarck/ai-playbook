"""Tests for scripts/rules/skills-sync.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_ss_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "skills-sync.rule.py",
)
assert SPEC and SPEC.loader
_ss = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_ss)


# --- helpers -----------------------------------------------------------------


def _make_consumer(
    tmp_path: Path,
    *,
    playbook_skills: list[str] | None = None,
    claude_skills: list[str] | None = None,
    with_materialiser: bool = False,
) -> Path:
    """Build a synthetic consumer root under tmp_path.

    - `playbook_skills`: skill slugs to seed under `.ai-playbook/skills/<slug>/SKILL.md`.
      None = do not create the `.ai-playbook/skills/` directory at all.
    - `claude_skills`: skill slugs to seed as directories under `.claude/skills/<slug>/`.
      None = do not create `.claude/skills/` at all.
    - `with_materialiser`: when True, place a no-op materialise_skills.py shim under
      `.ai-playbook/scripts/` so `apply` can exec it.
    """
    (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")

    if playbook_skills is not None:
        pb_root = tmp_path / ".ai-playbook" / "skills"
        pb_root.mkdir(parents=True)
        for slug in playbook_skills:
            sk = pb_root / slug
            sk.mkdir()
            (sk / "SKILL.md").write_text(f"# {slug}\n", encoding="utf-8")

    if claude_skills is not None:
        cc_root = tmp_path / ".claude" / "skills"
        cc_root.mkdir(parents=True)
        for slug in claude_skills:
            (cc_root / slug).mkdir()

    if with_materialiser:
        scripts_dir = tmp_path / ".ai-playbook" / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        # Minimal stand-in: exits 0 unconditionally; respects --dry-run flag
        # but doesn't actually mirror — sufficient for verifying the L1 rule
        # plumbs subprocess exit codes correctly.
        (scripts_dir / "materialise_skills.py").write_text(
            "import sys\n"
            "if '--source-missing' in sys.argv:\n"
            "    sys.exit(2)\n"
            "if '--fail' in sys.argv:\n"
            "    sys.exit(1)\n"
            "sys.exit(0)\n",
            encoding="utf-8",
        )
    return tmp_path


# --- validate ----------------------------------------------------------------


def test_validate_ok_when_mirror_has_at_least_one_playbook_skill(tmp_path: Path) -> None:
    root = _make_consumer(
        tmp_path,
        playbook_skills=["openspec-propose", "dev-flow"],
        claude_skills=["openspec-propose"],
    )
    assert _ss.validate(root) == 0


def test_validate_ok_when_mirror_has_extra_local_skills(tmp_path: Path) -> None:
    # The mirror contains a playbook skill PLUS a consumer-local skill — still ok.
    root = _make_consumer(
        tmp_path,
        playbook_skills=["openspec-propose"],
        claude_skills=["openspec-propose", "local-custom-skill"],
    )
    assert _ss.validate(root) == 0


def test_validate_drift_when_mirror_has_zero_playbook_skills(tmp_path: Path, capsys) -> None:
    root = _make_consumer(
        tmp_path,
        playbook_skills=["openspec-propose"],
        claude_skills=["unrelated-only"],
    )
    rc = _ss.validate(root)
    assert rc == 1
    assert "mirrors no playbook skills" in capsys.readouterr().err


def test_validate_drift_when_claude_skills_empty(tmp_path: Path, capsys) -> None:
    root = _make_consumer(
        tmp_path,
        playbook_skills=["openspec-propose"],
        claude_skills=[],  # dir exists but empty
    )
    rc = _ss.validate(root)
    assert rc == 1
    assert "mirrors no playbook skills" in capsys.readouterr().err


def test_validate_not_applicable_when_no_claude_skills_dir(tmp_path: Path) -> None:
    # Consumer opted out of Claude Code skills entirely.
    root = _make_consumer(
        tmp_path,
        playbook_skills=["openspec-propose"],
        claude_skills=None,
    )
    assert _ss.validate(root) == 0


def test_validate_not_applicable_when_no_playbook_skills_dir(tmp_path: Path) -> None:
    # Submodule not initialised — install-playbook owns that violation.
    root = _make_consumer(
        tmp_path,
        playbook_skills=None,
        claude_skills=["something"],
    )
    assert _ss.validate(root) == 0


def test_validate_fatal_when_no_consumer_root(tmp_path: Path, capsys) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    rc = _ss.validate(nested)
    assert rc == 2
    assert "no consumer root" in capsys.readouterr().err


def test_validate_skip_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Broken state would normally return 1, but the skip flag bypasses everything.
    root = _make_consumer(
        tmp_path,
        playbook_skills=["openspec-propose"],
        claude_skills=["unrelated-only"],
    )
    monkeypatch.setenv("AIPLAYBOOK_SKILLS_SYNC_SKIP", "1")
    assert _ss.validate(root) == 0


# --- apply -------------------------------------------------------------------


def test_apply_invokes_materialiser_when_present(tmp_path: Path) -> None:
    root = _make_consumer(
        tmp_path,
        playbook_skills=["openspec-propose"],
        claude_skills=["unrelated-only"],
        with_materialiser=True,
    )
    rc = _ss.apply(dry_run=False, cwd=root)
    assert rc == 0


def test_apply_dry_run_returns_zero(tmp_path: Path, capsys) -> None:
    root = _make_consumer(
        tmp_path,
        playbook_skills=["openspec-propose"],
        claude_skills=["unrelated-only"],
        with_materialiser=True,
    )
    rc = _ss.apply(dry_run=True, cwd=root)
    assert rc == 0
    assert "[dry-run]" in capsys.readouterr().out


def test_apply_fails_when_materialiser_absent(tmp_path: Path, capsys) -> None:
    root = _make_consumer(
        tmp_path,
        playbook_skills=["openspec-propose"],
        claude_skills=["unrelated-only"],
        with_materialiser=False,
    )
    rc = _ss.apply(dry_run=False, cwd=root)
    assert rc == 1
    assert "manual fix" in capsys.readouterr().err


def test_apply_idempotent_on_converged_state(tmp_path: Path) -> None:
    # Mirror already contains a playbook skill; running apply twice = exit 0 both times.
    root = _make_consumer(
        tmp_path,
        playbook_skills=["openspec-propose"],
        claude_skills=["openspec-propose"],
        with_materialiser=True,
    )
    assert _ss.apply(dry_run=False, cwd=root) == 0
    assert _ss.apply(dry_run=False, cwd=root) == 0


def test_apply_fatal_when_no_consumer_root(tmp_path: Path, capsys) -> None:
    nested = tmp_path / "deep" / "nested"
    nested.mkdir(parents=True)
    rc = _ss.apply(dry_run=False, cwd=nested)
    assert rc == 2
    assert "no consumer root" in capsys.readouterr().err
