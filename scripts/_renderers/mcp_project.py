"""Render ``mcp-servers.project.yaml`` from template + bundle.

The playbook-managed baseline (hindsight bootstrap) lives inside the
``id=project-servers-baseline`` marker block. Consumer-added MCP servers
from ``bundle.mcp_project_servers`` are appended below the marker as
additional entries under ``servers:``.

Because YAML's nested ``servers:`` mapping is finicky to merge with raw
string concatenation, we use a small custom emitter: the baseline block
already has the ``servers:`` line, and consumer entries are appended as
indented YAML under that same key OUTSIDE the marker block.
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


def _format_server_entry(server_id: str, fields: dict) -> str:
    """Emit one server entry as YAML indented under `servers:`."""
    lines = [f"  {server_id}:"]
    for key, value in fields.items():
        if isinstance(value, dict):
            lines.append(f"    {key}:")
            for k2, v2 in value.items():
                if isinstance(v2, list):
                    lines.append(f"      {k2}: {v2!r}")
                else:
                    lines.append(f"      {k2}: {v2}")
        elif isinstance(value, list):
            lines.append(f"    {key}: {value!r}")
        else:
            lines.append(f"    {key}: {value}")
    return "\n".join(lines) + "\n"


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

    extras = bundle.get("mcp_project_servers") or {}
    if not extras:
        return body

    if not body.endswith("\n"):
        body += "\n"
    body += "\n# Consumer-added project servers (preserved across apply_config)\n"
    for server_id, fields in extras.items():
        if not isinstance(fields, dict):
            continue
        body += _format_server_entry(server_id, fields)
    return body


__all__ = ["render"]
