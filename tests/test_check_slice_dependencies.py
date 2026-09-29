"""Tests for scripts/check_slice_dependencies.py — gh failure is a setup error, not "deps not Done"."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import bootstrap_gh_project as bgp
from scripts import check_slice_dependencies as csd


def test_failing_gh_is_setup_error_not_deps_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    slicing = tmp_path / "slice.md"
    slicing.write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(csd, "_gh_available", lambda: True)

    def fake_run(cmd, *args, check=False, **kwargs):  # type: ignore[no-untyped-def]
        if check:
            raise subprocess.CalledProcessError(1, cmd, output="", stderr="gh: HTTP 401")
        return subprocess.CompletedProcess(cmd, 1, "", "gh: HTTP 401")
    monkeypatch.setattr(bgp.subprocess, "run", fake_run)

    rc = csd.main([
        "--owner", "acme", "--project-number", "1",
        "--slicing-file", str(slicing), "--change-id", "c1",
    ])

    assert rc == 2
