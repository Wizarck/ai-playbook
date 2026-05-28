"""Build the static JSON inventories consumed by the config UI's
**Skills** + **MCPs** tabs.

Outputs (relative to ``<playbook>/config-ui/``):

- ``skills-inventory.json`` — one entry per directory under ``<playbook>/skills/``
  that contains a ``SKILL.md``. Each entry carries the slug, a short
  description (the YAML-frontmatter ``description`` field of ``SKILL.md``,
  or the first H1 line as a fallback), and a path pointer for hover info.
- ``mcps-inventory.json`` — one entry per server defined in any of the three
  YAML layers (base / project-template / personal template if present).
  Each entry carries the canonical ID, layer of origin, transport, scope,
  and short description.

Negative-list contract: the UI checks every entry by default. Operators
opt OUT by un-checking; only the disabled slugs/IDs land in the bundle.
The inventories themselves never carry enabled/disabled state.

CLI::

    python -m scripts.build_enforce_inventories

Exit codes::

    0 — both inventories written (or up-to-date).
    1 — fatal (playbook root not found, source YAML unparseable, etc.).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
UI_DIR = REPO_ROOT / "tools" / "config-ui"
SKILLS_OUT = UI_DIR / "skills-inventory.json"
MCPS_OUT = UI_DIR / "mcps-inventory.json"

BASE_LAYER = REPO_ROOT / "templates" / "rendered" / "mcp-servers-base.yaml.tmpl"
PROJECT_LAYER_TMPL = REPO_ROOT / "templates" / "new-project" / "mcp-servers.yaml.tmpl"


def _extract_skill_description(skill_md: Path) -> str:
    """Pull a one-line description from a SKILL.md.

    Strategy: prefer the YAML frontmatter ``description:`` line if present;
    fall back to the first non-blank prose line below the H1; final fallback
    is the H1 itself or the empty string.
    """
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    # YAML frontmatter (between leading --- fences).
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).splitlines():
            stripped = line.strip()
            if stripped.startswith("description:"):
                desc = stripped.split(":", 1)[1].strip()
                # Strip surrounding quotes if any.
                if desc.startswith(('"', "'")) and desc.endswith(desc[0]):
                    desc = desc[1:-1]
                # Collapse multi-line YAML continuation.
                return " ".join(desc.split())[:240]

    # Fallback: first H1 + first prose line.
    lines = text.splitlines()
    h1 = ""
    for ln in lines:
        if ln.startswith("# "):
            h1 = ln[2:].strip()
            break
    for ln in lines:
        s = ln.strip()
        if s and not s.startswith("#") and not s.startswith("---"):
            return s[:240]
    return h1[:240]


def build_skills_inventory() -> dict[str, Any]:
    """Walk ``skills/`` and emit the inventory shape consumed by the UI."""
    entries: list[dict[str, Any]] = []
    if not SKILLS_DIR.is_dir():
        return {
            "schema": "skills-inventory/v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "skills": entries,
        }
    for child in sorted(SKILLS_DIR.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        entries.append({
            "slug": child.name,
            "description": _extract_skill_description(skill_md),
            "doc_path": str(skill_md.relative_to(REPO_ROOT).as_posix()),
        })
    return {
        "schema": "skills-inventory/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "skills": entries,
    }


def _parse_mcp_servers(yaml_path: Path, layer_label: str) -> list[dict[str, Any]]:
    """Light YAML parser specialised for the v1 mcp-servers shape.

    Avoids the runtime PyYAML dependency at UI-build time by walking the
    file line-by-line. The shape is well-controlled (each server is a top-
    level dict under ``servers:`` with ``id:``, ``description:``,
    ``transport:``, ``scope:`` at depth 2), so a tolerant parser is enough.
    Unknown keys are ignored. Returns ``[]`` for missing files.
    """
    if not yaml_path.is_file():
        return []
    try:
        text = yaml_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    servers: list[dict[str, Any]] = []
    in_servers = False
    current: dict[str, Any] | None = None
    current_indent = -1

    for raw in text.splitlines():
        # Strip comments outside quoted strings (best-effort).
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        # Indent = number of leading spaces.
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.lstrip(" ")

        if not in_servers:
            if stripped.rstrip(":") == "servers" or stripped == "servers:":
                in_servers = True
                current_indent = indent
            continue

        if indent <= current_indent and stripped.rstrip(":") != "servers":
            # Left the servers: block.
            if current is not None and current.get("id"):
                current["layer"] = layer_label
                servers.append(current)
            break

        # A new server begins at indent == current_indent + 2 (typical) and
        # ends in ":". Capture <slug>: lines as new server objects.
        if stripped.endswith(":") and ":" not in stripped.rstrip(":"):
            if current is not None and current.get("id"):
                current["layer"] = layer_label
                servers.append(current)
            current = {"id": None, "description": "", "transport": "", "scope": ""}
            continue

        if current is None:
            continue

        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            # Strip surrounding quotes.
            if value.startswith(('"', "'")) and value.endswith(value[0]):
                value = value[1:-1]
            if key == "id" and value:
                current["id"] = value
            elif key == "description" and value:
                current["description"] = value[:240]
            elif key == "transport" and value:
                current["transport"] = value
            elif key == "scope" and value:
                current["scope"] = value

    # Tail flush.
    if in_servers and current is not None and current.get("id"):
        current["layer"] = layer_label
        servers.append(current)

    # De-dup by id within this layer (lossless: last wins).
    by_id: dict[str, dict[str, Any]] = {}
    for s in servers:
        by_id[s["id"]] = s
    return list(by_id.values())


def build_mcps_inventory() -> dict[str, Any]:
    """Aggregate MCP servers from base + project-template + (optional)
    personal-template layers into a single inventory."""
    entries: dict[str, dict[str, Any]] = {}
    for path, label in (
        (BASE_LAYER, "base"),
        (PROJECT_LAYER_TMPL, "project-template"),
    ):
        for srv in _parse_mcp_servers(path, label):
            # First occurrence wins; subsequent layers note the additional
            # layer-of-origin via the `also_in` field for transparency.
            sid = srv["id"]
            if sid not in entries:
                entries[sid] = srv
                entries[sid]["also_in"] = []
            else:
                entries[sid]["also_in"].append(label)

    return {
        "schema": "mcps-inventory/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "servers": sorted(entries.values(), key=lambda s: s["id"]),
    }


def main(argv: list[str] | None = None) -> int:
    UI_DIR.mkdir(parents=True, exist_ok=True)

    skills = build_skills_inventory()
    mcps = build_mcps_inventory()

    SKILLS_OUT.write_text(
        json.dumps(skills, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    MCPS_OUT.write_text(
        json.dumps(mcps, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"✅ wrote {SKILLS_OUT} ({len(skills['skills'])} skill(s))")
    print(f"✅ wrote {MCPS_OUT} ({len(mcps['servers'])} server(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
