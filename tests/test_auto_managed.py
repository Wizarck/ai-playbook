"""Tests for scripts/auto_managed.py.

Covers: marker parsing, extractor dispatch for the 4 documented source shapes,
the generic fallback, ``--check`` vs ``--fix`` behaviour, and the idempotency
contract.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import auto_managed as am


PLAYBOOK_ROOT = am.find_playbook_root()
assert PLAYBOOK_ROOT is not None, "test suite must run from inside the playbook"


# ---------------------------------------------------------------------------
# find_sections — parser behaviour
# ---------------------------------------------------------------------------


def test_find_sections_single_section() -> None:
    text = (
        "intro\n"
        "<!-- BEGIN auto-managed: specs/taxonomy:runtime -->\n"
        "stale content\n"
        "<!-- END auto-managed -->\n"
        "outro\n"
    )
    sections = am.find_sections(text)
    assert len(sections) == 1
    s = sections[0]
    assert s.source == "specs/taxonomy:runtime"
    assert s.start_line == 2
    assert s.end_line == 4
    assert s.current_content == "stale content"


def test_find_sections_multiple_sections() -> None:
    text = (
        "<!-- BEGIN auto-managed: a:b -->\n"
        "one\n"
        "<!-- END auto-managed -->\n"
        "mid\n"
        "<!-- BEGIN auto-managed: c:d -->\n"
        "two\n"
        "three\n"
        "<!-- END auto-managed -->\n"
    )
    sections = am.find_sections(text)
    assert [s.source for s in sections] == ["a:b", "c:d"]
    assert sections[1].current_content == "two\nthree"


def test_find_sections_no_markers() -> None:
    assert am.find_sections("plain content\n") == []


def test_find_sections_nested_raises() -> None:
    text = (
        "<!-- BEGIN auto-managed: a -->\n"
        "<!-- BEGIN auto-managed: b -->\n"
        "<!-- END auto-managed -->\n"
        "<!-- END auto-managed -->\n"
    )
    with pytest.raises(ValueError, match="Nested"):
        am.find_sections(text)


def test_find_sections_dangling_end_raises() -> None:
    text = "before\n<!-- END auto-managed -->\n"
    with pytest.raises(ValueError, match="Unbalanced END"):
        am.find_sections(text)


def test_find_sections_unterminated_raises() -> None:
    text = "<!-- BEGIN auto-managed: a:b -->\nno end\n"
    with pytest.raises(ValueError, match="Unterminated"):
        am.find_sections(text)


def test_find_sections_ignores_inline_marker() -> None:
    # Marker not on its own line should be ignored.
    text = "prefix <!-- BEGIN auto-managed: a:b --> suffix\n"
    assert am.find_sections(text) == []


# ---------------------------------------------------------------------------
# compute_expected — extractor dispatch
# ---------------------------------------------------------------------------


def test_compute_expected_taxonomy_runtime() -> None:
    out = am.compute_expected("specs/taxonomy:runtime", PLAYBOOK_ROOT)
    assert "Runtime entities" not in out  # heading stripped
    assert "| Agent |" in out
    assert "| Subagent |" in out
    assert out.strip() == out  # no surrounding blank lines


def test_compute_expected_taxonomy_config() -> None:
    out = am.compute_expected("specs/taxonomy:config", PLAYBOOK_ROOT)
    assert "| Skill |" in out
    assert "| Dispatcher |" in out


def test_compute_expected_verdict_levels() -> None:
    out = am.compute_expected("specs/verdict-contract:levels", PLAYBOOK_ROOT)
    assert "S1" in out
    assert "Correctness" in out


def test_compute_expected_generic_fallback() -> None:
    out = am.compute_expected("specs/taxonomy:Runtime entities", PLAYBOOK_ROOT)
    assert "| Agent |" in out


def test_compute_expected_universal_principles_hard_fails() -> None:
    with pytest.raises(ValueError, match="universal-principles"):
        am.compute_expected("specs/universal-principles", PLAYBOOK_ROOT)


def test_compute_expected_unknown_source_raises() -> None:
    with pytest.raises(ValueError, match="unknown source_spec"):
        am.compute_expected("bogus", PLAYBOOK_ROOT)


def test_compute_expected_missing_anchor_raises() -> None:
    with pytest.raises(LookupError):
        am.compute_expected("specs/taxonomy:nonexistent-anchor-xyz", PLAYBOOK_ROOT)


def test_compute_expected_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        am.compute_expected("specs/does-not-exist:foo", PLAYBOOK_ROOT)


# ---------------------------------------------------------------------------
# regenerate / apply_fix
# ---------------------------------------------------------------------------


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_regenerate_detects_stale(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "consumer.md",
        "header\n"
        "<!-- BEGIN auto-managed: specs/taxonomy:runtime -->\n"
        "stale placeholder\n"
        "<!-- END auto-managed -->\n"
        "footer\n",
    )
    diffs = am.regenerate(f, PLAYBOOK_ROOT)
    assert len(diffs) == 1
    d = diffs[0]
    assert d.changed
    assert "| Agent |" in d.after
    # regenerate must NOT touch the file on disk
    assert "stale placeholder" in f.read_text(encoding="utf-8")


def test_apply_fix_rewrites_in_place(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "consumer.md",
        "header\n"
        "<!-- BEGIN auto-managed: specs/taxonomy:runtime -->\n"
        "stale\n"
        "<!-- END auto-managed -->\n"
        "footer\n",
    )
    changed = am.apply_fix(f, PLAYBOOK_ROOT)
    assert len(changed) == 1
    new_text = f.read_text(encoding="utf-8")
    assert "stale" not in new_text
    assert "| Agent |" in new_text
    # Markers must be preserved verbatim.
    assert "<!-- BEGIN auto-managed: specs/taxonomy:runtime -->" in new_text
    assert "<!-- END auto-managed -->" in new_text
    # Surrounding prose must be preserved.
    assert new_text.startswith("header\n")
    assert new_text.rstrip().endswith("footer")


def test_apply_fix_idempotent(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "consumer.md",
        "<!-- BEGIN auto-managed: specs/taxonomy:runtime -->\n"
        "stale\n"
        "<!-- END auto-managed -->\n",
    )
    am.apply_fix(f, PLAYBOOK_ROOT)
    first = f.read_text(encoding="utf-8")
    # Second fix must be a no-op.
    changed = am.apply_fix(f, PLAYBOOK_ROOT)
    assert changed == []
    assert f.read_text(encoding="utf-8") == first


def test_apply_fix_preserves_trailing_newline(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "consumer.md",
        "<!-- BEGIN auto-managed: specs/taxonomy:runtime -->\n"
        "x\n"
        "<!-- END auto-managed -->\n",
    )
    am.apply_fix(f, PLAYBOOK_ROOT)
    assert f.read_text(encoding="utf-8").endswith("\n")


def test_apply_fix_multiple_sections(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "consumer.md",
        "top\n"
        "<!-- BEGIN auto-managed: specs/taxonomy:runtime -->\n"
        "a\n"
        "<!-- END auto-managed -->\n"
        "between\n"
        "<!-- BEGIN auto-managed: specs/verdict-contract:levels -->\n"
        "b\n"
        "<!-- END auto-managed -->\n"
        "bottom\n",
    )
    changed = am.apply_fix(f, PLAYBOOK_ROOT)
    assert len(changed) == 2
    text = f.read_text(encoding="utf-8")
    assert "| Agent |" in text
    assert "S1" in text
    assert "between" in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_check_reports_stale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = _write(
        tmp_path / "c.md",
        "<!-- BEGIN auto-managed: specs/taxonomy:runtime -->\n"
        "stale\n"
        "<!-- END auto-managed -->\n",
    )
    rc = am.main([str(f), "--playbook-root", str(PLAYBOOK_ROOT)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "stale" in err or "auto-managed" in err


def test_cli_fix_rewrites(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = _write(
        tmp_path / "c.md",
        "<!-- BEGIN auto-managed: specs/taxonomy:runtime -->\n"
        "stale\n"
        "<!-- END auto-managed -->\n",
    )
    rc = am.main(
        [str(f), "--fix", "--playbook-root", str(PLAYBOOK_ROOT)]
    )
    assert rc == 0
    assert "| Agent |" in f.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "Rewrote" in out


def test_cli_force_with_reason_bypasses_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = _write(
        tmp_path / "c.md",
        "<!-- BEGIN auto-managed: specs/taxonomy:runtime -->\n"
        "stale\n"
        "<!-- END auto-managed -->\n",
    )
    rc = am.main(
        [
            str(f),
            "--playbook-root", str(PLAYBOOK_ROOT),
            "--force-with-reason", "emergency release window is closing",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "OVERRIDE APPLIED" in out


def test_cli_missing_file_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = am.main(
        [str(tmp_path / "nope.md"), "--playbook-root", str(PLAYBOOK_ROOT)]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "file not found" in err
