"""Caveman compression policy — what can and cannot be compressed.

Per the AI/LLM-expert roundtable for the bundle-managed files redesign:
LLMs (Claude, Gemini, Cursor) rely on precise imperative grammar +
negations in certain AGENTS.md sections. Dropping articles, auxiliaries,
or negation words would cause catastrophic mis-execution of the rules.

This module makes that list authoritative + queryable so renderers and
the config UI can refuse to compress these sections regardless of the
user's global toggle.

Never-compress block IDs (marker-block ids in canonical templates)
-----------------------------------------------------------------
* ``bootstrap-directive``  (AGENTS.md §0) — sequential instructions; LLMs
  treat as a conditional flow. Compressing breaks ordering semantics.
* ``dispatcher-index``     (AGENTS.md §2) — link table; pointers depend on
  precise labels.
* ``capability-map``       (AGENTS.md §5) — tool-routing decision tree;
  ambiguous labels cause mis-routing.
* ``mcp-sources``          (AGENTS.md §6) — file-path SSOT pointer; literal
  filenames must survive.

Never-compress project_meta keys (free-form consumer content)
-------------------------------------------------------------
* ``hard_rules`` — contains negations ("never", "must not", "do not");
  highest catastrophic-failure risk.

Safe-to-compress project_meta keys (default behaviour)
-----------------------------------------------------
* ``project_identity`` — descriptive prose; LLM context only.
* ``inherited_overrides`` — enumerative; compression-tolerant.
* ``gotchas`` — already terse; compression near no-op.
* ``active_work`` — pointer-heavy; tolerant if links survive.

MCP server descriptions
-----------------------
* Per-server toggle, default OFF (see ``MCP_COMPRESS_DEFAULT_OFF``).
  Tool-selection F1 degrades when descriptions lose articles/verbs.
"""
from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Hardcoded never-compress sets — these override the user's global toggle.
# ---------------------------------------------------------------------------

NEVER_COMPRESS_BLOCK_IDS: Final[frozenset[str]] = frozenset({
    "bootstrap-directive",
    "dispatcher-index",
    "capability-map",
    "mcp-sources",
})

NEVER_COMPRESS_PROJECT_META_KEYS: Final[frozenset[str]] = frozenset({
    "hard_rules",
})

# project_meta keys that are safe to compress when the user enables the
# global caveman toggle for free-form content.
COMPRESSIBLE_PROJECT_META_KEYS: Final[frozenset[str]] = frozenset({
    "project_identity",
    "inherited_overrides",
    "gotchas",
    "active_work",
})

MCP_COMPRESS_DEFAULT_OFF: Final[bool] = True


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def is_block_compressible(block_id: str, *, user_global_enabled: bool) -> bool:
    """Return True when the marker block may be caveman-compressed.

    A block is NEVER compressible if its id appears in
    ``NEVER_COMPRESS_BLOCK_IDS``, regardless of the user's preference.
    Other blocks follow the user's global toggle.
    """
    if block_id in NEVER_COMPRESS_BLOCK_IDS:
        return False
    return bool(user_global_enabled)


def is_project_meta_key_compressible(
    key: str, *,
    user_global_enabled: bool,
    per_section_override: bool | None = None,
) -> bool:
    """Return True when a project_meta free-form key may be compressed.

    Precedence:
      1. ``NEVER_COMPRESS_PROJECT_META_KEYS`` ⇒ always False.
      2. Per-section override (from ``bundle.caveman_section_policy.sections``)
         takes precedence if provided.
      3. Else fall back to the global toggle.

    Unknown keys are treated as non-compressible (safe default).
    """
    if key in NEVER_COMPRESS_PROJECT_META_KEYS:
        return False
    if key not in COMPRESSIBLE_PROJECT_META_KEYS:
        return False
    if per_section_override is not None:
        return bool(per_section_override)
    return bool(user_global_enabled)


def is_mcp_description_compressible(
    server_id: str, *,  # noqa: ARG001 — server-id reserved for future per-tenant rules
    user_global_enabled: bool,
    per_server_override: bool | None = None,
) -> bool:
    """MCP descriptions are compress-OFF by default."""
    if per_server_override is not None:
        return bool(per_server_override)
    if MCP_COMPRESS_DEFAULT_OFF:
        return False
    return bool(user_global_enabled)


def describe_policy() -> dict[str, list[str]]:
    """Return a snapshot of the policy suitable for the UI preview panel."""
    return {
        "never_compress_block_ids": sorted(NEVER_COMPRESS_BLOCK_IDS),
        "never_compress_project_meta_keys": sorted(NEVER_COMPRESS_PROJECT_META_KEYS),
        "compressible_project_meta_keys": sorted(COMPRESSIBLE_PROJECT_META_KEYS),
        "mcp_default": ["compress-off-by-default — per-server opt-in required"],
    }


__all__ = [
    "COMPRESSIBLE_PROJECT_META_KEYS",
    "MCP_COMPRESS_DEFAULT_OFF",
    "NEVER_COMPRESS_BLOCK_IDS",
    "NEVER_COMPRESS_PROJECT_META_KEYS",
    "describe_policy",
    "is_block_compressible",
    "is_mcp_description_compressible",
    "is_project_meta_key_compressible",
]
