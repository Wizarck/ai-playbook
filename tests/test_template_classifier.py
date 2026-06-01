"""Tests for ``scripts._template_classifier`` — canonical/drifted/custom."""
from __future__ import annotations

from scripts._marker_blocks import CommentStyle
from scripts._template_classifier import (
    ORIGIN_CANONICAL,
    ORIGIN_CUSTOM,
    ORIGIN_DRIFTED,
    build_manifest,
    classify,
    compute_sha,
)

# ---------------------------------------------------------------------------
# compute_sha
# ---------------------------------------------------------------------------


def test_compute_sha_deterministic() -> None:
    assert compute_sha("hello world") == compute_sha("hello world")


def test_compute_sha_length() -> None:
    assert len(compute_sha("any content")) == 12


def test_compute_sha_differs_with_content() -> None:
    assert compute_sha("a") != compute_sha("b")


# ---------------------------------------------------------------------------
# build_manifest
# ---------------------------------------------------------------------------


def test_build_manifest_maps_each_block() -> None:
    canonical = {"section-a": "alpha content", "section-b": "beta content"}
    manifest = build_manifest(canonical)
    assert set(manifest.keys()) == {"section-a", "section-b"}
    assert manifest["section-a"] == compute_sha("alpha content")
    assert manifest["section-b"] == compute_sha("beta content")


# ---------------------------------------------------------------------------
# classify — canonical (SHA matches expected)
# ---------------------------------------------------------------------------


def test_classify_canonical_block() -> None:
    canonical_content = "this is the canonical bootstrap directive"
    expected = build_manifest({"bootstrap-directive": canonical_content})
    text = (
        f"<!-- ai-playbook:begin id=bootstrap-directive sha={expected['bootstrap-directive']} -->\n"
        f"{canonical_content}\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n"
    )
    fc = classify(text, CommentStyle.HTML, expected, rel_path="AGENTS.md")
    assert fc.canonical_count == 1
    assert fc.drifted_count == 0
    block_sections = [s for s in fc.sections if s.id == "bootstrap-directive"]
    assert len(block_sections) == 1
    assert block_sections[0].origin == ORIGIN_CANONICAL


def test_classify_drifted_when_content_changed() -> None:
    original = "canonical line"
    expected = build_manifest({"section-x": original})
    text = (
        f"<!-- ai-playbook:begin id=section-x sha={expected['section-x']} -->\n"
        "user-edited content that no longer matches\n"
        "<!-- ai-playbook:end section-x -->\n"
    )
    fc = classify(text, CommentStyle.HTML, expected)
    assert fc.canonical_count == 0
    assert fc.drifted_count == 1
    section = next(s for s in fc.sections if s.id == "section-x")
    assert section.origin == ORIGIN_DRIFTED
    assert section.expected_sha == expected["section-x"]
    assert section.actual_sha != section.expected_sha


def test_classify_orphan_block_when_id_missing_from_manifest() -> None:
    """Block present in file but not in current manifest (consumer upgraded playbook)."""
    text = (
        "<!-- ai-playbook:begin id=removed-in-newer-playbook -->\n"
        "stuff\n"
        "<!-- ai-playbook:end removed-in-newer-playbook -->\n"
    )
    fc = classify(text, CommentStyle.HTML, expected_shas={})
    # Orphan classifies as drifted (it's surface-area the consumer needs to review).
    assert fc.drifted_count == 1
    assert fc.orphan_block_ids == ["removed-in-newer-playbook"]


# ---------------------------------------------------------------------------
# classify — custom segments
# ---------------------------------------------------------------------------


def test_classify_custom_text_outside_blocks() -> None:
    canonical = "playbook canonical"
    expected = build_manifest({"playbook-section": canonical})
    text = (
        "## My project notes\n"
        "Some custom content here.\n\n"
        f"<!-- ai-playbook:begin id=playbook-section sha={expected['playbook-section']} -->\n"
        f"{canonical}\n"
        "<!-- ai-playbook:end playbook-section -->\n"
        "More custom content after.\n"
    )
    fc = classify(text, CommentStyle.HTML, expected)
    assert fc.canonical_count == 1
    assert fc.drifted_count == 0
    assert fc.custom_count == 2  # before + after
    custom_sections = [s for s in fc.sections if s.origin == ORIGIN_CUSTOM]
    assert "My project notes" in custom_sections[0].content
    assert "More custom content after" in custom_sections[1].content


