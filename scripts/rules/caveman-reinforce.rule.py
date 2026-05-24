"""Per-turn caveman reinforcement hook (UserPromptSubmit).

Reads ``<project>/.ai-playbook/caveman.json`` and emits a brief nudge to
stdout when caveman mode is ON with the ``response_style`` component
active. Never blocks; never raises; silent-fails on any error so a
broken hook never derails a user turn.

Triggered by Claude Code's ``UserPromptSubmit`` hook (registered in the
consumer's ``.claude/settings.json`` per
``docs/rules/caveman-reinforce.rule.md``).

Performance budget: ≤ 5 ms p50 (stdlib only, no jsonschema/yaml import).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


def _find_project_root(start: Path) -> Path | None:
    here = start.resolve()
    if here.is_file():
        here = here.parent
    for candidate in (here, *here.parents):
        try:
            if (candidate / "AGENTS.md").is_file():
                return candidate
        except OSError:
            continue
    return None


def _read_toggle(project_root: Path) -> dict[str, Any] | None:
    p = project_root / ".ai-playbook" / "caveman.json"
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8")
        loaded = json.loads(text)
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def compose_nudge(mode: str) -> str:
    return (
        f"Caveman mode active (intensity: {mode}). "
        "Drop articles, filler, pleasantries. Fragments OK. Code unchanged. "
        "Auto-clarity exceptions: security warnings, irreversible actions, "
        "multi-step sequences, user confused."
    )


def main(argv: list[str] | None = None, *, cwd: Path | None = None) -> int:
    try:
        root = _find_project_root(cwd or Path.cwd())
        if root is None:
            return 0
        state = _read_toggle(root)
        if not state:
            return 0
        if not state.get("enabled"):
            return 0
        components = state.get("components")
        if not isinstance(components, dict) or not components.get("response_style"):
            return 0
        mode = state.get("mode")
        if mode not in ("lite", "full", "ultra"):
            return 0
        print(compose_nudge(mode))
        return 0
    except Exception:  # noqa: BLE001 — hooks MUST NOT block user turn
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
