"""Render ``.pre-commit-config.yaml`` from template + bundle.

Playbook hooks live inside the ``id=playbook-hooks`` marker block. Consumer
hooks from ``bundle.pre_commit_extras.hooks`` are appended after the
``repos:`` block, in a separate ``- repo: local-extras`` group so the
overall YAML stays valid pre-commit syntax.
"""
from __future__ import annotations

from scripts._marker_blocks import CommentStyle, MarkerBlock, parse_blocks, write_blocks
from scripts._template_classifier import compute_sha


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
    """Render a YAML fragment with the consumer hooks under a `local-extras` repo."""
    if not hooks:
        return ""
    out = ["  - repo: local-extras"]
    out.append("    hooks:")
    for hook in hooks:
        out.append(f"      - id: {hook['id']}")
        for key, val in hook.items():
            if key == "id":
                continue
            if isinstance(val, bool):
                # YAML booleans are lowercase by convention (str(bool) is "True").
                out.append(f"        {key}: {'true' if val else 'false'}")
            elif isinstance(val, (str, int, float)):
                out.append(f"        {key}: {val}")
            elif isinstance(val, list):
                out.append(f"        {key}: {val!r}")
            else:
                out.append(f"        {key}: {val}")
    return "\n".join(out) + "\n"


def render(
    *,
    template: str,
    substitutions: dict[str, str],
    bundle: dict,
) -> str:
    body = template
    for key, value in substitutions.items():
        if value is not None:
            body = body.replace("{{" + key + "}}", str(value))
    body = _inject_sha(body)

    hooks = (bundle.get("pre_commit_extras") or {}).get("hooks") or []
    extras_yaml = _render_extras_yaml(hooks)
    if extras_yaml:
        if not body.endswith("\n"):
            body += "\n"
        body += "\n# Consumer hooks (preserved across apply_config)\n"
        body += extras_yaml
    return body


__all__ = ["render"]