def test_classify_pure_custom_file_no_blocks() -> None:
    text = "Just consumer content.\nNo markers at all.\n"
    fc = classify(text, CommentStyle.HTML, expected_shas={})
    assert fc.canonical_count == 0
    assert fc.drifted_count == 0
    assert fc.custom_count == 1


# ---------------------------------------------------------------------------
# classify — full AGENTS.md-style example
# ---------------------------------------------------------------------------


def test_classify_full_agents_md_mix() -> None:
    bootstrap_canonical = "1. Read playbook specs.\n2. Check active work.\n3. Then respond."
    capability_canonical = "| Need | Tool |\n|---|---|\n| Recall | retain_memory.py |"
    expected = build_manifest({
        "bootstrap-directive": bootstrap_canonical,
        "capability-map": capability_canonical,
    })
    text = (
        "# myproject — AGENTS.md\n\n"
        "## §0 Bootstrap directive\n"
        f"<!-- ai-playbook:begin id=bootstrap-directive sha={expected['bootstrap-directive']} -->\n"
        f"{bootstrap_canonical}\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n\n"
        "## §1 Project identity\n"
        "We build a markdown-driven dispatcher framework for AI agents.\n\n"
        "## §5 Capability map\n"
        f"<!-- ai-playbook:begin id=capability-map sha={expected['capability-map']} -->\n"
        # Drifted content — does not match expected:
        "| Need | Tool |\n|---|---|\n| Recall | OUR_OWN_SCRIPT.py |\n"
        "<!-- ai-playbook:end capability-map -->\n\n"
        "## §8 Gotchas\n"
        "- 2026-04-15 — Windows CRLF in templates ate our config. Pin newline=\"\\n\".\n"
    )
    fc = classify(text, CommentStyle.HTML, expected, rel_path="AGENTS.md")
    assert fc.canonical_count == 1
    assert fc.drifted_count == 1
    assert fc.custom_count >= 1
    assert fc.rel_path == "AGENTS.md"

    by_id = {s.id: s for s in fc.sections if s.id}
    assert by_id["bootstrap-directive"].origin == ORIGIN_CANONICAL
    assert by_id["capability-map"].origin == ORIGIN_DRIFTED
    assert by_id["capability-map"].actual_sha != by_id["capability-map"].expected_sha


# ---------------------------------------------------------------------------
# classify — hash-style files
# ---------------------------------------------------------------------------


def test_classify_gitignore_style_hash_markers() -> None:
    canonical = ".ai-playbook/overrides.log\n.claude/injected-context.md"
    expected = build_manifest({"playbook-patterns": canonical})
    text = (
        "node_modules/\n"
        "dist/\n\n"
        f"# >>> ai-playbook:begin id=playbook-patterns sha={expected['playbook-patterns']} >>>\n"
        f"{canonical}\n"
        "# <<< ai-playbook:end playbook-patterns <<<\n"
        "\n"
        "# my project-specific patterns\n"
        "*.local.env\n"
    )
    fc = classify(text, CommentStyle.HASH, expected, rel_path=".gitignore")
    assert fc.canonical_count == 1
    assert fc.drifted_count == 0
    assert fc.custom_count >= 1  # consumer's node_modules/dist + tail comment block


# ---------------------------------------------------------------------------
# Edge: block with no SHA in marker
# ---------------------------------------------------------------------------


def test_classify_marker_without_sha_attribute() -> None:
    """A marker lacking the sha= attribute is still classified by content SHA
    against the manifest — the marker's sha is record-keeping, not the source
    of truth."""
    canonical = "expected content"
    expected = build_manifest({"section": canonical})
    text_no_sha = (
        "<!-- ai-playbook:begin id=section -->\n"
        f"{canonical}\n"
        "<!-- ai-playbook:end section -->\n"
    )
    fc = classify(text_no_sha, CommentStyle.HTML, expected)
    # Content matches manifest → canonical despite missing sha attribute.
    assert fc.canonical_count == 1
    assert fc.drifted_count == 0
