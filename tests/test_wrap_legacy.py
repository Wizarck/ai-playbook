"""Tests for ``scripts._renderers._wrap_legacy`` — wrap-not-rewrite adoption."""
from __future__ import annotations

from scripts._marker_blocks import CommentStyle, parse_blocks
from scripts._renderers._wrap_legacy import missing_block_ids, seed_markers
from scripts._template_classifier import compute_sha

_TEMPLATE = (
    "# {{PROJECT_NAME}}\n\n"
    "<!-- ai-playbook:begin id=bootstrap-directive -->\n"
    "Canonical bootstrap.\n"
    "<!-- ai-playbook:end bootstrap-directive -->\n\n"
    "<!-- ai-playbook:begin id=hard-rules -->\n"
    "Canonical hard rules.\n"
    "<!-- ai-playbook:end hard-rules -->\n"
)


def test_seed_into_legacy_file_preserves_prose_and_appends_blocks() -> None:
    legacy = (
        "# My Project\n\n"
        "We have a lot of bespoke prose here that predates the playbook.\n"
        "It must survive adoption verbatim.\n"
    )
    out = seed_markers(legacy, _TEMPLATE, style=CommentStyle.HTML)
    # Legacy prose preserved verbatim.
    assert "bespoke prose here that predates the playbook." in out
    assert "It must survive adoption verbatim." in out
    # Canonical blocks appended + sealed.
    parsed = parse_blocks(out, CommentStyle.HTML)
    assert set(parsed.blocks) == {"bootstrap-directive", "hard-rules"}
    for blk in parsed.blocks.values():
        assert blk.sha == compute_sha(blk.content)


def test_seed_does_not_overwrite_existing_block() -> None:
    current = (
        "# My Project\n\n"
        "<!-- ai-playbook:begin id=bootstrap-directive sha=abc123abc123 -->\n"
        "MY edited bootstrap\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n"
    )
    out = seed_markers(current, _TEMPLATE, style=CommentStyle.HTML)
    parsed = parse_blocks(out, CommentStyle.HTML)
    # Existing block kept as the consumer's; the missing one seeded.
    assert parsed.blocks["bootstrap-directive"].content == "MY edited bootstrap"
    assert "hard-rules" in parsed.blocks


def test_seed_is_idempotent_when_all_blocks_present() -> None:
    once = seed_markers("# P\n\nprose\n", _TEMPLATE, style=CommentStyle.HTML)
    twice = seed_markers(once, _TEMPLATE, style=CommentStyle.HTML)
    assert once == twice  # second adoption pass is a no-op


def test_missing_block_ids() -> None:
    assert missing_block_ids("# P\n", _TEMPLATE) == ["bootstrap-directive", "hard-rules"]
    seeded = seed_markers("# P\n", _TEMPLATE)
    assert missing_block_ids(seeded, _TEMPLATE) == []


def test_seed_tolerates_malformed_current_markers() -> None:
    bad = "<!-- ai-playbook:begin id=x -->\nno end marker\n"
    # Malformed ⇒ returned unchanged (never corrupt further).
    assert seed_markers(bad, _TEMPLATE, style=CommentStyle.HTML) == bad
