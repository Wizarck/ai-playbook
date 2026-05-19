"""Tests for scripts/rules/output-completeness.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_oc_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "output-completeness.rule.py",
)
assert SPEC and SPEC.loader
_oc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_oc)


def _make(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_clean_python_passes(tmp_path: Path) -> None:
    f = _make(tmp_path, "ok.py", "def add(a, b):\n    return a + b\n")
    assert _oc.validate([str(f)]) == 0


def test_python_todo_fails(tmp_path: Path, capsys) -> None:
    f = _make(tmp_path, "bad.py", "def f():\n    pass  # TODO\n")
    rc = _oc.validate([str(f)])
    assert rc == 1
    assert "placeholder" in capsys.readouterr().err.lower()


def test_not_implemented_fails(tmp_path: Path, capsys) -> None:
    f = _make(tmp_path, "bad.py", "def f():\n    raise NotImplementedError\n")
    rc = _oc.validate([str(f)])
    assert rc == 1


def test_tbd_marker_fails(tmp_path: Path) -> None:
    f = _make(tmp_path, "bad.md", "Value: <TBD>\n")
    rc = _oc.validate([str(f)])
    assert rc == 1


def test_for_brevity_fails(tmp_path: Path) -> None:
    f = _make(tmp_path, "bad.md", "Implementation, for brevity, skipped.\n")
    rc = _oc.validate([str(f)])
    assert rc == 1


def test_ellipsis_existing_code_fails(tmp_path: Path) -> None:
    f = _make(tmp_path, "bad.js", "function x() {\n  // ... existing code ...\n}\n")
    rc = _oc.validate([str(f)])
    assert rc == 1


def test_markdown_todo_in_prose_is_allowed(tmp_path: Path) -> None:
    # Markdown bodies legitimately mention TODO/FIXME in discussion.
    f = _make(tmp_path, "doc.md", "# Status\n\nThe TODO comment was removed.\n")
    assert _oc.validate([str(f)]) == 0


def test_skip_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_OUTPUT_COMPLETENESS_SKIP", "1")
    f = _make(tmp_path, "bad.py", "# TODO: implement\n")
    assert _oc.validate([str(f)]) == 0
