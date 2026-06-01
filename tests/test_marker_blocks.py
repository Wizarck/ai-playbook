"""Tests for ``scripts._marker_blocks`` — parse + write per comment style."""
from __future__ import annotations

import pytest

from scripts._marker_blocks import (
    CommentStyle,
    MarkerBlock,
    parse_blocks,
    style_for_filename,
    write_blocks,
)

# ---------------------------------------------------------------------------
# Parse — HTML / markdown
# ---------------------------------------------------------------------------


def test_parse_html_single_block() -> None:
    text = (
        "Before custom text.\n"
        "<!-- ai-playbook:begin id=§4 sha=ab12 -->\n"
        "canonical §4 line one\n"
        "canonical §4 line two\n"
        "<!-- ai-playbook:end §4 -->\n"
        "After custom text.\n"
    )
    parsed = parse_blocks(text, CommentStyle.HTML)
    assert list(parsed.blocks.keys()) == ["§4"]
    block = parsed.blocks["§4"]
    assert block.content == "canonical §4 line one\ncanonical §4 line two"
    assert block.sha == "ab12"
    assert block.style is CommentStyle.HTML
    assert parsed.order == ["§4"]


def test_parse_html_multiple_blocks_in_order() -> None:
    text = (
        "<!-- ai-playbook:begin id=A -->\na-body\n<!-- ai-playbook:end A -->\n"
        "middle custom\n"
        "<!-- ai-playbook:begin id=B sha=ff -->\nb-body\n<!-- ai-playbook:end B -->\n"
    )
    parsed = parse_blocks(text, CommentStyle.HTML)
    assert parsed.order == ["A", "B"]
    assert parsed.blocks["A"].content == "a-body"
    assert parsed.blocks["A"].sha is None
    assert parsed.blocks["B"].sha == "ff"


def test_parse_html_no_blocks_keeps_custom_segments() -> None:
    text = "Just plain content with no markers at all.\n"
    parsed = parse_blocks(text, CommentStyle.HTML)
    assert parsed.blocks == {}
    assert parsed.custom_segments == [text]


# ---------------------------------------------------------------------------
# Parse — hash-comment (gitignore, yaml, shell)
# ---------------------------------------------------------------------------


def test_parse_hash_block_with_sha() -> None:
    text = (
        "# >>> ai-playbook:begin id=patterns sha=abcd >>>\n"
        ".ai-playbook/overrides.log\n"
        ".claude/injected-context.md\n"
        "# <<< ai-playbook:end patterns <<<\n"
    )
    parsed = parse_blocks(text, CommentStyle.HASH)
    assert "patterns" in parsed.blocks
    assert parsed.blocks["patterns"].sha == "abcd"
    assert ".ai-playbook/overrides.log" in parsed.blocks["patterns"].content


def test_parse_hash_block_no_sha() -> None:
    text = (
        "# >>> ai-playbook:begin id=hooks >>>\n"
        "  - id: trailing-whitespace\n"
        "# <<< ai-playbook:end hooks <<<\n"
    )
    parsed = parse_blocks(text, CommentStyle.HASH)
    assert parsed.blocks["hooks"].sha is None
    assert "trailing-whitespace" in parsed.blocks["hooks"].content


# ---------------------------------------------------------------------------
# Parse — JSON5 / slash-comment
# ---------------------------------------------------------------------------


def test_parse_slash_block() -> None:
    text = (
        "// ai-playbook:begin id=permissions sha=ee\n"
        '{"allow": []}\n'
        "// ai-playbook:end permissions\n"
    )
    parsed = parse_blocks(text, CommentStyle.SLASH)
    assert parsed.blocks["permissions"].sha == "ee"
    assert '{"allow": []}' in parsed.blocks["permissions"].content


# ---------------------------------------------------------------------------
# Parse — error cases
# ---------------------------------------------------------------------------


def test_parse_unmatched_begin_raises() -> None:
    text = "<!-- ai-playbook:begin id=A -->\nbody\n"
    with pytest.raises(ValueError, match="unmatched"):
        parse_blocks(text, CommentStyle.HTML)


def test_parse_mismatched_end_raises() -> None:
    text = (
        "<!-- ai-playbook:begin id=A -->\nbody\n"
        "<!-- ai-playbook:end B -->\n"
    )
    with pytest.raises(ValueError, match="marker mismatch"):
        parse_blocks(text, CommentStyle.HTML)


def test_parse_duplicate_id_raises() -> None:
    text = (
        "<!-- ai-playbook:begin id=A -->\nbody1\n<!-- ai-playbook:end A -->\n"
        "<!-- ai-playbook:begin id=A -->\nbody2\n<!-- ai-playbook:end A -->\n"
    )
    with pytest.raises(ValueError, match="duplicate marker block id"):
        parse_blocks(text, CommentStyle.HTML)


# ---------------------------------------------------------------------------
# Write — in-place replacement
# ---------------------------------------------------------------------------


