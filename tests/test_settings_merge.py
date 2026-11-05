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


# ---------------------------------------------------------------------------
# Dispatcher matcher widening only ADDS routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("matcher", "tool", "routed"), [
    ("Edit|Write", "Edit", True),
    ("Edit|Write", "NotebookEdit", False),  # a plain list matches names exactly
    ("Edit, Write", "Write", True),
    ("Edit|mcp__.*__x", "NotebookEdit", True),  # a regex is searched, unanchored
    ("mcp__.*__(create|edit)JiraIssue", "mcp__claude_ai_Atlassian__editJiraIssue", True),
    ("*", "Anything", True),
    ("", "Anything", True),
    (None, "Anything", True),
    ("(", "Edit", False),  # invalid regex routes nothing
])
def test_matcher_routes_reads_matchers_like_claude_code(matcher, tool: str, routed: bool) -> None:
    assert sm._matcher_routes(matcher, tool) is routed


_D = sm.DISPATCHER_PRE_TOOL_USE_COMMAND
_ENFORCE = 'python "$CLAUDE_PROJECT_DIR/.claude/hooks/openspec-apply-enforce.py"'
# A real consumer's shapes: a dispatcher sharing the Bash entry with an inline
# hook, and a Jira-only dispatcher wrapped in an env export + sops decryption.
_SHARED_DISP = ('cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0; python3 '
                '"${CLAUDE_PROJECT_DIR:-.}/.ai-playbook/scripts/hook_dispatcher.py" PreToolUse')
_WRAPPED_DISP = ('export AIPLAYBOOK_CLOSURE_DONE_TRANSITIONS=31; S=s/secrets.env; '
                 'sops exec-env "$S" "python .ai-playbook/scripts/hook_dispatcher.py PreToolUse"')
_INLINE = "CMD=$(cat) || true"
_JIRA = "mcp__.*__(createJiraIssue|editJiraIssue|transitionJiraIssue|addCommentToJiraIssue)"
_CANON = sm.DISPATCHER_PRE_TOOL_USE_MATCHER
_GEEPLO_JIRA = "mcp__.*__(create|edit|transition)JiraIssue|mcp__.*__addCommentToJiraIssue"
_EXTRA_TOOLS = ["NotebookEdit", "Read", "TodoWrite", "mcp__github__create_pull_request"]


def _pre(*entries: tuple[str | None, list[str]]) -> dict:
    """PreToolUse settings from (matcher, commands) pairs; a None matcher has no key."""
    out = []
    for matcher, cmds in entries:
        entry: dict = {"hooks": [{"type": "command", "command": c} for c in cmds]}
        if matcher is not None:
            entry = {"matcher": matcher, **entry}
        out.append(entry)
    return {"hooks": {"PreToolUse": out}}


