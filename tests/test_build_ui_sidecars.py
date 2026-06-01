"""Tests for scripts/build_ui_sidecars.py — the config-ui .js sidecar generator
and its freshness gate."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from scripts import build_ui_sidecars as bus

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_UI = REPO_ROOT / "config-ui"


def _seed(tmp_path: Path) -> Path:
    """Copy the committed inventory JSONs into a temp config-ui dir."""
    for name in bus.SIDECARS:
        shutil.copy(REAL_UI / name, tmp_path / name)
    return tmp_path


def test_committed_sidecars_are_fresh() -> None:
    """The gate dogfoods itself: the real repo must always pass --check, so a
    .json edited without regenerating its .js fails CI/pre-commit here too."""
    assert bus.main(["--check"]) == 0


def test_build_writes_sidecars_with_correct_globals(tmp_path, monkeypatch) -> None:
    _seed(tmp_path)
    monkeypatch.setattr(bus, "UI_DIR", tmp_path)
    assert bus.cmd_build(check=False) == 0
    for json_name, global_name in bus.SIDECARS.items():
        out = tmp_path / bus._sidecar_name(json_name)
        text = out.read_text(encoding="utf-8")
        assert text.startswith("/* Auto-generated")
        prefix = f"window.{global_name} = "
        assert prefix in text
        # The embedded value must round-trip to the source JSON byte-for-byte.
        value = text[text.index(prefix) + len(prefix):].rstrip().rstrip(";")
        source = json.loads((tmp_path / json_name).read_text(encoding="utf-8"))
        assert json.loads(value) == source


def test_check_passes_after_build(tmp_path, monkeypatch) -> None:
    _seed(tmp_path)
    monkeypatch.setattr(bus, "UI_DIR", tmp_path)
    assert bus.cmd_build(check=False) == 0
    assert bus.cmd_build(check=True) == 0


def test_check_detects_missing_sidecar(tmp_path, monkeypatch) -> None:
    _seed(tmp_path)
    monkeypatch.setattr(bus, "UI_DIR", tmp_path)
    # No build → sidecars absent → check must fail.
    assert bus.cmd_build(check=True) == 2


def test_check_detects_stale_sidecar(tmp_path, monkeypatch) -> None:
    _seed(tmp_path)
    monkeypatch.setattr(bus, "UI_DIR", tmp_path)
    assert bus.cmd_build(check=False) == 0
    # Mutate a source JSON without regenerating its sidecar → stale.
    src = tmp_path / "defaults.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    data["_test_marker"] = True
    src.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    assert bus.cmd_build(check=True) == 2


def test_invalid_source_json_fails(tmp_path, monkeypatch) -> None:
    _seed(tmp_path)
    monkeypatch.setattr(bus, "UI_DIR", tmp_path)
    (tmp_path / "defaults.json").write_text("{not valid json", encoding="utf-8")
    assert bus.cmd_build(check=False) == 2
