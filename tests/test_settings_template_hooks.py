"""The seeded settings template must survive a drifted shell cwd and a real sops.

A hook command runs from wherever the shell last `cd`ed, so a bare relative script path
makes `python` exit 2 (blocking the prompt). And sops 3.10 rejects `exec-env FILE -- cmd args`
with "missing file to decrypt" — hidden by the template's `2>/dev/null || true`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from scripts._renderers._settings_merge import command_identity

TMPL = Path(__file__).resolve().parent.parent / "templates/new-project/.claude/settings.json.tmpl"


def _commands() -> list[str]:
    settings = json.loads(TMPL.read_text(encoding="utf-8").replace("{{PROJECT_BANK}}", "demo"))
    return [h["command"] for entries in settings["hooks"].values() for e in entries for h in e["hooks"]]


def test_hook_scripts_are_not_cwd_relative():
    for cmd in _commands():
        assert not re.search(r"\bpython3?\s+\.", cmd), f"cwd-relative script path: {cmd}"


def test_sops_exec_env_takes_one_string():
    for cmd in _commands():
        assert not re.search(r"sops exec-env\s+\S+\s+--", cmd), f"unsupported sops form: {cmd}"


def test_identity_ignores_quotes():
    anchored = 'python "$CLAUDE_PROJECT_DIR/.claude/hooks/openspec-apply-enforce.py"'
    assert command_identity(anchored) == "openspec-apply-enforce.py"
    assert command_identity("python .claude/hooks/openspec-apply-enforce.py") == "openspec-apply-enforce.py"
