"""Tests for scripts/gemini_start.py — the Windows exec path."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import gemini_start as gs

# The shim `npm install -g @google/gemini-cli` writes (cmd-shim), byte for byte
# in shape: the user's args reach the target through `%*` inside cmd.exe.
NPM_SHIM = (
    "@ECHO off\r\nGOTO start\r\n:find_dp0\r\nSET dp0=%~dp0\r\nEXIT /b\r\n:start\r\n"
    "SETLOCAL\r\nCALL :find_dp0\r\n\r\n"
    'IF EXIST "%dp0%\\node.exe" (\r\n  SET "_prog=%dp0%\\node.exe"\r\n) ELSE (\r\n'
    '  SET "_prog=node"\r\n  SET PATHEXT=%PATHEXT:;.JS;=;%\r\n)\r\n\r\n'
    "endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "
    '"%_prog%"  "%dp0%\\node_modules\\@google\\gemini-cli\\dist\\index.js" %*\r\n'
)
OLD_NPM_SHIM = (
    '@IF EXIST "%~dp0\\node.exe" (\r\n'
    '  "%~dp0\\node.exe"  "%~dp0\\node_modules\\@google\\gemini-cli\\dist\\index.js" %*\r\n'
    ") ELSE (\r\n  @SETLOCAL\r\n  @SET PATHEXT=%PATHEXT:;.JS;=;%\r\n"
    '  node  "%~dp0\\node_modules\\@google\\gemini-cli\\dist\\index.js" %*\r\n)\r\n'
)
ENTRY = ("node_modules", "@google", "gemini-cli", "dist", "index.js")

# Prompts cmd.exe mangles or executes when they pass through a .cmd shim.
HOSTILE_PROMPTS = [
    "compare old > new & summarise",
    'explain "a && echo BROKE-OUT" please',
    'he said "x & echo INJECTED-AFTER-QUOTE',
    "cost is 100%PATHEXT% ok",
    'what does "cat x >notes.txt" do',
    "x>redir-target.txt",
]


def _shim(tmp_path: Path, text: str = NPM_SHIM, *, entry: tuple[str, ...] = ENTRY) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    shim = tmp_path / "gemini.cmd"
    shim.write_bytes(text.encode("utf-8"))
    script = tmp_path.joinpath(*entry)
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("// entry\n", encoding="utf-8")
    return shim


def _which(**found: str | None):
    return lambda name: found.get(name)


# ---------------------------------------------------------------------------
# Shim resolution (pure path logic — runs on every OS)
# ---------------------------------------------------------------------------


def test_npm_shim_resolves_to_node_beside_it(tmp_path: Path) -> None:
    shim = _shim(tmp_path)
    (tmp_path / "node.exe").write_bytes(b"")
    assert gs._resolve_npm_shim(str(shim)) == [
        str(tmp_path / "node.exe"), str(tmp_path.joinpath(*ENTRY)),
    ]


def test_npm_shim_falls_back_to_node_exe_on_path(tmp_path: Path, monkeypatch) -> None:
    shim = _shim(tmp_path)
    monkeypatch.setattr(gs.shutil, "which", _which(**{"node.exe": "/opt/node.exe"}))
    assert gs._resolve_npm_shim(str(shim)) == ["/opt/node.exe", str(tmp_path.joinpath(*ENTRY))]


def test_older_npm_shim_layout_resolves(tmp_path: Path, monkeypatch) -> None:
    shim = _shim(tmp_path, OLD_NPM_SHIM)
    monkeypatch.setattr(gs.shutil, "which", _which(**{"node.exe": "/opt/node.exe"}))
    assert gs._resolve_npm_shim(str(shim)) == ["/opt/node.exe", str(tmp_path.joinpath(*ENTRY))]


def test_shebang_node_flags_are_kept(tmp_path: Path, monkeypatch) -> None:
    shim = _shim(tmp_path, NPM_SHIM.replace('"%_prog%"  ', '"%_prog%"  --no-warnings '))
    monkeypatch.setattr(gs.shutil, "which", _which(**{"node.exe": "/opt/node.exe"}))
    assert gs._resolve_npm_shim(str(shim)) == [
        "/opt/node.exe", "--no-warnings", str(tmp_path.joinpath(*ENTRY)),
    ]


def test_native_exe_shim_resolves_to_the_exe(tmp_path: Path) -> None:
    rel = ("node_modules", "@google", "gemini-cli", "bin", "gemini.exe")
    text = ('@ECHO off\r\nGOTO start\r\n:find_dp0\r\nSET dp0=%~dp0\r\nEXIT /b\r\n:start\r\n'
            'SETLOCAL\r\nCALL :find_dp0\r\n'
            '"%dp0%\\node_modules\\@google\\gemini-cli\\bin\\gemini.exe"   %*\r\n')
    shim = _shim(tmp_path, text, entry=rel)
    assert gs._resolve_npm_shim(str(shim)) == [str(tmp_path.joinpath(*rel))]


@pytest.mark.parametrize("text", [
    "@echo off\r\ncall some-launcher.cmd %*\r\n",                        # not cmd-shim
    NPM_SHIM.replace("SETLOCAL\r\n", "SETLOCAL\r\n@SET NODE_OPTIONS=--x\r\n"),  # shebang env
])
def test_unrecognised_shims_are_not_bypassed(tmp_path: Path, text: str) -> None:
    assert gs._resolve_npm_shim(str(_shim(tmp_path, text))) is None


def test_missing_entry_script_is_not_bypassed(tmp_path: Path) -> None:
    shim = tmp_path / "gemini.cmd"
    shim.write_bytes(NPM_SHIM.encode("utf-8"))
    (tmp_path / "node.exe").write_bytes(b"")
    assert gs._resolve_npm_shim(str(shim)) is None


# ---------------------------------------------------------------------------
# _exec_gemini on Windows (os.name patched; subprocess mocked)
# ---------------------------------------------------------------------------


def _record_runs(monkeypatch) -> list[tuple[Any, dict[str, Any]]]:
    calls: list[tuple[Any, dict[str, Any]]] = []

    class _Proc:
        returncode = 7

    def fake_run(cmd: Any, **kwargs: Any) -> _Proc:
        calls.append((cmd, kwargs))
        return _Proc()

    monkeypatch.setattr(gs, "os", SimpleNamespace(name="nt"))  # never patch the real os.name
    monkeypatch.setattr(gs.subprocess, "run", fake_run)
    return calls


def test_windows_exec_passes_argv_list_without_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    """A prompt with spaces and cmd.exe metacharacters must reach gemini as ONE
    argv entry, never through a shell (it used to be split, and `>`/`&` ran)."""
    calls = _record_runs(monkeypatch)
    monkeypatch.setattr(gs.shutil, "which", lambda name: r"C:\npm\gemini.CMD")

    rc = gs._exec_gemini(["-p", "compare old > new & summarise"])

    assert rc == 7
    (cmd, kwargs), = calls
    assert cmd == [r"C:\npm\gemini.CMD", "-p", "compare old > new & summarise"]
    assert not kwargs.get("shell")


@pytest.mark.parametrize("prompt", HOSTILE_PROMPTS)
def test_windows_npm_shim_is_bypassed_so_argv_is_verbatim(
    tmp_path: Path, monkeypatch, prompt: str,
) -> None:
    """cmd.exe re-parses a .cmd's command line: a `"` flips its quote pairing and
    `%VAR%` expands. Running node + the shim's JS entry avoids cmd.exe."""
    calls = _record_runs(monkeypatch)
    shim = _shim(tmp_path)
    monkeypatch.setattr(gs.shutil, "which",
                        _which(gemini=str(shim), **{"node.exe": "/opt/node.exe"}))

    assert gs._exec_gemini(["-p", prompt]) == 7
    (cmd, _), = calls
    assert cmd == ["/opt/node.exe", str(tmp_path.joinpath(*ENTRY)), "-p", prompt]


