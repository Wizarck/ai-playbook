"""Tests for scripts/mcp/render.py — 3-layer MCP SSOT renderer."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from scripts.mcp import render as mcp_render
from scripts.mcp import validate as mcp_validate

# render.main() touches ~/.gemini/antigravity: tests/conftest.py points
# Path.home() at an empty per-test dir for the whole suite.

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
            "google-workspace-acme": {
                "id": "google-workspace-acme",
                "description": "Personal GWS.",
                "transport": "http",
                "endpoint": "https://gws-acme.example/",
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
    assert "google-workspace-acme" in claude_doc["mcpServers"]
    assert (claude_doc["mcpServers"]["google-workspace-acme"]["url"]
            == "https://gws-acme.example/")


def test_render_warns_about_an_ignored_args_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """absorb up to v0.24.1 wrote `args:` into the personal layer; v1 has no such
    field and render dropped it silently."""
    personal = {
        "schema": "mcp-servers/v1", "layer": "personal",
        "servers": {"rag-local": {
            "id": "rag-local", "transport": "stdio", "command": "python",
            "args": ["-m", "rag"], "scope": "personal",
        }},
    }
    playbook, consumer, personal_path = _stack(tmp_path, personal=personal)
    assert _run(playbook, consumer, personal_path, "--dry-run") == 0
    err = capsys.readouterr().err
    assert "`rag-local`" in err and "`args` is not an mcp-servers/v1 field" in err


def test_render_excludes_personal_when_personal_file_absent(tmp_path: Path) -> None:
    playbook, consumer, _ = _stack(tmp_path, project=PROJECT_MIN)
    # Point --personal-file at a non-existent path explicitly.
    ghost = tmp_path / "no-such-personal.yaml"
    rc = _run(playbook, consumer, ghost)
    assert rc == 0
    claude_doc = json.loads((consumer / ".mcp.json").read_text(encoding="utf-8"))
    assert "google-workspace-acme" not in claude_doc["mcpServers"]


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

    # Regression S1-44: OVERRIDE: none — break-glass is refused, nothing written.
    with pytest.raises(SystemExit) as exc:
        _run(playbook, consumer, personal,
             "--force-with-reason", "need it working today, sorry")
    assert exc.value.code == 3
    assert not (consumer / ".mcp.json").exists()


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


# ---------------------------------------------------------------------------
# Per-MCP enforcement (mcps-enforce/v1 state file)
# ---------------------------------------------------------------------------


def _write_mcps_enforce(consumer: Path, disabled: list[str]) -> None:
    state_dir = consumer / ".ai-playbook-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "mcps-enforce.json").write_text(
        json.dumps({"schema": "mcps-enforce/v1", "disabled": disabled}),
        encoding="utf-8",
    )


def test_render_excludes_disabled_mcp_servers(tmp_path: Path) -> None:
    """Disabled MCP IDs MUST NOT appear in either rendered output."""
    playbook, consumer, personal = _stack(tmp_path, project=PROJECT_MIN)
    _write_mcps_enforce(consumer, disabled=["rag"])
    rc = _run(playbook, consumer, personal)
    assert rc == 0
    claude_doc = json.loads((consumer / ".mcp.json").read_text(encoding="utf-8"))
    gemini_doc = json.loads((consumer / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert set(claude_doc["mcpServers"].keys()) == {"hindsight"}
    assert set(gemini_doc["mcpServers"].keys()) == {"hindsight"}


def test_render_empty_disabled_list_keeps_all_servers(tmp_path: Path) -> None:
    playbook, consumer, personal = _stack(tmp_path, project=PROJECT_MIN)
    _write_mcps_enforce(consumer, disabled=[])
    rc = _run(playbook, consumer, personal)
    assert rc == 0
    claude_doc = json.loads((consumer / ".mcp.json").read_text(encoding="utf-8"))
    assert set(claude_doc["mcpServers"].keys()) == {"hindsight", "rag"}


def test_render_unknown_disabled_id_is_tolerated(tmp_path: Path) -> None:
    """An ID in disabled[] that doesn't exist in any layer must not break render."""
    playbook, consumer, personal = _stack(tmp_path, project=PROJECT_MIN)
    _write_mcps_enforce(consumer, disabled=["ghost-server", "rag"])
    rc = _run(playbook, consumer, personal)
    assert rc == 0
    claude_doc = json.loads((consumer / ".mcp.json").read_text(encoding="utf-8"))
    assert set(claude_doc["mcpServers"].keys()) == {"hindsight"}


def test_render_gemini_preserves_user_settings_keys(tmp_path: Path) -> None:
    """Re-rendering replaces only mcpServers in .gemini/settings.json — user
    keys (theme, hooks, custom config) survive (merge-preserve, not clobber)."""
    playbook, consumer, personal = _stack(tmp_path, project=PROJECT_MIN)
    gemini_path = consumer / ".gemini" / "settings.json"
    gemini_path.parent.mkdir(parents=True, exist_ok=True)
    gemini_path.write_text(json.dumps({
        "theme": "GitHub Dark",
        "telemetry": {"enabled": False},
        "mcpServers": {"stale-server": {"command": "old"}},
    }, indent=2) + "\n", encoding="utf-8")

    rc = _run(playbook, consumer, personal)
    assert rc == 0
    doc = json.loads(gemini_path.read_text(encoding="utf-8"))
    # User keys preserved.
    assert doc["theme"] == "GitHub Dark"
    assert doc["telemetry"] == {"enabled": False}
    # mcpServers fully replaced by the render (stale entry gone).
    assert set(doc["mcpServers"].keys()) == {"hindsight", "rag"}
    assert "stale-server" not in doc["mcpServers"]


