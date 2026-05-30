"""Generate the ``files-state.js`` sidecar consumed by the config UI Files tab.

Reads the consumer's managed files, classifies each segment as
canonical / drifted / custom (per the bundle's ``file_states`` manifest),
and writes a window-scoped JS sidecar so the static HTML UI can render
the Files tab without filesystem access.

Layout::

    <consumer>/.ai-playbook-state/files-state.js
        window.FILES_STATE = {
          schema: "files-state/v1",
          generated_at: "...",
          files: [
            {
              rel_path: "AGENTS.md",
              style: "html",
              sections: [
                {id: "bootstrap-directive", origin: "canonical",
                 actual_sha: "...", expected_sha: "...",
                 preview: "first 200 chars"},
                {id: null, origin: "custom",
                 preview: "## §1 Project identity\\nWe build widgets."},
                ...
              ],
              counts: {canonical: 4, drifted: 0, custom: 5},
            },
            ...
          ],
          backups: [
            {rel_path: "AGENTS.md",
             timestamp: "...",
             backup_rel_path: "AGENTS.md.....bak",
             location: "next"},
            ...
          ],
        };

CLI::

    python -m scripts.build_files_state [--target PATH] [--out PATH] [--quiet]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts._backup_helper import read_index
from scripts._managed_files import MANAGED_FILES
from scripts._marker_blocks import CommentStyle
from scripts._template_classifier import classify, compute_file_sha


_PREVIEW_CHARS = 200


def _preview(text: str) -> str:
    """Compact preview for the UI — first non-empty line(s)."""
    stripped = text.strip()
    if len(stripped) <= _PREVIEW_CHARS:
        return stripped
    return stripped[:_PREVIEW_CHARS] + "…"


def _load_applied_bundle(consumer_root: Path) -> dict[str, Any]:
    p = consumer_root / ".ai-playbook" / "applied-config.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _style_label(style: CommentStyle | None) -> str:
    if style is None:
        return "none"
    return style.value


def build_files_state(consumer_root: Path) -> dict[str, Any]:
    bundle = _load_applied_bundle(consumer_root)
    file_states = bundle.get("file_states") or {}

    files: list[dict[str, Any]] = []
    for mf in MANAGED_FILES:
        dest = consumer_root / mf.rel_path
        if not dest.is_file():
            continue
        try:
            text = dest.read_text(encoding="utf-8")
        except OSError:
            continue

        expected_shas: dict[str, str] = (file_states.get(mf.rel_path) or {}).get("manifest") or {}
        # Whole-file CAS token: the UI stamps this into bundle.base_shas and
        # apply_config refuses to overwrite if the on-disk sha has since changed.
        file_sha = compute_file_sha(text)
        style = mf.style
        if style is None:
            # File without marker block support — present as a single custom section.
            files.append({
                "rel_path": mf.rel_path,
                "style": _style_label(style),
                "file_sha": file_sha,
                "sections": [{
                    "id": None,
                    "origin": "custom",
                    "preview": _preview(text),
                    "actual_sha": None,
                    "expected_sha": None,
                }],
                "counts": {"canonical": 0, "drifted": 0, "custom": 1},
            })
            continue

        fc = classify(text, style, expected_shas, rel_path=mf.rel_path)
        sections_payload = [
            {
                "id": s.id,
                "origin": s.origin,
                "preview": _preview(s.content),
                "actual_sha": s.actual_sha,
                "expected_sha": s.expected_sha,
            }
            for s in fc.sections
            if s.id is not None or s.content.strip()
        ]
        files.append({
            "rel_path": mf.rel_path,
            "style": _style_label(style),
            "file_sha": file_sha,
            "sections": sections_payload,
            "counts": {
                "canonical": fc.canonical_count,
                "drifted": fc.drifted_count,
                "custom": fc.custom_count,
            },
            "orphan_block_ids": fc.orphan_block_ids,
        })

    backup_records = read_index(consumer_root)
    backups_payload = [
        {
            "rel_path": r.rel_path,
            "backup_rel_path": r.backup_rel_path,
            "timestamp": r.timestamp,
            "location": r.location,
            "session_id": r.session_id,
        }
        for r in backup_records
    ]

    return {
        "schema": "files-state/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "files": files,
        "backups": backups_payload,
    }


def write_files_state(state: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(state, indent=2, ensure_ascii=False)
    js = (
        "/* Auto-generated by scripts/build_files_state.py. DO NOT EDIT. */\n"
        f"window.FILES_STATE = {body};\n"
    )
    out_path.write_text(js, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_files_state",
        description="Generate the files-state.js sidecar for the config UI Files tab.",
    )
    parser.add_argument("--target", type=Path, default=None,
                        help="Consumer root (default: cwd).")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output JS path (default: <target>/.ai-playbook-state/files-state.js).")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress success summary.")
    args = parser.parse_args(argv)

    target = (args.target or Path.cwd()).expanduser().resolve()
    if not target.is_dir():
        print(f"ERROR: target {target} is not a directory", file=sys.stderr)
        return 2

    state = build_files_state(target)
    out = args.out or (target / ".ai-playbook-state" / "files-state.js")
    write_files_state(state, out)
    if not args.quiet:
        n_files = len(state["files"])
        n_backups = len(state["backups"])
        print(f"wrote {out} ({n_files} file(s), {n_backups} backup(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
