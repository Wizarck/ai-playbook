"""Migrate an existing consumer to the bundle-driven model.

Reads the consumer's current files (AGENTS.md, .gitignore,
mcp-servers.project.yaml, .claude/settings.local.json), extracts
consumer-specific content, and assembles an ``ai-playbook-config/v1``
bundle that — when applied via ``apply_config`` — regenerates the
managed files with markers + canonical content, preserving the
consumer's customisations.

Idempotent: re-running on an already-migrated consumer produces the
same bundle (modulo timestamps). Originals are NOT modified by this
script — pass ``--apply`` to invoke ``apply_config`` afterwards, which
performs the backup + render.

Usage::

    python -m scripts.migrate_to_bundle [--target PATH] [--out BUNDLE.json] [--apply]

* ``--target`` defaults to the cwd. Must contain an AGENTS.md.
* ``--out`` defaults to ``<target>/.ai-playbook-state/migrated-bundle.json``.
* ``--apply`` immediately invokes ``apply_config`` on the produced bundle.
"""
from __future__ import annotations

import argparse
import json
import os
import re
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

from scripts._marker_blocks import CommentStyle, parse_blocks


SECTION_HEADER_RE = re.compile(
    r"^##\s*[§]?(\d+)\s*[.\-—]?\s*(.+?)\s*$", re.MULTILINE,
)

# AGENTS.md section number -> bundle.project_meta key
SECTION_TO_META_KEY = {
    1: "project_identity",
    3: "active_work",
    4: "hard_rules",
    7: "inherited_overrides",
    8: "gotchas",
}


# ---------------------------------------------------------------------------
# AGENTS.md extraction
# ---------------------------------------------------------------------------


def _strip_marker_blocks(text: str, style: CommentStyle) -> str:
    """Remove marker blocks (begin..end inclusive) so only non-marker text remains."""
    try:
        parsed = parse_blocks(text, style)
    except ValueError:
        return text
    return "".join(parsed.custom_segments)


def extract_project_meta(agents_md_text: str) -> dict[str, str]:
    """Parse AGENTS.md and extract the free-form consumer sections.

    Returns a dict keyed by ``bundle.project_meta`` keys. Sections not
    found in the file map to empty strings (so the bundle still validates
    against the schema).
    """
    # Strip marker blocks first so canonical sections (§0, §2, §5, §6) are
    # not confused with consumer slots.
    text = _strip_marker_blocks(agents_md_text, CommentStyle.HTML)

    # Find every "## N Title" header and the slice of text below it
    # (until the next header or EOF).
    matches = list(SECTION_HEADER_RE.finditer(text))
    out = {key: "" for key in SECTION_TO_META_KEY.values()}

    for i, m in enumerate(matches):
        try:
            section_num = int(m.group(1))
        except ValueError:
            continue
        if section_num not in SECTION_TO_META_KEY:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip("\n")
        if chunk.strip():
            out[SECTION_TO_META_KEY[section_num]] = chunk
    return out


# ---------------------------------------------------------------------------
# .gitignore extraction
# ---------------------------------------------------------------------------


def extract_gitignore_extras(gitignore_text: str) -> list[str]:
    """Return non-marker, non-comment, non-empty lines."""
    try:
        parsed = parse_blocks(gitignore_text, CommentStyle.HASH)
    except ValueError:
        # No markers — treat whole file as consumer extras.
        parsed = None

    out: list[str] = []
    segments = parsed.custom_segments if parsed else [gitignore_text]
    for segment in segments:
        for line in segment.splitlines():
            stripped = line.rstrip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            out.append(stripped)
    # De-duplicate while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for line in out:
        if line in seen:
            continue
        seen.add(line)
        deduped.append(line)
    return deduped


# ---------------------------------------------------------------------------
# mcp-servers.project.yaml extraction
# ---------------------------------------------------------------------------


