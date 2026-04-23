"""Tests for scripts/doctor.py (T14a)."""
from __future__ import annotations

import builtins
import importlib
import json
from pathlib import Path

import pytest

from scripts import doctor


# ---------------------------------------------------------------------------
# CheckResult shape
# ---------------------------------------------------------------------------


def test_checkresult_shape_is_stable() -> None:
    r = doctor.CheckResult("x", doctor.STATUS_OK, "ok detail")
    assert r.name == "x"
    assert r.status == "ok"
    assert r.detail == "ok detail"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def test_check_python_ok_on_311_plus() -> None:
    # The test suite itself runs on 3.11+ (env contract); this always passes.
    r = doctor.check_python()
    assert r.status == doctor.STATUS_OK
    assert "3." in r.detail


def test_check_git_ok_when_shutil_finds_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/git" if name == "git" else None)
    r = doctor.check_git()
    assert r.status == doctor.STATUS_OK
    assert "/usr/bin/git" in r.detail


def test_check_git_fail_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    r = doctor.check_git()
    assert r.status == doctor.STATUS_FAIL
    assert "git" in r.detail


def test_check_gh_warns_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    r = doctor.check_gh()
    assert r.status == doctor.STATUS_WARN


def test_check_npx_accepts_npx_cmd_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "C:/npx.cmd" if name == "npx.cmd" else None)
    r = doctor.check_npx()
    assert r.status == doctor.STATUS_OK


def test_check_pyyaml_ok_when_importable() -> None:
    # yaml is a hard dep per requirements; this always passes in this env.
    r = doctor.check_pyyaml()
    assert r.status == doctor.STATUS_OK


