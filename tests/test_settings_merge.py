"""Tests for ``scripts._renderers._settings_merge`` — hook identity + dispatcher matcher."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from scripts._renderers import _settings_merge as sm

REPO = Path(__file__).resolve().parents[1]


def _commands(settings: dict, event: str) -> list[str]:
    return [h["command"] for e in settings["hooks"][event] for h in e["hooks"]]


# ---------------------------------------------------------------------------
# Hook identity (dedupe)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("command", "identity"), [
    ('python "$CLAUDE_PROJECT_DIR/.claude/hooks/enforce.py"', "enforce.py"),
    ("python notify.py --quiet", "notify.py"),
    ('python "$CLAUDE_PROJECT_DIR/.ai-playbook/scripts/hook_dispatcher.py" PreToolUse',
     "hook_dispatcher.py"),
    ('sops exec-env "$CLAUDE_PROJECT_DIR/s/secrets.env" -- python '
     '"$CLAUDE_PROJECT_DIR/.ai-playbook/scripts/inject_context.py" --bank-id x 2>/dev/null || true',
     "inject_context.py"),
    ("C:\\hooks\\run.ps1", "run.ps1"),
])
def test_command_identity_is_script_token(command: str, identity: str) -> None:
    assert sm.command_identity(command) == identity


def test_command_identity_falls_back_to_whole_command() -> None:
    assert sm.command_identity("  echo hi || true ") == "echo hi || true"


def test_ensure_hooks_does_not_drop_substring_or_shared_tail_hooks() -> None:
    base = {"hooks": {
        "PreToolUse": [{"matcher": "Edit", "hooks": [
            {"type": "command", "command": "python .claude/hooks/openspec-apply-enforce.py"}]}],
        "Stop": [],
    }}
    out = sm.ensure_hooks(base, [
        {"event": "PreToolUse", "matcher": "Edit",
         "command": 'python "$CLAUDE_PROJECT_DIR/.claude/hooks/enforce.py"'},
        {"event": "Stop", "command": "python notify.py --quiet"},
        {"event": "Stop", "command": "python summarize.py --quiet"},
        {"event": "SessionStart", "command": "python a.py || true"},
        {"event": "SessionStart", "command": "python b.py || true"},
    ])
    assert any(c.endswith('hooks/enforce.py"') for c in _commands(out, "PreToolUse"))
    assert len(_commands(out, "Stop")) == 2
    assert len(_commands(out, "SessionStart")) == 2
    # still idempotent
    assert sm.ensure_hooks(out, [{"event": "Stop", "command": "python notify.py --quiet"}]) == out


def test_has_hook_uses_exact_basename() -> None:
    s = {"hooks": {"PreToolUse": [{"hooks": [
        {"type": "command", "command": "python .claude/hooks/openspec-apply-enforce.py"}]}]}}
    assert sm.has_hook(s, "PreToolUse", "openspec-apply-enforce.py")
    assert not sm.has_hook(s, "PreToolUse", "enforce.py")


# ---------------------------------------------------------------------------
# Dispatcher matcher covers every tool a pretooluse rule acts on
# ---------------------------------------------------------------------------


def _load_rule(slug: str):  # type: ignore[no-untyped-def]
    path = REPO / "scripts" / "rules" / f"{slug}.rule.py"
    spec = importlib.util.spec_from_file_location(f"_r_{slug.replace('-', '_')}", path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _rule_tools() -> list[str]:
    tools = ["Edit", "Write", "MultiEdit", "Bash"]
    tools += sorted(_load_rule("confirm-before-termination")._STOP_TOOLS)
    tools += [f"mcp__atlassian__{t}" for t in (
        "createJiraIssue", "editJiraIssue", "transitionJiraIssue", "addCommentToJiraIssue")]
    return tools


def _template_dispatcher_matcher() -> str:
    tmpl = json.loads((REPO / "templates/new-project/.claude/settings.json.tmpl")
                      .read_text(encoding="utf-8").replace("{{PROJECT_BANK}}", "x"))
    return next(e["matcher"] for e in tmpl["hooks"]["PreToolUse"]
                if any("hook_dispatcher.py" in h["command"] for h in e["hooks"]))


@pytest.mark.parametrize("tool", _rule_tools())
def test_dispatcher_matcher_routes_every_rule_tool(tool: str) -> None:
    assert re.fullmatch(sm.DISPATCHER_PRE_TOOL_USE_MATCHER, tool)


def test_template_uses_the_dispatcher_constant() -> None:
    assert _template_dispatcher_matcher() == sm.DISPATCHER_PRE_TOOL_USE_MATCHER


def test_merge_widens_narrow_existing_dispatcher_entry() -> None:
    narrow = {"hooks": {"PreToolUse": [
        {"matcher": "Edit|Write|MultiEdit|Bash", "hooks": [
            {"type": "command", "command": "python .claude/hooks/openspec-apply-enforce.py"},
            {"type": "command", "command": sm.DISPATCHER_PRE_TOOL_USE_COMMAND},
        ]},
    ]}}
    out = sm.merge_required_dispatcher(narrow)
    entries = out["hooks"]["PreToolUse"]
    disp = [e for e in entries if any("hook_dispatcher.py" in h["command"] for h in e["hooks"])]
    assert len(disp) == 1
    assert disp[0]["matcher"] == sm.DISPATCHER_PRE_TOOL_USE_MATCHER
    # the co-located consumer hook keeps its original (narrow) routing
    enforce = [e for e in entries if any("openspec" in h["command"] for h in e["hooks"])]
    assert enforce[0]["matcher"] == "Edit|Write|MultiEdit|Bash"
    assert sum("hook_dispatcher.py" in c for c in _commands(out, "PreToolUse")) == 1
    assert sm.merge_required_dispatcher(out) == out  # idempotent


def test_merge_leaves_match_all_dispatcher_entry_alone() -> None:
    s = {"hooks": {"PreToolUse": [
        {"matcher": "*", "hooks": [{"type": "command", "command": sm.DISPATCHER_PRE_TOOL_USE_COMMAND}]},
    ]}}
    assert sm.merge_required_dispatcher(s) == s
