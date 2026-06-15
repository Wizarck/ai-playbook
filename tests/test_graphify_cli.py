"""Tests for the graphify feature (scripts/graphify/{toggle,materialise,cli}.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.graphify import cli as gcli
from scripts.graphify import materialise as gmat
from scripts.graphify import toggle as gtoggle

AGENTS_STUB = "# Project AGENTS.md\n\nSome content.\n"


def _consumer(root: Path, *, graph: bool = False, gitignore: str = "") -> Path:
    (root / "AGENTS.md").write_text(AGENTS_STUB, encoding="utf-8")
    (root / ".gitignore").write_text(gitignore, encoding="utf-8")
    if graph:
        gdir = root / "graphify-out"
        gdir.mkdir(parents=True, exist_ok=True)
        (gdir / "graph.json").write_text("{}", encoding="utf-8")
    return root


# ── toggle state ────────────────────────────────────────────────────────────


def test_default_state_shape() -> None:
    st = gtoggle.default_state()
    assert st["schema"] == "graphify-toggle/v1"
    assert st["enabled"] is False
    assert set(st["components"]) == {"agent_guidance", "gitignore_hygiene", "enforce_skill"}
    assert "mode" not in st  # graphify has no intensity levels


def test_state_roundtrip(tmp_path: Path) -> None:
    st = gtoggle.default_state()
    st["enabled"] = True
    st["components"]["agent_guidance"] = True
    gtoggle.write_state(tmp_path, st)
    back = gtoggle.read_state(tmp_path)
    assert back["enabled"] is True
    assert back["components"]["agent_guidance"] is True


def test_read_state_defaults_when_missing(tmp_path: Path) -> None:
    st = gtoggle.read_state(tmp_path)
    assert st["enabled"] is False


# ── CLI on/off/status ─────────────────────────────────────────────────────────


def test_on_materialises_and_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    c = _consumer(tmp_path)
    assert gmat.is_materialised(c) is False
    rc = gcli.main(["on", "--project", str(c), "--components", "agent_guidance"])
    assert rc == 0
    # AGENTS.md now carries the auto-managed block
    agents = (c / "AGENTS.md").read_text(encoding="utf-8")
    assert "BEGIN auto-managed: graphify/ruleset" in agents
    assert gmat.is_materialised(c) is True
    # state ON
    st = gtoggle.read_state(c)
    assert st["enabled"] is True
    assert st["components"]["agent_guidance"] is True
    # next-steps surfaced
    assert "graphify hook install" in capsys.readouterr().out


def test_off_strips_block(tmp_path: Path) -> None:
    c = _consumer(tmp_path)
    gcli.main(["on", "--project", str(c), "--components", "agent_guidance"])
    rc = gcli.main(["off", "--project", str(c)])
    assert rc == 0
    agents = (c / "AGENTS.md").read_text(encoding="utf-8")
    assert "auto-managed: graphify/ruleset" not in agents
    assert gtoggle.read_state(c)["enabled"] is False
    assert gmat.is_materialised(c) is False


def test_on_gitignore_hygiene_applies_when_graph_present(tmp_path: Path) -> None:
    c = _consumer(tmp_path, graph=True, gitignore="# pre\n")
    rc = gcli.main(["on", "--project", str(c), "--components", "gitignore_hygiene"])
    assert rc == 0
    gi = (c / ".gitignore").read_text(encoding="utf-8")
    assert "graphify-out/cache/" in gi
    assert "graphify-out/.graphify_python" in gi


def test_on_invalid_component_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    c = _consumer(tmp_path)
    rc = gcli.main(["on", "--project", str(c), "--components", "bogus"])
    assert rc == 1
    assert "invalid component" in capsys.readouterr().err.lower()


def test_materialise_idempotent_single_block(tmp_path: Path) -> None:
    c = _consumer(tmp_path)
    gcli.main(["on", "--project", str(c), "--components", "agent_guidance"])
    gcli.main(["on", "--project", str(c), "--components", "agent_guidance"])
    agents = (c / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.count("BEGIN auto-managed: graphify/ruleset") == 1