def extract_mcp_project_servers(yaml_path: Path) -> dict[str, dict]:
    """Parse the project yaml and return servers OTHER than the hindsight baseline."""
    if not yaml_path.is_file():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    servers = data.get("servers")
    if not isinstance(servers, dict):
        return {}
    # Drop the canonical hindsight entry — it ships in the template.
    return {k: v for k, v in servers.items() if k != "hindsight"}


# ---------------------------------------------------------------------------
# .claude/settings.local.json extraction
# ---------------------------------------------------------------------------


def extract_claude_settings_extras(settings_local_path: Path) -> dict[str, Any]:
    """Return permissions_allow + additional_directories if present."""
    if not settings_local_path.is_file():
        return {}
    try:
        data = json.loads(settings_local_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    perms = data.get("permissions") or {}
    allow = perms.get("allow") or []
    addl = perms.get("additionalDirectories") or []
    if not allow and not addl:
        return {}
    out: dict[str, Any] = {}
    if allow:
        out["permissions_allow"] = [s for s in allow if isinstance(s, str)]
    if addl:
        out["additional_directories"] = [s for s in addl if isinstance(s, str)]
    return out


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def build_bundle(consumer_root: Path) -> dict[str, Any]:
    """Read consumer files, extract content, return a complete bundle dict."""
    agents_md_path = consumer_root / "AGENTS.md"
    if not agents_md_path.is_file():
        raise FileNotFoundError(f"AGENTS.md not found in {consumer_root}")

    agents_md = agents_md_path.read_text(encoding="utf-8")
    project_meta = extract_project_meta(agents_md)

    gitignore_path = consumer_root / ".gitignore"
    gitignore_extras = (
        extract_gitignore_extras(gitignore_path.read_text(encoding="utf-8"))
        if gitignore_path.is_file() else []
    )

    mcp_project = extract_mcp_project_servers(consumer_root / "mcp-servers.project.yaml")
    claude_extras = extract_claude_settings_extras(
        consumer_root / ".claude" / "settings.local.json"
    )

    bundle: dict[str, Any] = {
        "schema": "ai-playbook-config/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "generated_by": "scripts.migrate_to_bundle",
        "project_meta": project_meta,
    }
    if gitignore_extras:
        bundle["gitignore_extras"] = {"patterns": gitignore_extras}
    if mcp_project:
        bundle["mcp_project_servers"] = mcp_project
    if claude_extras:
        bundle["claude_settings_extras"] = claude_extras

    return bundle


def write_bundle(bundle: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(bundle, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="migrate_to_bundle",
        description=(
            "Extract consumer customisations into an ai-playbook-config/v1 "
            "bundle JSON. Combine with --apply to immediately project the bundle "
            "back onto the managed files (with backup-once protection)."
        ),
    )
    parser.add_argument(
        "--target", type=Path, default=None,
        help="Consumer root (default: cwd).",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Bundle output path (default: <target>/.ai-playbook-state/migrated-bundle.json).",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Invoke apply_config on the produced bundle immediately afterwards.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show the bundle that would be written; do not touch disk.",
    )
    args = parser.parse_args(argv)

    target = (args.target or Path.cwd()).expanduser().resolve()
    if not target.is_dir():
        print(f"ERROR: target {target} is not a directory", file=sys.stderr)
        return 2

    try:
        bundle = build_bundle(target)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    out_path = args.out or (target / ".ai-playbook-state" / "migrated-bundle.json")

    if args.dry_run:
        print(json.dumps(bundle, indent=2, ensure_ascii=False))
        print(f"\n(dry-run) would write to {out_path}", file=sys.stderr)
        return 0

    write_bundle(bundle, out_path)
    print(f"wrote {out_path}")

    if args.apply:
        env = os.environ.copy()
        cmd = [sys.executable, "-m", "scripts.apply_config", str(out_path), "--target", str(target)]
        print(f"invoking: {' '.join(cmd)}")
        rc = subprocess.run(cmd, env=env, check=False).returncode
        return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
