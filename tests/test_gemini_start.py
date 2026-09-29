"""Tests for scripts/gemini_start.py — the Windows exec path."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from scripts import gemini_start as gs


def test_windows_exec_passes_argv_list_without_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    """A prompt with spaces and cmd.exe metacharacters must reach gemini as ONE
    argv entry, never through a shell (it used to be split, and `>`/`&` ran)."""
    calls: list[tuple[Any, dict[str, Any]]] = []

    class _Proc:
        returncode = 7

    def fake_run(cmd: Any, **kwargs: Any) -> _Proc:
        calls.append((cmd, kwargs))
        return _Proc()

    monkeypatch.setattr(gs, "os", SimpleNamespace(name="nt"))  # never patch the real os.name
    monkeypatch.setattr(gs.shutil, "which", lambda name: r"C:\npm\gemini.CMD")
    monkeypatch.setattr(gs.subprocess, "run", fake_run)

    rc = gs._exec_gemini(["-p", "compare old > new & summarise"])

    assert rc == 7
    (cmd, kwargs), = calls
    assert cmd == [r"C:\npm\gemini.CMD", "-p", "compare old > new & summarise"]
    assert not kwargs.get("shell")


def test_windows_exec_missing_gemini_returns_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(gs, "os", SimpleNamespace(name="nt"))  # never patch the real os.name
    monkeypatch.setattr(gs.shutil, "which", lambda name: None)
    assert gs._exec_gemini([]) == 1
    assert "not found on PATH" in capsys.readouterr().err
