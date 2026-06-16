"""Tests for scripts.ponytail.cli — on / off / status flows."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ponytail import cli, toggle


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
    assert "ponytail: OFF" in out


def test_status_json(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["--project", str(project), "status", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"]["enabled"] is False
    assert payload["state"]["schema"] == "ponytail-toggle/v1"
    assert payload["state_path"].endswith("/.ai-playbook/ponytail.json")
    assert payload["derived"]["materialised"] is False


def test_status_materialised_flag_true_when_block_present(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (project / "AGENTS.md").write_text(
        "# fake\n\n<!-- BEGIN auto-managed: ponytail/ruleset:full -->\nrules\n<!-- END auto-managed -->\n",
        encoding="utf-8",
    )
    rc = cli.main(["--project", str(project), "status", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["derived"]["materialised"] is True


# ---------------------------------------------------------------------------
# on
# ---------------------------------------------------------------------------


def test_on_default_writes_state_and_materialises(project: Path) -> None:
    rc = cli.main(["--project", str(project), "on"])
    assert rc == 0
    state = toggle.read_state(project)
    assert state["enabled"] is True
    assert state["mode"] == "full"
    assert state["components"]["code_style"] is True
    # Other components stay false by default.
    assert state["components"]["review_ponytail"] is False
    # code_style materialises the block.
    assert "BEGIN auto-managed: ponytail/ruleset:full" in (project / "AGENTS.md").read_text(encoding="utf-8")


def test_on_with_mode_and_components(project: Path) -> None:
    rc = cli.main(
        [
            "--project", str(project), "on",
            "--mode", "ultra",
            "--components", "code_style,review_ponytail,audit_ponytail",
        ]
    )
    assert rc == 0
    state = toggle.read_state(project)
    assert state["enabled"] is True
    assert state["mode"] == "ultra"
    assert state["components"]["code_style"] is True
    assert state["components"]["review_ponytail"] is True
    assert state["components"]["audit_ponytail"] is True
    assert state["components"]["debt_ponytail"] is False


def test_on_capability_only_does_not_materialise(project: Path) -> None:
    # review/audit/debt without code_style → no AGENTS.md mutation.
    rc = cli.main(["--project", str(project), "on", "--components", "review_ponytail,debt_ponytail"])
    assert rc == 0
    state = toggle.read_state(project)
    assert state["enabled"] is True
    assert state["components"]["code_style"] is False
    assert "BEGIN auto-managed: ponytail" not in (project / "AGENTS.md").read_text(encoding="utf-8")


def test_on_rejects_invalid_mode(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["--project", str(project), "on", "--mode", "extremist"])
    assert rc == 1
    assert "invalid mode" in capsys.readouterr().err


def test_on_rejects_invalid_components(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["--project", str(project), "on", "--components", "code_style,mcp_shrink"])
    assert rc == 1
    assert "invalid component" in capsys.readouterr().err


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
    assert "BEGIN auto-managed: ponytail" not in (project / "AGENTS.md").read_text(encoding="utf-8")


def test_off_when_no_prior_state(project: Path) -> None:
    rc = cli.main(["--project", str(project), "off"])
    assert rc == 0
    state = toggle.read_state(project)
    assert state["enabled"] is False


# ---------------------------------------------------------------------------
# --project arg position (UI subprocess robustness)
# ---------------------------------------------------------------------------


def test_project_arg_accepted_before_subcommand(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["--project", str(project), "status"])
    assert rc == 0
    assert str(project) in capsys.readouterr().out


def test_project_arg_accepted_after_subcommand(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["status", "--project", str(project)])
    assert rc == 0
    assert str(project) in capsys.readouterr().out


def test_project_arg_after_subcommand_with_other_flag(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["status", "--json", "--project", str(project)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["project_root"].replace("\\", "/").endswith(project.name)
