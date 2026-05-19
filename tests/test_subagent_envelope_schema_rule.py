"""Tests for scripts/rules/subagent-envelope-schema.rule.py."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_ses_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "subagent-envelope-schema.rule.py",
)
assert SPEC and SPEC.loader
_ses = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_ses)


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "env.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_missing_jsonschema_returns_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_ses, "jsonschema", None)
    p = _write(tmp_path, {"slug": "x"})
    assert _ses.validate(p) == 2


def test_missing_envelope_returns_2(tmp_path: Path) -> None:
    rc = _ses.validate(tmp_path / "no-such.json")
    assert rc == 2


def test_missing_schema_returns_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _write(tmp_path, {"slug": "x"})
    monkeypatch.setattr(_ses, "SCHEMA_PATH", Path("/no/such/schema.json"))
    assert _ses.validate(p) == 2


def test_skip_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_SUBAGENT_ENVELOPE_SCHEMA_SKIP", "1")
    p = _write(tmp_path, {"slug": "x"})
    assert _ses.validate(p) == 0


def test_no_path_arg_is_noop() -> None:
    assert _ses.main(["validate"]) == 0


def test_malformed_json_returns_2(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not valid", encoding="utf-8")
    assert _ses.validate(p) == 2
