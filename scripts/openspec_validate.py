"""Thin wrapper around `npx @fission-ai/openspec@latest validate` so consumers
can call a single cross-platform Python entry point regardless of shell / OS.

Populated in T09. Supersedes the T11 stub.

CLI
---
    python -m scripts.openspec_validate [change-id] [--force-with-reason TEXT]

Behaviour
---------
- Forwards the call to `npx @fission-ai/openspec@latest validate [change-id]`.
- If the current working directory has no `openspec/changes/`, exits 2 with a
  canonical error pointing at OpenSpec setup.
- If `npx` is not on PATH, exits 2 with a canonical error pointing at Node.js.
- If `openspec validate` exits non-zero, bubbles up stderr and exits 1.
- `--force-with-reason="<text>"`: always allowed. Logs override and exits 0
  despite any failure above.

Exit codes
----------
    0 success (or override applied)
    1 validate failed (canonical error was emitted)
    2 environment failure (missing npx / no openspec/ folder)
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Force UTF-8 stdio — Windows default cp1252 cannot encode the sigils we emit.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts._break_glass import add_break_glass_flag, apply_break_glass  # noqa: E402

SCRIPT_BASENAME = "openspec_validate.py"
GATE_NAME = "openspec-validate"
NPX_PACKAGE = "@fission-ai/openspec@latest"


def emit_error(
    *, why: str, where: str, fix: str, override_invocation: str | None
) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    if override_invocation is None:
        print("   OVERRIDE: none", file=sys.stderr)
    else:
        print(f"   OVERRIDE: {override_invocation}", file=sys.stderr)


def find_npx() -> str | None:
    """Return path to npx executable (cross-platform) or None."""
    for name in ("npx", "npx.cmd", "npx.exe"):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


def has_openspec_folder(cwd: Path) -> bool:
    return (cwd / "openspec" / "changes").is_dir()


def run_openspec_validate(
    npx_path: str, change_id: str | None, cwd: Path
) -> subprocess.CompletedProcess[str]:
    """Invoke `npx @fission-ai/openspec@latest validate [change-id]` and capture output."""
    cmd = [npx_path, NPX_PACKAGE, "validate"]
    if change_id:
        cmd.append(change_id)
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="openspec_validate",
        description=(
            "Wrapper for `npx @fission-ai/openspec@latest validate`. Cross-platform."
        ),
    )
    parser.add_argument(
        "change_id",
        nargs="?",
        default=None,
        help="OpenSpec change id to validate (default: validate all).",
    )
    add_break_glass_flag(parser)
    args = parser.parse_args(argv)

    cwd = Path.cwd()

    def maybe_override(rc: int) -> int:
        result = apply_break_glass(
            gate=GATE_NAME,
            script=SCRIPT_BASENAME,
            reason=args.force_reason,
            override_allowed=True,
            repo_root=cwd,
        )
        if result.applied:
            print(f"⚠️ OVERRIDE APPLIED: {result.reason}")
            print(f"   logged: {(cwd / '.ai-playbook' / 'overrides.log').as_posix()}")
            return 0
        return rc

    if not has_openspec_folder(cwd):
        emit_error(
            why="openspec/changes/ folder not found",
            where=f"{cwd.as_posix()}/openspec/changes",
            fix=(
                "run this script from a repo set up with OpenSpec "
                "(`npx @fission-ai/openspec@latest init`)."
            ),
            override_invocation=(
                'python -m scripts.openspec_validate '
                '--force-with-reason="<>=10 char reason"'
            ),
        )
        return maybe_override(2)

    npx_path = find_npx()
    if npx_path is None:
        emit_error(
            why="`npx` not found on PATH",
            where=f"{SCRIPT_BASENAME}:find_npx",
            fix=(
                "install Node.js 18+ (ships with npx). On Windows: "
                "`winget install OpenJS.NodeJS`. On macOS: `brew install node`."
            ),
            override_invocation=(
                'python -m scripts.openspec_validate '
                '--force-with-reason="<>=10 char reason"'
            ),
        )
        return maybe_override(2)

    try:
        result = run_openspec_validate(npx_path, args.change_id, cwd)
    except (OSError, subprocess.SubprocessError) as exc:
        emit_error(
            why=f"failed to invoke `npx {NPX_PACKAGE} validate`: {exc}",
            where=f"{SCRIPT_BASENAME}:run_openspec_validate",
            fix="verify Node.js + npx work: `npx --version`.",
            override_invocation=(
                'python -m scripts.openspec_validate '
                '--force-with-reason="<>=10 char reason"'
            ),
        )
        return maybe_override(2)

    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)

    if result.returncode == 0:
        return 0

    emit_error(
        why=f"openspec validate failed (exit {result.returncode})",
        where=(
            f"{cwd.as_posix()}/openspec"
            + (f" (change: {args.change_id})" if args.change_id else "")
        ),
        fix=(
            "fix the errors reported by `npx @fission-ai/openspec@latest validate` "
            "then re-run."
        ),
        override_invocation=(
            f'python -m scripts.openspec_validate '
            f'{args.change_id or ""} --force-with-reason="<>=10 char reason"'
        ),
    )
    return maybe_override(1)


if __name__ == "__main__":
    from scripts.rules._telemetry import script_emit
    raise SystemExit(script_emit("openspec-validate", main))
