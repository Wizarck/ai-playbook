"""Per-mirror installed-skills manifest — provenance for additive materialise.

Records which skill directories the playbook installed into each mirror, so
``scripts/materialise_skills.py`` can remove only its own stale entries and
NEVER touch user-added skill directories.

State file: ``<consumer>/.ai-playbook-state/skills-manifest.json``
Schema: ``ai-playbook-skills-manifest/v1``

Layout::

    {
      "schema": "ai-playbook-skills-manifest/v1",
      "mirrors": {
        "skills":          ["hello-world", "ping"],
        ".claude/skills":  ["hello-world", "ping"],
        ".gemini/skills":  ["hello-world", "ping"]
      }
    }

Stdlib-only; imported from the materialise hot path. Tolerant reader: any
read/parse error yields an empty manifest (treated as "no provenance yet",
which triggers the safe migration-seed path in ``materialise_skills``).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from scripts._enforce_state import STATE_DIR_NAME

MANIFEST_FILENAME = "skills-manifest.json"
SCHEMA = "ai-playbook-skills-manifest/v1"


def manifest_path(consumer_root: Path) -> Path:
    return consumer_root / STATE_DIR_NAME / MANIFEST_FILENAME


def read(consumer_root: Path) -> dict[str, set[str]]:
    """Return ``{mirror_rel_posix: set(skill_names)}`` the playbook installed.

    Empty dict on a missing or malformed file (no provenance recorded yet).
    A mirror absent from the returned dict means "no manifest entry" — the
    caller MUST treat that as the migration-seed case, not as "owned nothing".
    """
    p = manifest_path(consumer_root)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    schema = data.get("schema", "")
    if not isinstance(schema, str) or not schema.startswith(SCHEMA.split("/")[0]):
        return {}
    mirrors = data.get("mirrors")
    if not isinstance(mirrors, dict):
        return {}
    out: dict[str, set[str]] = {}
    for rel, names in mirrors.items():
        if isinstance(rel, str) and isinstance(names, list):
            out[rel] = {n for n in names if isinstance(n, str)}
    return out


def write(consumer_root: Path, mirrors: dict[str, set[str]]) -> None:
    """Persist the manifest atomically (temp file + ``os.replace``)."""
    p = manifest_path(consumer_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "mirrors": {rel: sorted(names) for rel, names in sorted(mirrors.items())},
    }
    body = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=str(p.parent), prefix=p.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        os.replace(tmp_name, p)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


__all__ = ["SCHEMA", "MANIFEST_FILENAME", "manifest_path", "read", "write"]
