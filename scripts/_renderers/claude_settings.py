"""Render ``.claude/settings.json`` (canonical) and ``settings.local.json`` (consumer).

The canonical settings.json is overwritten on every apply. Consumer
extras live in settings.local.json which Claude Code merges natively on
top of settings.json — so we generate it from
``bundle.claude_settings_extras`` instead of editing the main file.
"""
from __future__ import annotations

import json
from typing import Any


def _apply_subs(template: str, substitutions: dict[str, str]) -> str:
    out = template
    for key, value in substitutions.items():
        if value is not None:
            out = out.replace("{{" + key + "}}", str(value))
    return out


def render_main(
    *,
    template: str,
    substitutions: dict[str, str],
    bundle: dict,  # noqa: ARG001 — bundle reserved for future Claude-side toggles
) -> str:
    """Return the canonical settings.json content. Pure template substitution."""
    return _apply_subs(template, substitutions)


def render_local(
    *,
    template: str,
    substitutions: dict[str, str],  # noqa: ARG001 — no placeholders in the stub
    bundle: dict,
) -> str:
    """Return settings.local.json content from bundle.claude_settings_extras.

    If the bundle has no extras section, return the template verbatim
    (seed-only behaviour for fresh installs).
    """
    extras = bundle.get("claude_settings_extras")
    if not extras:
        return template

    permissions_allow = list(extras.get("permissions_allow") or [])
    additional_dirs = list(extras.get("additional_directories") or [])
    payload: dict[str, Any] = {
        "_comment": (
            "Consumer-owned overrides for Claude Code. Merged on top of "
            "settings.json natively. Managed by apply_config from "
            "bundle.claude_settings_extras."
        ),
        "permissions": {
            "allow": permissions_allow,
            "additionalDirectories": additional_dirs,
        },
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


__all__ = ["render_main", "render_local"]
