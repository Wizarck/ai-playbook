"""Read per-consumer enforcement state for Skills and MCPs.

State files live at::

    <consumer>/.ai-playbook-state/skills-enforce.json
    <consumer>/.ai-playbook-state/mcps-enforce.json

Both follow a negative-list (opt-out) contract: only the DISABLED entries
are persisted. Everything not in the list is enforced (the default).
Missing file ⇒ default state ⇒ everything enforced.

Stdlib-only by design — imported from hot paths
(``scripts/materialise_skills.py``, ``scripts/mcp/render.py``,
``scripts/mcp/validate.py``). No jsonschema dependency: callers that
need strict validation can call ``scripts/apply_config.py`` which uses
jsonschema. The readers here trust the schema written by
``apply_config`` and tolerate unknown IDs gracefully.

Schemas at::

    schemas/schema-skills-enforce-v1.json
    schemas/schema-mcps-enforce-v1.json
"""
from __future__ import annotations

import json
from pathlib import Path

STATE_DIR_NAME = ".ai-playbook-state"
SKILLS_STATE_FILENAME = "skills-enforce.json"
MCPS_STATE_FILENAME = "mcps-enforce.json"

SKILLS_SCHEMA = "skills-enforce/v1"
MCPS_SCHEMA = "mcps-enforce/v1"


def _state_path(consumer_root: Path, filename: str) -> Path:
    return consumer_root / STATE_DIR_NAME / filename


def _read_disabled(consumer_root: Path, filename: str, expected_schema: str) -> set[str]:
    """Return the set of disabled IDs, or empty set if file missing/malformed.

    Tolerant by design: any read/parse error returns the empty set
    (everything enforced), since these readers run on hot paths where
    failing the operation would be more disruptive than silently
    enforcing the default.

    The expected_schema is verified loosely (substring) so a v1 reader
    still accepts a v1.x minor variant if one is ever introduced.
    """
    p = _state_path(consumer_root, filename)
    if not p.is_file():
        return set()
    try:
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(data, dict):
        return set()
    schema = data.get("schema", "")
    if not isinstance(schema, str) or not schema.startswith(expected_schema.split("/")[0]):
        return set()
    disabled = data.get("disabled")
    if not isinstance(disabled, list):
        return set()
    return {item for item in disabled if isinstance(item, str)}


def disabled_skills(consumer_root: Path) -> set[str]:
    """Return the set of skill slugs the consumer has marked NOT-enforced.

    Empty set ⇒ all skills enforced (the default).
    """
    return _read_disabled(consumer_root, SKILLS_STATE_FILENAME, SKILLS_SCHEMA)


def disabled_mcps(consumer_root: Path) -> set[str]:
    """Return the set of MCP server IDs the consumer has marked NOT-enforced.

    Empty set ⇒ all servers enforced (the default).
    """
    return _read_disabled(consumer_root, MCPS_STATE_FILENAME, MCPS_SCHEMA)


def skills_state_path(consumer_root: Path) -> Path:
    return _state_path(consumer_root, SKILLS_STATE_FILENAME)


def mcps_state_path(consumer_root: Path) -> Path:
    return _state_path(consumer_root, MCPS_STATE_FILENAME)


__all__ = [
    "MCPS_SCHEMA",
    "MCPS_STATE_FILENAME",
    "SKILLS_SCHEMA",
    "SKILLS_STATE_FILENAME",
    "STATE_DIR_NAME",
    "disabled_mcps",
    "disabled_skills",
    "mcps_state_path",
    "skills_state_path",
]
