"""Every entry script must run by path from a consumer root.

Consumer templates, hooks and runbooks invoke ``python .ai-playbook/scripts/X.py``.
Without the ``sys.path`` shim that crashes with ``No module named 'scripts'``.
An editable install masks the crash (``scripts`` resolves to this checkout), so the
child process drops the editable finder and any path entry pointing here.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_RUNNER = r"""
import os, runpy, sys
repo = os.path.realpath(sys.argv[1]); script = sys.argv[2]
sys.meta_path[:] = [f for f in sys.meta_path if "editable" not in repr(f).lower()]
sys.path[:] = [p for p in sys.path if os.path.realpath(p or ".") != repo]
sys.path.insert(0, os.path.dirname(script))
sys.argv = [script, "--help"]
runpy.run_path(script, run_name="__main__")
"""

# Another `scripts` on sys.path (pywin32 ships site-packages/win32/scripts) turns
# the crash into "No module named 'scripts._x'" or "cannot import name 'x' from 'scripts'".
_IMPORT_CRASH = re.compile(r"No module named 'scripts\b|cannot import name .* from 'scripts\b")


def _entry_scripts(root: Path) -> list[Path]:
    return sorted(
        p for p in (root / "scripts").rglob("*.py")
        if p.name != "__main__.py" and 'if __name__ == "__main__"' in p.read_text(encoding="utf-8")
    )


def _crashes_on_import(consumer: Path, script: Path) -> bool:
    proc = subprocess.run(
        [sys.executable, "-c", _RUNNER, str(REPO_ROOT), str(script)],
        cwd=consumer, capture_output=True, encoding="utf-8", errors="replace",
        timeout=120, stdin=subprocess.DEVNULL,
    )
    return bool(_IMPORT_CRASH.search(proc.stderr))


def test_entry_scripts_import_when_run_by_path(tmp_path: Path) -> None:
    playbook = tmp_path / ".ai-playbook"
    shutil.copytree(REPO_ROOT / "scripts", playbook / "scripts", ignore=shutil.ignore_patterns("__pycache__"))

    def run(script: Path) -> str | None:
        return script.relative_to(playbook).as_posix() if _crashes_on_import(tmp_path, script) else None

    scripts = _entry_scripts(playbook)
    assert len(scripts) > 50
    with ThreadPoolExecutor(max_workers=8) as pool:
        broken = [s for s in pool.map(run, scripts) if s]
    assert broken == [], f"crash with ModuleNotFoundError when run by path: {broken}"


def test_check_sees_a_script_without_the_shim(tmp_path: Path) -> None:
    """The check above must flag the crash it guards against, whatever else is installed."""
    canary = tmp_path / ".ai-playbook" / "scripts" / "canary.py"
    canary.parent.mkdir(parents=True)
    canary.write_text("from scripts._project_root import find_project_root\n", encoding="utf-8")
    assert _crashes_on_import(tmp_path, canary)
