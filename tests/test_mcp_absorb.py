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
    # v1 has no `args` field: args are folded into the shell `command`.
    assert stdio["command"] == "python -m z"
    assert "args" not in stdio


def test_to_layer_entry_maps_mcp_json_type_to_transport() -> None:
    sse = ab.to_layer_entry("x-y", {"type": "sse", "url": "https://e/sse"})
    assert sse["transport"] == "sse"
    assert sse["endpoint"] == "https://e/sse"


def test_absorb_then_render_round_trips_stdio_args(tmp_path: Path, monkeypatch) -> None:
    """Regression S1-41: absorbed stdio args must survive into every render,
    including the global Antigravity writer, which splits on whitespace."""
    import shlex

    from scripts.mcp import render as mr
    from scripts.mcp import validate as mv

    argv = ["npx", "-y", "@acme/hindsight-mcp", "--bank", "me", "--dir", "C:/Users/me/.hs"]
    playbook = _playbook(tmp_path)
    consumer = _consumer(tmp_path, {"mcpServers": {
        "hindsight-local": {"type": "stdio", "command": argv[0], "args": argv[1:]},
    }})
    personal = tmp_path / "personal.yaml"
    res = ab.absorb_mcp_json(
        consumer_root=consumer, playbook_root=playbook,
        personal_file=personal, dry_run=False,
    )
    assert res.written_personal == ["hindsight-local"]

    layers = mv.load_layers(
        playbook_root=playbook, consumer_root=consumer, personal_file=personal,
    )
    merged, _ = mv.merge_servers(*layers)
    for doc in (mv.render_claude_code(merged), mv.render_gemini(merged)):
        command = doc["mcpServers"]["hindsight-local"]["command"]
        assert shlex.split(command) == argv
        assert command.split() == argv

    home = tmp_path / "home"
    (home / ".gemini" / "antigravity").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    mr.update_global_antigravity_mcp(merged, {}, dry_run=False)
    cfg = json.loads((home / ".gemini" / "antigravity" / "mcp_config.json").read_text(encoding="utf-8"))
    item = cfg["mcpServers"]["hindsight-local"]
    assert [item["command"], *item["args"]] == argv


def test_absorb_reports_args_one_command_string_cannot_hold(tmp_path: Path) -> None:
    """A Windows path or an arg with a space came out quoted, and the Antigravity
    writer's whitespace split handed the client literal quotes and broken tokens."""
    playbook = _playbook(tmp_path)
    consumer = _consumer(tmp_path, {"mcpServers": {
        "google-workspace-win": {"command": "uvx", "args": ["workspace-mcp", "--dir", r"C:\Users\me\gws"]},
        "google-workspace-spaced": {"command": "uvx", "args": ["workspace-mcp", "--label", "two words"]},
        "google-workspace-plain": {"command": "uvx", "args": ["workspace-mcp", "--tools", "gmail"]},
    }})
    personal = tmp_path / "personal.yaml"

    res = ab.absorb_mcp_json(
        consumer_root=consumer, playbook_root=playbook,
        personal_file=personal, dry_run=False,
    )

    assert res.written_personal == ["google-workspace-plain"]
    assert res.report_manual == ["google-workspace-spaced", "google-workspace-win"]
    servers = yaml.safe_load(personal.read_text(encoding="utf-8"))["servers"]
    assert set(servers) == {"google-workspace-plain"}
    assert servers["google-workspace-plain"]["command"] == "uvx workspace-mcp --tools gmail"


def test_fold_command_unit() -> None:
    assert ab.fold_command({"command": "python", "args": ["-m", "z"]}) == "python -m z"
    assert ab.fold_command({"command": r"C:\Program Files\node.exe"}) == r"C:\Program Files\node.exe"
    assert ab.fold_command({"command": r"C:\node\node.exe", "args": ["s.js"]}) is None
    assert ab.fold_command({"command": "node", "args": ["it's.js"]}) is None
