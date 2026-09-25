"""Identity-based deep-merge helpers for Claude/agnostic settings JSON.

Shared by ``scripts/_renderers/settings.py`` (the door's ``.claude/settings.json``
renderer) and ``scripts/rules/claude-settings.rule.py`` (the L1 validate gate).
The contract everywhere is the same: NEVER remove or reorder consumer-authored
content — only ENSURE that a required hook exists, deduping by the command's
script identity (basename) rather than by an exact matcher string. Matching by
basename is what lets the canonical template's ``Edit|Write|MultiEdit|Bash``
matcher satisfy the ``Edit|Write|MultiEdit`` invariant without producing a
duplicate PreToolUse entry. The one rewrite allowed is ``anchor_hook_commands``,
which anchors cwd-relative script paths to ``$CLAUDE_PROJECT_DIR``.

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


def command_identity(command: str) -> str:
    """Return the script basename used to dedupe hook commands.

    ``"sops exec-env -- python .claude/hooks/openspec-apply-enforce.py"`` and
    ``"python .claude/hooks/openspec-apply-enforce.py"`` both reduce to
    ``"openspec-apply-enforce.py"`` so the invariant is matched regardless of
    wrapper prefixes, path separators or a quoted ``"$CLAUDE_PROJECT_DIR/…"`` path.
    """
    token = command.replace("\\", "/").split()[-1] if command.strip() else command
    return token.strip("\"'").rsplit("/", 1)[-1]


def has_hook(settings: dict[str, Any], event: str, identity: str) -> bool:
    """True iff some hook under ``settings.hooks[event]`` carries ``identity``
    as a substring of its command (any matcher)."""
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
            if isinstance(h, dict) and identity and identity in str(h.get("command", "")):
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
        # An explicit `identity` overrides basename dedup — needed when the
        # command carries a trailing arg (e.g. `... hook_dispatcher.py PreToolUse`)
        # so the last token isn't the script name.
        identity = h.get("identity") or command_identity(str(command))

        entries = list(hooks_root.get(event, [])) if isinstance(hooks_root.get(event), list) else []
        if any(
            isinstance(e, dict) and isinstance(e.get("hooks"), list) and any(
                isinstance(x, dict) and identity and identity in str(x.get("command", ""))
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
DISPATCHER_PRE_TOOL_USE_MATCHER = "Edit|Write|MultiEdit|Bash"
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

    Deduped by the ``hook_dispatcher.py`` basename (an explicit identity, since
    the command carries a trailing ``PreToolUse`` arg), so any matcher satisfies
    it and re-running never duplicates.

    ``available`` lets the caller suppress the entry when the consumer's submodule
    pin does NOT ship ``hook_dispatcher.py`` (older pins). Wiring a hook to an
    absent script would exit 2 on every tool call and block the whole session;
    the impure caller (``_managed_files``) does the on-disk existence check and
    passes the result here so this helper stays filesystem-free.
    """
    if not available:
        return dict(settings)
    return ensure_hooks(settings, [{
        "event": "PreToolUse",
        "matcher": DISPATCHER_PRE_TOOL_USE_MATCHER,
        "command": DISPATCHER_PRE_TOOL_USE_COMMAND,
        "timeout": DISPATCHER_PRE_TOOL_USE_TIMEOUT,
        "identity": DISPATCHER_IDENTITY,
    }])


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
