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
markerless file that already has its own ``servers:`` mapping does not get the
baseline block appended (it would open a second ``servers:``); the bundle
servers are added under the consumer's mapping. A current file that is not a
valid YAML mapping is regenerated from the template; the orchestrator backs it
up first.
"""
from __future__ import annotations

import re

import yaml

from scripts._marker_blocks import CommentStyle, MarkerBlock, parse_blocks, write_blocks
from scripts._renderers._yaml_merge import MergeConflictError, duplicate_key, load_mapping
from scripts._template_classifier import compute_sha

_BASELINE_ID = "project-servers-baseline"
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

    current = load_mapping(current_text) if current_text else None
    if current is not None:
        # Merge: refresh the canonical block(s) in the consumer's own file.
        sealed = parse_blocks(body, CommentStyle.HASH).blocks
        if (_BASELINE_ID not in parse_blocks(current_text, CommentStyle.HASH).blocks
                and "servers" in current):
            # Markerless file with its own `servers:` mapping: the baseline
            # block opens `servers:` too, so appending it would duplicate the
            # key (PyYAML keeps the last mapping, check-yaml rejects the file).
            sealed.pop(_BASELINE_ID, None)
        body = write_blocks(current_text, sealed, style=CommentStyle.HASH)
        body, removed = _EXTRAS_REGION_RE.subn("", body)
        if removed:
            body = body.rstrip("\n") + "\n"

    extras = bundle.get("mcp_project_servers") or {}
    declared = ((load_mapping(body) or {}).get("servers") or {})
    servers = {
        sid: fields for sid, fields in extras.items()
        if isinstance(fields, dict) and sid not in declared
    }
    if servers:
        body = body.rstrip("\n") + "\n\n" + _EXTRAS_HEADER + "\n"
        body += _format_servers(servers) + _EXTRAS_TRAILER + "\n"

    merged = load_mapping(body, strict=True)
    landed = (merged or {}).get("servers")
    if merged is None or any(not isinstance(landed, dict) or sid not in landed
                             for sid in servers):
        dup = duplicate_key(body)
        # Merging into the consumer's file: a layout conflict for that file
        # only. From the template alone it is a playbook bug.
        raise (MergeConflictError if current is not None else ValueError)(
            "merged mcp-servers.project.yaml is not a valid YAML mapping"
            + (f" (duplicate key {dup!r})" if dup else "")
            + " — bundle servers are appended at the end of the file, indented "
            "two spaces under `servers:`; move any content after the `servers:` "
            "mapping above it and re-apply"
        )
    return body


__all__ = ["render"]
