"""Wrap-not-rewrite legacy adoption primitive.

When the playbook first adopts a repo that already has an ``AGENTS.md`` /
``CLAUDE.md`` written WITHOUT ai-playbook markers, we must NOT rewrite it from
the template (that would destroy the consumer's legacy prose). Instead we
*wrap*: append the template's canonical marker blocks that are missing, leaving
every existing line — prose and any already-present blocks — byte-for-byte
intact. The consumer's content lands as ``custom_segment`` data that later
re-renders preserve, and the curate flow can subsequently consolidate.

This closes the ``_apply_curate_intents`` gap (``agents_md.py``): ``keep_mine``
can only preserve a block that already exists, so a legacy file with no markers
needs the canonical blocks seeded first. ``seed_markers`` is that seeding step.

Pure / stdlib-only.
"""
from __future__ import annotations

from scripts._marker_blocks import CommentStyle, MarkerBlock, parse_blocks, write_blocks
from scripts._template_classifier import compute_sha


def seed_markers(
    current_text: str,
    template: str,
    *,
    style: CommentStyle = CommentStyle.HTML,
) -> str:
    """Additively inject the template's canonical marker blocks into ``current_text``.

    Only blocks ABSENT from ``current_text`` are appended (with a freshly-sealed
    ``sha=``). Blocks already present are left untouched — their content is the
    consumer's and must not be overwritten by adoption. All non-block prose is
    preserved verbatim. Returns ``current_text`` unchanged when nothing is
    missing (idempotent: a second adoption pass is a no-op).
    """
    try:
        current_parsed = parse_blocks(current_text, style)
    except ValueError:
        # Consumer file has malformed markers — do not attempt to seed; the
        # conflict/validate layers surface it rather than risk corrupting it.
        return current_text
    try:
        template_parsed = parse_blocks(template, style)
    except ValueError:
        return current_text

    existing_ids = set(current_parsed.order)
    missing: dict[str, MarkerBlock] = {
        bid: MarkerBlock(
            id=bid, content=blk.content, sha=compute_sha(blk.content), style=style,
        )
        for bid, blk in template_parsed.blocks.items()
        if bid not in existing_ids
    }
    if not missing:
        return current_text

    return write_blocks(current_text, missing, style=style, append_missing=True)


def missing_block_ids(
    current_text: str,
    template: str,
    *,
    style: CommentStyle = CommentStyle.HTML,
) -> list[str]:
    """Canonical block ids the template defines but the consumer file lacks.

    Drives the adoption report ("N canonical blocks will be seeded") without
    mutating anything. Tolerant: returns the full template id list when the
    consumer file has malformed markers (treat as "nothing seeded yet")."""
    try:
        template_parsed = parse_blocks(template, style)
    except ValueError:
        return []
    try:
        current_parsed = parse_blocks(current_text, style)
    except ValueError:
        return list(template_parsed.order)
    existing = set(current_parsed.order)
    return [bid for bid in template_parsed.order if bid not in existing]


__all__ = ["missing_block_ids", "seed_markers"]
