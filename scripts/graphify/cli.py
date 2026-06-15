"""Graphify feature CLI — toggle state + in-repo side effects.

Subcommands
-----------
    python -m scripts.graphify status [--json] [--project PATH]
    python -m scripts.graphify on  [--components <csv>] [--project PATH]
    python -m scripts.graphify off [--project PATH]

Components (default on `on`: agent_guidance,gitignore_hygiene):
    agent_guidance     — inject the query-first guidance block into AGENTS.md
                         (auto-managed; backed up first).
    gitignore_hygiene  — run the graphify-adoption rule's `apply` so the
                         per-machine/per-run graph state is gitignored.
    enforce_skill      — capability flag for the graphify skill (no side effect).

NOTE — graphify wraps an EXTERNAL tool. This CLI manages the in-repo side
effects only; it CANNOT install `graphifyy` or run `graphify hook install`
(per-machine / per-clone). `on` prints those manual next steps.

Exit codes per docs/rules/error-message-standard.rule.md:
    0 ok · 1 user-actionable error · 2 environment/setup error
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts.graphify import materialise as materialise_mod  # noqa: E402
from scripts.graphify import toggle  # noqa: E402

VALID_COMPONENTS = toggle.COMPONENTS
DEFAULT_COMPONENTS = "agent_guidance,gitignore_hygiene"
NEXT_STEPS = (
    "next steps (per machine / per clone — this CLI cannot do them for you):\n"
    "   1. uv tool install \"graphifyy>=0.8.31\"   # or pipx\n"
    "   2. graphify hook install                   # graph.json union-merge driver"
)


def _emit_error(*, why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def _resolve_project_root(arg_project: Path | None) -> Path | None:
    if arg_project is not None:
        return arg_project.expanduser().resolve()
    return toggle.find_project_root()


def _applied_by_default() -> str | None:
    return os.environ.get("USER") or os.environ.get("USERNAME") or None


def _run_gitignore_hygiene(root: Path) -> tuple[bool, str]:
    """Load the graphify-adoption rule by path and run its `apply` on `root`.

    Returns (ok, detail). The rule's filename carries dots/hyphens so it is not
    importable as a module — load it via a file spec.
    """
    playbook = toggle.find_playbook_root()
    if playbook is None:
        return False, "ai-playbook root not found for graphify-adoption rule"
    rule_path = playbook / "scripts" / "rules" / "graphify-adoption.rule.py"
    if not rule_path.is_file():
        return False, f"rule not found: {rule_path}"
    spec = importlib.util.spec_from_file_location("_graphify_adoption_rule", rule_path)
    if spec is None or spec.loader is None:
        return False, "could not load graphify-adoption rule"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rc = mod.apply(dry_run=False, cwd=root)
    return rc == 0, f"graphify-adoption.rule apply exit {rc}"


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    root = _resolve_project_root(getattr(args, "project", None))
    if root is None:
        _emit_error(
            why="cannot resolve project root",
            where="graphify:status",
            fix="run from inside a project containing AGENTS.md or pass --project <PATH>.",
        )
        return 2
    try:
        state = toggle.read_state(root)
    except (ValueError, FileNotFoundError) as e:
        _emit_error(
            why=str(e),
            where=f"graphify:status:{root.as_posix()}",
            fix="repair or delete the corrupt state file then re-run `graphify on`.",
        )
        return 1

    materialised = materialise_mod.is_materialised(root)
    out = {
        "project_root": root.as_posix(),
        "state_path": toggle.state_path(root).as_posix(),
        "state": state,
        "derived": {"materialised": materialised},
    }
    if getattr(args, "json", False):
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        enabled = "ON" if state.get("enabled") else "OFF"
        print(f"graphify: {enabled}")
        print(f"project: {root}")
        print(f"state:   {toggle.state_path(root)}")
        print(f"guidance block in AGENTS.md: {'yes' if materialised else 'no'}")
        print("components:")
        for k in VALID_COMPONENTS:
            mark = "✓" if (state.get("components") or {}).get(k, False) else "·"
            print(f"  {mark} {k}")
    return 0


def cmd_on(args: argparse.Namespace) -> int:
    root = _resolve_project_root(getattr(args, "project", None))
    if root is None:
        _emit_error(
            why="cannot resolve project root",
            where="graphify:on",
            fix="run from inside a project directory or pass --project <PATH>.",
        )
        return 2

    components_csv = (args.components or DEFAULT_COMPONENTS).strip()
    requested = [c.strip() for c in components_csv.split(",") if c.strip()]
    bad = [c for c in requested if c not in VALID_COMPONENTS]
    if bad:
        _emit_error(
            why=f"invalid component(s): {bad}",
            where="graphify:on:components",
            fix=f"valid keys: {', '.join(VALID_COMPONENTS)}.",
        )
        return 1

    # Side effects FIRST so we never end up state-says-ON but not materialised.
    side_effects: dict[str, Any] = {}
    if "agent_guidance" in requested:
        try:
            backup = materialise_mod.materialise(root)
            side_effects["agents_md_backup"] = backup.as_posix()
        except (FileNotFoundError, ValueError, LookupError) as e:
            _emit_error(
                why=f"materialise failed: {e}",
                where="graphify:on:materialise",
                fix="ensure AGENTS.md exists and skills/graphify/SKILL.md has the required H2 sections.",
            )
            return 1

    if "gitignore_hygiene" in requested:
        ok, detail = _run_gitignore_hygiene(root)
        side_effects["gitignore_hygiene"] = detail
        if not ok:
            _emit_error(
                why=f"gitignore hygiene failed: {detail}",
                where="graphify:on:gitignore",
                fix="run `python .ai-playbook/scripts/rules/graphify-adoption.rule.py apply` manually.",
            )
            return 1

    state = toggle.read_state(root)
    state["enabled"] = True
    state["components"] = {c: (c in requested) for c in VALID_COMPONENTS}
    state["applied_at"] = datetime.now(UTC).isoformat()
    ab = _applied_by_default()
    if ab:
        state["applied_by"] = ab

    try:
        toggle.write_state(root, state)
    except Exception as e:  # noqa: BLE001
        _emit_error(
            why=f"failed to write state: {e}",
            where="graphify:on:write",
            fix="check file permissions on .ai-playbook/graphify.json and re-run.",
        )
        return 2

    if args.json:
        print(json.dumps({"ok": True, "state": state, "side_effects": side_effects}, indent=2, ensure_ascii=False))
    else:
        print(f"✅ graphify ON at {root}")
        print(f"   components: {', '.join(requested)}")
        if "agents_md_backup" in side_effects:
            print(f"   guidance block materialised in AGENTS.md (backup: {side_effects['agents_md_backup']})")
        if "gitignore_hygiene" in side_effects:
            print(f"   {side_effects['gitignore_hygiene']}")
        print(f"   {NEXT_STEPS}")
    return 0


def cmd_off(args: argparse.Namespace) -> int:
    root = _resolve_project_root(getattr(args, "project", None))
    if root is None:
        _emit_error(why="cannot resolve project root", where="graphify:off", fix="pass --project <PATH>.")
        return 2

    side_effects: dict[str, Any] = {}
    try:
        backup = materialise_mod.strip(root)
        if backup is not None:
            side_effects["agents_md_backup"] = backup.as_posix()
    except (FileNotFoundError, ValueError) as e:
        _emit_error(
            why=f"strip failed: {e}",
            where="graphify:off:strip",
            fix="resolve AGENTS.md manually (multiple graphify blocks / bad markers) then re-run.",
        )
        return 1

    state = toggle.read_state(root)
    state["enabled"] = False
    state["components"] = {c: False for c in VALID_COMPONENTS}
    state["applied_at"] = datetime.now(UTC).isoformat()
    ab = _applied_by_default()
    if ab:
        state["applied_by"] = ab

    try:
        toggle.write_state(root, state)
    except Exception as e:  # noqa: BLE001
        _emit_error(
            why=f"failed to write state: {e}",
            where="graphify:off:write",
            fix="check file permissions on .ai-playbook/graphify.json and re-run.",
        )
        return 2

    if args.json:
        print(json.dumps({"ok": True, "state": state, "side_effects": side_effects}, indent=2, ensure_ascii=False))
    else:
        print(f"✅ graphify OFF at {root}")
        if "agents_md_backup" in side_effects:
            print(f"   AGENTS.md guidance block stripped (backup: {side_effects['agents_md_backup']})")
        print("   note: .gitignore entries left in place (harmless; remove manually if desired).")
    return 0


# ---------------------------------------------------------------------------
# Argparse plumbing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--project",
        type=Path,
        default=argparse.SUPPRESS,
        help="Project root (default: auto-detect from cwd by walking up to AGENTS.md).",
    )

    p = argparse.ArgumentParser(prog="graphify", description="Graphify feature toggle CLI.", parents=[shared])
    sub = p.add_subparsers(dest="cmd")

    s_status = sub.add_parser("status", help="Show current toggle state.", parents=[shared])
    s_status.add_argument("--json", action="store_true", help="JSON output for UI consumers.")
    s_status.set_defaults(func=cmd_status)

    s_on = sub.add_parser("on", help="Enable graphify for this project.", parents=[shared])
    s_on.add_argument(
        "--components",
        default=DEFAULT_COMPONENTS,
        help=f"Comma-separated component keys ({', '.join(VALID_COMPONENTS)}).",
    )
    s_on.add_argument("--json", action="store_true")
    s_on.set_defaults(func=cmd_on)

    s_off = sub.add_parser("off", help="Disable graphify for this project.", parents=[shared])
    s_off.add_argument("--json", action="store_true")
    s_off.set_defaults(func=cmd_off)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        return cmd_status(argparse.Namespace(project=getattr(args, "project", None), json=False))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
