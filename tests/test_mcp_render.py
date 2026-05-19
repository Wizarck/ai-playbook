"""Tests for scripts/mcp/render.py — 3-layer MCP SSOT renderer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.mcp import render as mcp_render
from scripts.mcp import validate as mcp_validate

BASE_MIN = {
    "schema": "mcp-servers/v1",
    "version": "0.2.0",
    "layer": "base",
    "servers": {
        "hindsight": {
            "id": "hindsight",
            "description": "Episodic memory.",
            "transport": "http",
            "endpoint": None,
            "command": None,
            "env": {"required": [], "optional": []},
            "auth": "bearer",
            "scope": "universal",
            "capabilities_hint": ["recall"],
        },
        "rag": {
            "id": "rag",
            "description": "Vault RAG.",
            "transport": "stdio",
            "endpoint": None,
            "command": "python -m vault_rag",
            "env": {"required": [], "optional": []},
            "auth": "none",
            "scope": "universal",
            "capabilities_hint": ["search"],
        },
    },
}

PROJECT_MIN = {
    "schema": "mcp-servers/v1",
    "layer": "project",
    "servers": {
        "hindsight": {"endpoint": "https://project.example/mcp/"},
    },
}


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _stack(tmp_path: Path, *, base: dict | None = None, project: dict | None = None,
           personal: dict | None = None) -> tuple[Path, Path, Path]:
    playbook = tmp_path / "playbook"
    consumer = tmp_path / "consumer"
    playbook.mkdir()
    consumer.mkdir()
    (playbook / "templates" / "rendered").mkdir(parents=True, exist_ok=True)
    _write_yaml(
        playbook / "templates" / "rendered" / "mcp-servers-base.yaml.tmpl",
        base if base is not None else BASE_MIN,
    )
    if project is not None:
        _write_yaml(consumer / "mcp-servers.yaml", project)
    if personal is not None:
        personal_path = tmp_path / "personal" / "mcp-servers.yaml"
        _write_yaml(personal_path, personal)
    else:
        personal_path = tmp_path / "ghost-personal.yaml"
    return playbook, consumer, personal_path


def _run(playbook: Path, consumer: Path, personal: Path, *extra: str) -> int:
    argv = [
        "--playbook-root", str(playbook),
        "--consumer-root", str(consumer),
        "--personal-file", str(personal),
    ]
    argv += list(extra)
    return mcp_render.main(argv)


def test_render_writes_claude_and_gemini(tmp_path: Path) -> None:
    playbook, consumer, personal = _stack(tmp_path, project=PROJECT_MIN)
    rc = _run(playbook, consumer, personal)
    assert rc == 0
    claude_doc = json.loads((consumer / ".mcp.json").read_text(encoding="utf-8"))
    gemini_doc = json.loads((consumer / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert set(claude_doc["mcpServers"].keys()) == {"hindsight", "rag"}
    assert claude_doc["mcpServers"]["hindsight"]["url"] == "https://project.example/mcp/"
    assert claude_doc["mcpServers"]["rag"]["command"] == "python -m vault_rag"
    assert set(gemini_doc["mcpServers"].keys()) == {"hindsight", "rag"}
    assert gemini_doc["mcpServers"]["rag"]["command"] == "python -m vault_rag"


def test_render_dry_run_does_not_write(tmp_path: Path,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    playbook, consumer, personal = _stack(tmp_path, project=PROJECT_MIN)
    rc = _run(playbook, consumer, personal, "--dry-run")
    assert rc == 0
    assert not (consumer / ".mcp.json").exists()
    assert not (consumer / ".gemini" / "settings.json").exists()
    out = capsys.readouterr().out
    assert "hindsight" in out
    assert ".mcp.json" in out


def test_render_includes_personal_when_personal_file_present(tmp_path: Path) -> None:
    personal = {
        "schema": "mcp-servers/v1", "layer": "personal",
        "servers": {
            "google-workspace-arturo": {
                "id": "google-workspace-arturo",
                "description": "Personal GWS.",
                "transport": "http",
                "endpoint": "https://gws-arturo.example/",
                "env": {"required": [], "optional": []},
                "auth": "oauth",
                "scope": "personal",
                "capabilities_hint": ["gmail"],
            }
        },
    }
    playbook, consumer, personal_path = _stack(tmp_path, personal=personal)
    rc = _run(playbook, consumer, personal_path)
    assert rc == 0
    claude_doc = json.loads((consumer / ".mcp.json").read_text(encoding="utf-8"))
    assert "google-workspace-arturo" in claude_doc["mcpServers"]
    assert (claude_doc["mcpServers"]["google-workspace-arturo"]["url"]
            == "https://gws-arturo.example/")


def test_render_excludes_personal_when_personal_file_absent(tmp_path: Path) -> None:
    playbook, consumer, _ = _stack(tmp_path, project=PROJECT_MIN)
    # Point --personal-file at a non-existent path explicitly.
    ghost = tmp_path / "no-such-personal.yaml"
    rc = _run(playbook, consumer, ghost)
    assert rc == 0
    claude_doc = json.loads((consumer / ".mcp.json").read_text(encoding="utf-8"))
    assert "google-workspace-arturo" not in claude_doc["mcpServers"]


def test_render_refuses_personal_scope_without_personal_layer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    # Project layer tries to sneak in a personal-scoped server.
    project = {
        "schema": "mcp-servers/v1", "layer": "project",
        "servers": {
            "leaky": {
                "id": "leaky", "description": "nope",
                "transport": "http", "endpoint": "https://leaky.example/",
                "env": {"required": [], "optional": []},
                "auth": "bearer", "scope": "personal",
                "capabilities_hint": [],
            },
        },
    }
    playbook, consumer, personal = _stack(tmp_path, project=project)
    rc = _run(playbook, consumer, personal)
    assert rc == 1
    err = capsys.readouterr().err
    assert "scope: personal" in err


def test_render_only_claude(tmp_path: Path) -> None:
    playbook, consumer, personal = _stack(tmp_path, project=PROJECT_MIN)
    rc = _run(playbook, consumer, personal, "--only", "claude")
    assert rc == 0
    assert (consumer / ".mcp.json").exists()
    assert not (consumer / ".gemini" / "settings.json").exists()


def test_render_only_gemini(tmp_path: Path) -> None:
    playbook, consumer, personal = _stack(tmp_path, project=PROJECT_MIN)
    rc = _run(playbook, consumer, personal, "--only", "gemini")
    assert rc == 0
    assert not (consumer / ".mcp.json").exists()
    assert (consumer / ".gemini" / "settings.json").exists()


def test_render_claude_code_output_shape() -> None:
    merged = {
        "hindsight": {
            "id": "hindsight", "transport": "http", "endpoint": "https://h.example/",
            "env": {"required": ["HINDSIGHT_API_KEY"], "optional": ["HINDSIGHT_TIMEOUT_MS"]},
            "auth": "bearer",
        },
        "rag": {
            "id": "rag", "transport": "stdio", "command": "python -m x",
            "env": {"required": [], "optional": []}, "auth": "none",
        },
    }
    doc = mcp_validate.render_claude_code(merged)
    assert "mcpServers" in doc
    assert list(doc["mcpServers"].keys()) == ["hindsight", "rag"]  # sorted
    h = doc["mcpServers"]["hindsight"]
    assert h["url"] == "https://h.example/"
    assert h["env_required"] == ["HINDSIGHT_API_KEY"]
    assert h["env_optional"] == ["HINDSIGHT_TIMEOUT_MS"]
    r = doc["mcpServers"]["rag"]
    assert r["command"] == "python -m x"
    assert "url" not in r


def test_render_gemini_output_shape() -> None:
    merged = {
        "hindsight": {
            "id": "hindsight", "transport": "http", "endpoint": "https://h.example/",
            "env": {"required": ["HINDSIGHT_API_KEY"], "optional": []},
        },
    }
    doc = mcp_validate.render_gemini(merged)
    assert "mcpServers" in doc
    h = doc["mcpServers"]["hindsight"]
    assert h["httpUrl"] == "https://h.example/"
    assert h["env"] == {"HINDSIGHT_API_KEY": "${HINDSIGHT_API_KEY}"}


def test_render_summary_lists_provenance(tmp_path: Path,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    playbook, consumer, personal = _stack(tmp_path, project=PROJECT_MIN)
    rc = _run(playbook, consumer, personal, "--project", "demo")
    assert rc == 0
    err = capsys.readouterr().err
    assert "[demo]" in err
    assert "hindsight: base > project" in err
    assert "rag: base" in err


def test_render_is_deterministic(tmp_path: Path) -> None:
    """Two renders on the same input produce byte-identical output (drift-friendly)."""
    playbook, consumer, personal = _stack(tmp_path, project=PROJECT_MIN)
    rc = _run(playbook, consumer, personal)
    assert rc == 0
    first_claude = (consumer / ".mcp.json").read_bytes()
    first_gemini = (consumer / ".gemini" / "settings.json").read_bytes()

    # Re-render
    rc = _run(playbook, consumer, personal)
    assert rc == 0
    assert (consumer / ".mcp.json").read_bytes() == first_claude
    assert (consumer / ".gemini" / "settings.json").read_bytes() == first_gemini


def test_render_then_validate_drift_clean(tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """Render → validate round-trip reports zero drift."""
    # No required env vars in BASE_MIN, so skip-env-check isn't needed.
    playbook, consumer, personal = _stack(tmp_path, project=PROJECT_MIN)
    rc_render = _run(playbook, consumer, personal)
    assert rc_render == 0
    rc_validate = mcp_validate.main([
        "--playbook-root", str(playbook),
        "--consumer-root", str(consumer),
        "--personal-file", str(personal) if personal else str(tmp_path / "nope.yaml"),
    ])
    assert rc_validate == 0
