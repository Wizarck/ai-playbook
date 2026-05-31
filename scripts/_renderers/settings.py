"""Render ``.claude/settings.json`` via identity deep-merge.

Unlike the marker-block renderers, ``.claude/settings.json`` is plain JSON with
no markers — so provenance is preserved STRUCTURALLY: the renderer starts from
the consumer's current file (or the canonical template when the file is absent),
guarantees the openspec-apply-enforce PreToolUse invariant, projects the bundle's
model-agnostic ``settings`` surface (claude-targeted entries only) plus the legacy
``claude_settings_extras`` permissions, and re-serialises — **never dropping any
key the consumer added**. This is the door's fold of the legacy
``claude-settings.rule.py apply``; the rule's ``validate`` remains the L1 gate.

``use_current_text=True``, NOT seed-only: the invariant is re-ensured on every
reconcile. A current file that is present but unparseable JSON is returned
verbatim (never clobbered) — the L1 validate gate surfaces the syntax error.
"""
from __future__ import annotations

import json
from typing import Any

from scripts._renderers._settings_merge import (
    ensure_hooks,
    merge_permissions,
    merge_required_dispatcher,
    merge_required_pretooluse,
)

_HOOK_KEYS = ("event", "matcher", "command", "timeout")


def _apply_subs(template: str, substitutions: dict[str, str]) -> str:
    out = template
    for key, value in substitutions.items():
        if value is not None:
            out = out.replace("{{" + key + "}}", str(value))
    return out


def _claude_hooks(settings_section: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract claude-targeted hook entries from the agnostic ``settings.hooks``.

    A hook with no ``targets`` applies to every model; a hook with ``targets``
    applies only when ``"claude"`` is listed.
    """
    out: list[dict[str, Any]] = []
    for h in settings_section.get("hooks") or []:
        if not isinstance(h, dict):
            continue
        targets = h.get("targets")
        if targets and "claude" not in targets:
            continue
        out.append({k: h[k] for k in _HOOK_KEYS if k in h})
    return out


def render(
    *,
    template: str,
    substitutions: dict[str, str],
    bundle: dict,
    current_text: str | None = None,
) -> str:
    """Return the merged ``.claude/settings.json`` content (canonical JSON + \\n)."""
    if current_text is not None:
        try:
            base = json.loads(current_text)
        except json.JSONDecodeError:
            return current_text  # malformed — never clobber; L1 validate flags it
        if not isinstance(base, dict):
            return current_text  # non-object settings — leave as-is
    else:
        try:
            base = json.loads(_apply_subs(template, substitutions))
        except json.JSONDecodeError:
            base = {}
        if not isinstance(base, dict):
            base = {}

    merged = merge_required_pretooluse(base)
    # Generic L1 dispatcher entry — ensures trigger-declaring rules auto-fire
    # without per-rule settings edits (runs alongside the bespoke enforce hook).
    merged = merge_required_dispatcher(merged)

    settings_section = bundle.get("settings") or {}
    claude_hooks = _claude_hooks(settings_section)
    if claude_hooks:
        merged = ensure_hooks(merged, claude_hooks)

    # Agnostic permissions + legacy claude_settings_extras (compat) — union-merged.
    allow = list(settings_section.get("permissions_allow") or [])
    dirs = list(settings_section.get("additional_directories") or [])
    extras = bundle.get("claude_settings_extras") or {}
    for a in extras.get("permissions_allow") or []:
        if a not in allow:
            allow.append(a)
    for d in extras.get("additional_directories") or []:
        if d not in dirs:
            dirs.append(d)
    merged = merge_permissions(merged, allow=allow, additional_directories=dirs)

    # No semantic change ⇒ preserve the consumer's exact bytes (formatting,
    # key order, comments). Only a real merge re-serialises. This keeps a
    # reconcile that touches nothing a true byte-level no-op (no spurious
    # backup, no reformat churn on a freshly-copied template).
    if current_text is not None:
        try:
            if json.loads(current_text) == merged:
                return current_text
        except json.JSONDecodeError:
            pass

    return json.dumps(merged, indent=2, ensure_ascii=False) + "\n"


__all__ = ["render"]
