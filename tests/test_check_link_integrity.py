"""Fixture cases for scripts/check_link_integrity.py."""
from __future__ import annotations

from pathlib import Path

from scripts import check_link_integrity as cli


def test_external_links_skipped() -> None:
    assert cli.is_external("https://example.com")
    assert cli.is_external("http://example.com")
    assert cli.is_external("mailto:foo@bar.com")
    assert not cli.is_external("/local/path")
    assert not cli.is_external("relative.md")
    assert not cli.is_external("../parent.md")


def test_normalize_strips_anchor() -> None:
    assert cli.normalize_target("foo.md#section") == "foo.md"
    assert cli.normalize_target("foo.md?q=1") == "foo.md"
    assert cli.normalize_target("#in-document") == ""
    assert cli.normalize_target("") == ""


def test_clean_file_passes(tmp_path: Path) -> None:
    target = tmp_path / "target.md"
    target.write_text("# target", encoding="utf-8")
    source = tmp_path / "src.md"
    source.write_text("See [target](target.md).\n", encoding="utf-8")
    dead = cli.find_dead_links([source], tmp_path)
    assert dead == []


def test_dead_link_detected(tmp_path: Path) -> None:
    source = tmp_path / "src.md"
    source.write_text("See [missing](does-not-exist.md).\n", encoding="utf-8")
    dead = cli.find_dead_links([source], tmp_path)
    assert len(dead) == 1
    assert dead[0][2] == "does-not-exist.md"


def test_anchor_link_skipped(tmp_path: Path) -> None:
    source = tmp_path / "src.md"
    source.write_text("Jump to [section](#section).\n", encoding="utf-8")
    dead = cli.find_dead_links([source], tmp_path)
    assert dead == []


def test_external_url_skipped(tmp_path: Path) -> None:
    source = tmp_path / "src.md"
    source.write_text("See [docs](https://example.com/x).\n", encoding="utf-8")
    dead = cli.find_dead_links([source], tmp_path)
    assert dead == []


def test_image_syntax_not_treated_as_link(tmp_path: Path) -> None:
    source = tmp_path / "src.md"
    source.write_text("![alt](missing.png)\n", encoding="utf-8")
    dead = cli.find_dead_links([source], tmp_path)
    assert dead == []


def test_relative_parent_path_resolves(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    (tmp_path / "target.md").write_text("# target", encoding="utf-8")
    source = sub / "src.md"
    source.write_text("[up](../target.md)\n", encoding="utf-8")
    dead = cli.find_dead_links([source], tmp_path)
    assert dead == []


def test_anchor_attached_to_valid_target(tmp_path: Path) -> None:
    target = tmp_path / "target.md"
    target.write_text("# target", encoding="utf-8")
    source = tmp_path / "src.md"
    source.write_text("[t](target.md#section)\n", encoding="utf-8")
    dead = cli.find_dead_links([source], tmp_path)
    assert dead == []


def test_walk_recurses(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# a", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.md").write_text("# b", encoding="utf-8")
    files = cli.walk([tmp_path])
    assert sorted(f.name for f in files) == ["a.md", "b.md"]


def test_main_exits_zero_on_clean(tmp_path: Path) -> None:
    (tmp_path / "target.md").write_text("# t", encoding="utf-8")
    (tmp_path / "src.md").write_text("[t](target.md)\n", encoding="utf-8")
    code = cli.main([str(tmp_path), "--quiet"])
    assert code == 0


def test_main_exits_two_on_dead_default_strict(tmp_path: Path) -> None:
    """Default mode is strict since Slice 5.F (v0.18.1)."""
    (tmp_path / "src.md").write_text("[dead](missing.md)\n", encoding="utf-8")
    code = cli.main([str(tmp_path), "--quiet"])
    assert code == 2


def test_main_exits_two_on_dead_strict_flag_kept_for_compat(tmp_path: Path) -> None:
    """`--strict` flag is now a no-op (default is strict) but still accepted."""
    (tmp_path / "src.md").write_text("[dead](missing.md)\n", encoding="utf-8")
    code = cli.main([str(tmp_path), "--quiet", "--strict"])
    assert code == 2


def test_main_exits_zero_on_dead_warn_only(tmp_path: Path) -> None:
    """`--warn-only` is the legacy lenient mode; exits 0 on dead links."""
    (tmp_path / "src.md").write_text("[dead](missing.md)\n", encoding="utf-8")
    code = cli.main([str(tmp_path), "--quiet", "--warn-only"])
    assert code == 0


def test_line_number_reported(tmp_path: Path) -> None:
    source = tmp_path / "src.md"
    source.write_text("line 1\nline 2\n[dead](nope.md)\n", encoding="utf-8")
    dead = cli.find_dead_links([source], tmp_path)
    assert dead[0][1] == 3


def test_fenced_code_block_links_skipped(tmp_path: Path) -> None:
    """Links inside ``` fences are markdown examples, not real cross-refs."""
    source = tmp_path / "src.md"
    source.write_text(
        "Real link below.\n\n"
        "```markdown\n"
        "[#NN](...)\n"
        "[example](missing-target.md)\n"
        "```\n",
        encoding="utf-8",
    )
    dead = cli.find_dead_links([source], tmp_path)
    assert dead == []


def test_inline_code_links_skipped(tmp_path: Path) -> None:
    """Backtick-quoted `[label](path)` is documentation prose, not a real link."""
    source = tmp_path / "src.md"
    source.write_text(
        "Reference the link syntax as `[label](path.md)` in your doc.\n",
        encoding="utf-8",
    )
    dead = cli.find_dead_links([source], tmp_path)
    assert dead == []
