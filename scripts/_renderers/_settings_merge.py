"""Identity-based deep-merge helpers for Claude/agnostic settings JSON.

Shared by ``scripts/_renderers/settings.py`` (the door's ``.claude/settings.json``
renderer) and ``scripts/rules/claude-settings.rule.py`` (the L1 validate gate).
The contract everywhere is the same: NEVER remove or reorder consumer-authored
content — only ENSURE that a required hook exists, deduping by the command's
script identity (basename) rather than by an exact matcher string. Matching by
basename is what lets the canonical template's ``Edit|Write|MultiEdit|Bash``
matcher satisfy the ``Edit|Write|MultiEdit`` invariant without producing a
duplicate PreToolUse entry.

Stdlib-only; pure functions (no filesystem, no mutation of inputs).
"""
from __future__ import annotations

from typing import Any

# Canonical PreToolUse invariant. Source of truth:
# templates/new-project/.claude/settings.json.tmpl (which may extend the matcher,
# e.g. with `|Bash`). The invariant is satisfied as long as the enforce hook's
# script is wired under PreToolUse by *some* matcher.
REQUIRED_PRE_TOOL_USE_MATCHER = "Edit|Write|MultiEdit"
REQUIRED_PRE_TOOL_USE_COMMAND = "python .claude/hooks/openspec-apply-enforce.py"
REQUIRED_PRE_TOOL_USE_TIMEOUT = 10
REQUIRED_PRE_TOOL_USE_IDENTITY = "openspec-apply-enforce.py"


def command_identity(command: str) -> str:
    """Return the script basename used to dedupe hook commands.

    ``"sops exec-env -- python .claude/hooks/openspec-apply-enforce.py"`` and
    ``"python .claude/hooks/openspec-apply-enforce.py"`` both reduce to
    ``"openspec-apply-enforce.py"`` so the invariant is matched regardless of
    wrapper prefixes or path separators.
    """
    token = command.replace("\\", "/").split()[-1] if command.strip() else command
    return token.rsplit("/", 1)[-1]


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
        identity = command_identity(str(command))

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
    "REQUIRED_PRE_TOOL_USE_COMMAND",
    "REQUIRED_PRE_TOOL_USE_IDENTITY",
    "REQUIRED_PRE_TOOL_USE_MATCHER",
    "REQUIRED_PRE_TOOL_USE_TIMEOUT",
    "command_identity",
    "ensure_hooks",
    "has_hook",
    "merge_permissions",
    "merge_required_pretooluse",
]
