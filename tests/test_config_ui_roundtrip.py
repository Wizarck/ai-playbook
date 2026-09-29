"""config-ui: loading applied state then exporting must not drop bundle sections.

Drives the real page in Chromium via tests/config_ui_roundtrip.mjs. Skipped
when Node or a global Playwright install is unavailable.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _playwright_dir() -> Path | None:
    npm = shutil.which("npm")
    if not shutil.which("node") or not npm:
        return None
    root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True, check=False).stdout.strip()
    pkg = Path(root) / "playwright"
    return pkg if (pkg / "index.mjs").is_file() else None


def test_applied_state_roundtrips_through_export() -> None:
    pw = _playwright_dir()
    if pw is None:
        pytest.skip("node + global playwright not available")
    proc = subprocess.run(
        ["node", str(REPO_ROOT / "tests" / "config_ui_roundtrip.mjs"), str(REPO_ROOT), str(pw)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
