"""Pytest fixtures shared across the test suite."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point ``Path.home()`` at an empty per-test dir for the whole suite.

    In-process code reaches the developer's real home through it: the MCP render
    (reached by apply_config / bootstrap) rewrites ``~/.gemini/antigravity/
    mcp_config.json`` and reads ``~/.config/mcp-servers.yaml``. The dir is
    created on first use only.
    """
    home: list[Path] = []

    def _fake_home(cls: type[Path]) -> Path:
        if not home:
            home.append(tmp_path_factory.mktemp("home"))
        return home[0]

    monkeypatch.setattr(Path, "home", classmethod(_fake_home))
