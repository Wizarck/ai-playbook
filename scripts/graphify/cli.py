"""Graphify feature CLI — toggle state + in-repo side effects.

Subcommands
-----------
    python -m scripts.graphify status [--json] [--project PATH]
    python -m scripts.graphify on    [--components <csv>] [--project PATH]
    python -m scripts.graphify off   [--project PATH]
    python -m scripts.graphify setup [--dry-run] [--min-version X.Y.Z] [--project PATH]

Components (default on `on`: agent_guidance,gitignore_hygiene):
    agent_guidance     — inject the query-first guidance block into AGENTS.md
                         (auto-managed; backed up first).
    gitignore_hygiene  — run the graphify-adoption rule's `apply` so the
                         per-machine/per-run graph state is gitignored.
    enforce_skill      — capability flag for the graphify skill (no side effect).

NOTE — graphify wraps an EXTERNAL tool (`graphifyy`). `on`/`off`/`status`
manage the in-repo side effects only. The `setup` subcommand automates the
per-machine / per-clone bootstrap (`uv tool install "graphifyy>=X"` +
`graphify hook install`) so operators no longer run those by hand.

Exit codes per docs/rules/error-message-standard.rule.md:
    0 ok · 1 user-actionable error · 2 environment/setup error
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
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
GRAPHIFY_MIN_VERSION = "0.8.31"
NEXT_STEPS = (
    "next steps (per machine / per clone): run `python -m scripts.graphify setup`\n"
    "   it installs the external CLI + registers hooks, equivalent to:\n"
    f"   1. uv tool install \"graphifyy>={GRAPHIFY_MIN_VERSION}\"   # or pipx\n"
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


def _augmented_path() -> str:
    """PATH with uv's default tools bin (``~/.local/bin``) prepended.

    ``uv tool install`` puts the ``graphify`` executable on the tools bin, which
    is not on the current process PATH until the shell is reopened. Prepend it so
    we can resolve the freshly-installed CLI in the same run.

    Note: uv uses ``~/.local/bin`` as its tools bin on all platforms (incl.
    Windows, unless ``XDG_BIN_HOME``/``UV_TOOL_BIN_DIR`` override it), so the
    single ``Path.home() / ".local" / "bin"`` candidate covers the common case.
    A non-default bin dir still works as long as it is already on PATH — this
    only *adds* a fallback, it never removes the inherited PATH.
    """
    extra = [str(Path.home() / ".local" / "bin")]
    return os.pathsep.join([*extra, os.environ.get("PATH", "")])


def cmd_setup(args: argparse.Namespace) -> int:
    """Automate the per-machine/per-clone graphifyy bootstrap.

    1. ``uv tool install "graphifyy>=<floor>"`` (per machine).
    2. ``graphify hook install`` in this clone (registers the graph.json
       union-merge driver + post-commit/checkout hooks).

    Idempotent: re-running upgrades the tool and re-registers the hooks.
    """
    root = _resolve_project_root(getattr(args, "project", None))
    if root is None:
        _emit_error(
            why="cannot resolve project root",
            where="graphify:setup",
            fix="run from inside a project directory or pass --project <PATH>.",
        )
        return 2

    floor = getattr(args, "min_version", GRAPHIFY_MIN_VERSION)
    spec = f"graphifyy>={floor}"
    install_cmd = ["uv", "tool", "install", spec]
    hook_cmd = ["graphify", "hook", "install"]

    if getattr(args, "dry_run", False):
        print("[dry-run] would run:")
        print(f"   {' '.join(install_cmd)}")
        print(f"   {' '.join(hook_cmd)}   (cwd={root})")
        return 0

    if shutil.which("uv") is None:
        _emit_error(
            why="`uv` not found on PATH",
            where="graphify:setup",
            fix=f'install uv (https://docs.astral.sh/uv/), or run manually: '
                f'pipx install "{spec}" && graphify hook install.',
        )
        return 2

    # 1. Install the external graphifyy CLI (per machine).
    try:
        proc = subprocess.run(
            install_cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        _emit_error(
            why=f"`uv tool install` failed to start: {e}",
            where="graphify:setup:install",
            fix=f'run manually: uv tool install "{spec}".',
        )
        return 2
    if proc.returncode != 0:
        _emit_error(
            why=f"`uv tool install {spec}` exited {proc.returncode}",
            where="graphify:setup:install",
            fix=(proc.stderr or proc.stdout or "see uv output").strip()[:400],
        )
        return 2

    # 2. Register the per-clone hooks + merge driver.
    exe = shutil.which("graphify", path=_augmented_path())
    if exe is None:
        print(f"✅ graphifyy installed ({spec}).")
        _emit_error(
            why="`graphify` not on PATH after install",
            where="graphify:setup:hook",
            fix="add uv's tools bin (e.g. ~/.local/bin) to PATH (`uv tool update-shell`), "
                "reopen your shell, then run `graphify hook install`.",
        )
        return 2
    try:
        hproc = subprocess.run(
            [exe, "hook", "install"], cwd=str(root), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        _emit_error(
            why=f"`graphify hook install` failed to start: {e}",
            where="graphify:setup:hook",
            fix="run `graphify hook install` manually in this clone.",
        )
        return 2
    if hproc.returncode != 0:
        _emit_error(
            why=f"`graphify hook install` exited {hproc.returncode}",
            where="graphify:setup:hook",
            fix=(hproc.stderr or hproc.stdout or "see graphify output").strip()[:400],
        )
        return 2

    if getattr(args, "json", False):
        print(json.dumps(
            {"ok": True, "installed": spec, "hook": "installed", "graphify": exe},
            indent=2, ensure_ascii=False,
        ))
    else:
        print(f"✅ graphify setup complete at {root}")
        print(f"   installed {spec} ({exe})")
        print("   per-clone hooks + graph.json merge driver registered")
        print("   next: `python -m scripts.graphify on` (in-repo guidance) "
              "then `graphify update .` to build the graph.")
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

    s_setup = sub.add_parser(
        "setup",
        help="Install the external graphifyy CLI + register per-clone hooks.",
        parents=[shared],
    )
    s_setup.add_argument(
        "--dry-run", action="store_true",
        help="Print the commands without running them.",
    )
    s_setup.add_argument(
        "--min-version", default=GRAPHIFY_MIN_VERSION,
        help=f"graphifyy version floor (default: {GRAPHIFY_MIN_VERSION}).",
    )
    s_setup.add_argument("--json", action="store_true")
    s_setup.set_defaults(func=cmd_setup)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        return cmd_status(argparse.Namespace(project=getattr(args, "project", None), json=False))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