def test_write_replaces_block_preserves_custom_text() -> None:
    current = (
        "My project notes.\n"
        "<!-- ai-playbook:begin id=§0 -->\n"
        "old canonical\n"
        "<!-- ai-playbook:end §0 -->\n"
        "Project gotchas list.\n"
    )
    desired = {
        "§0": MarkerBlock(
            id="§0", content="new canonical line 1\nnew canonical line 2",
            style=CommentStyle.HTML,
        ),
    }
    out = write_blocks(current, desired, style=CommentStyle.HTML)
    assert "My project notes.\n" in out
    assert "Project gotchas list.\n" in out
    assert "new canonical line 1" in out
    assert "new canonical line 2" in out
    assert "old canonical" not in out


def test_write_appends_missing_block_when_flag_true() -> None:
    current = "Initial custom content.\n"
    desired = {
        "newly-added": MarkerBlock(
            id="newly-added", content="freshly introduced",
            style=CommentStyle.HTML,
        ),
    }
    out = write_blocks(current, desired, style=CommentStyle.HTML, append_missing=True)
    assert "Initial custom content." in out
    assert "<!-- ai-playbook:begin id=newly-added -->" in out
    assert "freshly introduced" in out
    assert "<!-- ai-playbook:end newly-added -->" in out


def test_write_skips_missing_when_flag_false() -> None:
    current = "Just custom.\n"
    desired = {
        "skipped": MarkerBlock(id="skipped", content="x", style=CommentStyle.HTML),
    }
    out = write_blocks(current, desired, style=CommentStyle.HTML, append_missing=False)
    assert "skipped" not in out
    assert out == current


def test_write_leaves_existing_blocks_unchanged_when_not_in_desired() -> None:
    current = (
        "<!-- ai-playbook:begin id=A -->\noriginal A\n<!-- ai-playbook:end A -->\n"
        "<!-- ai-playbook:begin id=B -->\noriginal B\n<!-- ai-playbook:end B -->\n"
    )
    desired = {
        "A": MarkerBlock(id="A", content="updated A", style=CommentStyle.HTML),
    }
    out = write_blocks(current, desired, style=CommentStyle.HTML)
    assert "updated A" in out
    assert "original A" not in out
    assert "original B" in out  # B preserved untouched


def test_write_round_trip_preserves_structure() -> None:
    """A parse → write cycle with no changes should be idempotent."""
    current = (
        "head custom\n"
        "<!-- ai-playbook:begin id=§0 sha=ab -->\n"
        "canonical body\n"
        "<!-- ai-playbook:end §0 -->\n"
        "tail custom\n"
    )
    parsed = parse_blocks(current, CommentStyle.HTML)
    out = write_blocks(current, parsed.blocks, style=CommentStyle.HTML)
    assert out == current


# ---------------------------------------------------------------------------
# Hash + slash write tests
# ---------------------------------------------------------------------------


def test_write_hash_replaces_block() -> None:
    current = (
        "# Project custom patterns\n"
        "dist/\n"
        "# >>> ai-playbook:begin id=core >>>\n"
        ".ai-playbook/overrides.log\n"
        "# <<< ai-playbook:end core <<<\n"
        "logs/\n"
    )
    desired = {
        "core": MarkerBlock(
            id="core",
            content=".ai-playbook/overrides.log\n.claude/injected-context.md",
            style=CommentStyle.HASH,
        ),
    }
    out = write_blocks(current, desired, style=CommentStyle.HASH)
    assert "dist/" in out
    assert "logs/" in out
    assert ".claude/injected-context.md" in out


def test_write_slash_replaces_block() -> None:
    current = (
        "// some js-style comment\n"
        "// ai-playbook:begin id=cfg\n"
        '{"old": true}\n'
        "// ai-playbook:end cfg\n"
    )
    desired = {
        "cfg": MarkerBlock(id="cfg", content='{"new": true}', style=CommentStyle.SLASH),
    }
    out = write_blocks(current, desired, style=CommentStyle.SLASH)
    assert '{"new": true}' in out
    assert '{"old": true}' not in out


# ---------------------------------------------------------------------------
# Convenience: style_for_filename
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,expected", [
    ("AGENTS.md", CommentStyle.HTML),
    ("CLAUDE.md", CommentStyle.HTML),
    ("00-dispatcher.mdc", CommentStyle.HTML),
    ("settings.json", CommentStyle.SLASH),
    ("config.json5", CommentStyle.SLASH),
    (".gitignore", CommentStyle.HASH),
    ("pre-commit.yaml", CommentStyle.HASH),
    ("mcp-servers.yaml", CommentStyle.HASH),
    ("script.sh", CommentStyle.HASH),
    ("random.txt", CommentStyle.HASH),  # fallback
])
def test_style_for_filename(name: str, expected: CommentStyle) -> None:
    assert style_for_filename(name) is expected
