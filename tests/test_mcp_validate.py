"""Tests for scripts/mcp/validate.py — 3-layer MCP SSOT validator."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from scripts.mcp import validate as mcp_validate

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
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
            "env": {
                "required": ["HINDSIGHT_API_KEY", "HINDSIGHT_URL", "HINDSIGHT_BANK_ID"],
                "optional": [],
            },
            "auth": "bearer",
            "scope": "universal",
            "capabilities_hint": ["recall"],
        },
        "litellm": {
            "id": "litellm",
            "description": "LLM routing.",
            "transport": "http",
            "endpoint": None,
            "command": None,
            "env": {
                "required": ["LITELLM_URL", "LITELLM_MASTER_KEY"],
                "optional": [],
            },
            "auth": "bearer",
            "scope": "universal",
            "capabilities_hint": ["completion"],
        },
    },
}


@pytest.fixture
def all_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set every required env var across the minimal base fixture."""
    for var in ("HINDSIGHT_API_KEY", "HINDSIGHT_URL", "HINDSIGHT_BANK_ID",
                "LITELLM_URL", "LITELLM_MASTER_KEY"):
        monkeypatch.setenv(var, f"test-{var.lower()}")


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _stack(tmp_path: Path, *, base: dict | None = None, project: dict | None = None,
           personal: dict | None = None) -> tuple[Path, Path, Path]:
    """Return (playbook_root, consumer_root, personal_path).

    ``personal_path`` is always returned — either a real file when ``personal`` dict is
    passed, or a guaranteed non-existent path so the resolver doesn't fall back to
    the machine's real personal yaml (which would poison tests).
    """
    playbook = tmp_path / "playbook"
    consumer = tmp_path / "consumer"
    playbook.mkdir()
    consumer.mkdir()
    _write_yaml(playbook / "mcp-servers-base.yaml", base if base is not None else BASE_MIN)
    if project is not None:
        _write_yaml(consumer / "mcp-servers.yaml", project)
    if personal is not None:
        personal_path = tmp_path / "personal" / "mcp-servers.yaml"
        _write_yaml(personal_path, personal)
    else:
        personal_path = tmp_path / "ghost-personal.yaml"  # does not exist on disk
    return playbook, consumer, personal_path


def _run(playbook: Path, consumer: Path, personal: Path, *extra: str) -> int:
    argv = [
        "--playbook-root", str(playbook),
        "--consumer-root", str(consumer),
        "--personal-file", str(personal),
    ]
    argv += list(extra)
    return mcp_validate.main(argv)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_base_only_valid(tmp_path: Path, all_env_set: None,
                         capsys: pytest.CaptureFixture[str]) -> None:
    playbook, consumer, personal = _stack(tmp_path)
    rc = _run(playbook, consumer, personal, "--skip-drift")
    err = capsys.readouterr().err
    assert rc == 0, err
    assert "MCP SSOT validation passed" in err


def test_base_plus_project_merge(tmp_path: Path, all_env_set: None,
                                 capsys: pytest.CaptureFixture[str]) -> None:
    project = {
        "schema": "mcp-servers/v1",
        "version": "0.1.0",
        "layer": "project",
        "servers": {
            "hindsight": {
                "endpoint": "https://prod.example/mcp/",
                "env": {"optional": ["HINDSIGHT_TIMEOUT_MS"]},
            },
        },
    }
    playbook, consumer, personal = _stack(tmp_path, project=project)
    rc = _run(playbook, consumer, personal, "--skip-drift")
    err = capsys.readouterr().err
    assert rc == 0, err


def test_base_plus_project_plus_personal_merge(tmp_path: Path, all_env_set: None) -> None:
    project = {
        "schema": "mcp-servers/v1", "layer": "project",
        "servers": {"hindsight": {"endpoint": "https://project.example/mcp/"}},
    }
    personal = {
        "schema": "mcp-servers/v1", "layer": "personal",
        "servers": {
            "hindsight": {"endpoint": "https://personal.example/mcp/"},
            "google-workspace-arturo": {
                "id": "google-workspace-arturo",
                "description": "Gmail+Drive.",
                "transport": "http",
                "endpoint": "https://gws-arturo.example/",
                "env": {"required": [], "optional": []},
                "auth": "oauth",
                "scope": "personal",
                "capabilities_hint": ["gmail"],
            },
        },
    }
    playbook, consumer, personal_path = _stack(tmp_path, project=project, personal=personal)

    # Verify the merge programmatically (bypasses CLI to inspect result).
    base_layer, project_layer, personal_layer = mcp_validate.load_layers(
        playbook_root=playbook, consumer_root=consumer, personal_file=personal_path,
    )
    merged, provenance = mcp_validate.merge_servers(base_layer, project_layer, personal_layer)
    assert merged["hindsight"]["endpoint"] == "https://personal.example/mcp/"
    assert provenance["hindsight"] == ["base", "project", "personal"]
    assert "google-workspace-arturo" in merged
    assert merged["google-workspace-arturo"]["scope"] == "personal"


