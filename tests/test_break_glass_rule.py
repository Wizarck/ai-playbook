"""Tests for scripts/rules/break-glass.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_bg_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "break-glass.rule.py",
)
assert SPEC and SPEC.loader
_bg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_bg)


def _mk(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_non_blocking_script_passes(tmp_path: Path) -> None:
    p = _mk(tmp_path, "ok.py", "def hello(): return 1\n")
    assert _bg.main(["validate", str(p)]) == 0


def test_blocking_with_helper_passes(tmp_path: Path) -> None:
    body = """\
from scripts._break_glass import add_break_glass_flag, apply_break_glass
import sys
def main():
    add_break_glass_flag(None)
    if bad:
        sys.exit(1)
"""
    p = _mk(tmp_path, "ok.py", body)
    assert _bg.main(["validate", str(p)]) == 0


def test_blocking_with_override_none_passes(tmp_path: Path) -> None:
    body = '"""script.\n\nOVERRIDE: none — protects credentials.\n"""\nimport sys\nsys.exit(1)\n'
    p = _mk(tmp_path, "ok.py", body)
    assert _bg.main(["validate", str(p)]) == 0


def test_blocking_without_signals_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    body = "import sys\ndef main():\n    sys.exit(1)\n"
    p = _mk(tmp_path, "bad.py", body)
    rc = _bg.main(["validate", str(p)])
    assert rc == 1
    assert "break-glass" in capsys.readouterr().err.lower()


def test_missing_file_returns_two(tmp_path: Path) -> None:
    assert _bg.main(["validate", str(tmp_path / "absent.py")]) == 2


def test_skip_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIPLAYBOOK_BREAK_GLASS_SKIP", "1")
    body = "import sys\nsys.exit(1)\n"
    p = _mk(tmp_path, "bad.py", body)
    assert _bg.main(["validate", str(p)]) == 0
