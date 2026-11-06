"""Stdlib-only read side of the rules toggle (``.ai-playbook/rules-toggle.json``).

Split out of ``scripts.rules_toggle`` because that module self-installs
``jsonschema`` at import and raises ``SystemExit(2)`` when it cannot. The hook
dispatcher and ``scripts/rules/_telemetry.py`` only need a json read to decide
whether a rule is OFF; importing the full CLI from a PreToolUse hook turned a
missing optional dependency into exit 2 on every Edit/Write/Bash call.
Keep this module stdlib-only.
"""
from __future__ import annotations

import json
from pathlib import Path

STATE_DIR_NAME = ".ai-playbook"
STATE_FILENAME = "rules-toggle.json"
VALID_LAYERS = ("L1", "L2", "L3")


def state_path(project_root: Path) -> Path:
    return project_root / STATE_DIR_NAME / STATE_FILENAME


def is_rule_disabled(
    project_root: Path,
    slug: str,
    *,
    layer: str = "L1",
) -> bool:
    """Return True if ``slug`` is OFF at ``layer`` in the consumer's state.

    Resolution cascade (rule absent or file absent → ON):
        1. No state file or no entry for slug → False (rule ON).
        2. Entry has ``enabled=False`` → True (whole rule OFF).
        3. Entry has ``layers.<layer>=False`` → True (only this layer OFF).
        4. Otherwise → False (rule ON at this layer).
    """
    if layer not in VALID_LAYERS:
        raise ValueError(f"invalid layer {layer!r}; valid: {VALID_LAYERS}")
    p = state_path(project_root)
    if not p.is_file():
        return False
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Fail-safe: corrupt / undecodable file = treat as absent.
        return False
    entry = (state.get("rules") or {}).get(slug) if isinstance(state, dict) else None
    if not isinstance(entry, dict):
        return False
    if entry.get("enabled") is False:
        return True
    layers = entry.get("layers") or {}
    return isinstance(layers, dict) and layers.get(layer) is False
