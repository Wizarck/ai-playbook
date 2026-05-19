"""Tests for scripts/rules/agentic-failure-catalog-schema.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_afcs_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "agentic-failure-catalog-schema.rule.py",
)
assert SPEC and SPEC.loader
_afcs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_afcs)

VALID_CATALOG = """---
schema: concept/v1
slug: agentic-failures
---

# Agentic Failures

## 1. Failure catalog

| ID | Short name | Severity class | Detectable? |
|---|---|---|---|
| `hallucination` | Cited entity does not exist | S1 | Yes |
| `infinite_loop` | Same tool ≥3× no progress | S2 | Yes |
| `prompt_injection` | Imperative strings in tool output | S1 | Partial |
"""

NO_HEADING = """---
schema: concept/v1
slug: agentic-failures
---
just some prose without the catalog heading.
"""

NO_ROWS = """---
schema: concept/v1
slug: agentic-failures
---

## 1. Failure catalog

heading present but no table rows at all.
"""

DUPLICATE_ID = """---
schema: concept/v1
slug: agentic-failures
---

## 1. Failure catalog

| ID | Short | Severity | Detect |
|---|---|---|---|
| `hallucination` | A | S1 | Y |
| `hallucination` | B | S1 | Y |
"""


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "agentic-failures.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_valid_catalog_passes(tmp_path: Path) -> None:
    p = _write(tmp_path, VALID_CATALOG)
    assert _afcs.main(["validate", str(p)]) == 0


def test_missing_heading_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _write(tmp_path, NO_HEADING)
    assert _afcs.main(["validate", str(p)]) == 1
    assert "missing" in capsys.readouterr().err.lower()


def test_no_rows_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _write(tmp_path, NO_ROWS)
    assert _afcs.main(["validate", str(p)]) == 1
    assert "rows" in capsys.readouterr().err.lower()


def test_duplicate_id_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _write(tmp_path, DUPLICATE_ID)
    assert _afcs.main(["validate", str(p)]) == 1
    assert "duplicate" in capsys.readouterr().err.lower()


def test_missing_file_returns_two(tmp_path: Path) -> None:
    assert _afcs.main(["validate", str(tmp_path / "absent.md")]) == 2


def test_skip_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIPLAYBOOK_AGENTIC_FAILURE_CATALOG_SCHEMA_SKIP", "1")
    p = _write(tmp_path, NO_HEADING)
    assert _afcs.main(["validate", str(p)]) == 0
