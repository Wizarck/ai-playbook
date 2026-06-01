"""Render ``AGENTS.md`` from template + bundle.

The template's structure (headers, marker positions, section ordering) is
authoritative. The renderer:

1. Substitutes ``{{PLACEHOLDER}}`` tokens (PROJECT_NAME, OWNER_EMAIL, TODAY,
   PLAYBOOK_PIN, PROJECT_BANK).
2. Substitutes the free-form consumer-content placeholders
   ({{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}, etc.) with values from
   ``bundle.project_meta`` when present; otherwise leaves them as
   sentinel TODO lines for the operator to fill in.
3. Honours per-block curate intents from
   ``bundle.file_curate_intents["AGENTS.md"]`` — blocks marked
   ``keep_mine`` are overridden with content from ``current_text`` (the
   file as-is on disk).
4. Computes SHA-256[:12] of each marker block's content and injects
   ``sha=<hex>`` into the begin marker so downstream tooling can detect
   drift without consulting the bundle manifest.
"""
from __future__ import annotations

from scripts._marker_blocks import (
    CommentStyle,
    MarkerBlock,
    parse_blocks,
    write_blocks,
)
from scripts._template_classifier import compute_sha

_PROJECT_META_TO_PLACEHOLDER = {
    "project_identity": "{{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}",
    "active_work": "{{ACTIVE_OPENSPEC_CHANGE_OR_NONE}}",
    "hard_rules": "{{PROJECT_SPECIFIC_RULES_NOT_DUPLICATING_PLAYBOOK}}",
    "inherited_overrides": "{{NONE_OR_EXPLICIT_OVERRIDES_WITH_RATIONALE}}",
    "gotchas": "{{EMPTY_FILL_AS_YOU_LEARN}}",
}

_DEFAULT_TODO_TEXT = {
    "project_identity": "TODO: 1-3 lines describing what this project does.",
    "active_work": "TODO: link to the active OpenSpec change, or write 'none'.",
    "hard_rules": "TODO: list project-specific hard rules that don't duplicate the playbook.",
    "inherited_overrides": "none",
    "gotchas": "(none yet — add dated entries here as you discover them)",
}


def _apply_substitutions(template: str, substitutions: dict[str, str]) -> str:
    out = template
    for key, value in substitutions.items():
        if value is None:
            continue
        out = out.replace("{{" + key + "}}", str(value))
    return out


def _apply_project_meta(text: str, project_meta: dict | None) -> str:
    project_meta = project_meta or {}
    for meta_key, placeholder in _PROJECT_META_TO_PLACEHOLDER.items():
        value = project_meta.get(meta_key)
        if not isinstance(value, str) or not value.strip():
            value = _DEFAULT_TODO_TEXT.get(meta_key, "")
        text = text.replace(placeholder, value)
    return text


def _resolve_block_action(
    block_id: str, intents: dict | None,
) -> str:
    if not intents:
        return "take_playbook"
    blocks = intents.get("blocks") or {}
    explicit = blocks.get(block_id)
    if explicit in ("take_playbook", "keep_mine"):
        return explicit
    default = intents.get("default_action")
    if default in ("take_playbook", "keep_mine"):
        return default
    return "take_playbook"


def _apply_curate_intents(
    text: str,
    current_text: str | None,
    intents: dict | None,
) -> str:
    """Override blocks marked ``keep_mine`` with content from ``current_text``."""
    if not intents or not current_text:
        return text
    try:
        current_parsed = parse_blocks(current_text, CommentStyle.HTML)
    except ValueError:
        return text
    try:
        rendered_parsed = parse_blocks(text, CommentStyle.HTML)
    except ValueError:
        return text

    overrides: dict[str, MarkerBlock] = {}
    for block_id, _block in rendered_parsed.blocks.items():
        action = _resolve_block_action(block_id, intents)
        if action != "keep_mine":
            continue
        current_block = current_parsed.blocks.get(block_id)
        if current_block is None:
            # The consumer's file lacks this block — fall back to playbook default.
            continue
        overrides[block_id] = MarkerBlock(
            id=block_id,
            content=current_block.content,
            sha=None,  # will be set by _inject_sha_into_markers below
            style=CommentStyle.HTML,
        )

    if not overrides:
        return text
    return write_blocks(text, overrides, style=CommentStyle.HTML)


def _inject_sha_into_markers(text: str) -> str:
    parsed = parse_blocks(text, CommentStyle.HTML)
    if not parsed.blocks:
        return text
    desired = {
        bid: MarkerBlock(
            id=bid, content=block.content, sha=compute_sha(block.content),
            style=CommentStyle.HTML,
        )
        for bid, block in parsed.blocks.items()
    }
    return write_blocks(text, desired, style=CommentStyle.HTML)


def render(
    *,
    template: str,
    substitutions: dict[str, str],
    bundle: dict,
    current_text: str | None = None,
) -> str:
    """Return the final AGENTS.md content.

    ``current_text`` is the consumer's existing AGENTS.md content (if any).
    When ``bundle.file_curate_intents["AGENTS.md"]`` marks blocks as
    ``keep_mine``, those blocks are taken from ``current_text`` instead of
    the template. Without curate intents, ``current_text`` is unused.
    """
    body = _apply_substitutions(template, substitutions)
    body = _apply_project_meta(body, bundle.get("project_meta"))
    intents = (bundle.get("file_curate_intents") or {}).get("AGENTS.md")
    body = _apply_curate_intents(body, current_text, intents)
    body = _inject_sha_into_markers(body)
    return body


__all__ = ["render"]
