"""Tests for `scripts/materialise_skills.py` (v0.17.0 single-source design).

Covers:

1. Fresh consumer with no existing mirrors.
2. Idempotency — second run on the same source is a no-op.
3. Orphan removal — skill removed upstream disappears from the mirror.
4. Mirror parity — Claude vs Gemini vs generic mirrors are byte-identical.
5. Dry-run mode does not touch the filesystem.
6. Source missing emits canonical error + exit code 2.
7. Partial mirror (only one of three exists) regenerates the other two.
8. Nested skill assets (subdirectories under SKILL.md) copy correctly.
9. Quiet mode suppresses stdout.
10. `--source` override accepts an arbitrary path.
11. CLI exit 0 on success.
12. CLI exit 2 on missing source.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Make scripts importable when running pytest from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import materialise_skills as ms


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_source(playbook_skills: Path, skills: dict[str, dict[str, str]]) -> None:
    """Seed a fake `.ai-playbook/skills/` tree.

    Parameters
    ----------
    playbook_skills
        Target root (the `.ai-playbook/skills/` directory).
    skills
        Mapping `{skill_name: {rel_path: content}}`. Every skill always gets
        an implicit `SKILL.md` if not supplied — count helpers depend on it.
    """
    playbook_skills.mkdir(parents=True, exist_ok=True)
    for name, files in skills.items():
        skill_dir = playbook_skills / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        if "SKILL.md" not in files:
            (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        for rel, content in files.items():
            target = skill_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")


def _build_consumer(tmp_path: Path, skills: dict[str, dict[str, str]] | None = None) -> Path:
    """Build a consumer dir with a fake `.ai-playbook/skills/` source."""
    consumer = tmp_path / "consumer"
    consumer.mkdir(parents=True, exist_ok=True)
    source = consumer / ms.SOURCE_REL
    _seed_source(source, skills or {"hello-world": {}, "ping": {}})
    return consumer


def _read_skill(consumer: Path, mirror_rel: Path, skill: str) -> str:
    return (consumer / mirror_rel / skill / "SKILL.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Fresh consumer
# ---------------------------------------------------------------------------


def test_fresh_consumer_creates_all_three_mirrors(tmp_path: Path) -> None:
    consumer = _build_consumer(tmp_path)

    result = ms.materialise_skills(consumer, quiet=True)

    assert result.ok
    assert result.skills_total == 2
    assert result.mirrors_rewritten == 3
    assert result.mirrors_in_sync == 0
    for rel in ms.MIRROR_RELS:
        assert (consumer / rel / "hello-world" / "SKILL.md").is_file()
        assert (consumer / rel / "ping" / "SKILL.md").is_file()


# ---------------------------------------------------------------------------
# 2. Idempotency
# ---------------------------------------------------------------------------


def test_idempotent_second_run_is_noop(tmp_path: Path) -> None:
    consumer = _build_consumer(tmp_path)

    first = ms.materialise_skills(consumer, quiet=True)
    assert first.ok
    assert first.mirrors_rewritten == 3

    # Capture mtimes after first run.
    first_run_mtimes = {
        rel: (consumer / rel / "hello-world" / "SKILL.md").stat().st_mtime_ns
        for rel in ms.MIRROR_RELS
    }

    second = ms.materialise_skills(consumer, quiet=True)
    assert second.ok
    assert second.mirrors_rewritten == 0
    assert second.mirrors_in_sync == 3

    # FS untouched — mtimes unchanged.
    for rel in ms.MIRROR_RELS:
        cur = (consumer / rel / "hello-world" / "SKILL.md").stat().st_mtime_ns
        assert cur == first_run_mtimes[rel], (
            f"{rel} was rewritten unnecessarily on second run"
        )


# ---------------------------------------------------------------------------
# 3. Orphan removal
# ---------------------------------------------------------------------------


def test_orphan_skill_removed_from_mirrors(tmp_path: Path) -> None:
    consumer = _build_consumer(tmp_path, {"alpha": {}, "beta": {}})
    ms.materialise_skills(consumer, quiet=True)

    # Remove `beta` from source — simulates an upstream skill deletion.
    import shutil
    shutil.rmtree(consumer / ms.SOURCE_REL / "beta")

    result = ms.materialise_skills(consumer, quiet=True)

    assert result.ok
    assert result.skills_total == 1
    # All three mirrors rewritten (fingerprint changed).
    assert result.mirrors_rewritten == 3
    for rel in ms.MIRROR_RELS:
        assert (consumer / rel / "alpha" / "SKILL.md").is_file()
        assert not (consumer / rel / "beta").exists(), (
            f"{rel}/beta should have been removed as an orphan"
        )


# ---------------------------------------------------------------------------
# 4. Mirror parity (Claude vs Gemini vs generic)
# ---------------------------------------------------------------------------


def test_mirror_parity_byte_identical(tmp_path: Path) -> None:
    consumer = _build_consumer(
        tmp_path,
        {
            "complex": {
                "SKILL.md": "# complex\n\nbody\n",
                "templates/a.txt": "alpha",
                "templates/b.txt": "beta",
                "data/nested/c.json": '{"k":"v"}',
            },
        },
    )

    ms.materialise_skills(consumer, quiet=True)

    fp_claude = ms._dir_fingerprint(consumer / Path(".claude") / "skills")
    fp_gemini = ms._dir_fingerprint(consumer / Path(".gemini") / "skills")
    fp_generic = ms._dir_fingerprint(consumer / "skills")
    fp_source = ms._dir_fingerprint(consumer / ms.SOURCE_REL)

    assert fp_source != ""
    assert fp_claude == fp_source
    assert fp_gemini == fp_source
    assert fp_generic == fp_source


# ---------------------------------------------------------------------------
# 5. Dry-run mode
# ---------------------------------------------------------------------------


def test_dry_run_does_not_touch_filesystem(tmp_path: Path) -> None:
    consumer = _build_consumer(tmp_path)

    result = ms.materialise_skills(consumer, dry_run=True, quiet=True)

    assert result.ok
    assert result.skills_total == 2
    # mirrors_rewritten counts what WOULD be rewritten — but no FS writes.
    assert result.mirrors_rewritten == 3
    for rel in ms.MIRROR_RELS:
        assert not (consumer / rel).exists(), (
            f"{rel} created during dry-run (must not write)"
        )


# ---------------------------------------------------------------------------
# 6. Source missing
# ---------------------------------------------------------------------------


def test_source_missing_emits_canonical_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    consumer = tmp_path / "consumer-no-source"
    consumer.mkdir()

    result = ms.materialise_skills(consumer, quiet=True)

    assert not result.ok
    assert any(err.startswith("source missing:") for err in result.errors)
    captured = capsys.readouterr()
    assert "❌" in captured.err
    assert "FIX:" in captured.err


# ---------------------------------------------------------------------------
# 7. Partial mirror — only one of three already exists
# ---------------------------------------------------------------------------


def test_partial_mirror_regenerates_missing_targets(tmp_path: Path) -> None:
    consumer = _build_consumer(tmp_path)
    # Pre-create one mirror with wrong content; leave the other two missing.
    skewed = consumer / Path(".claude") / "skills"
    skewed.mkdir(parents=True, exist_ok=True)
    (skewed / "stale-skill").mkdir()
    (skewed / "stale-skill" / "SKILL.md").write_text("stale", encoding="utf-8")

    result = ms.materialise_skills(consumer, quiet=True)

    assert result.ok
    # All three mirrors get written (the stale one is wiped + recopied).
    assert result.mirrors_rewritten == 3
    for rel in ms.MIRROR_RELS:
        assert (consumer / rel / "hello-world" / "SKILL.md").is_file()
        assert (consumer / rel / "ping" / "SKILL.md").is_file()
        assert not (consumer / rel / "stale-skill").exists()


# ---------------------------------------------------------------------------
# 8. Nested skill assets
# ---------------------------------------------------------------------------


def test_nested_assets_copy_intact(tmp_path: Path) -> None:
    consumer = _build_consumer(
        tmp_path,
        {
            "tree-skill": {
                "SKILL.md": "# tree\n",
                "steps-c/step-1.md": "step one",
                "steps-c/step-2.md": "step two",
                "data/seed/01.json": '{"id": 1}',
                "data/seed/02.json": '{"id": 2}',
                "references/links.md": "[a](https://example.com)",
            },
        },
    )

    ms.materialise_skills(consumer, quiet=True)

    for rel in ms.MIRROR_RELS:
        base = consumer / rel / "tree-skill"
        assert (base / "SKILL.md").read_text(encoding="utf-8") == "# tree\n"
        assert (base / "steps-c" / "step-1.md").read_text(encoding="utf-8") == "step one"
        assert (base / "steps-c" / "step-2.md").read_text(encoding="utf-8") == "step two"
        assert (base / "data" / "seed" / "01.json").read_text(encoding="utf-8") == '{"id": 1}'
        assert (base / "data" / "seed" / "02.json").read_text(encoding="utf-8") == '{"id": 2}'
        assert (base / "references" / "links.md").read_text(encoding="utf-8") == (
            "[a](https://example.com)"
        )


# ---------------------------------------------------------------------------
# 9. Quiet mode
# ---------------------------------------------------------------------------


def test_quiet_mode_suppresses_stdout(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    consumer = _build_consumer(tmp_path)

    result = ms.materialise_skills(consumer, quiet=True)
    captured = capsys.readouterr()

    assert result.ok
    assert captured.out == ""


def test_loud_mode_emits_summary_line(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    consumer = _build_consumer(tmp_path)

    result = ms.materialise_skills(consumer, quiet=False)
    captured = capsys.readouterr()

    assert result.ok
    assert "Done." in captured.out


# ---------------------------------------------------------------------------
# 10. --source override
# ---------------------------------------------------------------------------


def test_source_override_accepts_arbitrary_path(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    external_source = tmp_path / "external-skills"
    _seed_source(external_source, {"external-skill": {}})

    result = ms.materialise_skills(
        consumer, source_override=external_source, quiet=True,
    )

    assert result.ok
    assert result.skills_total == 1
    for rel in ms.MIRROR_RELS:
        assert (consumer / rel / "external-skill" / "SKILL.md").is_file()


# ---------------------------------------------------------------------------
# 11 + 12. CLI exit codes
# ---------------------------------------------------------------------------


def test_cli_exit_zero_on_success(tmp_path: Path) -> None:
    consumer = _build_consumer(tmp_path)
    rc = ms.main(["--consumer", str(consumer), "--quiet"])
    assert rc == 0


def test_cli_exit_two_on_missing_source(tmp_path: Path) -> None:
    consumer = tmp_path / "no-source"
    consumer.mkdir()
    rc = ms.main(["--consumer", str(consumer), "--quiet"])
    assert rc == 2


def test_cli_dry_run_smoke(tmp_path: Path) -> None:
    consumer = _build_consumer(tmp_path)
    rc = ms.main(["--consumer", str(consumer), "--dry-run", "--quiet"])
    assert rc == 0
    for rel in ms.MIRROR_RELS:
        assert not (consumer / rel).exists()


# ---------------------------------------------------------------------------
# Smoke: subprocess invocation (matches how the post-merge hook calls us)
# ---------------------------------------------------------------------------


def test_subprocess_invocation(tmp_path: Path) -> None:
    consumer = _build_consumer(tmp_path)
    script = Path(__file__).resolve().parent.parent / "scripts" / "materialise_skills.py"

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, str(script), "--consumer", str(consumer), "--quiet"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )

    assert result.returncode == 0, (
        f"subprocess failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    for rel in ms.MIRROR_RELS:
        assert (consumer / rel / "hello-world" / "SKILL.md").is_file()
