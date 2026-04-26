"""Tests for scripts/gen_indexes.py.

Pure FS + string logic — no mocks, everything runs against `tmp_path`.
"""
from __future__ import annotations

from pathlib import Path

from scripts import gen_indexes as gi


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_extract_status_blockquote_bold() -> None:
    text = "# foo\n\n> **Status**: v1.0.0. Populated in T07.\n\nbody\n"
    assert gi.extract_status(text) == "v1.0.0. Populated in T07."


def test_extract_status_missing_returns_dash() -> None:
    text = "# foo\n\nSome summary paragraph.\n"
    assert gi.extract_status(text) == "—"


def test_extract_status_skips_frontmatter() -> None:
    text = (
        "---\n"
        "schema: agents-md/v1\n"
        "> **Status**: not-a-real-status\n"
        "---\n"
        "# body\n\n> **Status**: v2.0.0\n"
    )
    assert gi.extract_status(text) == "v2.0.0"


def test_extract_summary_first_paragraph_line() -> None:
    text = "# Title\n\nThis is the first paragraph line.\n\nSecond.\n"
    assert gi.extract_summary(text) == "This is the first paragraph line."


def test_extract_summary_skips_status_and_headings() -> None:
    text = (
        "# heading\n\n"
        "> **Status**: v1.0.0\n\n"
        "## sub\n\n"
        "Real summary here.\n"
    )
    assert gi.extract_summary(text) == "Real summary here."


def test_extract_summary_truncates() -> None:
    body = "x" * 200
    text = f"# heading\n\n{body}\n"
    result = gi.extract_summary(text)
    assert len(result) == gi.SUMMARY_MAX_LEN
    assert result.endswith("…")


def test_extract_summary_dash_when_empty() -> None:
    assert gi.extract_summary("# only heading\n") == "—"


def test_extract_summary_ignores_code_fence() -> None:
    text = "# t\n\n```\nprint('nope')\n```\n\nReal summary.\n"
    assert gi.extract_summary(text) == "Real summary."


def test_render_index_shape_and_sort(tmp_path: Path) -> None:
    _write(tmp_path / "beta.md", "# Beta\n\n> **Status**: v0.2\n\nBeta summary.\n")
    _write(tmp_path / "alpha.md", "# Alpha\n\n> **Status**: v1.0\n\nAlpha summary.\n")
    out = gi.render_index(tmp_path)
    assert out.startswith(f"# {tmp_path.name} — index\n")
    assert gi.BANNER in out
    assert "| File | Status | Summary |" in out
    alpha_pos = out.index("[alpha.md]")
    beta_pos = out.index("[beta.md]")
    assert alpha_pos < beta_pos
    assert "v1.0" in out
    assert "Alpha summary." in out


def test_render_index_sub_directories_listed(tmp_path: Path) -> None:
    _write(tmp_path / "top.md", "# top\n\nRoot doc.\n")
    _write(tmp_path / "sub" / "inner.md", "# inner\n\nInner doc.\n")
    out = gi.render_index(tmp_path)
    assert "## Sub-directories" in out
    assert "[sub/](sub/INDEX.md)" in out


def test_render_index_empty_folder(tmp_path: Path) -> None:
    out = gi.render_index(tmp_path)
    assert f"# {tmp_path.name} — index" in out
    assert "No markdown files" in out


def test_write_creates_index_and_is_idempotent(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "# a\n\n> **Status**: v1\n\nAye.\n")
    changed, missing = gi.write_index(tmp_path, check=False)
    assert missing is True
    assert changed is True
    # Second run: no diff
    changed2, missing2 = gi.write_index(tmp_path, check=False)
    assert missing2 is False
    assert changed2 is False


def test_check_mode_reports_stale(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "# a\n\nAye.\n")
    (tmp_path / "INDEX.md").write_text("stale content\n", encoding="utf-8")
    changed, missing = gi.write_index(tmp_path, check=True)
    assert changed is True
    assert missing is False
    # File on disk is untouched
    assert (tmp_path / "INDEX.md").read_text(encoding="utf-8") == "stale content\n"


def test_no_index_written_for_empty_folder_via_cli(tmp_path: Path) -> None:
    # Empty tree — should NOT write an INDEX.md because there's no md and no subdirs
    rc = gi.main(["--root", str(tmp_path)])
    assert rc == 0
    assert not (tmp_path / "INDEX.md").exists()


def test_main_respects_root_arg(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "# a\n\nSummary here.\n")
    rc = gi.main(["--root", str(tmp_path)])
    assert rc == 0
    idx = tmp_path / "INDEX.md"
    assert idx.is_file()
    assert "[a.md](a.md)" in idx.read_text(encoding="utf-8")


def test_main_check_exits_1_when_stale(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "# a\n\nbody.\n")
    rc = gi.main(["--root", str(tmp_path), "--check"])
    assert rc == 1  # missing INDEX.md


def test_main_check_passes_after_generation(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "# a\n\nbody.\n")
    assert gi.main(["--root", str(tmp_path)]) == 0
    assert gi.main(["--root", str(tmp_path), "--check"]) == 0


def test_main_invalid_root(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent"
    rc = gi.main(["--root", str(missing)])
    assert rc == 2


def test_ignore_dirs_not_indexed(tmp_path: Path) -> None:
    _write(tmp_path / "top.md", "# t\n\nbody.\n")
    _write(tmp_path / ".git" / "junk.md", "# skip me\n\nnope.\n")
    _write(tmp_path / "__pycache__" / "x.md", "# skip\n\nnope.\n")
    rc = gi.main(["--root", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "INDEX.md").exists()
    assert not (tmp_path / ".git" / "INDEX.md").exists()
    assert not (tmp_path / "__pycache__" / "INDEX.md").exists()


def test_cell_escapes_pipes(tmp_path: Path) -> None:
    _write(tmp_path / "p.md", "# p\n\nA | B summary.\n")
    out = gi.render_index(tmp_path)
    # The pipe from the summary must be escaped so it doesn't split the row
    assert "A \\| B summary." in out


def test_curated_homepage_skips_index(tmp_path: Path) -> None:
    # A directory that already owns a curated `index.md` homepage must NOT get an auto INDEX.md.
    _write(tmp_path / "index.md", "# Curated homepage\n\nHand-written.\n")
    _write(tmp_path / "a.md", "# a\n\nalpha.\n")
    rc = gi.main(["--root", str(tmp_path)])
    assert rc == 0
    # On Windows + macOS (case-insensitive), index.md IS INDEX.md, so the homepage must survive untouched.
    assert (tmp_path / "index.md").read_text(encoding="utf-8").startswith("# Curated homepage")
    # --check should also be happy (no missing, no stale).
    assert gi.main(["--root", str(tmp_path), "--check"]) == 0


def test_nested_tree_writes_index_per_folder(tmp_path: Path) -> None:
    _write(tmp_path / "root.md", "# root\n\nroot doc.\n")
    _write(tmp_path / "child" / "kid.md", "# kid\n\nkid doc.\n")
    rc = gi.main(["--root", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "INDEX.md").is_file()
    assert (tmp_path / "child" / "INDEX.md").is_file()
    # Second run is idempotent
    assert gi.main(["--root", str(tmp_path), "--check"]) == 0
