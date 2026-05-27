"""Render ``AGENTS.md`` from template + bundle.

The template's structure (headers, marker positions, section ordering) is
authoritative. The renderer:

1. Substitutes ``{{PLACEHOLDER}}`` tokens (PROJECT_NAME, OWNER_EMAIL, TODAY,
   PLAYBOOK_PIN, PROJECT_BANK).
2. Substitutes the free-form consumer-content placeholders
   ({{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}, etc.) with values from
   ``bundle.project_meta`` when present; otherwise leaves them as
   sentinel TODO lines for the operator to fill in.
3. Computes SHA-256[:12] of each marker block's content and injects
   ``sha=<hex>`` into the begin marker so downstream tooling can detect
   drift without consulting the bundle manifest.
"""
from __future__ import annotations

from scripts._marker_blocks import CommentStyle, parse_blocks, write_blocks
from scripts._template_classifier import compute_sha

# Map between bundle.project_meta keys and the literal template placeholders.
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
    """Apply ``{{KEY}}`` -> value substitution. Empty/missing keys are left untouched."""
    out = template
    for key, value in substitutions.items():
        if value is None:
            continue
        out = out.replace("{{" + key + "}}", str(value))
    return out


def _apply_project_meta(text: str, project_meta: dict | None) -> str:
    """Replace consumer-content placeholders with bundle values or sane defaults."""
    project_meta = project_meta or {}
    for meta_key, placeholder in _PROJECT_META_TO_PLACEHOLDER.items():
        value = project_meta.get(meta_key)
        if not isinstance(value, str) or not value.strip():
            value = _DEFAULT_TODO_TEXT.get(meta_key, "")
        text = text.replace(placeholder, value)
    return text


def _inject_sha_into_markers(text: str) -> str:
    """Parse marker blocks, compute SHA of each block's content, re-emit with sha attr."""
    parsed = parse_blocks(text, CommentStyle.HTML)
    if not parsed.blocks:
        return text
    desired = {}
    for block_id, block in parsed.blocks.items():
        sha = compute_sha(block.content)
        # Re-emit with the up-to-date sha attribute.
        desired[block_id] = type(block)(
            id=block.id,
            content=block.content,
            sha=sha,
            style=CommentStyle.HTML,
        )
    return write_blocks(text, desired, style=CommentStyle.HTML)


def render(
    *,
    template: str,
    substitutions: dict[str, str],
    bundle: dict,
) -> str:
    """Return the final AGENTS.md content."""
    body = _apply_substitutions(template, substitutions)
    body = _apply_project_meta(body, bundle.get("project_meta"))
    body = _inject_sha_into_markers(body)
    return body


__all__ = ["render"]
