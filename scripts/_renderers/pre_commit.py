"""Render ``.pre-commit-config.yaml`` from template + bundle.

Playbook hooks live inside the ``id=playbook-hooks`` marker block. Consumer
hooks from ``bundle.pre_commit_extras.hooks`` are appended after the
``repos:`` block as a second ``- repo: local`` group (pre-commit accepts
several ``local`` repos; any other name would need a ``rev``), between a
``# Consumer hooks …`` header and a ``# (end of consumer hooks)`` trailer.

When the file already exists (``current_text``), it is merged instead of
regenerated: the marker block is refreshed in place, the bundle-extras region
is replaced, and everything else the consumer wrote is kept verbatim. A
current file that is not a valid YAML mapping (e.g. corrupted by an older renderer) is
regenerated from the template; the orchestrator backs it up first.
"""
from __future__ import annotations

import re

import yaml

from scripts._marker_blocks import CommentStyle, MarkerBlock, parse_blocks, write_blocks
from scripts._template_classifier import compute_sha

_EXTRAS_HEADER = "# Consumer hooks (preserved across apply_config)"
_EXTRAS_TRAILER = "# (end of consumer hooks)"
_EXTRAS_REGION_RE = re.compile(
    r"^" + re.escape(_EXTRAS_HEADER) + r"\n"
    r"(?:"
    r".*?^" + re.escape(_EXTRAS_TRAILER) + r"[ \t]*(?:\n|\Z)"
    # Legacy (pre-trailer) region: the old emitter wrote one `local-extras`
    # group whose lines were all indented by four spaces.
    r"|  - repo: local-extras\n(?:    [^\n]*(?:\n|\Z))*"
    r")",
    re.MULTILINE | re.DOTALL,
)


def _inject_sha(text: str) -> str:
    parsed = parse_blocks(text, CommentStyle.HASH)
    if not parsed.blocks:
        return text
    desired = {
        bid: MarkerBlock(id=bid, content=block.content, sha=compute_sha(block.content),
                         style=CommentStyle.HASH)
        for bid, block in parsed.blocks.items()
    }
    return write_blocks(text, desired, style=CommentStyle.HASH)


def _render_extras_yaml(hooks: list[dict]) -> str:
    """Render the consumer hooks as one ``- repo: local`` item under ``repos:``."""
    hooks = [h for h in hooks if isinstance(h, dict)]
    if not hooks:
        return ""
    dumped = yaml.safe_dump(
        [{"repo": "local", "hooks": hooks}],
        sort_keys=False, default_flow_style=False, allow_unicode=True,
        width=4096,
    )
    return "".join(f"  {line}" if line.strip() else line
                   for line in dumped.splitlines(keepends=True))


def _is_mapping(text: str) -> bool:
    try:
        return isinstance(yaml.safe_load(text), dict)
    except yaml.YAMLError:
        return False


def render(
    *,
    template: str,
    substitutions: dict[str, str],
    bundle: dict,
    current_text: str | None = None,
) -> str:
    body = template
    for key, value in substitutions.items():
        if value is not None:
            body = body.replace("{{" + key + "}}", str(value))
    body = _inject_sha(body)

    if current_text and _is_mapping(current_text):
        # Merge: refresh the canonical block(s) in the consumer's own file.
        sealed = parse_blocks(body, CommentStyle.HASH).blocks
        body = write_blocks(current_text, sealed, style=CommentStyle.HASH)
        body, removed = _EXTRAS_REGION_RE.subn("", body)
        if removed:
            body = body.rstrip("\n") + "\n"

    hooks = (bundle.get("pre_commit_extras") or {}).get("hooks") or []
    extras_yaml = _render_extras_yaml(hooks)
    if extras_yaml:
        body = body.rstrip("\n") + "\n\n" + _EXTRAS_HEADER + "\n"
        body += extras_yaml + _EXTRAS_TRAILER + "\n"

    if not _is_mapping(body):
        raise ValueError(
            "merged .pre-commit-config.yaml is not a valid YAML mapping — consumer content "
            "after the `repos:` list? Move it above `repos:` and re-apply"
        )
    return body


__all__ = ["render"]