@pytest.mark.parametrize("prompt", HOSTILE_PROMPTS[1:])
def test_windows_unrecognised_shim_refuses_args_cmd_would_reinterpret(
    tmp_path: Path, monkeypatch, capsys, prompt: str,
) -> None:
    calls = _record_runs(monkeypatch)
    shim = tmp_path / "gemini.bat"
    shim.write_text("@echo off\r\ncall launcher.cmd %*\r\n", encoding="utf-8")
    monkeypatch.setattr(gs.shutil, "which", _which(gemini=str(shim)))

    assert gs._exec_gemini(["-p", prompt]) == 1
    assert calls == []
    err = capsys.readouterr().err
    assert "refusing to pass these arguments through cmd.exe" in err
    assert "OVERRIDE: none" in err


def test_windows_unrecognised_shim_still_runs_plain_args(tmp_path: Path, monkeypatch) -> None:
    """NEGATIVE CONTROL: quoted spaces and metacharacters inside them are safe."""
    calls = _record_runs(monkeypatch)
    shim = tmp_path / "gemini.bat"
    shim.write_text("@echo off\r\ncall launcher.cmd %*\r\n", encoding="utf-8")
    monkeypatch.setattr(gs.shutil, "which", _which(gemini=str(shim)))

    assert gs._exec_gemini(["-p", "compare old > new & summarise", "--yolo"]) == 7
    (cmd, _), = calls
    assert cmd == [str(shim), "-p", "compare old > new & summarise", "--yolo"]


def test_windows_native_exe_runs_directly(monkeypatch) -> None:
    calls = _record_runs(monkeypatch)
    monkeypatch.setattr(gs.shutil, "which", lambda name: r"C:\volta\gemini.exe")
    assert gs._exec_gemini(["-p", 'a "b" %c%']) == 7
    (cmd, _), = calls
    assert cmd == [r"C:\volta\gemini.exe", "-p", 'a "b" %c%']


def test_windows_exec_missing_gemini_returns_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(gs, "os", SimpleNamespace(name="nt"))  # never patch the real os.name
    monkeypatch.setattr(gs.shutil, "which", lambda name: None)
    assert gs._exec_gemini([]) == 1
    assert "not found on PATH" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The real thing: a real npm .cmd shim, real cmd.exe resolution, real node
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe shim semantics are Windows-only")
@pytest.mark.skipif(shutil.which("node.exe") is None, reason="node not on PATH")
def test_windows_real_npm_shim_passes_hostile_prompts_verbatim(
    tmp_path: Path, monkeypatch, capfd,
) -> None:
    bin_dir, work = tmp_path / "bin", tmp_path / "work"
    work.mkdir()
    _shim(bin_dir)
    bin_dir.joinpath(*ENTRY).write_text(
        'console.log("ARGV=" + JSON.stringify(process.argv.slice(2)));\n', encoding="utf-8",
    )
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.chdir(work)

    for prompt in HOSTILE_PROMPTS:
        assert gs._exec_gemini(["-p", prompt]) == 0, prompt
        out = capfd.readouterr().out
        argv = json.loads(out.split("ARGV=", 1)[1].splitlines()[0])
        assert argv == ["-p", prompt]
    assert list(work.iterdir()) == [], "cmd.exe redirected or ran part of a prompt"