# layout -> (settings, matchers expected after the merge)
_LAYOUTS = {
    "template v0.22.9-v0.24.1": (
        _pre(("Edit|Write|MultiEdit|Bash", [_ENFORCE]),
             ("Edit|Write|MultiEdit|Bash|KillShell|TaskStop|mcp__.*__(create|edit)JiraIssue", [_D])),
        ["Edit|Write|MultiEdit|Bash", _CANON]),
    "merge path up to v0.24.1": (
        _pre(("Edit|Write|MultiEdit", [_ENFORCE]), ("Edit|Write|MultiEdit|Bash", [_D])),
        ["Edit|Write|MultiEdit", _CANON]),
    "dispatcher shares an entry": (
        _pre(("Edit|Write|MultiEdit|Bash", [_ENFORCE, _D])),
        ["Edit|Write|MultiEdit|Bash", f"KillShell|TaskStop|BashOutputKill|{_JIRA}"]),
    "shared and wrapped dispatchers": (
        _pre(("Edit|Write|MultiEdit", [_ENFORCE]), ("Bash", [_INLINE, _SHARED_DISP]),
             ("Read|Glob", [_INLINE]), (_GEEPLO_JIRA, [_WRAPPED_DISP])),
        ["Edit|Write|MultiEdit", "Bash", "Read|Glob", _GEEPLO_JIRA,
         "Edit|Write|MultiEdit|KillShell|TaskStop|BashOutputKill"]),
    "custom wider matcher": (
        _pre(("Edit|Write|MultiEdit|Bash|NotebookEdit|mcp__github__create_pull_request", [_D])),
        [f"Edit|Write|MultiEdit|Bash|NotebookEdit|mcp__github__create_pull_request|"
         f"KillShell|TaskStop|BashOutputKill|{_JIRA}"]),
    "plain list with commas": (_pre(("Edit, Write , MultiEdit|", [_D])), [_CANON]),
    "two dispatcher entries": (
        _pre(("Bash", [_D]), ("mcp__.*__transitionJiraIssue", [_WRAPPED_DISP])),
        ["Bash|Edit|Write|MultiEdit|KillShell|TaskStop|BashOutputKill|"
         "mcp__.*__(createJiraIssue|editJiraIssue|addCommentToJiraIssue)",
         "mcp__.*__transitionJiraIssue"]),
    "match-all star": (_pre(("*", [_D])), ["*"]),
    "match-all regex": (_pre((".*", [_D])), [".*"]),
    "no matcher": (_pre((None, [_D])), [None]),
    "canonical": (_pre(("Edit|Write|MultiEdit|Bash", [_ENFORCE]), (_CANON, [_D])),
                  ["Edit|Write|MultiEdit|Bash", _CANON]),
}


def _dispatcher_routes(settings: dict, tool: str) -> int:
    """How many entries send ``tool`` to a dispatcher hook."""
    return sum(
        any("hook_dispatcher.py" in h["command"] for h in e["hooks"])
        and sm._matcher_routes(e.get("matcher"), tool)
        for e in settings["hooks"]["PreToolUse"]
    )


@pytest.mark.parametrize("layout", list(_LAYOUTS))
def test_dispatcher_merge_only_adds_routing(layout: str) -> None:
    before, expected = _LAYOUTS[layout]
    after = sm.merge_required_dispatcher(before)
    old, new = before["hooks"]["PreToolUse"], after["hooks"]["PreToolUse"]
    assert [e.get("matcher") for e in new] == expected
    # no hook is moved or dropped; an added entry holds only the bare dispatcher
    assert [e["hooks"] for e in new[:len(old)]] == [e["hooks"] for e in old]
    assert all(e["hooks"] == [{"type": "command", "command": _D, "timeout": 10}] for e in new[len(old):])
    # every rule tool reaches the dispatcher, never through one more entry than before
    for tool in [*_rule_tools(), "mcp__claude_ai_Atlassian__transitionJiraIssue"]:
        assert _dispatcher_routes(after, tool) == max(1, _dispatcher_routes(before, tool)), tool
    # no matcher is narrowed
    for tool in _rule_tools() + _EXTRA_TOOLS:
        for o, n in zip(old, new[:len(old)], strict=True):
            if sm._matcher_routes(o.get("matcher"), tool):
                assert sm._matcher_routes(n.get("matcher"), tool), (tool, n.get("matcher"))
    assert sm.merge_required_dispatcher(after) == after  # idempotent


@pytest.mark.parametrize("old", sorted(sm._PREVIOUS_DISPATCHER_MATCHERS))
def test_previous_dispatcher_matchers_are_covered_by_the_canonical_one(old: str) -> None:
    for tool in _rule_tools() + _EXTRA_TOOLS:
        if sm._matcher_routes(old, tool):
            assert sm._matcher_routes(_CANON, tool), tool


def test_merge_leaves_match_all_dispatcher_entry_alone() -> None:
    s = {"hooks": {"PreToolUse": [
        {"matcher": "*", "hooks": [{"type": "command", "command": sm.DISPATCHER_PRE_TOOL_USE_COMMAND}]},
    ]}}
    assert sm.merge_required_dispatcher(s) == s
