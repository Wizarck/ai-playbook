"""L1 hardrule: claude-settings (paired with docs/rules/claude-settings.rule.md).

Verifies that a consumer repository configured for Claude Code declares the
playbook's required hooks in `.claude/settings.json` (or its `.local.json`
variant). The canonical hook surface is `templates/new-project/.claude/settings.json.tmpl`
in the playbook submodule; at minimum the PreToolUse matcher
`Edit|Write|MultiEdit` MUST wire `python .claude/hooks/openspec-apply-enforce.py`.

`apply` performs an idempotent deep-merge of the missing declarations into the
existing JSON, preserving user-added keys (formatters, telemetry, custom
SessionStart hooks). It will NOT clobber a divergent existing matcher.

CLI:
    python scripts/rules/claude-settings.rule.py validate
    python scripts/rules/claude-settings.rule.py apply [--dry-run]

Exit codes:
    0 — settings.json declares the required hooks, OR Claude Code not in use here.
    1 — required hook declarations missing / drift.
    2 — fatal (no readable consumer root, or malformed JSON on disk).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

SKIP_ENV = "AIPLAYBOOK_CLAUDE_SETTINGS_SKIP"

# Canonical required hook declarations. Source of truth:
# templates/new-project/.claude/settings.json.tmpl. The SessionStart hook in
# the template carries a project-specific SOPS path and a `{{PROJECT_BANK}}`
# placeholder, so it cannot be auto-merged generically — the rule requires
# only the PreToolUse matcher, which is the LLM-agnostic invariant.
REQUIRED_PRE_TOOL_USE_MATCHER = "Edit|Write|MultiEdit"
REQUIRED_PRE_TOOL_USE_COMMAND = "python .claude/hooks/openspec-apply-enforce.py"
REQUIRED_PRE_TOOL_USE_TIMEOUT = 10


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(f"   OVERRIDE: {SKIP_ENV}=1", file=sys.stderr)


def _consumer_root(cwd: Path | None = None) -> Path | None:
    """Locate the consumer root: directory containing AGENTS.md."""
    cur = (cwd or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / "AGENTS.md").is_file():
            return p
    return None


def _claude_in_use(root: Path) -> bool:
    """Heuristic: is this repo configured for Claude Code? True iff `.claude/` exists."""
    return (root / ".claude").is_dir()


def _settings_path(root: Path) -> Path:
    """Prefer `.claude/settings.local.json` if present, else `.claude/settings.json`."""
    local = root / ".claude" / "settings.local.json"
    if local.is_file():
        return local
    return root / ".claude" / "settings.json"


def _load_settings(path: Path) -> dict[str, Any] | None:
    """Read and parse settings JSON. Returns None on missing file. Raises on invalid JSON."""
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def _has_required_pretooluse(settings: dict[str, Any]) -> bool:
    """Check the parsed settings for the required PreToolUse declaration.

    Matches by COMMAND identity (the enforce script's basename) under ANY
    PreToolUse matcher, not by an exact matcher string. The canonical template
    ships ``Edit|Write|MultiEdit|Bash`` (v0.20.0+); requiring an exact
    ``Edit|Write|MultiEdit`` matcher would false-flag that as drift and would
    push apply_config's settings renderer to append a duplicate entry. The
    invariant is satisfied as long as the script is wired under PreToolUse.
    """
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    pre = hooks.get("PreToolUse")
    if not isinstance(pre, list):
        return False
    for entry in pre:
        if not isinstance(entry, dict):
            continue
        sub_hooks = entry.get("hooks")
        if not isinstance(sub_hooks, list):
            continue
        for h in sub_hooks:
            if not isinstance(h, dict):
                continue
            cmd = h.get("command", "")
            # Match by substring on the script path — allow optional `sops exec-env` prefixes.
            if "openspec-apply-enforce.py" in str(cmd):
                return True
    return False


def validate(cwd: Path | None = None) -> int:
    if os.environ.get(SKIP_ENV):
        return 0
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2
    if not _claude_in_use(root):
        return 0  # not applicable for this consumer

    path = _settings_path(root)
    if not path.is_file():
        _emit_error(
            why=".claude/settings.json missing",
            where=str(path),
            fix="run `python .ai-playbook/scripts/rules/claude-settings.rule.py apply`.",
        )
        return 1

    try:
        settings = _load_settings(path)
    except json.JSONDecodeError as exc:
        _emit_error(
            why=f"settings JSON malformed: {exc}",
            where=str(path),
            fix="fix the JSON syntax by hand, then re-run validate.",
        )
        return 2
    except OSError as exc:
        _emit_error(why=str(exc), where=str(path), fix="check file permissions.")
        return 2

    if settings is None:
        # _load_settings returned None only if the file disappeared between is_file() and read.
        _emit_error(why=".claude/settings.json unreadable", where=str(path), fix="re-create the file.")
        return 1

    if not _has_required_pretooluse(settings):
        _emit_error(
            why="PreToolUse matcher 'Edit|Write|MultiEdit' for openspec-apply-enforce.py missing",
            where=str(path),
            fix="run `python .ai-playbook/scripts/rules/claude-settings.rule.py apply` to merge it.",
        )
        return 1

    return 0


def _merge_required_pretooluse(settings: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge the required PreToolUse declaration into `settings`. Returns a NEW dict.

    Idempotent: if the required matcher+command already exists, the input is returned
    structurally unchanged. Preserves all other top-level keys and other matchers.
    """
    # If the enforce script is already wired under PreToolUse by ANY matcher
    # (e.g. the template's `Edit|Write|MultiEdit|Bash`), do not append a second
    # entry — return a structural copy unchanged.
    if _has_required_pretooluse(settings):
        return dict(settings)

    # Shallow copy at each layer that we mutate.
    out = dict(settings)
    hooks = dict(out.get("hooks", {})) if isinstance(out.get("hooks"), dict) else {}
    pre = list(hooks.get("PreToolUse", [])) if isinstance(hooks.get("PreToolUse"), list) else []

    required_hook_obj = {
        "type": "command",
        "command": REQUIRED_PRE_TOOL_USE_COMMAND,
        "timeout": REQUIRED_PRE_TOOL_USE_TIMEOUT,
    }

    # Look for an existing matcher entry to merge into.
    found_matcher_idx: int | None = None
    for i, entry in enumerate(pre):
        if isinstance(entry, dict) and entry.get("matcher") == REQUIRED_PRE_TOOL_USE_MATCHER:
            found_matcher_idx = i
            break

    if found_matcher_idx is None:
        pre.append({
            "matcher": REQUIRED_PRE_TOOL_USE_MATCHER,
            "hooks": [required_hook_obj],
        })
    else:
        entry = dict(pre[found_matcher_idx])
        sub_hooks = list(entry.get("hooks", [])) if isinstance(entry.get("hooks"), list) else []
        already_present = any(
            isinstance(h, dict) and "openspec-apply-enforce.py" in str(h.get("command", ""))
            for h in sub_hooks
        )
        if not already_present:
            sub_hooks.append(required_hook_obj)
        entry["hooks"] = sub_hooks
        pre[found_matcher_idx] = entry

    hooks["PreToolUse"] = pre
    out["hooks"] = hooks
    return out


def apply(*, dry_run: bool, cwd: Path | None = None) -> int:
    """Deep-merge the required hook declarations into `.claude/settings.json`. Idempotent."""
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2

    if not _claude_in_use(root):
        # Bootstrap: create `.claude/` so the heuristic flips for next validate.
        (root / ".claude").mkdir(parents=True, exist_ok=True)

    path = _settings_path(root)
    # If no local override exists, target the canonical settings.json (not .local.json).
    if path.name == "settings.local.json" and not path.is_file():
        path = root / ".claude" / "settings.json"

    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = _load_settings(path)
            if loaded is not None:
                existing = loaded
        except json.JSONDecodeError as exc:
            print(f"error: cannot parse existing {path}: {exc}", file=sys.stderr)
            return 2
        except OSError as exc:
            print(f"error: cannot read {path}: {exc}", file=sys.stderr)
            return 2

    merged = _merge_required_pretooluse(existing)

    if merged == existing and _has_required_pretooluse(existing):
        print(f"ok: {path} already declares required hooks (no-op)")
        return 0

    new_text = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"

    if dry_run:
        print(f"[dry-run] would write {path}")
        print(new_text)
        return 0

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_text, encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write {path}: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claude-settings")
    parser.add_argument("subcommand", choices=["validate", "apply"])
    parser.add_argument("--dry-run", action="store_true", help="With 'apply': print plan, mutate nothing.")
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    if args.subcommand == "apply":
        return apply(dry_run=args.dry_run)
    return 2


if __name__ == "__main__":
    # File-path invocation from a consumer root: put the playbook root on
    # sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("claude-settings", main))
