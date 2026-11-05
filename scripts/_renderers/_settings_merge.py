"""Identity-based deep-merge helpers for Claude/agnostic settings JSON.

Shared by ``scripts/_renderers/settings.py`` (the door's ``.claude/settings.json``
renderer) and ``scripts/rules/claude-settings.rule.py`` (the L1 validate gate).
The contract everywhere is the same: NEVER remove or reorder consumer-authored
content — only ENSURE that a required hook exists, deduping by the command's
script identity (basename) rather than by an exact matcher string. Matching by
basename is what lets the canonical template's ``Edit|Write|MultiEdit|Bash``
matcher satisfy the ``Edit|Write|MultiEdit`` invariant without producing a
duplicate PreToolUse entry. Two rewrites are allowed: ``anchor_hook_commands``
anchors cwd-relative script paths to ``$CLAUDE_PROJECT_DIR``, and
``merge_required_dispatcher`` ADDS the tools no dispatcher entry routes yet
(never narrowing a matcher, never moving or dropping a hook).

Stdlib-only; pure functions (no filesystem, no mutation of inputs).
"""
from __future__ import annotations

import re
from typing import Any

# Canonical PreToolUse invariant. Source of truth:
# templates/new-project/.claude/settings.json.tmpl (which may extend the matcher,
# e.g. with `|Bash`). The invariant is satisfied as long as the enforce hook's
# script is wired under PreToolUse by *some* matcher.
REQUIRED_PRE_TOOL_USE_MATCHER = "Edit|Write|MultiEdit"
REQUIRED_PRE_TOOL_USE_COMMAND = 'python "$CLAUDE_PROJECT_DIR/.claude/hooks/openspec-apply-enforce.py"'
REQUIRED_PRE_TOOL_USE_TIMEOUT = 10
REQUIRED_PRE_TOOL_USE_IDENTITY = "openspec-apply-enforce.py"


_SCRIPT_EXTS = (".py", ".sh", ".bash", ".js", ".mjs", ".cjs", ".ts", ".ps1", ".rb", ".pl")


def command_identity(command: str) -> str:
    """Return the identity used to dedupe hook commands.

    The identity is the basename of the command's first script token (a token
    ending in a script extension such as ``.py`` / ``.sh``), so
    ``"sops exec-env -- python .claude/hooks/openspec-apply-enforce.py"`` and
    ``'python "$CLAUDE_PROJECT_DIR/.claude/hooks/openspec-apply-enforce.py"'``
    both reduce to ``"openspec-apply-enforce.py"`` regardless of wrapper
    prefixes, trailing args (``--quiet``, ``|| true``), path separators or
    quoting. A command with no script token falls back to the whole
    (stripped) command, i.e. exact command equality.
    """
    for raw in command.replace("\\", "/").split():
        base = raw.strip("\"'").rsplit("/", 1)[-1]
        if base.lower().endswith(_SCRIPT_EXTS):
            return base
    return command.strip()


def _command_has_identity(command: object, identity: str) -> bool:
    return bool(identity) and command_identity(str(command or "")) == identity


