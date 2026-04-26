"""Detect drift between a consumer's legacy mcp-servers.yaml SSOT and the
playbook v1 layer file (mcp-servers.project.yaml).

Some consumers (consumer-d today) ship a legacy v2-metadata `mcp-servers.yaml`
that drives helm + desktop-stack + sync scripts, plus a separate
`mcp-servers.project.yaml` (schema mcp-servers/v1) for the playbook render
pipeline. Both files declare the same servers (today: at least `hindsight`).
If the two drift — different endpoints, different env vars, different
auth — the helm chart and the playbook render produce inconsistent state.

This script:

    1. Loads the legacy yaml (any consumer/<root>/mcp-servers.yaml that does
       NOT declare `schema: mcp-servers/v1`).
    2. Loads the v1 project layer (consumer/<root>/mcp-servers.project.yaml).
    3. For each server present in BOTH, compares fields known to matter:
       endpoint/url, auth, env.required, env.optional, transport.
    4. Reports any mismatch in canonical error format.

Usage:

    python -m scripts.check_mcp_drift --consumer-root /c/Projects/consumer-d
    python -m scripts.check_mcp_drift --consumer-root . --json    # CI-friendly
    python -m scripts.check_mcp_drift --consumer-root .           # exits non-zero on drift

Exit codes:

    0  No drift, or one of the files is absent (single-file consumer is fine).
    1  Drift detected (canonical error emitted; details to stderr).
    2  Setup error (consumer-root missing, malformed yaml).

Designed to run in pre-commit + CI. Stdlib + PyYAML only.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._break_glass import add_break_glass_flag, apply_break_glass  # noqa: E402

SCRIPT_BASENAME = "check_mcp_drift.py"
GATE = "mcp-drift"
LEGACY_FILENAME = "mcp-servers.yaml"
PROJECT_FILENAME = "mcp-servers.project.yaml"
PLAYBOOK_SCHEMA = "mcp-servers/v1"

# Fields we cross-check between the two files. The legacy schema uses different
# field names for some of these — we normalise per-file.
TRACKED_FIELDS = ("transport", "endpoint", "auth", "env_required", "env_optional")


@dataclass
class ServerView:
    """Normalised view of a server entry from either schema."""

    transport: str | None = None
    endpoint: str | None = None
    auth: str | None = None
    env_required: tuple[str, ...] = ()
    env_optional: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "transport": self.transport,
            "endpoint": self.endpoint,
            "auth": self.auth,
            "env_required": list(self.env_required),
            "env_optional": list(self.env_optional),
        }


@dataclass
class DriftFinding:
    server_id: str
    field: str
    legacy_value: Any
    project_value: Any


def _load_yaml(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"❌ cannot read {path}: {exc}", file=sys.stderr)
        sys.exit(2)
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        print(f"❌ malformed yaml in {path}: {exc}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict):
        print(f"❌ {path}: top-level must be a mapping", file=sys.stderr)
        sys.exit(2)
    return data


def _normalise_legacy(entry: dict[str, Any]) -> ServerView:
    """The legacy schema uses ``url`` / ``url_local`` / ``url_vps`` for endpoints."""
    endpoint = (
        entry.get("url")
        or entry.get("endpoint")
        or entry.get("url_vps")
        or entry.get("url_local")
    )
    secrets_refs = tuple(entry.get("secrets_refs") or [])
    auth = entry.get("auth")
    if auth is None and secrets_refs:
        auth = "bearer"  # legacy convention when secrets_refs is set
    return ServerView(
        transport=entry.get("transport"),
        endpoint=endpoint,
        auth=auth,
        env_required=secrets_refs,
        env_optional=tuple(entry.get("env_optional") or []),
    )


def _normalise_v1(entry: dict[str, Any]) -> ServerView:
    env = entry.get("env") or {}
    return ServerView(
        transport=entry.get("transport"),
        endpoint=entry.get("endpoint"),
        auth=entry.get("auth"),
        env_required=tuple(env.get("required") or []),
        env_optional=tuple(env.get("optional") or []),
    )


def _is_legacy(data: dict[str, Any]) -> bool:
    """A file is legacy iff it declares any schema other than mcp-servers/v1
    (typical legacy: ``metadata: {version: 2, ...}`` and no top-level ``schema``)."""
    return data.get("schema") != PLAYBOOK_SCHEMA


def _compare(server_id: str, legacy: ServerView, project: ServerView) -> list[DriftFinding]:
    """Compare two views; only flag where BOTH sides declare a value and disagree.

    Rationale: the legacy schema and the v1 layer schema track different facets
    of the same server (legacy targets helm + desktop-stack consumers; v1 targets
    the playbook render). One file can omit a field that the other tracks
    without that being "drift". Drift is when both sides claim to know the
    field's value AND those values disagree.
    """
    findings: list[DriftFinding] = []
    for field in TRACKED_FIELDS:
        l = getattr(legacy, field)
        p = getattr(project, field)
        # Treat None / empty tuple as "not declared on this side".
        l_present = l is not None and l != ()
        p_present = p is not None and p != ()
        if not l_present or not p_present:
            continue
        if isinstance(l, tuple) and isinstance(p, tuple):
            if set(l) != set(p):
                findings.append(DriftFinding(server_id, field, list(l), list(p)))
        elif l != p:
            findings.append(DriftFinding(server_id, field, l, p))
    return findings


def detect_drift(consumer_root: Path) -> tuple[list[DriftFinding], dict[str, Any]]:
    """Return ``(findings, summary)``. summary captures which files were inspected."""
    legacy_path = consumer_root / LEGACY_FILENAME
    project_path = consumer_root / PROJECT_FILENAME

    legacy_data = _load_yaml(legacy_path)
    project_data = _load_yaml(project_path)

    summary: dict[str, Any] = {
        "consumer_root": str(consumer_root),
        "legacy_present": legacy_data is not None,
        "project_present": project_data is not None,
        "legacy_is_v1": False,
        "skipped_reason": None,
    }

    if legacy_data is None or project_data is None:
        summary["skipped_reason"] = "single-file consumer (no legacy/project pair)"
        return [], summary

    if not _is_legacy(legacy_data):
        # Both files are v1 — that's structural drift in itself, since
        # the legacy file's purpose is to NOT be v1. Surface it.
        summary["legacy_is_v1"] = True
        summary["skipped_reason"] = (
            f"both files declare {PLAYBOOK_SCHEMA}; the legacy slot should hold a "
            f"different schema or be deleted."
        )
        return [], summary

    legacy_servers = legacy_data.get("servers") or {}
    project_servers = project_data.get("servers") or {}

    summary["legacy_servers_count"] = len(legacy_servers)
    summary["project_servers_count"] = len(project_servers)

    findings: list[DriftFinding] = []
    for server_id, project_entry in project_servers.items():
        if not isinstance(project_entry, dict):
            continue
        legacy_entry = legacy_servers.get(server_id)
        if not isinstance(legacy_entry, dict):
            # The v1 file declares a server the legacy file does not. That's
            # NEW work, not drift — skip without flagging.
            continue
        legacy_view = _normalise_legacy(legacy_entry)
        project_view = _normalise_v1(project_entry)
        findings.extend(_compare(server_id, legacy_view, project_view))

    summary["compared_servers"] = list(
        set(legacy_servers.keys()) & set(project_servers.keys())
    )
    return findings, summary


def _emit_canonical(findings: list[DriftFinding], consumer_root: Path) -> None:
    print(
        f"❌ MCP SSOT drift between {LEGACY_FILENAME} and {PROJECT_FILENAME} at "
        f"{consumer_root}",
        file=sys.stderr,
    )
    print(
        f"   FIX: align the two files. Either edit {PROJECT_FILENAME} to match "
        f"{LEGACY_FILENAME} (helm/desktop-stack/scripts authoritative) or vice "
        f"versa, then re-run `python -m scripts.mcp.render`.",
        file=sys.stderr,
    )
    print(
        f"   OVERRIDE: python -m scripts.check_mcp_drift "
        f"--consumer-root '{consumer_root}' "
        f'--force-with-reason="<text >=10 chars>"',
        file=sys.stderr,
    )
    print(file=sys.stderr)
    print("Detail:", file=sys.stderr)
    for f in findings:
        print(
            f"  - {f.server_id}.{f.field}: legacy={f.legacy_value!r} != "
            f"project={f.project_value!r}",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.check_mcp_drift", description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--consumer-root", type=Path, default=Path.cwd(),
                   help="Consumer repo root (default: cwd).")
    p.add_argument("--json", action="store_true",
                   help="Emit machine-readable JSON instead of canonical text.")
    add_break_glass_flag(p)
    args = p.parse_args(argv)

    consumer_root = args.consumer_root.resolve()
    if not consumer_root.is_dir():
        print(f"❌ consumer-root {consumer_root} does not exist", file=sys.stderr)
        return 2

    findings, summary = detect_drift(consumer_root)

    if args.json:
        print(json.dumps(
            {
                "summary": summary,
                "findings": [
                    {"server_id": f.server_id, "field": f.field,
                     "legacy_value": f.legacy_value, "project_value": f.project_value}
                    for f in findings
                ],
            },
            indent=2, ensure_ascii=False,
        ))
        return 1 if findings else 0

    if not findings:
        if summary["skipped_reason"]:
            print(f"✓ no drift to check — {summary['skipped_reason']}")
        else:
            n = len(summary.get("compared_servers", []))
            print(f"✅ no drift across {n} server(s) shared between {LEGACY_FILENAME} "
                  f"and {PROJECT_FILENAME}")
        return 0

    _emit_canonical(findings, consumer_root)
    if args.force_reason:
        result = apply_break_glass(
            gate=GATE, script=SCRIPT_BASENAME, reason=args.force_reason,
            override_allowed=True, repo_root=consumer_root,
        )
        if result.applied:
            print(f"⚠️ OVERRIDE APPLIED: {result.reason}", file=sys.stderr)
            print(f"   logged: {consumer_root / '.ai-playbook' / 'overrides.log'}",
                  file=sys.stderr)
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
