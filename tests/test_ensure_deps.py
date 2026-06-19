"""Tests for scripts/_ensure_deps.py — the runtime-dependency self-heal."""
from __future__ import annotations

import pytest

from scripts import _ensure_deps as ed


def test_already_present_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[list[str]] = []
    monkeypatch.setattr(ed, "_install", lambda dists: called.append(dists))
    # stdlib modules are always importable → nothing to install
    assert ed.ensure_runtime_deps("json", "sys") == []
    assert called == []


def test_dist_name_mapping() -> None:
    assert ed._dists(["yaml", "jsonschema"]) == ["pyyaml", "jsonschema"]


def test_self_heal_installs_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"installed": False}

    def fake_import(name: str):
        if name == "fakepkg" and not state["installed"]:
            raise ImportError(name)
        return object()

    def fake_install(dists: list[str]) -> None:
        assert dists == ["fakepkg"]
        state["installed"] = True

    monkeypatch.setattr(ed.importlib, "import_module", fake_import)
    monkeypatch.setattr(ed, "_install", fake_install)
    # missing first, installed by the backend, importable on re-check
    assert ed.ensure_runtime_deps("fakepkg") == ["fakepkg"]
    assert state["installed"] is True


def test_still_missing_after_install_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    def always_missing(name: str):
        raise ImportError(name)

    monkeypatch.setattr(ed.importlib, "import_module", always_missing)
    monkeypatch.setattr(ed, "_install", lambda dists: None)  # backend does nothing
    with pytest.raises(SystemExit) as exc:
        ed.ensure_runtime_deps("fakepkg")
    assert exc.value.code == 2


def test_install_prefers_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    cmds: list[list[str]] = []
    monkeypatch.setattr(ed.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(ed, "_run", lambda cmd: cmds.append(cmd) or True)
    ed._install(["jsonschema"])
    assert cmds and cmds[0][:2] == ["uv", "pip"]
    assert "jsonschema" in cmds[0]
