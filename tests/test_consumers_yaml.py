"""Schema check for consumers.yaml — guards against drift like the v0.6.0 routing fix.

Every active consumer must declare tracker_kind explicitly. tracker_kind=jira
also requires jira_project. This test runs against the committed consumers.yaml
at the repo root; if a consumer is added without tracker_kind, CI fails loudly
instead of letting the silent-fallback heuristic that caused the v0.5.x drift
recur.

Why this lives in tests/ (not tools/): the existing test rig already runs in
CI on every PR, so the guard fires automatically. No separate workflow wiring.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONSUMERS_YAML = REPO_ROOT / "consumers.yaml"

VALID_TRACKER_KINDS = {"github", "jira"}
VALID_STATUSES = {"active", "paused", "archived"}


def _load() -> dict:
    text = CONSUMERS_YAML.read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


def test_consumers_yaml_exists() -> None:
    assert CONSUMERS_YAML.is_file(), f"{CONSUMERS_YAML} missing"


def test_consumers_yaml_schema_header() -> None:
    data = _load()
    assert data.get("schema") == "ai-playbook/consumers/v1", (
        "schema field must be 'ai-playbook/consumers/v1'"
    )


def test_every_active_consumer_has_tracker_kind() -> None:
    data = _load()
    consumers = data.get("consumers") or {}
    missing: list[str] = []
    invalid: list[tuple[str, object]] = []
    for name, entry in consumers.items():
        meta = entry or {}
        if meta.get("status") != "active":
            continue
        kind = meta.get("tracker_kind")
        if kind is None:
            missing.append(name)
        elif kind not in VALID_TRACKER_KINDS:
            invalid.append((name, kind))
    assert not missing, (
        f"active consumers missing tracker_kind: {missing}. "
        f"Declare tracker_kind: github | jira on each."
    )
    assert not invalid, (
        f"active consumers with invalid tracker_kind (must be github | jira): {invalid}"
    )


def test_jira_consumers_have_jira_project() -> None:
    data = _load()
    consumers = data.get("consumers") or {}
    bad: list[str] = []
    for name, entry in consumers.items():
        meta = entry or {}
        if meta.get("status") != "active":
            continue
        if meta.get("tracker_kind") == "jira" and not meta.get("jira_project"):
            bad.append(name)
    assert not bad, (
        f"consumers with tracker_kind=jira missing jira_project: {bad}"
    )


def test_status_values_are_valid() -> None:
    data = _load()
    consumers = data.get("consumers") or {}
    bad: list[tuple[str, object]] = []
    for name, entry in consumers.items():
        status = (entry or {}).get("status")
        if status is None:
            bad.append((name, "missing"))
        elif status not in VALID_STATUSES:
            bad.append((name, status))
    assert not bad, (
        f"consumers with invalid/missing status (active|paused|archived): {bad}"
    )


def test_repo_field_present_on_every_consumer() -> None:
    data = _load()
    consumers = data.get("consumers") or {}
    bad = [name for name, entry in consumers.items() if not (entry or {}).get("repo")]
    assert not bad, f"consumers missing repo field: {bad}"


@pytest.mark.parametrize("required_field", ["repo", "default_branch", "status"])
def test_required_fields_present(required_field: str) -> None:
    data = _load()
    consumers = data.get("consumers") or {}
    bad = [
        name for name, entry in consumers.items()
        if not (entry or {}).get(required_field)
    ]
    assert not bad, f"consumers missing {required_field!r}: {bad}"
