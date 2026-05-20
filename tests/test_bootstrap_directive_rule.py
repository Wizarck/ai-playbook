"""Tests for scripts/rules/bootstrap-directive.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_bd_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "bootstrap-directive.rule.py",
)
assert SPEC and SPEC.loader
_bd = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_bd)


VALID_AGENTS = (
    "## 0 Bootstrap directive\n\n"
    "Before responding:\n"
    "1. Read dispatcher-chain.md\n"
    "2. Consult injected-context.md\n"
    "3. Scan openspec/changes/*/\n"
    "4. Respond\n"
)


def _make(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "AGENTS.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_canonical_block_passes(tmp_path: Path) -> None:
    assert _bd.validate([str(_make(tmp_path, VALID_AGENTS))]) == 0


def test_missing_section_zero_fails(tmp_path: Path, capsys) -> None:
    text = "# Introduction\n\nBlah.\n"
    rc = _bd.validate([str(_make(tmp_path, text))])
    assert rc == 1
    assert "§0" in capsys.readouterr().err


def test_missing_token_fails(tmp_path: Path, capsys) -> None:
    text = "## 0 Bootstrap\n\nNothing useful here.\n"
    rc = _bd.validate([str(_make(tmp_path, text))])
    assert rc == 1
    assert "missing tokens" in capsys.readouterr().err


def test_missing_file_returns_2(capsys) -> None:
    assert _bd.validate(["/no/such/AGENTS.md"]) == 2


def test_skip_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_BOOTSTRAP_DIRECTIVE_SKIP", "1")
    assert _bd.validate([str(_make(tmp_path, "broken"))]) == 0


# --- apply ---------------------------------------------------------------------

def test_apply_inserts_canonical_when_section_zero_missing(tmp_path: Path) -> None:
    p = _make(tmp_path, "# My Project\n\nSome other content here.\n")
    rc = _bd.apply([str(p)], dry_run=False)
    assert rc == 0
    new = p.read_text(encoding="utf-8")
    assert "## 0. Bootstrap directive" in new
    assert "dispatcher-chain.md" in new
    assert "openspec/changes" in new
    # Validate now passes.
    assert _bd.validate([str(p)]) == 0


def test_apply_idempotent_when_already_canonical(tmp_path: Path) -> None:
    p = _make(tmp_path, "# Project\n\n" + VALID_AGENTS)
    rc = _bd.apply([str(p)], dry_run=False)
    assert rc == 0
    # File unchanged in content.
    assert "## 0 Bootstrap directive" in p.read_text(encoding="utf-8")


def test_apply_refuses_when_section_zero_malformed(tmp_path: Path, capsys) -> None:
    # §0 present but missing required tokens → validate fails → apply refuses.
    p = _make(tmp_path, "## 0 Bootstrap\n\nSome custom prose.\n")
    rc = _bd.apply([str(p)], dry_run=False)
    assert rc == 1
    assert "refuse" in capsys.readouterr().err


def test_apply_dry_run_does_not_write(tmp_path: Path) -> None:
    body = "# Project\n\nOther content.\n"
    p = _make(tmp_path, body)
    rc = _bd.apply([str(p)], dry_run=True)
    assert rc == 0
    assert p.read_text(encoding="utf-8") == body


def test_apply_preserves_frontmatter(tmp_path: Path) -> None:
    body = "---\nschema: agents-md/v1\n---\n\n# Project\n\nContent.\n"
    p = _make(tmp_path, body)
    rc = _bd.apply([str(p)], dry_run=False)
    assert rc == 0
    new = p.read_text(encoding="utf-8")
    # Frontmatter still at top.
    assert new.startswith("---\nschema: agents-md/v1\n---")
    # H1 preserved.
    assert "# Project" in new


def test_apply_fatal_when_path_missing(tmp_path: Path) -> None:
    rc = _bd.apply([str(tmp_path / "missing.md")], dry_run=False)
    assert rc == 2


def test_apply_fatal_when_no_paths_given() -> None:
    assert _bd.apply([], dry_run=False) == 2
