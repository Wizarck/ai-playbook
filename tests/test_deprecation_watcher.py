"""Tests for scripts/deprecation_watcher.py (T22i)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from scripts import deprecation_watcher as dw


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_registry(tmp_path: Path, projects: dict[str, Path]) -> Path:
    data = {
        "schema": "ai-playbook/projects-registry/v1",
        "projects": {name: {"path": str(path)} for name, path in projects.items()},
    }
    reg = tmp_path / "projects.yaml"
    reg.write_text(yaml.safe_dump(data), encoding="utf-8")
    return reg


def _make_v1_agents_md(path: Path) -> None:
    path.write_text(
        "---\n"
        "schema: agents-md/v1\n"
        "version: 1.0.0\n"
        "inherits_from:\n  - github.com/Wizarck/ai-playbook@v0.1.0\n"
        "updated: 2026-04-23\n"
        "project: x\n"
        "owner: a@b.c\n"
        "capabilities_map: false\n"
        "---\n\n# x\n",
        encoding="utf-8",
    )


def _make_v0_agents_md(path: Path) -> None:
    path.write_text("# no frontmatter here\n", encoding="utf-8")


def _make_mcp_yaml(path: Path, deprecated_id: str) -> None:
    path.write_text(
        "schema: mcp-servers/v1\n"
        "servers:\n"
        f"  {deprecated_id}:\n"
        "    command: python\n"
        "    args: []\n",
        encoding="utf-8",
    )


def _make_lifecycle_report(project_dir: Path, stem: str) -> Path:
    lc = project_dir / "reports" / "lifecycle"
    lc.mkdir(parents=True, exist_ok=True)
    md = lc / f"{stem}.md"
    md.write_text(f"# Lifecycle {stem}\n", encoding="utf-8")
    return md


def _config(tmp_path: Path, registry_path: Path) -> dw.WatcherConfig:
    return dw.WatcherConfig(
        registry_path=registry_path,
        playbook_root=tmp_path / "does-not-exist",
        mcp_deprecations=dict(dw.DEFAULT_MCP_DEPRECATIONS),
        env_aliases=dict(dw.DEFAULT_ENV_ALIASES),
    )


# ---------------------------------------------------------------------------
# v0 schema detection
# ---------------------------------------------------------------------------


def test_scan_agents_md_flags_missing_frontmatter(tmp_path: Path) -> None:
    proj = tmp_path / "p"
    proj.mkdir()
    _make_v0_agents_md(proj / "AGENTS.md")
    findings = dw.scan_agents_md_schema(proj, "p")
    assert len(findings) == 1
    assert findings[0].kind == "v0_schema"
    assert findings[0].project == "p"


def test_scan_agents_md_valid_v1_no_finding(tmp_path: Path) -> None:
    proj = tmp_path / "p"
    proj.mkdir()
    _make_v1_agents_md(proj / "AGENTS.md")
    assert dw.scan_agents_md_schema(proj, "p") == []


def test_scan_agents_md_no_file_no_finding(tmp_path: Path) -> None:
    assert dw.scan_agents_md_schema(tmp_path, "p") == []


# ---------------------------------------------------------------------------
# Env-var alias detection
# ---------------------------------------------------------------------------


def test_env_alias_flagged_when_canonical_absent() -> None:
    findings = dw.scan_env_aliases(
        env={"ANTHROPIC_CACHE_TOKENS_MIN": "1024"},
        aliases={"ANTHROPIC_CACHE_TOKENS_MIN": "AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN"},
    )
    assert len(findings) == 1
    assert findings[0].kind == "env_alias"
    assert findings[0].subject == "ANTHROPIC_CACHE_TOKENS_MIN"


def test_env_alias_quiet_when_canonical_present() -> None:
    findings = dw.scan_env_aliases(
        env={
            "ANTHROPIC_CACHE_TOKENS_MIN": "1024",
            "AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN": "1024",
        },
        aliases={"ANTHROPIC_CACHE_TOKENS_MIN": "AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN"},
    )
    assert findings == []


# ---------------------------------------------------------------------------
# MCP deprecated IDs
# ---------------------------------------------------------------------------


def test_mcp_deprecated_id_detected_in_yaml(tmp_path: Path) -> None:
    proj = tmp_path / "p"
    proj.mkdir()
    _make_mcp_yaml(proj / "mcp-servers.yaml", "opentrattos-guardrails-mcp")
    findings = dw.scan_mcp_deprecations(proj, "p", dw.DEFAULT_MCP_DEPRECATIONS)
    assert len(findings) == 1
    assert findings[0].kind == "mcp_deprecated_id"
    assert "opentrattos-guardrails-mcp" in findings[0].subject


def test_mcp_deprecated_id_detected_in_json(tmp_path: Path) -> None:
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / ".mcp.json").write_text(
        '{\n  "mcpServers": {\n    "opentrattos-guardrails-mcp": {"command": "x"}\n  }\n}\n',
        encoding="utf-8",
    )
    findings = dw.scan_mcp_deprecations(proj, "p", dw.DEFAULT_MCP_DEPRECATIONS)
    assert len(findings) == 1


def test_mcp_no_findings_when_canonical_used(tmp_path: Path) -> None:
    proj = tmp_path / "p"
    proj.mkdir()
    _make_mcp_yaml(proj / "mcp-servers.yaml", "guardrails-mcp")
    assert dw.scan_mcp_deprecations(proj, "p", dw.DEFAULT_MCP_DEPRECATIONS) == []


# ---------------------------------------------------------------------------
# Stale retro scanning
# ---------------------------------------------------------------------------


def test_stale_retro_flagged_past_cutoff(tmp_path: Path) -> None:
    proj = tmp_path / "p"
    proj.mkdir()
    _make_lifecycle_report(proj, "2025-01")  # ~16 months before 2026-04
    now = datetime(2026, 4, 23, tzinfo=timezone.utc)
    findings = dw.scan_stale_retros(proj, "p", now=now)
    assert len(findings) == 1
    assert findings[0].kind == "stale_retro"


def test_stale_retro_ignored_within_cutoff(tmp_path: Path) -> None:
    proj = tmp_path / "p"
    proj.mkdir()
    _make_lifecycle_report(proj, "2026-03")  # 1 month before
    now = datetime(2026, 4, 23, tzinfo=timezone.utc)
    assert dw.scan_stale_retros(proj, "p", now=now) == []


def test_stale_retro_no_dir_no_finding(tmp_path: Path) -> None:
    assert dw.scan_stale_retros(tmp_path, "p") == []


# ---------------------------------------------------------------------------
# Deprecations YAML loading
# ---------------------------------------------------------------------------


def test_load_deprecations_yaml_missing_falls_back(tmp_path: Path) -> None:
    (tmp_path / "specs").mkdir()
    mcp, env = dw.load_deprecations_yaml(tmp_path)
    assert mcp == dw.DEFAULT_MCP_DEPRECATIONS
    assert env == dw.DEFAULT_ENV_ALIASES


def test_load_deprecations_yaml_merges_with_defaults(tmp_path: Path) -> None:
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "deprecations.yaml").write_text(
        "mcp_servers:\n  extra-old-id: extra-canonical\n",
        encoding="utf-8",
    )
    mcp, env = dw.load_deprecations_yaml(tmp_path)
    # Merged: defaults + the yaml additions.
    assert "extra-old-id" in mcp
    assert "opentrattos-guardrails-mcp" in mcp  # still present
    assert env == dw.DEFAULT_ENV_ALIASES


# ---------------------------------------------------------------------------
# Orchestration: collect_findings end-to-end
# ---------------------------------------------------------------------------


def test_collect_findings_end_to_end(tmp_path: Path) -> None:
    proj_v0 = tmp_path / "legacy"
    proj_v0.mkdir()
    _make_v0_agents_md(proj_v0 / "AGENTS.md")

    proj_v1 = tmp_path / "modern"
    proj_v1.mkdir()
    _make_v1_agents_md(proj_v1 / "AGENTS.md")
    _make_mcp_yaml(proj_v1 / "mcp-servers.yaml", "opentrattos-guardrails-mcp")

    registry = _write_registry(tmp_path, {"legacy": proj_v0, "modern": proj_v1})
    config = dw.WatcherConfig(
        registry_path=registry,
        playbook_root=tmp_path / "no-root",  # unused here
        mcp_deprecations=dict(dw.DEFAULT_MCP_DEPRECATIONS),
        env_aliases=dict(dw.DEFAULT_ENV_ALIASES),
    )
    findings = dw.collect_findings(
        config,
        env={"ANTHROPIC_CACHE_TOKENS_MIN": "1024"},
    )
    kinds = {f.kind for f in findings}
    assert "v0_schema" in kinds
    assert "mcp_deprecated_id" in kinds
    assert "env_alias" in kinds


# ---------------------------------------------------------------------------
# CLI / exit codes
# ---------------------------------------------------------------------------


def test_cli_default_exit_zero_even_with_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    proj = tmp_path / "legacy"
    proj.mkdir()
    _make_v0_agents_md(proj / "AGENTS.md")
    registry = _write_registry(tmp_path, {"legacy": proj})
    # Prevent real env vars from leaking in.
    monkeypatch.delenv("ANTHROPIC_CACHE_TOKENS_MIN", raising=False)

    rc = dw.main(["--registry", str(registry), "--playbook-root", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "v0_schema" in out


def test_cli_strict_exit_one_on_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = tmp_path / "legacy"
    proj.mkdir()
    _make_v0_agents_md(proj / "AGENTS.md")
    registry = _write_registry(tmp_path, {"legacy": proj})
    monkeypatch.delenv("ANTHROPIC_CACHE_TOKENS_MIN", raising=False)

    rc = dw.main(["--strict", "--registry", str(registry), "--playbook-root", str(tmp_path)])
    assert rc == 1


def test_cli_strict_exit_zero_when_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = tmp_path / "modern"
    proj.mkdir()
    _make_v1_agents_md(proj / "AGENTS.md")
    registry = _write_registry(tmp_path, {"modern": proj})
    monkeypatch.delenv("ANTHROPIC_CACHE_TOKENS_MIN", raising=False)
    # Make sure the playbook-root we pass has no AGENTS.md / configs of its own.
    pb = tmp_path / "pb"
    pb.mkdir()

    rc = dw.main(["--strict", "--registry", str(registry), "--playbook-root", str(pb)])
    assert rc == 0


def test_cli_json_output_is_valid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    proj = tmp_path / "legacy"
    proj.mkdir()
    _make_v0_agents_md(proj / "AGENTS.md")
    registry = _write_registry(tmp_path, {"legacy": proj})
    monkeypatch.delenv("ANTHROPIC_CACHE_TOKENS_MIN", raising=False)

    rc = dw.main(
        ["--json", "--registry", str(registry), "--playbook-root", str(tmp_path)]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert any(item["kind"] == "v0_schema" for item in payload)
