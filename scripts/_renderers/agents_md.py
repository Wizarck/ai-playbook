"""Render ``AGENTS.md`` from template + bundle.

For a new (or markerless) file the template's structure (headers, marker
positions, section ordering) is authoritative. For a file that already carries
marker blocks, only the blocks are refreshed; everything outside them is kept
verbatim (see ``render``). The renderer:

1. Substitutes ``{{PLACEHOLDER}}`` tokens (PROJECT_NAME, OWNER_EMAIL, TODAY,
   PLAYBOOK_PIN, PROJECT_BANK).
2. Substitutes the free-form consumer-content placeholders
   ({{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}, etc.) with values from
   ``bundle.project_meta`` when present; otherwise leaves them as
   sentinel TODO lines for the operator to fill in. A value that itself
   still contains a slot placeholder (a section read back with its
   placeholder unfilled) is not substituted into the consumer's file;
   rendered from the template, it replaces the whole slot (placeholder
   and template text after it), so the section comes back as it was read.
3. Honours per-block curate intents from
   ``bundle.file_curate_intents["AGENTS.md"]`` — blocks marked
   ``keep_mine`` are overridden with content from ``current_text`` (the
   file as-is on disk).
4. Computes SHA-256[:12] of each marker block's content and injects
   ``sha=<hex>`` into the begin marker so downstream tooling can detect
   drift without consulting the bundle manifest.
"""
from __future__ import annotations

import re

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

# A template slot runs from its placeholder to the next section header or
# canonical block.
_SLOT_END_RE = re.compile(r"^(?:## |<!-- ai-playbook:begin )", re.MULTILINE)

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


def _apply_project_meta(text: str, project_meta: dict | None, *, splice: bool) -> str:
    project_meta = project_meta or {}
    for meta_key, placeholder in _PROJECT_META_TO_PLACEHOLDER.items():
        value = project_meta.get(meta_key)
        if not isinstance(value, str) or not value.strip():
            value = _DEFAULT_TODO_TEXT.get(meta_key, "")
        elif any(ph in value for ph in _PROJECT_META_TO_PLACEHOLDER.values()):
            # A section read back by extract_project_meta: its placeholder, the
            # template tail after it and anything the consumer added, verbatim.
            # Substituting it for the placeholder repeats the tail (in the
            # consumer's own file, on every render). The consumer's file keeps
            # the slot as it is; the template takes the value as the whole slot.
            start = text.find(placeholder)
            if not splice and start >= 0 and placeholder in value:
                nxt = _SLOT_END_RE.search(text, start)
                end = len(text[:nxt.start() if nxt else len(text)].rstrip("\n"))
                text = text[:start] + value + text[end:]
            continue
        text = text.replace(placeholder, value)
    return text


def _carry_auto_managed(body: str, current_text: str) -> str:
    """Append the ``auto-managed`` blocks of ``current_text`` that ``body`` lacks.

    caveman / ponytail / graphify write their block into AGENTS.md earlier in
    the same apply; regenerating a markerless file from the template would
    drop it until the next apply. A block whose source (ignoring a trailing
    ``:<mode>``) ``body`` already has, e.g. through ``project_meta``, is not
    added again.
    """
    from scripts.auto_managed import find_sections

    try:
        carried = find_sections(current_text)
        present = {s.source.rsplit(":", 1)[0] for s in find_sections(body)}
    except ValueError:
        return body
    lines = current_text.replace("\r\n", "\n").split("\n")
    for sec in carried:
        if sec.source.rsplit(":", 1)[0] not in present:
            block = "\n".join(lines[sec.start_line - 1:sec.end_line])
            body = body.rstrip("\n") + "\n\n" + block + "\n"
    return body


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

    * No file, or a markerless (never-adopted) file: the output is generated
      from the template, with ``project_meta`` filling the free-form slots
      (markerless prose is recovered through backup + ``curate``, see
      openspec/changes/lossless-adoption D2). The file's ``auto-managed``
      blocks (caveman / ponytail / graphify) are appended to it.
    * A file that already carries marker blocks: the template's canonical
      blocks are spliced INTO ``current_text`` (missing ones appended); the
      frontmatter and every section outside the blocks are kept verbatim.
      ``project_meta`` only fills placeholder tokens still present in it.

    When ``bundle.file_curate_intents["AGENTS.md"]`` marks blocks as
    ``keep_mine``, those blocks are taken from ``current_text`` instead of
    the template.
    """
    body = _apply_substitutions(template, substitutions)
    splice = bool(current_text) and bool(parse_blocks(current_text, CommentStyle.HTML).blocks)
    if splice:
        sealed = parse_blocks(_inject_sha_into_markers(body), CommentStyle.HTML).blocks
        body = write_blocks(current_text, sealed, style=CommentStyle.HTML)
    body = _apply_project_meta(body, bundle.get("project_meta"), splice=splice)
    if current_text and not splice:
        body = _carry_auto_managed(body, current_text)
    intents = (bundle.get("file_curate_intents") or {}).get("AGENTS.md")
    body = _apply_curate_intents(body, current_text, intents)
    body = _inject_sha_into_markers(body)
    return body


__all__ = ["render"]
