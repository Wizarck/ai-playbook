"""Ponytail feature CLI — single entry point for toggle state + side effects.

Subcommands
-----------
    python -m scripts.ponytail status [--json] [--project PATH]
    python -m scripts.ponytail on  [--mode lite|full|ultra] [--components <csv>] [--project PATH]
    python -m scripts.ponytail off [--project PATH]

Components (default on `on`: code_style):
    code_style        — inject the ponytail ladder block into AGENTS.md
                        (auto-managed; backed up first) + enable the per-turn
                        reinforcement hook. The only component with a side effect.
    review_ponytail   — capability flag for the /ponytail-review skill (no side effect).
    audit_ponytail    — capability flag for the /ponytail-audit skill (no side effect).
    debt_ponytail     — capability flag for the /ponytail-debt skill (no side effect).

Exit codes per docs/rules/error-message-standard.rule.md:
    0 ok · 1 user-actionable error · 2 environment/setup error
"""
from __future__ import annotations

import argparse
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

from scripts.ponytail import materialise as materialise_mod  # noqa: E402
from scripts.ponytail import toggle  # noqa: E402

VALID_MODES = toggle.MODES
VALID_COMPONENTS = toggle.COMPONENTS
DEFAULT_COMPONENTS = "code_style"


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


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    root = _resolve_project_root(getattr(args, "project", None))
    if root is None:
        _emit_error(
            why="cannot resolve project root",
            where="ponytail:status",
            fix="run from inside a project containing AGENTS.md or pass --project <PATH>.",
        )
        return 2
    try:
        state = toggle.read_state(root)
    except (ValueError, FileNotFoundError) as e:
        _emit_error(
            why=str(e),
            where=f"ponytail:status:{root.as_posix()}",
            fix="repair or delete the corrupt state file then re-run `ponytail on`.",
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
        mode = state.get("mode", "—")
        print(f"ponytail: {enabled} (mode={mode})")
        print(f"project: {root}")
        print(f"state:   {toggle.state_path(root)}")
        print(f"ladder block in AGENTS.md: {'yes' if materialised else 'no'}")
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
            where="ponytail:on",
            fix="run from inside a project directory or pass --project <PATH>.",
        )
        return 2

    mode = args.mode
    if mode not in VALID_MODES:
        _emit_error(
            why=f"invalid mode '{mode}'",
            where="ponytail:on:mode",
            fix=f"pass --mode one of: {', '.join(VALID_MODES)}.",
        )
        return 1

    components_csv = (args.components or DEFAULT_COMPONENTS).strip()
    requested = [c.strip() for c in components_csv.split(",") if c.strip()]
    bad = [c for c in requested if c not in VALID_COMPONENTS]
    if bad:
        _emit_error(
            why=f"invalid component(s): {bad}",
            where="ponytail:on:components",
            fix=f"valid keys: {', '.join(VALID_COMPONENTS)}.",
        )
        return 1

    # Side effect FIRST so we never end up state-says-ON but not materialised.
    side_effects: dict[str, Any] = {}
    if "code_style" in requested:
        try:
            backup = materialise_mod.materialise(root, mode)
            side_effects["agents_md_backup"] = backup.as_posix()
        except (FileNotFoundError, ValueError, LookupError) as e:
            _emit_error(
                why=f"materialise failed: {e}",
                where="ponytail:on:materialise",
                fix="ensure AGENTS.md exists and skills/ponytail/SKILL.md has the required H2 sections.",
            )
            return 1

    state = toggle.read_state(root)
    state["enabled"] = True
    state["mode"] = mode
    state["components"] = {c: (c in requested) for c in VALID_COMPONENTS}
    state["applied_at"] = datetime.now(UTC).isoformat()
    ab = _applied_by_default()
    if ab:
        state["applied_by"] = ab

    try:
        toggle.write_state(root, state)
    except Exception as e:  # noqa: BLE001 — any write error becomes env error
        _emit_error(
            why=f"failed to write state: {e}",
            where="ponytail:on:write",
            fix="check file permissions on .ai-playbook/ponytail.json and re-run.",
        )
        return 2

    if args.json:
        print(json.dumps({"ok": True, "state": state, "side_effects": side_effects}, indent=2, ensure_ascii=False))
    else:
        print(f"✅ ponytail ON (mode={mode}) at {root}")
        print(f"   components: {', '.join(requested)}")
        if "agents_md_backup" in side_effects:
            print(f"   ladder block materialised in AGENTS.md (backup: {side_effects['agents_md_backup']})")
    return 0


def cmd_off(args: argparse.Namespace) -> int:
    root = _resolve_project_root(getattr(args, "project", None))
    if root is None:
        _emit_error(why="cannot resolve project root", where="ponytail:off", fix="pass --project <PATH>.")
        return 2

    side_effects: dict[str, Any] = {}
    try:
        backup = materialise_mod.strip(root)
        if backup is not None:
            side_effects["agents_md_backup"] = backup.as_posix()
    except (FileNotFoundError, ValueError) as e:
        _emit_error(
            why=f"strip failed: {e}",
            where="ponytail:off:strip",
            fix="resolve AGENTS.md manually (multiple ponytail blocks / bad markers) then re-run.",
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
            where="ponytail:off:write",
            fix="check file permissions on .ai-playbook/ponytail.json and re-run.",
        )
        return 2

    if args.json:
        print(json.dumps({"ok": True, "state": state, "side_effects": side_effects}, indent=2, ensure_ascii=False))
    else:
        print(f"✅ ponytail OFF at {root}")
        if "agents_md_backup" in side_effects:
            print(f"   AGENTS.md ladder block stripped (backup: {side_effects['agents_md_backup']})")
    return 0


# ---------------------------------------------------------------------------
# Argparse plumbing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    # Shared parent parser so --project can appear before OR after the
    # subcommand (UI subprocess invocations rely on this).
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--project",
        type=Path,
        default=argparse.SUPPRESS,
        help="Project root (default: auto-detect from cwd by walking up to AGENTS.md).",
    )

    p = argparse.ArgumentParser(prog="ponytail", description="Ponytail feature toggle CLI.", parents=[shared])
    sub = p.add_subparsers(dest="cmd")

    s_status = sub.add_parser("status", help="Show current toggle state.", parents=[shared])
    s_status.add_argument("--json", action="store_true", help="JSON output for UI consumers.")
    s_status.set_defaults(func=cmd_status)

    s_on = sub.add_parser("on", help="Enable ponytail for this project.", parents=[shared])
    s_on.add_argument(
        "--mode",
        default=toggle.DEFAULT_MODE,
        help=f"Intensity: {', '.join(VALID_MODES)}. Default: {toggle.DEFAULT_MODE}.",
    )
    s_on.add_argument(
        "--components",
        default=DEFAULT_COMPONENTS,
        help=f"Comma-separated component keys ({', '.join(VALID_COMPONENTS)}).",
    )
    s_on.add_argument("--json", action="store_true")
    s_on.set_defaults(func=cmd_on)

    s_off = sub.add_parser("off", help="Disable ponytail for this project.", parents=[shared])
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
