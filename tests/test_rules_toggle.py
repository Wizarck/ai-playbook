"""Tests for scripts.rules_toggle — CLI + state IO + inventory."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import rules_toggle


# ---------------------------------------------------------------------------
# Discovery + state IO
# ---------------------------------------------------------------------------


def test_find_playbook_root_found() -> None:
    root = rules_toggle.find_playbook_root()
    assert root is not None
    assert (root / "schemas" / "schema-rules-toggle-v1.json").is_file()


def test_default_state_shape() -> None:
    s = rules_toggle.default_state()
    assert s["schema"] == "rules-toggle/v1"
    assert s["rules"] == {}
    from datetime import datetime
    datetime.fromisoformat(s["applied_at"])


def _fake_project(tmp_path: Path) -> Path:
    (tmp_path / "AGENTS.md").write_text("# fake\n", encoding="utf-8")
    return tmp_path


def test_read_state_missing_returns_default(tmp_path: Path) -> None:
    project = _fake_project(tmp_path)
    s = rules_toggle.read_state(project)
    assert s["schema"] == "rules-toggle/v1"
    assert s["rules"] == {}


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    project = _fake_project(tmp_path)
    state = rules_toggle.default_state()
    state["rules"]["apply-skill-enforcement"] = {
        "enabled": False,
        "reason": "test reason >=10 chars",
    }
    rules_toggle.write_state(project, state)
    loaded = rules_toggle.read_state(project)
    assert loaded["rules"]["apply-skill-enforcement"]["enabled"] is False


def test_write_state_rejects_invalid_schema(tmp_path: Path) -> None:
    project = _fake_project(tmp_path)
    bad = {"schema": "rules-toggle/v1", "rules": {"foo": {"extra_field": True}}}
    with pytest.raises(Exception):
        rules_toggle.write_state(project, bad)


def test_read_state_rejects_corrupt_json(tmp_path: Path) -> None:
    project = _fake_project(tmp_path)
    p = rules_toggle.state_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        rules_toggle.read_state(project)


# ---------------------------------------------------------------------------
# is_rule_disabled (used by hook + cli_emit)
# ---------------------------------------------------------------------------


def test_is_rule_disabled_no_state_file(tmp_path: Path) -> None:
    project = _fake_project(tmp_path)
    assert rules_toggle.is_rule_disabled(project, "anything", layer="L1") is False


def test_is_rule_disabled_rule_absent(tmp_path: Path) -> None:
    project = _fake_project(tmp_path)
    rules_toggle.write_state(project, rules_toggle.default_state())
    assert rules_toggle.is_rule_disabled(project, "missing-rule", layer="L1") is False


def test_is_rule_disabled_full_disable(tmp_path: Path) -> None:
    project = _fake_project(tmp_path)
    state = rules_toggle.default_state()
    state["rules"]["apply-skill-enforcement"] = {"enabled": False, "reason": "ten-chars!"}
    rules_toggle.write_state(project, state)
    assert rules_toggle.is_rule_disabled(project, "apply-skill-enforcement", layer="L1") is True
    assert rules_toggle.is_rule_disabled(project, "apply-skill-enforcement", layer="L3") is True


def test_is_rule_disabled_layer_specific(tmp_path: Path) -> None:
    project = _fake_project(tmp_path)
    state = rules_toggle.default_state()
    state["rules"]["apply-skill-enforcement"] = {
        "enabled": True,
        "layers": {"L3": False},
    }
    rules_toggle.write_state(project, state)
    assert rules_toggle.is_rule_disabled(project, "apply-skill-enforcement", layer="L1") is False
    assert rules_toggle.is_rule_disabled(project, "apply-skill-enforcement", layer="L3") is True


def test_is_rule_disabled_invalid_layer(tmp_path: Path) -> None:
    project = _fake_project(tmp_path)
    with pytest.raises(ValueError):
        rules_toggle.is_rule_disabled(project, "x", layer="L7")


def test_is_rule_disabled_corrupt_file_safe(tmp_path: Path) -> None:
    project = _fake_project(tmp_path)
    p = rules_toggle.state_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json", encoding="utf-8")
    # Corrupt file → fail-safe to False (rule remains ON).
    assert rules_toggle.is_rule_disabled(project, "anything", layer="L1") is False


# ---------------------------------------------------------------------------
# Inventory generation
# ---------------------------------------------------------------------------


def test_build_rules_inventory_returns_known_rules() -> None:
    inv = rules_toggle.build_rules_inventory()
    assert inv["schema"] == "rules-inventory/v1"
    slugs = {r["slug"] for r in inv["rules"]}
    # apply-skill-enforcement is the rule with paired L3 + advanced bash_inspection.
    assert "apply-skill-enforcement" in slugs
    ase = next(r for r in inv["rules"] if r["slug"] == "apply-skill-enforcement")
    assert ase["has_l1"] is True
    assert ase["has_l3"] is True
    assert ase["break_glass_env"] == "AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE"
    assert "Bash" in ase["triggers"]
    assert "advanced" in ase
    keys = [a["key"] for a in ase["advanced"]]
    assert "bash_inspection" in keys


def test_inventory_advanced_mapping_has_env_var() -> None:
    inv = rules_toggle.build_rules_inventory()
    ase = next(r for r in inv["rules"] if r["slug"] == "apply-skill-enforcement")
    adv = next(a for a in ase["advanced"] if a["key"] == "bash_inspection")
    assert adv["env_var"] == "AIPLAYBOOK_BASH_INSPECTION"
    assert adv["value_on"] == "1"
    assert adv["value_off"] == "0"


# ---------------------------------------------------------------------------
# CLI subcommands
# ---------------------------------------------------------------------------


def _run_cli(monkeypatch: pytest.MonkeyPatch, project: Path, argv: list[str]) -> int:
    """Run rules_toggle.main with cwd=project and capture exit code."""
    monkeypatch.chdir(project)
    return rules_toggle.main(argv)


def test_cli_list_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    project = _fake_project(tmp_path)
    rc = _run_cli(monkeypatch, project, ["list", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "rules" in data
    assert len(data["rules"]) > 0


def test_cli_off_then_on_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    project = _fake_project(tmp_path)
    # Off with reason.
    rc = _run_cli(monkeypatch, project, ["off", "apply-skill-enforcement", "--reason", "test ten-chars reason"])
    assert rc == 0
    capsys.readouterr()
    # State file should exist.
    assert rules_toggle.state_path(project).is_file()
    # Audit log should have one line.
    audit = rules_toggle.audit_path(project).read_text(encoding="utf-8").strip().splitlines()
    assert len(audit) == 1
    assert json.loads(audit[0])["action"] == "off"
    # On.
    rc = _run_cli(monkeypatch, project, ["on", "apply-skill-enforcement"])
    assert rc == 0
    capsys.readouterr()
    state = rules_toggle.read_state(project)
    assert "apply-skill-enforcement" not in state.get("rules", {})


def test_cli_off_requires_reason_for_break_glass(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    project = _fake_project(tmp_path)
    rc = _run_cli(monkeypatch, project, ["off", "apply-skill-enforcement"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "break_glass_env" in err
    assert "reason" in err.lower()


def test_cli_off_layer_specific(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    project = _fake_project(tmp_path)
    rc = _run_cli(monkeypatch, project, ["off", "apply-skill-enforcement", "--layer", "L3", "--reason", "L3 ten-chars"])
    assert rc == 0
    capsys.readouterr()
    state = rules_toggle.read_state(project)
    entry = state["rules"]["apply-skill-enforcement"]
    assert entry["enabled"] is True  # only the layer was disabled
    assert entry["layers"]["L3"] is False


def test_cli_status_exit_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    project = _fake_project(tmp_path)
    state = rules_toggle.default_state()
    state["rules"]["apply-skill-enforcement"] = {"enabled": True, "layers": {"L3": False}}
    rules_toggle.write_state(project, state)
    # L3 OFF → exit-code 1.
    rc = _run_cli(monkeypatch, project, ["status", "--slug", "apply-skill-enforcement", "--layer", "L3", "--exit-code"])
    assert rc == 1
    capsys.readouterr()
    # L1 ON → exit-code 0.
    rc = _run_cli(monkeypatch, project, ["status", "--slug", "apply-skill-enforcement", "--layer", "L1", "--exit-code"])
    assert rc == 0


def test_cli_init_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    project = _fake_project(tmp_path)
    rc = _run_cli(monkeypatch, project, ["init"])
    assert rc == 0
    capsys.readouterr()
    assert rules_toggle.state_path(project).is_file()


def test_cli_inventory_writes_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    project = _fake_project(tmp_path)
    out = tmp_path / "out-inv.json"
    rc = _run_cli(monkeypatch, project, ["inventory", "--output", str(out), "--json"])
    assert rc == 0
    capsys.readouterr()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == "rules-inventory/v1"
    assert len(data["rules"]) > 0
