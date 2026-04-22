"""Render per-CLI MCP config files from the 3-layer YAML merge.

Outputs (written next to the consumer repo root):

- ``<consumer>/.mcp.json``           — Claude Code format.
- ``<consumer>/.gemini/settings.json`` — Gemini CLI / Antigravity format.

Merge precedence is the same as ``scripts.mcp.validate``:
**personal > project > base**, field-by-field deep merge. This module reuses the
loader / merger / renderer helpers from ``validate.py`` so the two stay in sync.

Personal-layer servers are only included in the rendered output when the personal
layer file is present on this machine (detected via the resolver). CI machines
without a personal layer still get a valid base+project render.

Usage::

    python -m scripts.mcp.render                    # write both files
    python -m scripts.mcp.render --dry-run          # print rendered content to stdout
    python -m scripts.mcp.render --project web      # tag output with project name

TODO: verify against Gemini CLI docs — shape assumption documented in
``render_gemini`` in ``validate.py``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Force UTF-8 stdio.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts.mcp.validate import (
    CanonicalError,
    _apply_break_glass,
    _emit,
    _path_str,
    load_layers,
    merge_servers,
    render_claude_code,
    render_gemini,
    resolve_personal_file,
    resolve_playbook_root,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts.mcp.render",
        description="Render Claude Code + Gemini MCP configs from the 3-layer YAML SSOT.",
    )
    parser.add_argument("--project", default=None,
                        help="Consumer project name (informational, included in summary).")
    parser.add_argument("--playbook-root", type=Path, default=None,
                        help="Override path to the ai-playbook repo root.")
    parser.add_argument("--consumer-root", type=Path, default=None,
                        help="Override path to the consumer repo root (default: cwd).")
    parser.add_argument("--personal-file", type=Path, default=None,
                        help="Override personal layer YAML path.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print rendered files to stdout instead of writing them.")
    parser.add_argument("--only", choices=["claude", "gemini"], default=None,
                        help="Only render one target format.")
    parser.add_argument("--force-with-reason", dest="force_reason", default=None,
                        metavar="TEXT",
                        help="Break-glass: accept validation errors with audit trail (≥10 chars).")
    return parser


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
    path.write_text(body + "\n", encoding="utf-8")


def _summary(*, merged: dict[str, dict[str, Any]],
             provenance: dict[str, list[str]],
             consumer_root: Path, project: str | None,
             claude_path: Path, gemini_path: Path,
             dry_run: bool, only: str | None) -> str:
    lines = []
    tag = f" [{project}]" if project else ""
    lines.append(f"✅ rendered {len(merged)} server(s){tag} from MCP SSOT layers")
    lines.append(f"   consumer: {_path_str(consumer_root)}")
    if only != "gemini":
        lines.append(f"   claude   : {_path_str(claude_path)}"
                     f"{' (dry-run)' if dry_run else ''}")
    if only != "claude":
        lines.append(f"   gemini   : {_path_str(gemini_path)}"
                     f"{' (dry-run)' if dry_run else ''}")
    lines.append("")
    lines.append("   layers per server:")
    for sid in sorted(merged):
        layers = " > ".join(provenance.get(sid, []))
        lines.append(f"     - {sid}: {layers}")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    consumer_root = (args.consumer_root or cwd).expanduser().resolve()
    playbook_root = resolve_playbook_root(args.playbook_root, consumer_root)
    personal_file = resolve_personal_file(args.personal_file)

    try:
        base, project, personal = load_layers(
            playbook_root=playbook_root,
            consumer_root=consumer_root,
            personal_file=personal_file,
        )
    except RuntimeError as exc:
        _emit(CanonicalError(
            why=f"could not load MCP YAML layers: {exc}",
            where=f"playbook={_path_str(playbook_root)} consumer={_path_str(consumer_root)}",
            fix="fix the YAML file named above or correct the --playbook-root / --consumer-root path",
        ))
        return 2

    if not base.present:
        _emit(CanonicalError(
            why="base layer `mcp-servers-base.yaml` not found",
            where=_path_str(playbook_root / "mcp-servers-base.yaml"),
            fix=("set --playbook-root to the ai-playbook checkout, set $AIPLAYBOOK_ROOT, "
                 "or ensure .ai-playbook/ is submoduled under the consumer repo"),
        ))
        return 2

    # Personal layer is only applied if its file is present on this machine.
    # merge_servers already tolerates an absent (present=False) personal layer.
    merged, provenance = merge_servers(base, project, personal)

    # Refuse to render if any server still carries `scope: personal` after merge
    # AND the personal layer was not loaded — means a base/project entry leaked.
    illegal: list[tuple[str, list[str]]] = []
    for sid, entry in merged.items():
        if entry.get("scope") == "personal":
            layers = provenance.get(sid, [])
            if personal.name not in layers:
                illegal.append((sid, layers))
    if illegal:
        for sid, layers in illegal:
            _emit(CanonicalError(
                why=f"server `{sid}` carries `scope: personal` without a personal-layer source",
                where=f"mcp-servers(merged):servers.{sid}.scope",
                fix=("move this entry to ~/.config/mcp-servers.yaml or drop the scope to "
                     "`universal`/`project` in its source layer"),
                detail=f"contributing layers: {layers}",
            ))
        applied = _apply_break_glass(
            gate="mcp.render",
            script="scripts/mcp/render.py",
            reason=args.force_reason,
            repo_root=consumer_root,
        )
        if not applied:
            return 1

    claude_path = consumer_root / ".mcp.json"
    gemini_path = consumer_root / ".gemini" / "settings.json"

    claude_doc = render_claude_code(merged)
    gemini_doc = render_gemini(merged)

    if args.dry_run:
        if args.only != "gemini":
            print(f"# --- {_path_str(claude_path)} ---")
            print(json.dumps(claude_doc, indent=2, sort_keys=True, ensure_ascii=False))
            print()
        if args.only != "claude":
            print(f"# --- {_path_str(gemini_path)} ---")
            print(json.dumps(gemini_doc, indent=2, sort_keys=True, ensure_ascii=False))
            print()
    else:
        if args.only != "gemini":
            _write_json(claude_path, claude_doc)
        if args.only != "claude":
            _write_json(gemini_path, gemini_doc)

    print(_summary(
        merged=merged, provenance=provenance,
        consumer_root=consumer_root, project=args.project,
        claude_path=claude_path, gemini_path=gemini_path,
        dry_run=args.dry_run, only=args.only,
    ), file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        _emit(CanonicalError(
            why=f"unexpected failure during mcp.render: {type(exc).__name__}: {exc}",
            where="scripts/mcp/render.py",
            fix="report with full stacktrace to FEEDBACK.md",
        ))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