def has_hook(settings: dict[str, Any], event: str, identity: str) -> bool:
    """True iff some hook under ``settings.hooks[event]`` has exactly
    ``identity`` as its :func:`command_identity` (any matcher)."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    entries = hooks.get(event)
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        sub = entry.get("hooks")
        if not isinstance(sub, list):
            continue
        for h in sub:
            if isinstance(h, dict) and _command_has_identity(h.get("command"), identity):
                return True
    return False


def ensure_hooks(settings: dict[str, Any], hooks: list[dict[str, Any]]) -> dict[str, Any]:
    """Idempotently ensure each entry in ``hooks`` is wired into ``settings``.

    Each ``hooks`` item is a flat dict ``{event, matcher?, command, timeout?}``.
    Dedup is by command identity (basename) across ALL matcher entries for that
    event — so a hook already present under a broader matcher is left untouched
    and never duplicated. When absent, the hook is appended to the entry whose
    ``matcher`` equals the requested one, or a fresh entry is created. Returns a
    new dict; inputs are not mutated.
    """
    out = dict(settings)
    hooks_root = dict(out.get("hooks", {})) if isinstance(out.get("hooks"), dict) else {}

    for h in hooks:
        event = h.get("event")
        command = h.get("command")
        if not event or not command:
            continue
        matcher = h.get("matcher")
        timeout = h.get("timeout")
        # An explicit `identity` overrides the derived script identity.
        identity = h.get("identity") or command_identity(str(command))

        entries = list(hooks_root.get(event, [])) if isinstance(hooks_root.get(event), list) else []
        if any(
            isinstance(e, dict) and isinstance(e.get("hooks"), list) and any(
                isinstance(x, dict) and _command_has_identity(x.get("command"), identity)
                for x in e["hooks"]
            )
            for e in entries
        ):
            hooks_root[event] = entries
            continue  # already wired under some matcher — no-op

        hook_obj: dict[str, Any] = {"type": "command", "command": command}
        if timeout is not None:
            hook_obj["timeout"] = timeout

        idx = next(
            (i for i, e in enumerate(entries)
             if isinstance(e, dict) and e.get("matcher") == matcher),
            None,
        )
        if idx is None:
            new_entry: dict[str, Any] = {"hooks": [hook_obj]}
            if matcher is not None:
                new_entry = {"matcher": matcher, "hooks": [hook_obj]}
            entries.append(new_entry)
        else:
            entry = dict(entries[idx])
            sub = list(entry.get("hooks", [])) if isinstance(entry.get("hooks"), list) else []
            sub.append(hook_obj)
            entry["hooks"] = sub
            entries[idx] = entry
        hooks_root[event] = entries

    out["hooks"] = hooks_root
    return out


def merge_required_pretooluse(settings: dict[str, Any]) -> dict[str, Any]:
    """Ensure the openspec-apply-enforce PreToolUse invariant. Idempotent."""
    return ensure_hooks(settings, [{
        "event": "PreToolUse",
        "matcher": REQUIRED_PRE_TOOL_USE_MATCHER,
        "command": REQUIRED_PRE_TOOL_USE_COMMAND,
        "timeout": REQUIRED_PRE_TOOL_USE_TIMEOUT,
    }])


# Generic L1 dispatcher entry (D21). Routes PreToolUse events to every
# trigger-declaring rule with an in-process hook — so adding such a rule needs
# ZERO settings edits. Runs ALONGSIDE the bespoke openspec-apply-enforce hook
# (which keeps its own precise Bash-inspection behaviour); deduped by basename.
# Single source of truth for the dispatcher matcher: it MUST route every tool a
# `pretooluse()` rule acts on (secrets-handling / english-only-docs: Edit|Write|
# MultiEdit; shared-test-db-mutex: Bash; confirm-before-termination: KillShell|
# TaskStop|BashOutputKill; jira-ticket-standard: create/editJiraIssue;
# jira-closure-evidence: transitionJiraIssue + addCommentToJiraIssue). The Jira
# tools are MCP tools whose `mcp__<alias>__` prefix varies per client, hence the
# regex. The canonical settings.json.tmpl carries the same string (pinned by a
# test); tools an existing dispatcher wiring does not route are added on merge.
_DISPATCHER_TOOLS = ("Edit", "Write", "MultiEdit", "Bash", "KillShell", "TaskStop", "BashOutputKill")
_DISPATCHER_MCP_TOOLS = ("createJiraIssue", "editJiraIssue", "transitionJiraIssue", "addCommentToJiraIssue")


def _dispatcher_matcher(tools: list[str] | tuple[str, ...], mcp_tools: list[str] | tuple[str, ...]) -> str:
    parts = list(tools)
    if mcp_tools:
        parts.append("mcp__.*__(" + "|".join(mcp_tools) + ")")
    return "|".join(parts)


DISPATCHER_PRE_TOOL_USE_MATCHER = _dispatcher_matcher(_DISPATCHER_TOOLS, _DISPATCHER_MCP_TOOLS)
# Matchers earlier versions wired the dispatcher under (merge path / template).
# Each routes a subset of the canonical tools, so it may become the canonical one.
# Changing the canonical matcher? Add its old value here.
_PREVIOUS_DISPATCHER_MATCHERS = frozenset({
    "Edit|Write|MultiEdit|Bash",
    "Edit|Write|MultiEdit|Bash|KillShell|TaskStop",
    "Edit|Write|MultiEdit|Bash|KillShell|TaskStop|mcp__.*__(create|edit)JiraIssue",
})
# A Jira tool counts as routed only if it is under every probe alias (a local
# `atlassian` MCP server, the claude.ai connector).
_MCP_PROBE_ALIASES = ("atlassian", "claude_ai_Atlassian")
# Claude Code reads a PreToolUse matcher made only of these characters as a list
# of exact tool names separated by `|` or `,`; anything else is a regex.
_PLAIN_MATCHER_RE = re.compile(r"[A-Za-z0-9_|, -]+")
# `<interpreter> <path>/hook_dispatcher.py PreToolUse` and nothing else: no
# wrapper (`sops exec-env`, `export`, `cd … ||`) that more tools would also run.
_BARE_DISPATCHER_RE = re.compile(r'\s*\S+\s+\S*hook_dispatcher\.py"?\s+PreToolUse\s*')
# Anchor to $CLAUDE_PROJECT_DIR (like the openspec-apply-enforce hook) instead of
# a bare relative path. A relative `.ai-playbook/...` resolves against the hook's
# cwd — which can be a sibling repo when the session's shell has cd'd away — so a
# missing-file error (exit 2) blocks EVERY Edit/Write/Bash, leaving no tool able
# to repair settings.json. The absolute form removes that cwd fragility.
DISPATCHER_PRE_TOOL_USE_COMMAND = (
    'python "$CLAUDE_PROJECT_DIR/.ai-playbook/scripts/hook_dispatcher.py" PreToolUse'
)
DISPATCHER_PRE_TOOL_USE_TIMEOUT = 10
DISPATCHER_IDENTITY = "hook_dispatcher.py"


def merge_required_dispatcher(
    settings: dict[str, Any], *, available: bool = True
) -> dict[str, Any]:
    """Ensure the generic L1 dispatcher PreToolUse entry. Idempotent.

    Deduped by the ``hook_dispatcher.py`` basename, so re-running never
    duplicates; canonical tools the existing dispatcher wiring does not route
    yet are added to it (see ``_widen_dispatcher_matcher``).

    ``available`` lets the caller suppress the entry when the consumer's submodule
    pin does NOT ship ``hook_dispatcher.py`` (older pins). Wiring a hook to an
    absent script would exit 2 on every tool call and block the whole session;
    the impure caller (``_managed_files``) does the on-disk existence check and
    passes the result here so this helper stays filesystem-free.
    """
    if not available:
        return dict(settings)
    out = ensure_hooks(settings, [{
        "event": "PreToolUse",
        "matcher": DISPATCHER_PRE_TOOL_USE_MATCHER,
        "command": DISPATCHER_PRE_TOOL_USE_COMMAND,
        "timeout": DISPATCHER_PRE_TOOL_USE_TIMEOUT,
        "identity": DISPATCHER_IDENTITY,
    }])
    return _widen_dispatcher_matcher(out)


def _plain_names(matcher: str) -> list[str]:
    return [p.strip() for p in re.split(r"[|,]", matcher) if p.strip()]


def _matcher_routes(matcher: object, tool: str) -> bool:
    """Whether a PreToolUse ``matcher`` sends ``tool`` to its hooks, read the way
    Claude Code reads it: empty or ``*`` match every tool, a plain ``A|B`` list
    matches names exactly, anything else is an unanchored regex search."""
    if matcher in (None, "", "*"):
        return True
    if not isinstance(matcher, str):
        return False
    if _PLAIN_MATCHER_RE.fullmatch(matcher):
        return tool in _plain_names(matcher)
    try:
        return re.search(matcher, tool) is not None
    except re.error:
        return False


def _routed_dispatcher_tools(matcher: object) -> set[str]:
    routed = {t for t in _DISPATCHER_TOOLS if _matcher_routes(matcher, t)}
    routed.update(t for t in _DISPATCHER_MCP_TOOLS
                  if all(_matcher_routes(matcher, f"mcp__{a}__{t}") for a in _MCP_PROBE_ALIASES))
    return routed


def _widen_dispatcher_matcher(settings: dict[str, Any]) -> dict[str, Any]:
    """Route every canonical tool to the dispatcher by ADDING the missing ones.

    Basename dedup alone would freeze an older ``Edit|Write|MultiEdit|Bash``
    entry forever, leaving TaskStop/KillShell/Jira rules silently inert. The
    tools no dispatcher entry routes yet are appended to the matcher of the first
    entry that holds only bare dispatcher hooks (a matcher an earlier version
    wrote becomes the canonical one); without such an entry they get a new entry
    of their own. A matcher is never narrowed, a hook is never moved or dropped,
    and a tool some dispatcher entry already routes is not routed again, so a
    wrapped (``sops exec-env …``) or shared entry keeps exactly its routing.
    """
    entries = settings["hooks"].get("PreToolUse")
    if not isinstance(entries, list):
        return settings

    def _hooks(e: Any) -> list[Any]:
        return e["hooks"] if isinstance(e, dict) and isinstance(e.get("hooks"), list) else []

    def _is_disp(h: Any) -> bool:
        return isinstance(h, dict) and _command_has_identity(h.get("command"), DISPATCHER_IDENTITY)

    routed: set[str] = set()
    for e in entries:
        if any(_is_disp(h) for h in _hooks(e)):
            routed |= _routed_dispatcher_tools(e.get("matcher"))
    missing = [t for t in _DISPATCHER_TOOLS if t not in routed]
    missing_mcp = [t for t in _DISPATCHER_MCP_TOOLS if t not in routed]
    if not missing and not missing_mcp:
        return settings

    def _extendable(e: Any) -> bool:
        m = e.get("matcher") if isinstance(e, dict) else None
        if not isinstance(m, str) or not _hooks(e):
            return False
        try:
            re.compile(m)
        except re.error:
            return False
        return all(_is_disp(h) and _BARE_DISPATCHER_RE.fullmatch(str(h["command"])) for h in _hooks(e))

    addition = _dispatcher_matcher(missing, missing_mcp)
    new_entries = list(entries)
    idx = next((i for i, e in enumerate(entries) if _extendable(e)), None)
    if idx is None:
        new_entries.append({"matcher": addition, "hooks": [{
            "type": "command",
            "command": DISPATCHER_PRE_TOOL_USE_COMMAND,
            "timeout": DISPATCHER_PRE_TOOL_USE_TIMEOUT,
        }]})
    else:
        matcher = entries[idx]["matcher"]
        if matcher in _PREVIOUS_DISPATCHER_MATCHERS and routed <= _routed_dispatcher_tools(matcher):
            new_matcher = DISPATCHER_PRE_TOOL_USE_MATCHER
        else:
            if _PLAIN_MATCHER_RE.fullmatch(matcher):
                # Normalise to `A|B` first: once the addition makes the matcher a
                # regex, `Edit, Write` would mean that literal text and an empty
                # alternative (`Edit|`) would match every tool.
                matcher = "|".join(_plain_names(matcher))
            new_matcher = "|".join(p for p in (matcher, addition) if p)
        new_entries[idx] = {**entries[idx], "matcher": new_matcher}
    return {**settings, "hooks": {**settings["hooks"], "PreToolUse": new_entries}}


# Hooks run in the session's CURRENT cwd, which drifts whenever the agent `cd`s
# (into a subdirectory or a sibling repo). A bare `.ai-playbook/...` path then
# names a missing file, and a UserPromptSubmit / PreToolUse hook that exits
# non-zero blocks the prompt or every tool call. Claude Code sets
# $CLAUDE_PROJECT_DIR for every hook, so anchoring to it removes the drift.
_REL_PROJECT_PATH_RE = re.compile(r"(?<![\w$/.{}-])((?:\.ai-playbook|\.claude)/[\w./-]+)")
_SOPS_REL_ENV_FILE_RE = re.compile(r"(\bsops\s+exec-env\s+)(?![A-Za-z]:)([\w.][\w./-]*)")


def anchor_command(command: str) -> str:
    """Anchor a hook command's project-relative paths to ``$CLAUDE_PROJECT_DIR``.

    Rewrites ``.ai-playbook/…`` / ``.claude/…`` script paths and a relative
    ``sops exec-env <file>`` argument. Commands that already mention
    ``CLAUDE_PROJECT_DIR`` or contain quotes are hand-written shell (a ``cd``
    prefix, nested ``sh -c "…"`` strings) and are returned untouched rather
    than risk breaking their quoting.
    """
    if "CLAUDE_PROJECT_DIR" in command or '"' in command or "'" in command:
        return command
    out = _SOPS_REL_ENV_FILE_RE.sub(r'\1"$CLAUDE_PROJECT_DIR/\2"', command)
    return _REL_PROJECT_PATH_RE.sub(r'"$CLAUDE_PROJECT_DIR/\1"', out)


def anchor_hook_commands(settings: dict[str, Any]) -> dict[str, Any]:
    """Apply :func:`anchor_command` to every hook command. Returns a new dict;
    everything else (events, matchers, timeouts, other keys) is kept as-is."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return dict(settings)
    new_hooks: dict[str, Any] = {}
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            new_hooks[event] = entries
            continue
        new_entries = []
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("hooks"), list):
                entry = dict(entry)
                entry["hooks"] = [
                    {**h, "command": anchor_command(h["command"])}
                    if isinstance(h, dict) and isinstance(h.get("command"), str) else h
                    for h in entry["hooks"]
                ]
            new_entries.append(entry)
        new_hooks[event] = new_entries
    out = dict(settings)
    out["hooks"] = new_hooks
    return out


