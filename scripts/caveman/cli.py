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
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts.caveman import backup as backup_mod
from scripts.caveman import compress as compress_mod
from scripts.caveman import materialise as materialise_mod
from scripts.caveman import mcp_shrink as mcp_shrink_mod
from scripts.caveman import stats as stats_mod
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
PHASE_B_NOT_IMPLEMENTED: tuple[str, ...] = ()


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
    root = _resolve_project_root(getattr(args, "project", None))
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

    # Side effects FIRST so that on failure we never end up with state-says-ON
    # but file-wasn't-materialised drift. Each side effect handles its own
    # backup before mutation.
    side_effects: dict[str, Any] = {}
    if "response_style" in requested:
        try:
            backup = materialise_mod.materialise(root, mode)
            side_effects["agents_md_backup"] = backup.as_posix()
        except (FileNotFoundError, ValueError, LookupError) as e:
            _emit_error(
                why=f"materialise failed: {e}",
                where="caveman:on:materialise",
                fix="ensure AGENTS.md exists at the project root and SKILL.md has the required H2 sections.",
            )
            return 1

    if "mcp_shrink" in requested:
        try:
            shrink_result = mcp_shrink_mod.shrink_project(root)
            side_effects["mcp_shrink"] = shrink_result
        except Exception as e:  # noqa: BLE001
            _emit_error(
                why=f"mcp shrink failed: {e}",
                where="caveman:on:mcp_shrink",
                fix="re-run scripts/mcp/render.py to regenerate clean .mcp.json then retry.",
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
        print(
            json.dumps(
                {"ok": True, "state": state, "side_effects": side_effects},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(f"✅ caveman ON (mode={mode}) at {root}")
        print(f"   components: {', '.join(requested)}")
        if "agents_md_backup" in side_effects:
            print(f"   materialised in AGENTS.md (backup: {side_effects['agents_md_backup']})")
        if "mcp_shrink" in side_effects:
            sr = side_effects["mcp_shrink"]
            cw = sr["claude"]["wrapped"]
            gw = sr["gemini"]["wrapped"]
            print(f"   mcp shrink wrapped {cw} (.mcp.json) + {gw} (.gemini/settings.json) entries")
    return 0


def cmd_off(args: argparse.Namespace) -> int:
    root = _resolve_project_root(getattr(args, "project", None))
    if root is None:
        _emit_error(
            why="cannot resolve project root",
            where="caveman:off",
            fix="pass --project <PATH>.",
        )
        return 2

    side_effects: dict[str, Any] = {}
    try:
        backup = materialise_mod.strip(root)
        if backup is not None:
            side_effects["agents_md_backup"] = backup.as_posix()
    except (FileNotFoundError, ValueError) as e:
        _emit_error(
            why=f"strip failed: {e}",
            where="caveman:off:strip",
            fix="resolve AGENTS.md manually (multiple caveman blocks, bad markers, etc.) then re-run.",
        )
        return 1

    try:
        restore_result = mcp_shrink_mod.restore_project(root)
        # Only surface when something was actually unwrapped.
        if restore_result["claude"]["unwrapped"] or restore_result["gemini"]["unwrapped"]:
            side_effects["mcp_restore"] = restore_result
    except Exception as e:  # noqa: BLE001
        _emit_error(
            why=f"mcp restore failed: {e}",
            where="caveman:off:mcp_restore",
            fix="run `python -m scripts.caveman mcp-restore` to retry, or manually unwrap the .mcp.json entries.",
        )
        return 1

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
        print(
            json.dumps(
                {"ok": True, "state": state, "side_effects": side_effects},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(f"✅ caveman OFF at {root}")
        if "agents_md_backup" in side_effects:
            print(f"   AGENTS.md block stripped (backup: {side_effects['agents_md_backup']})")
        if "mcp_restore" in side_effects:
            rr = side_effects["mcp_restore"]
            cu = rr["claude"]["unwrapped"]
            gu = rr["gemini"]["unwrapped"]
            print(f"   mcp restored {cu} (.mcp.json) + {gu} (.gemini/settings.json) entries")
    return 0


def cmd_mcp_shrink(args: argparse.Namespace) -> int:
    root = _resolve_project_root(getattr(args, "project", None))
    if root is None:
        _emit_error(why="cannot resolve project root", where="caveman:mcp-shrink", fix="pass --project <PATH>.")
        return 2
    try:
        result = mcp_shrink_mod.shrink_project(root)
    except Exception as e:  # noqa: BLE001
        _emit_error(why=f"mcp shrink failed: {e}", where=f"caveman:mcp-shrink:{root}", fix="check .mcp.json validity.")
        return 1
    if args.json:
        print(json.dumps({"ok": True, "result": result}, indent=2, ensure_ascii=False))
    else:
        cw = result["claude"]["wrapped"]
        gw = result["gemini"]["wrapped"]
        print(f"✅ wrapped {cw} (.mcp.json) + {gw} (.gemini/settings.json) stdio entries at {root}")
        if not mcp_shrink_mod.is_shrink_available():
            print("   ⚠️  caveman-shrink npm package not detected — wrapped commands will fail at runtime until `npx caveman-shrink` resolves.")
    return 0


def cmd_mcp_restore(args: argparse.Namespace) -> int:
    root = _resolve_project_root(getattr(args, "project", None))
    if root is None:
        _emit_error(why="cannot resolve project root", where="caveman:mcp-restore", fix="pass --project <PATH>.")
        return 2
    try:
        result = mcp_shrink_mod.restore_project(root)
    except Exception as e:  # noqa: BLE001
        _emit_error(why=f"mcp restore failed: {e}", where=f"caveman:mcp-restore:{root}", fix="check backup directory at .ai-playbook/backups/mcp/.")
        return 1
    if args.json:
        print(json.dumps({"ok": True, "result": result}, indent=2, ensure_ascii=False))
    else:
        cu = result["claude"]["unwrapped"]
        gu = result["gemini"]["unwrapped"]
        print(f"✅ unwrapped {cu} (.mcp.json) + {gu} (.gemini/settings.json) entries at {root}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    root = _resolve_project_root(getattr(args, "project", None))
    if root is None:
        _emit_error(why="cannot resolve project root", where="caveman:stats", fix="pass --project <PATH>.")
        return 2

    since = None
    if args.since_caveman_on:
        state = toggle.read_state(root)
        since = state.get("applied_at") if state.get("enabled") else None
        if since is None:
            print(f"⚠️  caveman is OFF; --since-caveman-on has no effect. Showing all sessions.", file=sys.stderr)
    elif args.since:
        since = args.since

    stats = stats_mod.collect_stats(root, since=since)
    saved = stats_mod.extrapolated_savings(stats.output_tokens)

    if args.update_statusline:
        target = stats_mod.write_statusline_suffix(root, saved)
        suffix_note = f" (statusline suffix written to {target})"
    else:
        suffix_note = ""

    if args.json:
        print(json.dumps({
            "project_root": root.as_posix(),
            "scope": since or "all",
            "sessions": stats.sessions,
            "events": stats.events,
            "input_tokens": stats.input_tokens,
            "output_tokens": stats.output_tokens,
            "cache_creation_tokens": stats.cache_creation_tokens,
            "cache_read_tokens": stats.cache_read_tokens,
            "extrapolated_saved": saved,
            "savings_rate_assumption": stats_mod.SAVINGS_RATE,
            "estimated_cost_usd": round(stats_mod.estimated_cost_usd(stats.input_tokens, stats.output_tokens), 4),
            "statusline_suffix": stats_mod.statusline_suffix(saved),
            "models": stats.models,
            "first_event_at": stats.first_event_at,
            "last_event_at": stats.last_event_at,
        }, indent=2, ensure_ascii=False))
    else:
        print(stats_mod.render_report(stats, project_root=root, since=since), end="")
        if suffix_note:
            print(suffix_note)
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    root = _resolve_project_root(getattr(args, "project", None))
    if root is None:
        _emit_error(why="cannot resolve project root", where="caveman:rollback", fix="pass --project <PATH>.")
        return 2

    # Discover what backups exist.
    agents_md = root / "AGENTS.md"
    mcp_json = root / ".mcp.json"
    gemini_json = root / ".gemini" / "settings.json"

    candidates = []
    for area, source in (("agents", agents_md), ("mcp", mcp_json), ("mcp", gemini_json)):
        latest = backup_mod.latest_backup(root, area, source.name)
        if latest is not None:
            candidates.append((area, source, latest))

    if args.list:
        if args.json:
            print(json.dumps({
                "project_root": root.as_posix(),
                "candidates": [
                    {"area": a, "target": str(s), "backup": str(b)}
                    for a, s, b in candidates
                ],
            }, indent=2, ensure_ascii=False))
        else:
            if not candidates:
                print(f"No backups found under {root}/.ai-playbook/backups/")
                return 0
            print(f"Latest backups under {root}:")
            for a, s, b in candidates:
                print(f"  [{a}] {s.name}: would restore from {b.name}")
        return 0

    if not candidates:
        _emit_error(
            why="no backups found to restore",
            where=f"caveman:rollback:{root.as_posix()}",
            fix="nothing to roll back — backups live at .ai-playbook/backups/{agents,mcp}/. Run `caveman on` then `off` to create some, or use the per-file .original.md backup for compressed docs.",
        )
        return 1

    if not args.yes:
        _emit_error(
            why="rollback requires explicit confirmation",
            where="caveman:rollback",
            fix=f"re-run with --yes. This will overwrite: {', '.join(str(s.relative_to(root)) for _, s, _ in candidates)}.",
        )
        return 1

    restored = []
    for area, source, backup in candidates:
        try:
            used = backup_mod.restore_backup(root, area, source)
            restored.append({"area": area, "source": source.as_posix(), "backup": used.as_posix()})
        except (FileNotFoundError, OSError) as e:
            _emit_error(
                why=f"restore failed for {source}: {e}",
                where=f"caveman:rollback:{area}",
                fix="check file permissions and disk state; other restores in this pass may have succeeded.",
            )
            return 1

    if args.json:
        print(json.dumps({"ok": True, "restored": restored}, indent=2, ensure_ascii=False))
    else:
        print(f"✅ rolled back {len(restored)} file(s) at {root}")
        for r in restored:
            print(f"   {r['area']:7s} {r['source']}  ⟵  {r['backup']}")
    return 0


def cmd_compress(args: argparse.Namespace) -> int:
    source = Path(args.file).expanduser().resolve()
    mode = args.mode
    if mode not in compress_mod.VALID_MODES:
        _emit_error(
            why=f"invalid mode '{mode}'",
            where="caveman:compress:mode",
            fix=f"pass --mode one of: {', '.join(compress_mod.VALID_MODES)}.",
        )
        return 1
    try:
        result = compress_mod.compress(
            source,
            mode=mode,
            force_large=args.force_large,
        )
    except FileNotFoundError as e:
        _emit_error(why=str(e), where=f"caveman:compress:{source.as_posix()}", fix="pass an existing markdown file.")
        return 1
    except ValueError as e:
        _emit_error(why=str(e), where=f"caveman:compress:{source.as_posix()}", fix="check file type, size, and --mode.")
        return 1
    except FileExistsError as e:
        _emit_error(why=str(e), where=f"caveman:compress:{source.as_posix()}", fix="delete the stale .original.md backup if you want to recompress.")
        return 1
    except compress_mod.CompressionFailedError as e:
        _emit_error(why=str(e), where=f"caveman:compress:{source.as_posix()}", fix="source was restored from backup. Try a different --mode or split the file.")
        return 1
    except Exception as e:  # noqa: BLE001 — surface LLM routing failures cleanly
        _emit_error(why=f"compression failed: {e}", where=f"caveman:compress:{source.as_posix()}", fix="check LITELLM_BASE_URL and the proxy health, then retry.")
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "source": result.source.as_posix(),
                    "backup": result.backup.as_posix(),
                    "original_bytes": result.original_bytes,
                    "compressed_bytes": result.compressed_bytes,
                    "percent_saved": round(result.percent_saved, 2),
                    "retries_used": result.retries_used,
                    "model_actual": result.model_actual,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(
            f"✅ {result.source.name}: {result.original_bytes} → {result.compressed_bytes} bytes "
            f"({result.percent_saved:.1f}% saved, {result.retries_used} retr{'y' if result.retries_used == 1 else 'ies'})"
        )
        print(f"   backup: {result.backup}")
        if result.model_actual:
            print(f"   model:  {result.model_actual}")
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
    # Shared parent parser so --project can appear before OR after the
    # subcommand. Without it, argparse only honours --project before the
    # subcommand, which makes UI subprocess invocations brittle. Each
    # subparser includes `parents=[shared]` so the flag is recognised
    # at either position.
    shared = argparse.ArgumentParser(add_help=False)
    # SUPPRESS as default so that if --project is given to the parent and
    # omitted from the subparser, the subparser's parse does NOT overwrite
    # the parent's value with None. Callers read via getattr(args, "project", None).
    shared.add_argument(
        "--project",
        type=Path,
        default=argparse.SUPPRESS,
        help="Project root (default: auto-detect from cwd by walking up to AGENTS.md).",
    )

    p = argparse.ArgumentParser(
        prog="caveman",
        description="Caveman feature toggle CLI.",
        parents=[shared],
    )
    sub = p.add_subparsers(dest="cmd")

    s_status = sub.add_parser("status", help="Show current toggle state.", parents=[shared])
    s_status.add_argument("--json", action="store_true", help="JSON output for UI consumers.")
    s_status.set_defaults(func=cmd_status)

    s_on = sub.add_parser("on", help="Enable caveman for this project.", parents=[shared])
    s_on.add_argument("--mode", default="full", help=f"Intensity: {', '.join(VALID_MODES)}. Default: full.")
    s_on.add_argument(
        "--components",
        default="response_style",
        help=f"Comma-separated component keys ({', '.join(VALID_COMPONENTS)}).",
    )
    s_on.add_argument("--json", action="store_true")
    s_on.set_defaults(func=cmd_on)

    s_off = sub.add_parser("off", help="Disable caveman for this project.", parents=[shared])
    s_off.add_argument(
        "--keep-backups",
        action="store_true",
        help="Keep backup files when disabling (default: keep — Phase B has no side effects to undo).",
    )
    s_off.add_argument("--json", action="store_true")
    s_off.set_defaults(func=cmd_off)

    s_stats = sub.add_parser("stats", help="Session-token stats from Claude Code transcripts.", parents=[shared])
    s_stats.add_argument("--since", default=None, help="ISO 8601 timestamp — only count events at-or-after.")
    s_stats.add_argument("--since-caveman-on", action="store_true", help="Scope to events since caveman was last toggled on.")
    s_stats.add_argument("--update-statusline", action="store_true", help="Write .ai-playbook/.caveman-statusline-suffix.")
    s_stats.add_argument("--json", action="store_true")
    s_stats.set_defaults(func=cmd_stats)

    s_rollback = sub.add_parser("rollback", help="Restore the latest backups for AGENTS.md and .mcp.json/.gemini.", parents=[shared])
    s_rollback.add_argument("--list", action="store_true", help="List candidate backups; do NOT restore.")
    s_rollback.add_argument("--yes", action="store_true", help="Confirm the overwrite. Required for actual restore.")
    s_rollback.add_argument("--json", action="store_true")
    s_rollback.set_defaults(func=cmd_rollback)

    s_shrink = sub.add_parser("mcp-shrink", help="Wrap MCP server commands with caveman-shrink.", parents=[shared])
    s_shrink.add_argument("--json", action="store_true")
    s_shrink.set_defaults(func=cmd_mcp_shrink)

    s_restore = sub.add_parser("mcp-restore", help="Unwrap MCP server commands (restore from markers or backup).", parents=[shared])
    s_restore.add_argument("--json", action="store_true")
    s_restore.set_defaults(func=cmd_mcp_restore)

    s_compress = sub.add_parser("compress", help="Compress a markdown file in caveman style with byte-preservation validation.", parents=[shared])
    s_compress.add_argument("file", type=str, help="Markdown file to compress.")
    s_compress.add_argument("--mode", default="full", help=f"Intensity: {', '.join(compress_mod.VALID_MODES)}.")
    s_compress.add_argument("--force-large", action="store_true", help="Allow files >100 KB.")
    s_compress.add_argument("--json", action="store_true")
    s_compress.set_defaults(func=cmd_compress)

    for name in PHASE_B_NOT_IMPLEMENTED:
        s = sub.add_parser(name, help=f"{name} — not implemented yet.")
        s.set_defaults(func=cmd_not_implemented, subcommand_name=name)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        # No subcommand → default to status
        return cmd_status(argparse.Namespace(project=getattr(args, "project", None), json=False))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
