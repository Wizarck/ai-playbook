"""Render ``mcp-servers.project.yaml`` from template + bundle.

The playbook-managed baseline (hindsight bootstrap) lives inside the
``id=project-servers-baseline`` marker block, which opens the ``servers:``
mapping. Consumer-added MCP servers from ``bundle.mcp_project_servers`` are
appended at the end of the file, indented under that same ``servers:`` key,
between a ``# Consumer-added project servers …`` header and a
``# (end of consumer-added project servers)`` trailer. Entries are
serialised with ``yaml.safe_dump`` so any scalar (null, ``#``, ``: ``,
quotes) round-trips.

When the file already exists (``current_text``), it is merged instead of
regenerated: the marker block is refreshed in place, the bundle region is
replaced, and everything else the consumer wrote is kept verbatim. Servers
the consumer declared by hand outside the region are consumer-owned; a bundle
entry with the same id is not emitted again (it would be a duplicate key). A
current file that is not a valid YAML mapping is regenerated from the
template; the orchestrator backs it up first.
"""
from __future__ import annotations

import re

import yaml

from scripts._marker_blocks import CommentStyle, MarkerBlock, parse_blocks, write_blocks
from scripts._template_classifier import compute_sha

_EXTRAS_HEADER = "# Consumer-added project servers (preserved across apply_config)"
_EXTRAS_TRAILER = "# (end of consumer-added project servers)"
_EXTRAS_REGION_RE = re.compile(
    r"^" + re.escape(_EXTRAS_HEADER) + r"\n"
    r"(?:"
    r".*?^" + re.escape(_EXTRAS_TRAILER) + r"[ \t]*(?:\n|\Z)"
    # Legacy (pre-trailer) region: the old emitter wrote every line of every
    # entry indented by at least two spaces, through to the end of the file.
    r"|(?:  [^\n]*(?:\n|\Z))*"
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


def _load_mapping(text: str) -> dict | None:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _format_servers(servers: dict[str, dict]) -> str:
    """Emit ``servers`` as YAML entries indented under an existing ``servers:``."""
    dumped = yaml.safe_dump(
        {"servers": servers},
        sort_keys=False, default_flow_style=False, allow_unicode=True, width=4096,
    )
    # Drop the `servers:` line itself; the entries are already 2-space indented.
    return dumped.split("\n", 1)[1]


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

    if current_text and _load_mapping(current_text) is not None:
        # Merge: refresh the canonical block(s) in the consumer's own file.
        sealed = parse_blocks(body, CommentStyle.HASH).blocks
        body = write_blocks(current_text, sealed, style=CommentStyle.HASH)
        body, removed = _EXTRAS_REGION_RE.subn("", body)
        if removed:
            body = body.rstrip("\n") + "\n"

    extras = bundle.get("mcp_project_servers") or {}
    declared = ((_load_mapping(body) or {}).get("servers") or {})
    servers = {
        sid: fields for sid, fields in extras.items()
        if isinstance(fields, dict) and sid not in declared
    }
    if servers:
        body = body.rstrip("\n") + "\n\n" + _EXTRAS_HEADER + "\n"
        body += _format_servers(servers) + _EXTRAS_TRAILER + "\n"

    if _load_mapping(body) is None:
        raise ValueError(
            "merged mcp-servers.project.yaml is not a valid YAML mapping — "
            "consumer content after the `servers:` mapping? Move it above the "
            "marker block and re-apply"
        )
    return body


__all__ = ["render"]
