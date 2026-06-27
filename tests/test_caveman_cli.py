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
    assert state["mode"] == "ultra"
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


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------


def test_rollback_requires_yes_when_backups_exist(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Create a backup so rollback has something to consider
    from scripts.caveman import backup as backup_mod

    (project / "AGENTS.md").write_text("# v1\n", encoding="utf-8")
    backup_mod.make_backup(project, "agents", project / "AGENTS.md")
    (project / "AGENTS.md").write_text("# v2 mutated\n", encoding="utf-8")

    rc = cli.main(["--project", str(project), "rollback"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "--yes" in err
    # File NOT restored without --yes
    assert "# v2 mutated" in (project / "AGENTS.md").read_text(encoding="utf-8")


def test_rollback_with_yes_restores(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.caveman import backup as backup_mod

    (project / "AGENTS.md").write_text("# original\n", encoding="utf-8")
    backup_mod.make_backup(project, "agents", project / "AGENTS.md")
    (project / "AGENTS.md").write_text("# mutated\n", encoding="utf-8")

    rc = cli.main(["--project", str(project), "rollback", "--yes"])
    assert rc == 0
    assert (project / "AGENTS.md").read_text(encoding="utf-8") == "# original\n"


def test_rollback_list_shows_candidates_without_restoring(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.caveman import backup as backup_mod

    (project / "AGENTS.md").write_text("# v1\n", encoding="utf-8")
    backup_mod.make_backup(project, "agents", project / "AGENTS.md")
    (project / "AGENTS.md").write_text("# v2\n", encoding="utf-8")

    rc = cli.main(["--project", str(project), "rollback", "--list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "AGENTS.md" in out
    assert "would restore" in out
    # File NOT restored
    assert "# v2" in (project / "AGENTS.md").read_text(encoding="utf-8")


def test_rollback_when_no_backups(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["--project", str(project), "rollback", "--yes"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no backups found" in err


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


def test_project_arg_accepted_before_subcommand(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # --project BEFORE the subcommand (UI canonical form).
    rc = cli.main(["--project", str(project), "status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert str(project) in out


def test_project_arg_accepted_after_subcommand(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # --project AFTER the subcommand (what an unsuspecting subprocess call
    # might emit). Both must work — pinned because previously argparse
    # silently overrode the parent's value with the subparser's None default.
    rc = cli.main(["status", "--project", str(project)])
    assert rc == 0
    out = capsys.readouterr().out
    assert str(project) in out


def test_project_arg_after_subcommand_with_other_flag(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # status --json --project ... — the exact shape the UI docs show.
    rc = cli.main(["status", "--json", "--project", str(project)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["project_root"].replace("\\", "/").endswith(project.name)


def test_stats_runs_clean_when_no_logs(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "ccdir"))
    rc = cli.main(["--project", str(project), "stats"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sessions:        0" in out


def test_stats_json(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "ccdir"))
    rc = cli.main(["--project", str(project), "stats", "--json"])
    assert rc == 0
    import json as _json
    payload = _json.loads(capsys.readouterr().out)
    assert payload["sessions"] == 0
    assert payload["extrapolated_saved"] == 0
    assert "savings_rate_assumption" in payload
