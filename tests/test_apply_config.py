"""Tests for scripts.apply_config — bundle → rules + caveman + global_flags."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import apply_config, rules_toggle


def _fake_project(tmp_path: Path) -> Path:
    (tmp_path / "AGENTS.md").write_text("# fake project\n", encoding="utf-8")
    return tmp_path


def _write_bundle(tmp_path: Path, bundle: dict) -> Path:
    p = tmp_path / "bundle.json"
    p.write_text(json.dumps(bundle), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_apply_rejects_missing_bundle(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        apply_config.apply(tmp_path / "missing.json", target=_fake_project(tmp_path))


def test_apply_rejects_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError):
        apply_config.apply(p, target=_fake_project(tmp_path))


def test_apply_rejects_wrong_schema(tmp_path: Path) -> None:
    bundle = {"schema": "wrong/v1"}
    bp = _write_bundle(tmp_path, bundle)
    with pytest.raises(ValueError):
        apply_config.apply(bp, target=_fake_project(tmp_path))


# ---------------------------------------------------------------------------
# Rules section
# ---------------------------------------------------------------------------


def test_apply_rules_section_writes_state_file(tmp_path: Path) -> None:
    target = _fake_project(tmp_path)
    bundle = {
        "schema": "ai-playbook-config/v1",
        "rules": {
            "apply-skill-enforcement": {
                "enabled": False,
                "reason": "test ten-chars reason",
            }
        },
    }
    bp = _write_bundle(tmp_path, bundle)
    # Mock caveman subprocess to avoid actually invoking it.
    with patch.object(apply_config, "apply_caveman") as mock_cv:
        from scripts.apply_config import SectionResult
        mock_cv.return_value = SectionResult(name="features.caveman", ok=True, detail="mocked")
        report = apply_config.apply(bp, target=target)
    assert report.ok
    state = rules_toggle.read_state(target)
    assert state["rules"]["apply-skill-enforcement"]["enabled"] is False


def test_apply_rules_advanced_projects_to_env_file(tmp_path: Path) -> None:
    target = _fake_project(tmp_path)
    bundle = {
        "schema": "ai-playbook-config/v1",
        "rules": {
            "apply-skill-enforcement": {
                "enabled": True,
                "advanced": {"bash_inspection": False},
            }
        },
    }
    bp = _write_bundle(tmp_path, bundle)
    with patch.object(apply_config, "apply_caveman") as mock_cv:
        from scripts.apply_config import SectionResult
        mock_cv.return_value = SectionResult(name="features.caveman", ok=True)
        apply_config.apply(bp, target=target)
    env_file = target / ".ai-playbook" / "feature-flags.env"
    assert env_file.is_file()
    body = env_file.read_text(encoding="utf-8")
    assert "AIPLAYBOOK_BASH_INSPECTION=0" in body
    assert apply_config.ENV_MARKER_BEGIN in body
    assert apply_config.ENV_MARKER_END in body


# ---------------------------------------------------------------------------
# Global flags section
# ---------------------------------------------------------------------------


def test_apply_global_flag_writes_env_block(tmp_path: Path) -> None:
    target = _fake_project(tmp_path)
    bundle = {
        "schema": "ai-playbook-config/v1",
        "global_flags": {"llm_routing_strict": True},
    }
    bp = _write_bundle(tmp_path, bundle)
    with patch.object(apply_config, "apply_caveman") as mock_cv:
        from scripts.apply_config import SectionResult
        mock_cv.return_value = SectionResult(name="features.caveman", ok=True)
        report = apply_config.apply(bp, target=target)
    assert report.ok
    env_file = target / ".ai-playbook" / "feature-flags.env"
    assert env_file.is_file()
    body = env_file.read_text(encoding="utf-8")
    assert "AIPLAYBOOK_LLM_ROUTING_STRICT=1" in body


def test_env_block_idempotent_on_reapply(tmp_path: Path) -> None:
    target = _fake_project(tmp_path)
    bundle = {
        "schema": "ai-playbook-config/v1",
        "global_flags": {"llm_routing_strict": True},
    }
    bp = _write_bundle(tmp_path, bundle)
    with patch.object(apply_config, "apply_caveman") as mock_cv:
        from scripts.apply_config import SectionResult
        mock_cv.return_value = SectionResult(name="features.caveman", ok=True)
        apply_config.apply(bp, target=target)
        first = (target / ".ai-playbook" / "feature-flags.env").read_text(encoding="utf-8")
        apply_config.apply(bp, target=target)
        second = (target / ".ai-playbook" / "feature-flags.env").read_text(encoding="utf-8")
    assert first == second  # idempotent: re-apply yields identical file


def test_env_block_preserves_user_lines_outside_markers(tmp_path: Path) -> None:
    target = _fake_project(tmp_path)
    (target / ".ai-playbook").mkdir(parents=True, exist_ok=True)
    env_file = target / ".ai-playbook" / "feature-flags.env"
    env_file.write_text("USER_VAR=preserved\n", encoding="utf-8")
    bundle = {
        "schema": "ai-playbook-config/v1",
        "global_flags": {"llm_routing_strict": True},
    }
    bp = _write_bundle(tmp_path, bundle)
    with patch.object(apply_config, "apply_caveman") as mock_cv:
        from scripts.apply_config import SectionResult
        mock_cv.return_value = SectionResult(name="features.caveman", ok=True)
        apply_config.apply(bp, target=target)
    body = env_file.read_text(encoding="utf-8")
    assert "USER_VAR=preserved" in body  # user's existing line preserved
    assert "AIPLAYBOOK_LLM_ROUTING_STRICT=1" in body  # block added


# ---------------------------------------------------------------------------
# Caveman section (subprocess delegation, mocked)
# ---------------------------------------------------------------------------


def test_caveman_on_subprocess_args(tmp_path: Path) -> None:
    target = _fake_project(tmp_path)
    bundle = {
        "schema": "ai-playbook-config/v1",
        "features": {
            "caveman": {
                "enabled": True,
                "mode": "lite",
                "components": {
                    "response_style": True,
                    "compress_docs": False,
                    "subagents_cavecrew": False,
                    "commit_caveman": False,
                    "review_caveman": False,
                    "mcp_shrink": False,
                },
            }
        },
    }
    bp = _write_bundle(tmp_path, bundle)
    captured: dict = {}
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")
    with patch.object(subprocess, "run", side_effect=fake_run):
        report = apply_config.apply(bp, target=target)
    assert report.ok
    assert captured["cmd"][1:4] == ["-m", "scripts.caveman", "on"]
    assert "--mode" in captured["cmd"]
    mode_idx = captured["cmd"].index("--mode")
    assert captured["cmd"][mode_idx + 1] == "lite"
    assert "--components" in captured["cmd"]
    comp_idx = captured["cmd"].index("--components")
    assert captured["cmd"][comp_idx + 1] == "response_style"


def test_caveman_off_subprocess_args(tmp_path: Path) -> None:
    target = _fake_project(tmp_path)
    bundle = {
        "schema": "ai-playbook-config/v1",
        "features": {"caveman": {"enabled": False}},
    }
    bp = _write_bundle(tmp_path, bundle)
    captured: dict = {}
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="off", stderr="")
    with patch.object(subprocess, "run", side_effect=fake_run):
        apply_config.apply(bp, target=target)
    assert captured["cmd"][1:5] == ["-m", "scripts.caveman", "off"]


def test_caveman_failure_does_not_block_other_sections(tmp_path: Path) -> None:
    target = _fake_project(tmp_path)
    bundle = {
        "schema": "ai-playbook-config/v1",
        "rules": {"apply-skill-enforcement": {"enabled": False, "reason": "ten-chars test"}},
        "features": {"caveman": {"enabled": True, "mode": "full"}},
        "global_flags": {"llm_routing_strict": True},
    }
    bp = _write_bundle(tmp_path, bundle)
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="caveman boom")
    with patch.object(subprocess, "run", side_effect=fake_run):
        report = apply_config.apply(bp, target=target)
    # Overall report is not ok because caveman failed.
    assert not report.ok
    # But rules + global_flags sections still ran.
    section_names = [s.name for s in report.sections]
    assert "rules" in section_names
    assert "features.caveman" in section_names
    assert "global_flags" in section_names
    rules_section = next(s for s in report.sections if s.name == "rules")
    assert rules_section.ok
    flags_section = next(s for s in report.sections if s.name == "global_flags")
    assert flags_section.ok
    # State file written despite caveman failure.
    state = rules_toggle.read_state(target)
    assert state["rules"]["apply-skill-enforcement"]["enabled"] is False
    # Env file written.
    env_file = target / ".ai-playbook" / "feature-flags.env"
    assert env_file.is_file()


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    target = _fake_project(tmp_path)
    bundle = {
        "schema": "ai-playbook-config/v1",
        "rules": {"apply-skill-enforcement": {"enabled": False, "reason": "ten-chars test"}},
        "global_flags": {"llm_routing_strict": True},
    }
    bp = _write_bundle(tmp_path, bundle)
    apply_config.apply(bp, target=target, dry_run=True)
    # No state file, no env file, no sidecar.
    assert not rules_toggle.state_path(target).is_file()
    assert not (target / ".ai-playbook" / "feature-flags.env").is_file()
    assert not (target / ".ai-playbook" / "applied-config.json").is_file()
    assert not (target / ".ai-playbook" / "applied-config.js").is_file()


# ---------------------------------------------------------------------------
# applied-config.json + applied-config.js sidecar (UI source of truth)
# ---------------------------------------------------------------------------


def test_applied_bundle_sidecar_written(tmp_path: Path) -> None:
    """apply_config must persist both applied-config.json and applied-config.js."""
    target = _fake_project(tmp_path)
    bundle = {
        "schema": "ai-playbook-config/v1",
        "rules": {"apply-skill-enforcement": {"enabled": True, "advanced": {"bash_inspection": False}}},
        "global_flags": {"llm_routing_strict": True},
    }
    bp = _write_bundle(tmp_path, bundle)
    with patch.object(apply_config, "apply_caveman") as mock_cv:
        from scripts.apply_config import SectionResult
        mock_cv.return_value = SectionResult(name="features.caveman", ok=True)
        apply_config.apply(bp, target=target)
    json_path = target / ".ai-playbook" / "applied-config.json"
    js_path = target / ".ai-playbook" / "applied-config.js"
    assert json_path.is_file()
    assert js_path.is_file()
    # JSON has the bundle (round-trip).
    persisted = json.loads(json_path.read_text(encoding="utf-8"))
    assert persisted["schema"] == "ai-playbook-config/v1"
    assert persisted["rules"]["apply-skill-enforcement"]["advanced"]["bash_inspection"] is False
    assert persisted["global_flags"]["llm_routing_strict"] is True
    # JS sidecar assigns window.APPLIED_CONFIG = <same bundle>.
    js_body = js_path.read_text(encoding="utf-8")
    assert "window.APPLIED_CONFIG = " in js_body
    # Extract the JSON literal from the assignment for shape verification.
    assigned = js_body.split("window.APPLIED_CONFIG = ", 1)[1].rstrip().rstrip(";").rstrip()
    parsed = json.loads(assigned)
    assert parsed == persisted


def test_applied_bundle_round_trip_through_reapply(tmp_path: Path) -> None:
    """Two applies in a row leave the sidecar matching the second bundle."""
    target = _fake_project(tmp_path)
    bundle_v1 = {
        "schema": "ai-playbook-config/v1",
        "global_flags": {"llm_routing_strict": True},
    }
    bundle_v2 = {
        "schema": "ai-playbook-config/v1",
        "global_flags": {"llm_routing_strict": False},
    }
    bp1 = _write_bundle(tmp_path, bundle_v1)
    bp2 = tmp_path / "bundle2.json"
    bp2.write_text(json.dumps(bundle_v2), encoding="utf-8")
    with patch.object(apply_config, "apply_caveman") as mock_cv:
        from scripts.apply_config import SectionResult
        mock_cv.return_value = SectionResult(name="features.caveman", ok=True)
        apply_config.apply(bp1, target=target)
        apply_config.apply(bp2, target=target)
    json_path = target / ".ai-playbook" / "applied-config.json"
    persisted = json.loads(json_path.read_text(encoding="utf-8"))
    assert persisted["global_flags"]["llm_routing_strict"] is False  # v2 wins


def test_applied_bundle_section_in_report(tmp_path: Path) -> None:
    """Report must list the applied-bundle section regardless of which other sections ran."""
    target = _fake_project(tmp_path)
    bundle = {"schema": "ai-playbook-config/v1"}  # empty: no rules, no caveman, no flags
    bp = _write_bundle(tmp_path, bundle)
    with patch.object(apply_config, "apply_caveman") as mock_cv:
        from scripts.apply_config import SectionResult
        mock_cv.return_value = SectionResult(name="features.caveman", ok=True)
        report = apply_config.apply(bp, target=target)
    section_names = [s.name for s in report.sections]
    assert "applied-bundle" in section_names
    # Even with empty bundle, the sidecar is written so the UI can render it.
    assert (target / ".ai-playbook" / "applied-config.json").is_file()
    assert (target / ".ai-playbook" / "applied-config.js").is_file()
