"""Tests for scripts/mcp/absorb.py — lossless adoption of an inline .mcp.json.

Safety invariants under test:
- tenant instances (``<base-type>-<tenant>``) auto-write to the PERSONAL layer;
- non-tenant servers are REPORTED, never written (no leak to the committed layer);
- only env-var NAMES land in the layer, never values;
- ids already in a layer are skipped; the write is idempotent;
- ``dry_run`` writes nothing.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.mcp import absorb as ab

_BASE_YAML = (
    "schema: mcp-servers/v1\n"
    "version: 0.1.0\n"
    "layer: base\n"
    "servers:\n"
    "  hindsight:\n    id: hindsight\n    transport: http\n    scope: universal\n"
    "  google-workspace:\n    id: google-workspace\n    transport: http\n    scope: universal\n"
)


def _playbook(tmp_path: Path) -> Path:
    root = tmp_path / "playbook"
    base = root / "templates" / "rendered"
    base.mkdir(parents=True)
    (base / "mcp-servers-base.yaml.tmpl").write_text(_BASE_YAML, encoding="utf-8")
    return root


def _consumer(tmp_path: Path, mcp: dict) -> Path:
    c = tmp_path / "consumer"
    c.mkdir()
    (c / ".mcp.json").write_text(json.dumps(mcp), encoding="utf-8")
    return c


_MCP = {
    "mcpServers": {
        "google-workspace-arturo": {
            "transport": "http", "url": "https://gw/arturo",
            "env": {"GOOGLE_TOKEN": "secret-value-123"},
        },
        "my-rag": {"command": "python", "args": ["-m", "rag"]},
        "hindsight": {"transport": "http", "url": "https://h"},
    }
}


def test_absorb_writes_tenant_to_personal_reports_project_skips_base(tmp_path: Path) -> None:
    playbook = _playbook(tmp_path)
    consumer = _consumer(tmp_path, _MCP)
    personal = tmp_path / "personal.yaml"

    res = ab.absorb_mcp_json(
        consumer_root=consumer, playbook_root=playbook,
        personal_file=personal, dry_run=False,
    )

    assert res.written_personal == ["google-workspace-arturo"]
    assert res.report_project == ["my-rag"]           # non-tenant → reported, not written
    assert res.skipped == ["hindsight"]                # already in base layer
    data = yaml.safe_load(personal.read_text(encoding="utf-8"))
    assert "google-workspace-arturo" in data["servers"]
    assert data["servers"]["google-workspace-arturo"]["scope"] == "personal"
    # The project-scoped server is NEVER written anywhere by absorb.
    assert "my-rag" not in data["servers"]


def test_absorb_carries_env_names_not_values(tmp_path: Path) -> None:
    playbook = _playbook(tmp_path)
    consumer = _consumer(tmp_path, _MCP)
    personal = tmp_path / "personal.yaml"
    ab.absorb_mcp_json(
        consumer_root=consumer, playbook_root=playbook,
        personal_file=personal, dry_run=False,
    )
    text = personal.read_text(encoding="utf-8")
    entry = yaml.safe_load(text)["servers"]["google-workspace-arturo"]
    assert entry["env"]["required"] == ["GOOGLE_TOKEN"]
    assert "secret-value-123" not in text  # no secret value leaked into the layer


def test_absorb_is_idempotent(tmp_path: Path) -> None:
    playbook = _playbook(tmp_path)
    consumer = _consumer(tmp_path, _MCP)
    personal = tmp_path / "personal.yaml"
    ab.absorb_mcp_json(consumer_root=consumer, playbook_root=playbook,
                       personal_file=personal, dry_run=False)
    first = personal.read_text(encoding="utf-8")
    res2 = ab.absorb_mcp_json(consumer_root=consumer, playbook_root=playbook,
                              personal_file=personal, dry_run=False)
    assert res2.written_personal == []                       # already present
    assert "google-workspace-arturo" in res2.skipped
    assert personal.read_text(encoding="utf-8") == first     # no duplicate / churn


def test_absorb_dry_run_writes_nothing(tmp_path: Path) -> None:
    playbook = _playbook(tmp_path)
    consumer = _consumer(tmp_path, _MCP)
    personal = tmp_path / "personal.yaml"
    res = ab.absorb_mcp_json(consumer_root=consumer, playbook_root=playbook,
                             personal_file=personal, dry_run=True)
    assert res.dry_run is True
    assert res.written_personal == ["google-workspace-arturo"]  # would-write preview
    assert not personal.exists()


def test_absorb_no_mcp_json(tmp_path: Path) -> None:
    playbook = _playbook(tmp_path)
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    personal = tmp_path / "personal.yaml"
    res = ab.absorb_mcp_json(consumer_root=consumer, playbook_root=playbook,
                             personal_file=personal, dry_run=False)
    assert "no inline" in res.detail
    assert not personal.exists()


def test_absorb_never_clobbers_existing_personal_entry(tmp_path: Path) -> None:
    playbook = _playbook(tmp_path)
    consumer = _consumer(tmp_path, _MCP)
    personal = tmp_path / "personal.yaml"
    personal.write_text(
        "schema: mcp-servers/v1\nlayer: personal\nservers:\n"
        "  google-workspace-arturo:\n    id: google-workspace-arturo\n"
        "    transport: http\n    endpoint: https://curated\n    scope: personal\n",
        encoding="utf-8",
    )
    res = ab.absorb_mcp_json(consumer_root=consumer, playbook_root=playbook,
                             personal_file=personal, dry_run=False)
    # Already present → skipped, the curated endpoint is preserved.
    assert "google-workspace-arturo" in res.skipped
    entry = yaml.safe_load(personal.read_text(encoding="utf-8"))["servers"]["google-workspace-arturo"]
    assert entry["endpoint"] == "https://curated"


def test_classify_unit() -> None:
    base = {"google-workspace", "hindsight"}
    assert ab.classify("google-workspace-arturo", base) == "personal"
    assert ab.classify("my-rag", base) == "project"


def test_to_layer_entry_http_and_stdio() -> None:
    http = ab.to_layer_entry("x-y", {"transport": "http", "url": "https://e", "auth": "cf-access"})
    assert http["transport"] == "http"
    assert http["endpoint"] == "https://e"
    assert http["scope"] == "personal"
    assert http["auth"] == "cf-access"
    stdio = ab.to_layer_entry("z", {"command": "python", "args": ["-m", "z"]})
    assert stdio["transport"] == "stdio"
    assert stdio["command"] == "python"
    assert stdio["args"] == ["-m", "z"]