def test_check_pyyaml_fail_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kw):  # noqa: ANN001
        if name == "yaml":
            raise ImportError("simulated missing yaml")
        return real_import(name, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    r = doctor.check_pyyaml()
    assert r.status == doctor.STATUS_FAIL


def test_check_jsonschema_fail_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kw):  # noqa: ANN001
        if name == "jsonschema":
            raise ImportError("simulated missing jsonschema")
        return real_import(name, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    r = doctor.check_jsonschema()
    assert r.status == doctor.STATUS_FAIL


def test_check_playbook_submodule_warns_when_absent(tmp_path: Path) -> None:
    r = doctor.check_playbook_submodule(tmp_path)
    assert r.status == doctor.STATUS_WARN


def test_check_playbook_submodule_ok_when_healthy(tmp_path: Path) -> None:
    sub = tmp_path / ".ai-playbook"
    (sub / "specs").mkdir(parents=True)
    (sub / "scripts").mkdir(parents=True)
    r = doctor.check_playbook_submodule(tmp_path)
    assert r.status == doctor.STATUS_OK


def test_check_playbook_submodule_fail_when_incomplete(tmp_path: Path) -> None:
    (tmp_path / ".ai-playbook").mkdir()
    r = doctor.check_playbook_submodule(tmp_path)
    assert r.status == doctor.STATUS_FAIL
    assert "specs" in r.detail


def test_check_projects_registry_warn_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AIPLAYBOOK_PROJECTS_FILE", str(tmp_path / "none.yaml"))
    r = doctor.check_projects_registry()
    assert r.status == doctor.STATUS_WARN


def test_check_projects_registry_ok_when_populated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reg = tmp_path / "projects.yaml"
    reg.write_text(
        "schema: ai-playbook/projects-registry/v1\n"
        "projects:\n"
        "  acme:\n"
        "    path: /tmp/acme\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIPLAYBOOK_PROJECTS_FILE", str(reg))
    r = doctor.check_projects_registry()
    assert r.status == doctor.STATUS_OK
    assert "1 project" in r.detail


def test_check_projects_registry_fail_on_bad_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reg = tmp_path / "projects.yaml"
    reg.write_text("::not: [valid", encoding="utf-8")
    monkeypatch.setenv("AIPLAYBOOK_PROJECTS_FILE", str(reg))
    r = doctor.check_projects_registry()
    assert r.status == doctor.STATUS_FAIL


def test_parse_required_env_vars_picks_yes_rows() -> None:
    text = (
        "| Var | Prefix | Purpose | Required? | Default | Where |\n"
        "|---|---|---|---|---|---|\n"
        "| `FOO_KEY` | `FOO_` | foo | yes | unset | x |\n"
        "| `OPT_KEY` | `OPT_` | opt | no | unset | y |\n"
        "| `BAR_KEY` | `BAR_` | bar | yes (conditional) | unset | z |\n"
    )
    names = doctor._parse_required_env_vars(text)
    assert "FOO_KEY" in names
    assert "BAR_KEY" in names
    assert "OPT_KEY" not in names


def test_check_env_vars_required_warns_on_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    (spec_dir / "env-vars.md").write_text(
        "| Var | Prefix | Purpose | Required? | Default | Where |\n"
        "|---|---|---|---|---|---|\n"
        "| `DOCTOR_TEST_VAR_XYZ` | `DOCTOR_` | test | yes | unset | x |\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DOCTOR_TEST_VAR_XYZ", raising=False)
    r = doctor.check_env_vars_required(tmp_path)
    assert r.status == doctor.STATUS_WARN
    assert "DOCTOR_TEST_VAR_XYZ" in r.detail


def test_check_env_vars_required_ok_when_all_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    (spec_dir / "env-vars.md").write_text(
        "| Var | Prefix | Purpose | Required? | Default | Where |\n"
        "|---|---|---|---|---|---|\n"
        "| `DOCTOR_PRESENT_VAR` | `DOCTOR_` | test | yes | unset | x |\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCTOR_PRESENT_VAR", "1")
    r = doctor.check_env_vars_required(tmp_path)
    assert r.status == doctor.STATUS_OK


def test_check_env_vars_alias_warning_fires_when_only_alias_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_CACHE_TOKENS_MIN", "2048")
    monkeypatch.delenv("AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN", raising=False)
    r = doctor.check_env_vars_alias_warning()
    assert r.status == doctor.STATUS_WARN
    assert "ANTHROPIC_CACHE_TOKENS_MIN" in r.detail


def test_check_env_vars_alias_warning_silent_when_canonical_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN", "2048")
    monkeypatch.setenv("ANTHROPIC_CACHE_TOKENS_MIN", "2048")
    r = doctor.check_env_vars_alias_warning()
    assert r.status == doctor.STATUS_OK


def test_check_context_budget_warns_when_over_threshold(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    (spec_dir / "big.md").write_text("x" * (101 * 1024), encoding="utf-8")
    r = doctor.check_context_budget(tmp_path)
    assert r.status == doctor.STATUS_WARN


def test_check_context_budget_ok_when_under_threshold(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    (spec_dir / "small.md").write_text("hello", encoding="utf-8")
    r = doctor.check_context_budget(tmp_path)
    assert r.status == doctor.STATUS_OK


# ---------------------------------------------------------------------------
# run_all + CLI
# ---------------------------------------------------------------------------


def test_run_all_returns_one_result_per_check() -> None:
    results = doctor.run_all()
    assert len(results) == len(doctor.ALL_CHECKS)
    names = {r.name for r in results}
    assert "python" in names
    assert "git" in names
    assert "context-budget" in names


def test_main_json_output_is_valid_array(capsys: pytest.CaptureFixture[str]) -> None:
    rc = doctor.main(["--json"])
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert all("status" in r and "name" in r for r in parsed)
    # doctor is advisory; in a healthy env we expect either 0 (warnings-allowed)
    # or 1 (some hard dep missing). Both are valid, we just guard against 2.
    assert rc in {0, 1}


def test_main_strict_promotes_warnings_to_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Simulate a WARN-only environment: the playbook-submodule check returns
    # warn when .ai-playbook/ is absent, which is true in any tmp cwd.
    fake_result = doctor.CheckResult("fake", doctor.STATUS_WARN, "simulated")

    def _one_warn() -> list[doctor.CheckResult]:
        return [fake_result]

    monkeypatch.setattr(doctor, "run_all", _one_warn)
    rc_default = doctor.main([])
    assert rc_default == 0
    rc_strict = doctor.main(["--strict"])
    assert rc_strict == 1


def test_main_returns_1_on_any_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_result = doctor.CheckResult("fake", doctor.STATUS_FAIL, "simulated")

    def _one_fail() -> list[doctor.CheckResult]:
        return [fake_result]

    monkeypatch.setattr(doctor, "run_all", _one_fail)
    assert doctor.main([]) == 1


def test_main_pretty_output_contains_sigils(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _mixed() -> list[doctor.CheckResult]:
        return [
            doctor.CheckResult("a", doctor.STATUS_OK, "ok"),
            doctor.CheckResult("b", doctor.STATUS_WARN, "meh"),
        ]

    monkeypatch.setattr(doctor, "run_all", _mixed)
    rc = doctor.main([])
    err = capsys.readouterr().err
    assert rc == 0
    assert "✅" in err
    assert "⚠️" in err
    assert "Summary:" in err
