"""Fixture cases for scripts/check_doc_language.py (D6)."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import check_doc_language as cdl


def test_pure_english_passes_heuristic() -> None:
    text = "# Hello\n\nThis is plain English prose.\n"
    p = Path("ignored")
    # Avoid disk I/O.
    ok = cdl._is_english_heuristic(cdl._strip_code_and_frontmatter(text))
    assert ok is True


def test_spanish_diacritics_caught_by_heuristic() -> None:
    text = "Esta línea contiene caracteres en español como áéíóú."
    ok = cdl._is_english_heuristic(text)
    assert ok is False


def test_spanish_question_mark_caught() -> None:
    text = "¿Cómo está?"
    ok = cdl._is_english_heuristic(text)
    assert ok is False


def test_code_blocks_stripped() -> None:
    text = "Normal prose.\n\n```python\nimport ñoñoño  # this is in a code block\n```\n\nMore prose.\n"
    stripped = cdl._strip_code_and_frontmatter(text)
    assert "ñoñoño" not in stripped
    assert "Normal prose" in stripped


def test_frontmatter_stripped() -> None:
    text = "---\nslug: fooño\n---\n# body\nclean prose\n"
    stripped = cdl._strip_code_and_frontmatter(text)
    assert "fooño" not in stripped


def test_inline_code_stripped() -> None:
    text = "Normal prose with `inline_código()` inside.\n"
    stripped = cdl._strip_code_and_frontmatter(text)
    assert "código" not in stripped
    assert "Normal prose" in stripped


def test_link_text_kept_but_url_stripped() -> None:
    text = "See [the docs](http://example.com/españa).\n"
    stripped = cdl._strip_code_and_frontmatter(text)
    assert "the docs" in stripped
    assert "españa" not in stripped


def test_empty_prose_is_clean() -> None:
    ok = cdl._is_english_heuristic("")
    assert ok is True


def test_check_file_returns_tuple(tmp_path: Path) -> None:
    p = tmp_path / "x.md"
    p.write_text("# Pure english.\n", encoding="utf-8")
    ok, reason = cdl.check_file(p)
    assert ok is True
    assert isinstance(reason, str)


def test_check_file_spanish_fails(tmp_path: Path) -> None:
    p = tmp_path / "x.md"
    p.write_text("# Página de configuración\n\nEsto está en español con muchísimo acento.\n", encoding="utf-8")
    ok, _ = cdl.check_file(p)
    assert ok is False


def test_walk_includes_md_only(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("not md\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.md").write_text("# c\n", encoding="utf-8")
    files = cdl.walk([tmp_path])
    names = sorted(f.name for f in files)
    assert names == ["a.md", "c.md"]


def test_main_passes_below_threshold(tmp_path: Path) -> None:
    (tmp_path / "good1.md").write_text("# English doc 1\n\nPure English.\n", encoding="utf-8")
    (tmp_path / "good2.md").write_text("# English doc 2\n\nAlso pure English.\n", encoding="utf-8")
    code = cdl.main([str(tmp_path), "--quiet"])
    assert code == 0


def test_main_fails_above_threshold(tmp_path: Path) -> None:
    (tmp_path / "bad1.md").write_text("# Página con áccentos\n\nEsto está en español.\n", encoding="utf-8")
    code = cdl.main([str(tmp_path), "--quiet", "--threshold-percent", "0"])
    assert code == 2


def test_main_threshold_5_percent_lets_one_through(tmp_path: Path) -> None:
    # 1 bad in 50 files = 2% < 5% threshold.
    for i in range(49):
        (tmp_path / f"good{i}.md").write_text(f"# doc {i}\npure english.\n", encoding="utf-8")
    (tmp_path / "bad.md").write_text("# Página con español áéíóú.\n", encoding="utf-8")
    code = cdl.main([str(tmp_path), "--quiet"])
    assert code == 0