def test_scope_personal_in_base_is_error(tmp_path: Path, all_env_set: None,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    bad_base = json.loads(json.dumps(BASE_MIN))  # deep copy via json
    bad_base["servers"]["hindsight"]["scope"] = "personal"
    playbook, consumer, personal = _stack(tmp_path, base=bad_base)
    rc = _run(playbook, consumer, personal, "--skip-drift")
    err = capsys.readouterr().err
    assert rc == 1
    assert "scope: personal" in err
    assert "personal-layer-only" in err
    assert "OVERRIDE: none" in err


def test_scope_personal_in_project_is_error(tmp_path: Path, all_env_set: None,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    project = {
        "schema": "mcp-servers/v1", "layer": "project",
        "servers": {
            "foo": {"id": "foo", "description": "bad", "transport": "http",
                    "endpoint": "https://x.example/", "scope": "personal"},
        },
    }
    playbook, consumer, personal = _stack(tmp_path, project=project)
    rc = _run(playbook, consumer, personal, "--skip-drift")
    err = capsys.readouterr().err
    assert rc == 1
    assert "scope: personal" in err
    assert "project layer" in err


def test_missing_env_required_is_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    for var in ("HINDSIGHT_API_KEY", "HINDSIGHT_URL", "HINDSIGHT_BANK_ID",
                "LITELLM_URL", "LITELLM_MASTER_KEY"):
        monkeypatch.delenv(var, raising=False)
    playbook, consumer, personal = _stack(tmp_path)
    rc = _run(playbook, consumer, personal, "--skip-drift")
    err = capsys.readouterr().err
    assert rc == 1
    assert "required env var" in err
    assert "HINDSIGHT_API_KEY" in err
    # Canonical shape
    assert err.count("❌ ") >= 2  # hindsight + litellm
    assert "FIX:" in err
    assert "OVERRIDE:" in err


def test_invalid_schema_field_is_error(tmp_path: Path, all_env_set: None,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    bad = json.loads(json.dumps(BASE_MIN))
    bad["schema"] = "mcp-servers/v0"
    playbook, consumer, personal = _stack(tmp_path, base=bad)
    rc = _run(playbook, consumer, personal, "--skip-drift")
    err = capsys.readouterr().err
    assert rc == 1
    assert "schema" in err


def test_drift_detected_when_committed_mcp_json_differs(
    tmp_path: Path, all_env_set: None, capsys: pytest.CaptureFixture[str],
) -> None:
    playbook, consumer, personal = _stack(tmp_path)
    # Write a bogus committed .mcp.json that will not match the fresh render.
    (consumer / ".mcp.json").write_text(json.dumps({"mcpServers": {"bogus": {}}}),
                                        encoding="utf-8")
    rc = _run(playbook, consumer, personal)
    err = capsys.readouterr().err
    assert rc == 1
    assert "diverges from committed .mcp.json" in err


def test_drift_clean_when_committed_matches_render(
    tmp_path: Path, all_env_set: None, capsys: pytest.CaptureFixture[str],
) -> None:
    playbook, consumer, personal = _stack(tmp_path)
    # Compute fresh render in-memory and write it as committed.
    base_layer, project_layer, personal_layer = mcp_validate.load_layers(
        playbook_root=playbook, consumer_root=consumer, personal_file=personal,
    )
    merged, _ = mcp_validate.merge_servers(base_layer, project_layer, personal_layer)
    (consumer / ".mcp.json").write_text(
        json.dumps(mcp_validate.render_claude_code(merged), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    rc = _run(playbook, consumer, personal)
    err = capsys.readouterr().err
    assert rc == 0, err


def test_force_with_reason_short_circuits_validation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    for var in ("HINDSIGHT_API_KEY", "HINDSIGHT_URL", "HINDSIGHT_BANK_ID",
                "LITELLM_URL", "LITELLM_MASTER_KEY"):
        monkeypatch.delenv(var, raising=False)
    playbook, consumer, personal = _stack(tmp_path)
    rc = _run(playbook, consumer, personal, "--skip-drift",
              "--force-with-reason", "CI without SOPS keys available this run")
    err = capsys.readouterr().err
    assert rc == 0
    assert "OVERRIDE APPLIED" in err
    # Audit log written
    log_path = consumer / ".ai-playbook" / "overrides.log"
    assert log_path.is_file()
    assert "mcp.validate" in log_path.read_text(encoding="utf-8")


def test_force_with_short_reason_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("HINDSIGHT_API_KEY", "HINDSIGHT_URL"):
        monkeypatch.delenv(var, raising=False)
    playbook, consumer, personal = _stack(tmp_path)
    with pytest.raises(SystemExit) as exc:
        _run(playbook, consumer, personal, "--skip-drift",
             "--force-with-reason", "too-short")
    assert exc.value.code == 1


def test_missing_base_layer_is_env_error(tmp_path: Path, all_env_set: None,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    playbook = tmp_path / "playbook"
    consumer = tmp_path / "consumer"
    playbook.mkdir()
    consumer.mkdir()
    # Intentionally do NOT write the base yaml.
    rc = mcp_validate.main([
        "--playbook-root", str(playbook),
        "--consumer-root", str(consumer),
        "--skip-drift",
    ])
    err = capsys.readouterr().err
    assert rc == 2
    assert "mcp-servers-base.yaml" in err


def test_real_base_yaml_is_structurally_valid(tmp_path: Path, all_env_set: None,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    """The populated mcp-servers-base.yaml in the playbook repo itself must pass shape check."""
    repo_root = Path(__file__).resolve().parent.parent
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    # Set every env required by the real base file.
    real = yaml.safe_load((repo_root / "mcp-servers-base.yaml").read_text(encoding="utf-8"))
    for _sid, entry in (real.get("servers") or {}).items():
        for var in (entry.get("env") or {}).get("required", []):
            os.environ.setdefault(var, "test")
    rc = mcp_validate.main([
        "--playbook-root", str(repo_root),
        "--consumer-root", str(consumer),
        "--personal-file", str(tmp_path / "does-not-exist.yaml"),
        "--skip-drift",
    ])
    err = capsys.readouterr().err
    assert rc == 0, err


def test_duplicate_ids_across_layers_is_fine(tmp_path: Path, all_env_set: None) -> None:
    """Same id in base+project is a MERGE, not a duplicate (duplicates are within-a-single-layer)."""
    project = {
        "schema": "mcp-servers/v1", "layer": "project",
        "servers": {"hindsight": {"endpoint": "https://project.example/"}},
    }
    playbook, consumer, personal = _stack(tmp_path, project=project)
    rc = _run(playbook, consumer, personal, "--skip-drift")
    assert rc == 0


def test_malformed_yaml_is_env_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    playbook = tmp_path / "playbook"
    consumer = tmp_path / "consumer"
    playbook.mkdir()
    consumer.mkdir()
    (playbook / "mcp-servers-base.yaml").write_text(
        "schema: mcp-servers/v1\nlayer: base\nservers:\n  foo: {transport: http",
        encoding="utf-8",
    )
    rc = mcp_validate.main([
        "--playbook-root", str(playbook),
        "--consumer-root", str(consumer),
        "--skip-drift", "--skip-env-check",
    ])
    err = capsys.readouterr().err
    assert rc == 2
    assert "could not load MCP YAML layers" in err


def test_canonical_error_render_format() -> None:
    err = mcp_validate.CanonicalError(
        why="missing invariant X",
        where="path/to/file.yaml:key",
        fix="do Y",
        override="none",
    )
    rendered = err.render()
    lines = rendered.splitlines()
    assert lines[0].startswith("❌ ")
    assert lines[0].endswith("path/to/file.yaml:key")
    assert lines[1] == "   FIX: do Y"
    assert lines[2] == "   OVERRIDE: none"