def merge_permissions(
    settings: dict[str, Any],
    *,
    allow: list[str] | None = None,
    additional_directories: list[str] | None = None,
) -> dict[str, Any]:
    """Union-merge ``permissions.allow`` / ``permissions.additionalDirectories``.

    Order-preserving, de-duplicated, additive (never drops existing entries).
    Returns a new dict; inputs are not mutated.
    """
    if not allow and not additional_directories:
        return dict(settings)
    out = dict(settings)
    perms = dict(out.get("permissions", {})) if isinstance(out.get("permissions"), dict) else {}

    if allow:
        cur = list(perms.get("allow", [])) if isinstance(perms.get("allow"), list) else []
        for a in allow:
            if a not in cur:
                cur.append(a)
        perms["allow"] = cur
    if additional_directories:
        cur = (
            list(perms.get("additionalDirectories", []))
            if isinstance(perms.get("additionalDirectories"), list) else []
        )
        for d in additional_directories:
            if d not in cur:
                cur.append(d)
        perms["additionalDirectories"] = cur

    out["permissions"] = perms
    return out


__all__ = [
    "DISPATCHER_IDENTITY",
    "DISPATCHER_PRE_TOOL_USE_COMMAND",
    "DISPATCHER_PRE_TOOL_USE_MATCHER",
    "DISPATCHER_PRE_TOOL_USE_TIMEOUT",
    "REQUIRED_PRE_TOOL_USE_COMMAND",
    "REQUIRED_PRE_TOOL_USE_IDENTITY",
    "REQUIRED_PRE_TOOL_USE_MATCHER",
    "REQUIRED_PRE_TOOL_USE_TIMEOUT",
    "anchor_command",
    "anchor_hook_commands",
    "command_identity",
    "ensure_hooks",
    "has_hook",
    "merge_permissions",
    "merge_required_dispatcher",
    "merge_required_pretooluse",
]
