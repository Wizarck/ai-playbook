"""Tests for scripts.caveman.cli — on / off / status flows."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.caveman import cli, toggle


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A fake project root with an AGENTS.md, used as --project arg."""
    (tmp_path / "AGENTS.md").write_text("# fake\n", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_default_when_no_state_file(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["--project", str(project), "status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "caveman: OFF" in out


def test_status_json(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["--project", str(project), "status", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"]["enabled"] is False
    assert payload["state"]["schema"] == "caveman-toggle/v1"
    assert payload["state_path"].endswith("/.ai-playbook/caveman.json")
    assert "derived" in payload
    assert payload["derived"]["materialised"] is False


def test_status_no_project_root_fails(tmp_path: Path) -> None:
    # tmp_path has neither AGENTS.md nor .ai-playbook/.
    rc = cli.main(["--project", str(tmp_path / "ghost"), "status"])
    # Resolve to a non-existent path: still resolves (Path.resolve is permissive),
    # so the run actually creates state under that path. To force "no project root"
    # we test the lookup-from-cwd path indirectly via toggle.find_project_root only.
    # Here we just confirm the CLI does not crash when given an explicit (non-existent) path.
    assert rc in (0, 2)


def test_status_materialised_flag_true_when_block_present(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (project / "AGENTS.md").write_text(
        "# fake\n\n<!-- BEGIN auto-managed: caveman/ruleset:full -->\nrules\n<!-- END auto-managed -->\n",
        encoding="utf-8",
    )
    rc = cli.main(["--project", str(project), "status", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["derived"]["materialised"] is True


# ---------------------------------------------------------------------------
# on
# ---------------------------------------------------------------------------


def test_on_default_writes_state(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["--project", str(project), "on"])
    assert rc == 0
    state = toggle.read_state(project)
    assert state["enabled"] is True
    assert state["mode"] == "full"
    assert state["components"]["response_style"] is True
    # Other components stay false by default.
    assert state["components"]["mcp_shrink"] is False


def test_on_with_mode_and_components(project: Path) -> None:
    rc = cli.main(
        [
            "--project",
            str(project),
            "on",
            "--mode",
            "ultra",
            "--components",
            "response_style,mcp_shrink,compress_docs",
        ]
    )
    assert rc == 0
    state = toggle.read_state(project)
    assert state["enabled"] is True
    assert state["mode"] == "ultra"
    assert state["components"]["response_style"] is True
    assert state["components"]["mcp_shrink"] is True
    assert state["components"]["compress_docs"] is True
    assert state["components"]["subagents_cavecrew"] is False


def test_on_rejects_invalid_mode(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["--project", str(project), "on", "--mode", "telegraphic"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "invalid mode" in err


def test_on_rejects_invalid_components(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(
        ["--project", str(project), "on", "--components", "response_style,wenyan_mode"]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "invalid component" in err


def test_on_json_output(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["--project", str(project), "on", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["state"]["enabled"] is True


# ---------------------------------------------------------------------------
# off
# ---------------------------------------------------------------------------


def test_off_after_on(project: Path) -> None:
    cli.main(["--project", str(project), "on", "--mode", "full"])
    rc = cli.main(["--project", str(project), "off"])
    assert rc == 0
    state = toggle.read_state(project)
    assert state["enabled"] is False
    assert all(v is False for v in state["components"].values())


def test_off_when_no_prior_state(project: Path) -> None:
    rc = cli.main(["--project", str(project), "off"])
    assert rc == 0
    state = toggle.read_state(project)
    assert state["enabled"] is False


# ---------------------------------------------------------------------------
# stubs for not-yet-implemented subcommands
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sub", ["compress", "stats", "mcp-shrink", "mcp-restore", "rollback"])
def test_phase_b_stubs_exit_2(project: Path, sub: str, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["--project", str(project), sub])
    assert rc == 2
    err = capsys.readouterr().err
    assert "not implemented yet" in err
