"""Best-effort runtime-dependency self-heal (stdlib-only, zero-cost to import).

The playbook's hard deps (``jsonschema``, ``pyyaml``) are sometimes absent from
a consumer's active interpreter — most notably **uv-managed venvs that ship no
pip**. Every CLI entrypoint that needs them used to die at import time with a
``raise SystemExit(2)``, *before* any self-heal could run (the chicken-and-egg
that made ``doctor --install-deps`` unreachable when a guarded module was on the
import path).

This module fixes that at the dep guard itself. Importing it costs nothing;
calling :func:`ensure_runtime_deps` imports each package and, on ImportError,
installs the missing ones into the **running** interpreter using the first
backend that works:

    1. ``uv pip install --python <sys.executable>``  — handles pip-less uv venvs
    2. ``python -m pip install``                     — when pip is importable
    3. ``python -m ensurepip`` then pip              — last resort

Idempotent and quiet on success. Raises ``SystemExit(2)`` with an actionable,
copy-pasteable command only when a dep is still missing after every backend
fails — so the failure mode is never worse than the old hard guard, only better.
"""
from __future__ import annotations

import importlib
import shutil
import subprocess
import sys

# import-name -> pip distribution name (only when they differ).
_DIST = {"yaml": "pyyaml"}


def _missing(import_names: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for name in import_names:
        try:
            importlib.import_module(name)
        except ImportError:
            out.append(name)
    return out


def _dists(import_names: list[str]) -> list[str]:
    return [_DIST.get(n, n) for n in import_names]


def _run(cmd: list[str]) -> bool:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _install(dists: list[str]) -> None:
    """Try each backend in order; best-effort, never raises."""
    if shutil.which("uv") and _run(
        ["uv", "pip", "install", "--python", sys.executable, *dists]
    ):
        return
    try:
        import pip  # noqa: F401  (presence check only)
    except ImportError:
        _run([sys.executable, "-m", "ensurepip", "--upgrade"])
    _run([sys.executable, "-m", "pip", "install", *dists])


def ensure_runtime_deps(*import_names: str, quiet: bool = True) -> list[str]:
    """Ensure each importable ``import_names`` resolves; self-install if missing.

    Returns the list of packages that had to be installed (empty when all were
    already present). Raises ``SystemExit(2)`` only if a package is still
    unimportable after every install backend has been tried.
    """
    missing = _missing(import_names)
    if not missing:
        return []
    if not quiet:
        print(
            f"… ai-playbook: self-healing missing dependencies: {', '.join(missing)}",
            file=sys.stderr,
        )
    _install(_dists(missing))
    importlib.invalidate_caches()
    still = _missing(tuple(missing))
    if still:
        manual = " ".join(_dists(still))
        print(
            f"❌ required dependency missing: {', '.join(still)}. "
            f"Auto-install failed (no working uv/pip backend). Install manually:\n"
            f"    uv pip install {manual}\n"
            f"    # or: {sys.executable} -m pip install {manual}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return missing