# ---------------------------------------------------------------------------
# Regression S1-42: global Antigravity mcp_config.json (under a fake HOME)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    (home / ".gemini" / "antigravity").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


_STDIO = {"srv": {"transport": "stdio", "command": "npx srv"}}


@pytest.mark.parametrize("broken", [
    '{"mcpServers": {"my-private-server": {"command": "x"},}}',  # trailing comma
    '["not", "an", "object"]',
    '{"mcpServers": ["nope"]}',
])
def test_unparseable_global_config_is_never_overwritten(
    fake_home: Path, broken: str, capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = fake_home / ".gemini" / "antigravity" / "mcp_config.json"
    cfg.write_text(broken, encoding="utf-8")
    assert mcp_render.update_global_antigravity_mcp(_STDIO, {}, dry_run=False) is None
    assert cfg.read_text(encoding="utf-8") == broken
    assert "skipping" in capsys.readouterr().err


def test_force_with_reason_help_promises_no_override() -> None:
    """1ba4418 made render's only gate OVERRIDE: none; the help still said the
    flag would 'accept validation errors'."""
    text = " ".join(mcp_render._build_parser().format_help().split())
    assert "accept validation errors" not in text
    assert "OVERRIDE: none" in text


def test_failed_permission_step_leaves_global_config_intact(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Regression: the file used to be truncated BEFORE a chmod that could fail
    (EPERM on a file the user can write but does not own), leaving 0 bytes."""
    cfg = fake_home / ".gemini" / "antigravity" / "mcp_config.json"
    original = '{"mcpServers": {"other-project": {"command": "keep"}}}'
    cfg.write_text(original, encoding="utf-8")

    def _eperm(*_a, **_k):
        raise PermissionError(1, "Operation not permitted (simulated)")
    monkeypatch.setattr(mcp_render.os, "chmod", _eperm)

    assert mcp_render.update_global_antigravity_mcp(_STDIO, {}, dry_run=False) is None
    assert cfg.read_text(encoding="utf-8") == original
    assert sorted(p.name for p in cfg.parent.iterdir()) == ["mcp_config.json"]  # no temp left
    assert "Failed to write" in capsys.readouterr().err


def test_global_config_bom_is_parsed_not_skipped(fake_home: Path) -> None:
    """PowerShell 5.1 writes a UTF-8 BOM; such a file must still be merged into."""
    cfg = fake_home / ".gemini" / "antigravity" / "mcp_config.json"
    cfg.write_bytes(b"\xef\xbb\xbf" + b'{"mcpServers": {"keep": {"command": "k"}}}')
    assert mcp_render.update_global_antigravity_mcp(_STDIO, {}, dry_run=False) == cfg
    doc = json.loads(cfg.read_text(encoding="utf-8"))
    assert set(doc["mcpServers"]) == {"keep", "srv"}


def test_global_config_symlink_survives_the_write(fake_home: Path, tmp_path: Path) -> None:
    """The global file is often a symlink into a shared config dir: replace the
    link's target, never the link itself."""
    real = tmp_path / "shared-config" / "mcp_config.json"
    real.parent.mkdir()
    real.write_text('{"mcpServers": {"keep": {"command": "k"}}}', encoding="utf-8")
    link = fake_home / ".gemini" / "antigravity" / "mcp_config.json"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available (Windows without developer mode)")

    assert mcp_render.update_global_antigravity_mcp(_STDIO, {}, dry_run=False) == link
    assert link.is_symlink()
    assert set(json.loads(real.read_text(encoding="utf-8"))["mcpServers"]) == {"keep", "srv"}


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_global_config_written_owner_only(fake_home: Path) -> None:
    cfg = fake_home / ".gemini" / "antigravity" / "mcp_config.json"
    cfg.write_text('{"mcpServers": {"keep": {"command": "k"}}}', encoding="utf-8")
    cfg.chmod(0o644)
    out = mcp_render.update_global_antigravity_mcp(_STDIO, {}, dry_run=False)
    assert out == cfg
    assert cfg.stat().st_mode & 0o777 == 0o600
    doc = json.loads(cfg.read_text(encoding="utf-8"))
    assert set(doc["mcpServers"]) == {"keep", "srv"}

# find_secrets_env — no project name is baked in
# ---------------------------------------------------------------------------


def _secrets(root: Path, name: str) -> Path:
    p = root / name / "secrets" / "secrets.env"
    p.parent.mkdir(parents=True)
    p.write_text("K=v\n", encoding="utf-8")
    return p


def test_find_secrets_env_prefers_the_explicit_env_var(tmp_path, monkeypatch):
    explicit = tmp_path / "elsewhere.env"
    explicit.write_text("K=v\n", encoding="utf-8")
    _secrets(tmp_path, "sibling")
    monkeypatch.setenv("AIPLAYBOOK_SECRETS_ENV", str(explicit))
    assert mcp_render.find_secrets_env(tmp_path / "app") == explicit


def test_find_secrets_env_takes_the_one_sibling(tmp_path, monkeypatch):
    monkeypatch.delenv("AIPLAYBOOK_SECRETS_ENV", raising=False)
    only = _secrets(tmp_path, "vault")
    assert mcp_render.find_secrets_env(tmp_path / "app") == only


def test_find_secrets_env_refuses_to_guess_between_siblings(tmp_path, monkeypatch):
    monkeypatch.delenv("AIPLAYBOOK_SECRETS_ENV", raising=False)
    _secrets(tmp_path, "one")
    _secrets(tmp_path, "two")
    assert mcp_render.find_secrets_env(tmp_path / "app") is None
