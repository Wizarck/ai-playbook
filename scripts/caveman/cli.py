"""Caveman feature CLI — single entry point for toggle state + side effects.

Subcommands (Phase B scope)
---------------------------
    python -m scripts.caveman status [--json] [--project PATH]
    python -m scripts.caveman on  [--mode lite|full|ultra] [--components <csv>]
    python -m scripts.caveman off [--keep-backups]

Subcommands stubbed for later phases (print "not implemented" + exit 2):
    compress, stats, mcp-shrink, mcp-restore, rollback

Exit codes per docs/rules/error-message-standard.rule.md:
    0 ok
    1 user-actionable error (invalid state, bad input)
    2 environment/setup error
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts.caveman import toggle


VALID_MODES = ("lite", "full", "ultra")
VALID_COMPONENTS = (
    "response_style",
    "compress_docs",
    "subagents_cavecrew",
    "commit_caveman",
    "review_caveman",
    "mcp_shrink",
)
PHASE_B_NOT_IMPLEMENTED = ("compress", "stats", "mcp-shrink", "mcp-restore", "rollback")


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
            where="caveman:status",
            fix="run from inside a project directory containing AGENTS.md or .ai-playbook/, or pass --project <PATH>.",
        )
        return 2
    try:
        state = toggle.read_state(root)
    except (ValueError, FileNotFoundError) as e:
        _emit_error(
            why=str(e),
            where=f"caveman:status:{root.as_posix()}",
            fix="repair or delete the corrupt state file then re-run `caveman on`.",
        )
        return 1

    materialised = False
    agents_md = root / "AGENTS.md"
    if agents_md.is_file():
        try:
            materialised = "BEGIN auto-managed: caveman/" in agents_md.read_text(encoding="utf-8")
        except OSError:
            materialised = False

    out = {
        "project_root": root.as_posix(),
        "state_path": toggle.state_path(root).as_posix(),
        "state": state,
        "derived": {
            "materialised": materialised,
        },
    }
    if getattr(args, "json", False):
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        enabled = "ON" if state.get("enabled") else "OFF"
        mode = state.get("mode", "—")
        print(f"caveman: {enabled} (mode={mode})")
        print(f"project: {root}")
        print(f"state:   {toggle.state_path(root)}")
        print(f"materialised in AGENTS.md: {'yes' if materialised else 'no'}")
        print("components:")
        for k in VALID_COMPONENTS:
            v = (state.get("components") or {}).get(k, False)
            mark = "✓" if v else "·"
            print(f"  {mark} {k}")
    return 0


def cmd_on(args: argparse.Namespace) -> int:
    root = _resolve_project_root(args.project)
    if root is None:
        _emit_error(
            why="cannot resolve project root",
            where="caveman:on",
            fix="run from inside a project directory or pass --project <PATH>.",
        )
        return 2

    mode = args.mode
    if mode not in VALID_MODES:
        _emit_error(
            why=f"invalid mode '{mode}'",
            where="caveman:on:mode",
            fix=f"pass --mode one of: {', '.join(VALID_MODES)}.",
        )
        return 1

    components_csv = (args.components or "response_style").strip()
    requested = [c.strip() for c in components_csv.split(",") if c.strip()]
    bad = [c for c in requested if c not in VALID_COMPONENTS]
    if bad:
        _emit_error(
            why=f"invalid component(s): {bad}",
            where="caveman:on:components",
            fix=f"valid keys: {', '.join(VALID_COMPONENTS)}.",
        )
        return 1

    state = toggle.read_state(root)
    state["enabled"] = True
    state["mode"] = mode
    new_components = {c: False for c in VALID_COMPONENTS}
    for c in requested:
        new_components[c] = True
    state["components"] = new_components
    state["applied_at"] = datetime.now(timezone.utc).isoformat()
    ab = _applied_by_default()
    if ab:
        state["applied_by"] = ab

    try:
        toggle.write_state(root, state)
    except Exception as e:  # noqa: BLE001 — any write error becomes env error
        _emit_error(
            why=f"failed to write state: {e}",
            where="caveman:on:write",
            fix="check file permissions on .ai-playbook/caveman.json and re-run.",
        )
        return 2

    if args.json:
        print(json.dumps({"ok": True, "state": state}, indent=2, ensure_ascii=False))
    else:
        print(f"✅ caveman ON (mode={mode}) at {root}")
        print(f"   components: {', '.join(requested)}")
        print("   ⚠️  Phase B: state-only — side effects (materialise, MCP wrap) land in Phase C+.")
    return 0


def cmd_off(args: argparse.Namespace) -> int:
    root = _resolve_project_root(args.project)
    if root is None:
        _emit_error(
            why="cannot resolve project root",
            where="caveman:off",
            fix="pass --project <PATH>.",
        )
        return 2

    state = toggle.read_state(root)
    state["enabled"] = False
    state["components"] = {c: False for c in VALID_COMPONENTS}
    state["applied_at"] = datetime.now(timezone.utc).isoformat()
    ab = _applied_by_default()
    if ab:
        state["applied_by"] = ab

    try:
        toggle.write_state(root, state)
    except Exception as e:  # noqa: BLE001
        _emit_error(
            why=f"failed to write state: {e}",
            where="caveman:off:write",
            fix="check file permissions on .ai-playbook/caveman.json and re-run.",
        )
        return 2

    if args.json:
        print(json.dumps({"ok": True, "state": state}, indent=2, ensure_ascii=False))
    else:
        print(f"✅ caveman OFF at {root}")
    return 0


def cmd_not_implemented(args: argparse.Namespace) -> int:
    name = args.subcommand_name
    _emit_error(
        why=f"subcommand '{name}' is not implemented yet",
        where=f"caveman:{name}",
        fix="lands in a later phase per ~/.claude/plans/snappy-orbiting-peach.md. Use `caveman status` / `on` / `off` for Phase B.",
    )
    return 2


# ---------------------------------------------------------------------------
# Argparse plumbing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="caveman",
        description="Caveman feature toggle CLI (Phase B: state-only).",
    )
    p.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Project root (default: auto-detect from cwd by walking up to AGENTS.md or .ai-playbook/).",
    )
    sub = p.add_subparsers(dest="cmd")

    s_status = sub.add_parser("status", help="Show current toggle state.")
    s_status.add_argument("--json", action="store_true", help="JSON output for UI consumers.")
    s_status.set_defaults(func=cmd_status)

    s_on = sub.add_parser("on", help="Enable caveman for this project.")
    s_on.add_argument("--mode", default="full", help=f"Intensity: {', '.join(VALID_MODES)}. Default: full.")
    s_on.add_argument(
        "--components",
        default="response_style",
        help=f"Comma-separated component keys ({', '.join(VALID_COMPONENTS)}).",
    )
    s_on.add_argument("--json", action="store_true")
    s_on.set_defaults(func=cmd_on)

    s_off = sub.add_parser("off", help="Disable caveman for this project.")
    s_off.add_argument(
        "--keep-backups",
        action="store_true",
        help="Keep backup files when disabling (default: keep — Phase B has no side effects to undo).",
    )
    s_off.add_argument("--json", action="store_true")
    s_off.set_defaults(func=cmd_off)

    for name in PHASE_B_NOT_IMPLEMENTED:
        s = sub.add_parser(name, help=f"{name} — not implemented in Phase B.")
        s.set_defaults(func=cmd_not_implemented, subcommand_name=name)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        # No subcommand → default to status
        return cmd_status(argparse.Namespace(project=args.project, json=False))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
