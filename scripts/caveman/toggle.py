"""Single source of truth for caveman toggle state.

State lives at ``<project>/.ai-playbook/caveman.json``. Read/write only via
this module so schema validation and atomic temp+rename are always honoured.

Public API
----------
    SCHEMA_VERSION         — const string, ``caveman-toggle/v1``
    STATE_DIR_NAME         — const, ``.ai-playbook``
    STATE_FILENAME         — const, ``caveman.json``
    find_playbook_root()   — locate the ai-playbook repo (for schema lookup)
    find_project_root()    — locate the consumer project root
    state_path(root)       — derive the state file path from a project root
    default_state()        — return a fresh OFF/default state dict
    read_state(root)       — read + schema-validate; defaults if missing
    write_state(root, st)  — schema-validate + atomic temp+rename write

Exit codes (when used as part of CLI flows; see scripts/caveman/cli.py)
    0  ok
    1  user-actionable error (invalid state, schema fail, etc.)
    2  environment/setup error (jsonschema missing, schema file missing)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

try:
    import jsonschema
except ImportError:
    print(
        "❌ jsonschema is required for scripts.caveman.toggle. "
        "Install with: pip install jsonschema",
        file=sys.stderr,
    )
    raise SystemExit(2) from None


SCHEMA_VERSION = "caveman-toggle/v1"
STATE_DIR_NAME = ".ai-playbook"
STATE_FILENAME = "caveman.json"


def find_playbook_root(start: Path | None = None) -> Path | None:
    """Locate the ai-playbook repo root (contains ``specs/`` + ``scripts/`` + ``schemas/``).

    Walks up from ``start`` (defaults to this script's directory). Same
    discipline as ``scripts.auto_managed.find_playbook_root`` but also
    requires ``schemas/`` so schema-validation always has its source.
    """
    here = (start or Path(__file__)).resolve()
    if here.is_file():
        here = here.parent
    for candidate in (here, *here.parents):
        if (
            (candidate / "specs").is_dir()
            and (candidate / "scripts").is_dir()
            and (candidate / "schemas").is_dir()
        ):
            return candidate
    return None


def find_project_root(start: Path | None = None) -> Path | None:
    """Find the consumer project root.

    A "project root" is a directory that contains ``AGENTS.md``. Walks up
    from ``start`` (defaults to cwd). First match wins.

    Note: an ``.ai-playbook/`` directory alone is NOT sufficient — the
    user's home contains ``~/.ai-playbook/projects.yaml`` (the personal
    registry, not a project), and matching on that would cause every
    directory under ``$HOME`` on a developer machine to resolve as the
    home directory. Consumer projects per ``docs/concepts/projects-registry.md``
    always carry an ``AGENTS.md``.
    """
    here = (start or Path.cwd()).resolve()
    if here.is_file():
        here = here.parent
    for candidate in (here, *here.parents):
        if (candidate / "AGENTS.md").is_file():
            return candidate
    return None


def _load_schema() -> dict[str, Any]:
    root = find_playbook_root()
    if root is None:
        raise FileNotFoundError(
            "ai-playbook root not found (need specs/ + scripts/ + schemas/ on parent chain)."
        )
    schema_path = root / "schemas" / "schema-caveman-toggle-v1.json"
    if not schema_path.is_file():
        raise FileNotFoundError(f"Schema not found: {schema_path}")
    return json.loads(schema_path.read_text(encoding="utf-8"))


def default_state() -> dict[str, Any]:
    """Return a fresh OFF-default state dict (all components false, mode full)."""
    return {
        "schema": SCHEMA_VERSION,
        "enabled": False,
        "mode": "full",
        "components": {
            "response_style": False,
            "compress_docs": False,
            "subagents_cavecrew": False,
            "commit_caveman": False,
            "review_caveman": False,
            "mcp_shrink": False,
        },
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }


def state_path(project_root: Path) -> Path:
    return project_root / STATE_DIR_NAME / STATE_FILENAME


def read_state(project_root: Path) -> dict[str, Any]:
    """Read state from disk; return ``default_state()`` if the file is missing.

    Validates against the v1 schema either way. If the file exists but is
    malformed (bad JSON, schema-invalid), raises ``ValueError``.
    """
    p = state_path(project_root)
    schema = _load_schema()
    if not p.is_file():
        state = default_state()
        jsonschema.validate(state, schema)
        return state
    raw = p.read_text(encoding="utf-8")
    try:
        state = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON in {p}: {e}") from e
    try:
        jsonschema.validate(state, schema)
    except jsonschema.ValidationError as e:
        raise ValueError(f"schema validation failed for {p}: {e.message}") from e
    return state


def write_state(project_root: Path, state: dict[str, Any]) -> None:
    """Validate ``state`` against the schema, then atomic temp+rename write.

    Creates ``<project>/.ai-playbook/`` if missing. Sets 0600 perms on POSIX.
    """
    schema = _load_schema()
    jsonschema.validate(state, schema)  # raises ValidationError on failure
    p = state_path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    fd, tmp_path_str = tempfile.mkstemp(prefix=".caveman-", suffix=".tmp", dir=str(p.parent))
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        if os.name != "nt":
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
        os.replace(tmp_path, p)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


__all__ = [
    "SCHEMA_VERSION",
    "STATE_DIR_NAME",
    "STATE_FILENAME",
    "find_playbook_root",
    "find_project_root",
    "state_path",
    "default_state",
    "read_state",
    "write_state",
]
