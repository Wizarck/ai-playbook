"""Lossless adoption — absorb a pre-existing inline ``.mcp.json`` into the layers.

When a repo adopts the playbook with a hand-authored ``.mcp.json`` (Claude Code's
native inline server map), ``render.py`` regenerates ``.mcp.json`` from the
3-layer merge, so inline servers that live in no source layer would vanish on the
next render / fresh clone. ``absorb`` migrates them into the layer files so they
survive.

Safety contract (lossless-adoption Slice B — "auto only to personal, project by
hand"):

- AUTO-WRITES only to the PERSONAL layer (``~/.config/mcp-servers.yaml`` — local,
  never committed), and only for servers it is CONFIDENT are personal/tenant
  instances: ``id == <base-server-type>-<tenant-slug>`` (the documented
  tenant-naming convention).
- NEVER auto-writes to the COMMITTED project layer. Every other new server is
  REPORTED for the operator to add to ``mcp-servers.project.yaml`` by hand — so a
  misclassification can never leak a personal server into a committed file.
- Only env-var NAMES are carried into the layer, never their values (no secret
  leak).
- Idempotent: ids already present in any layer are skipped; the personal layer is
  backed up before append and never clobbers an existing entry.

Pure-ish: stdlib + PyYAML; the only side effects are the personal-file write and a
sibling ``.pre-absorb.bak`` backup, both gated on ``dry_run=False``.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from scripts._backup_helper import backup_base
from scripts.mcp.validate import load_layers


@dataclass
class AbsorbResult:
    written_personal: list[str] = field(default_factory=list)
    report_project: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    personal_path: Path | None = None
    backed_up_mcp: bool = False
    dry_run: bool = False
    detail: str = ""


def parse_mcp_json(path: Path) -> dict[str, dict[str, Any]] | None:
    """Return the ``mcpServers`` map from ``.mcp.json``, or None if absent/invalid."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return None
    return {sid: entry for sid, entry in servers.items() if isinstance(entry, dict)}


def classify(sid: str, base_ids: set[str]) -> str:
    """``personal`` for a ``<base-type>-<tenant>`` instance, else ``project``.

    Called only for ids absent from every layer. A tenant instance of a known
    base server-type is confidently personal; anything else is left for manual
    review (reported, never auto-written) so nothing personal can leak into the
    committed project layer.
    """
    for b in base_ids:
        if sid.startswith(f"{b}-"):
            return "personal"
    return "project"


def _env_names(item: dict[str, Any]) -> list[str]:
    """Env-var NAMES only (never values) from a .mcp.json entry, order-preserved."""
    names: list[str] = []
    req = item.get("env_required")
    if isinstance(req, list):
        names.extend(str(n) for n in req)
    env = item.get("env")
    if isinstance(env, (dict, list)):
        names.extend(str(n) for n in env)
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def to_layer_entry(sid: str, item: dict[str, Any]) -> dict[str, Any]:
    """Map a ``.mcp.json`` server entry to a ``mcp-servers/v1`` personal entry."""
    if item.get("transport"):
        transport = str(item["transport"])
    elif item.get("command"):
        transport = "stdio"
    else:
        transport = "http"

    entry: dict[str, Any] = {
        "id": sid,
        "description": item.get("description") or f"Absorbed from .mcp.json ({sid}).",
        "transport": transport,
        "scope": "personal",
    }
    if transport == "stdio":
        if item.get("command"):
            entry["command"] = item["command"]
        if isinstance(item.get("args"), list):
            entry["args"] = list(item["args"])
    else:
        endpoint = item.get("endpoint") or item.get("url") or item.get("httpUrl")
        if endpoint:
            entry["endpoint"] = endpoint
    env_names = _env_names(item)
    if env_names:
        entry["env"] = {"required": env_names}
    if item.get("auth"):
        entry["auth"] = item["auth"]
    return entry


def _scaffold_personal() -> dict[str, Any]:
    return {"schema": "mcp-servers/v1", "version": "0.1.0", "layer": "personal", "servers": {}}


def _write_personal(path: Path, entries: dict[str, dict[str, Any]]) -> list[str]:
    """Append ``entries`` to the personal layer; de-dupe by id; never clobber.

    Backs up an existing file to ``<file>.pre-absorb.bak`` first, validates the
    result parses, and rolls back on a parse failure. Returns the ids written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if path.is_file():
        backup = path.with_name(path.name + ".pre-absorb.bak")
        shutil.copy2(path, backup)
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        data = loaded if isinstance(loaded, dict) else _scaffold_personal()
    else:
        data = _scaffold_personal()

    servers = data.get("servers")
    if not isinstance(servers, dict):
        servers = {}
    written: list[str] = []
    for sid, entry in entries.items():
        if sid not in servers:  # never clobber an existing curated entry
            servers[sid] = entry
            written.append(sid)
    data["servers"] = servers

    new_text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    path.write_text(new_text, encoding="utf-8", newline="\n")
    try:
        reloaded = yaml.safe_load(new_text)
        if not isinstance(reloaded, dict):
            raise ValueError("personal layer did not round-trip to a mapping")
    except (yaml.YAMLError, ValueError):
        if backup is not None:
            shutil.copy2(backup, path)  # roll back
        raise
    return sorted(written)


def absorb_mcp_json(
    *,
    consumer_root: Path,
    playbook_root: Path,
    personal_file: Path | None,
    dry_run: bool = False,
) -> AbsorbResult:
    """Absorb inline ``.mcp.json`` servers into the personal layer (safe path)."""
    consumer_root = consumer_root.resolve()
    mcp_path = consumer_root / ".mcp.json"
    servers = parse_mcp_json(mcp_path)
    if not servers:
        return AbsorbResult(dry_run=dry_run, detail="no inline .mcp.json servers to absorb")

    base, project, personal = load_layers(
        playbook_root=playbook_root, consumer_root=consumer_root, personal_file=personal_file,
    )
    existing: set[str] = set()
    for layer in (base, project, personal):
        existing |= set((layer.data.get("servers") or {}).keys())
    base_ids = set((base.data.get("servers") or {}).keys())

    to_personal: dict[str, dict[str, Any]] = {}
    report_project: list[str] = []
    skipped: list[str] = []
    for sid, item in servers.items():
        if sid in existing:
            skipped.append(sid)
            continue
        if classify(sid, base_ids) == "personal":
            to_personal[sid] = to_layer_entry(sid, item)
        else:
            report_project.append(sid)

    target = personal_file or (Path.home() / ".config" / "mcp-servers.yaml")
    written: list[str] = []
    backed_up = False
    if not dry_run:
        backed_up = backup_base(consumer_root, mcp_path) is not None
        if to_personal:
            written = _write_personal(target, to_personal)

    return AbsorbResult(
        written_personal=written if not dry_run else sorted(to_personal),
        report_project=sorted(report_project),
        skipped=sorted(skipped),
        personal_path=target,
        backed_up_mcp=backed_up,
        dry_run=dry_run,
        detail="",
    )


__all__ = [
    "AbsorbResult",
    "absorb_mcp_json",
    "classify",
    "parse_mcp_json",
    "to_layer_entry",
]
