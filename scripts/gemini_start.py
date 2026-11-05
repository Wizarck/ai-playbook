"""Cross-platform wrapper to start Gemini CLI with playbook context injection.

Gemini CLI / Antigravity does NOT have a built-in session-start hook (unlike
Claude Code's `.claude/settings.json` PreToolUse / SessionStart). This wrapper
runs the playbook's context-injection step before exec'ing the `gemini`
binary, so Gemini sessions begin with the same memory a Claude session would.

Workflow
--------
1. Optionally re-sync the skills mirrors (idempotent fingerprint short-circuit).
2. Run `inject_context.py` for the matching bank-id (resolved from cwd via the
   projects registry, or via `--bank-id <slug>` on the CLI).
3. Exec the `gemini` binary with any user-supplied args.

Run from the consumer root:

    python .ai-playbook/scripts/gemini_start.py [--bank-id <slug>] [args...]

Or, after `bash scripts/install-playbook-hooks.sh`, the
`templates/new-project/scripts/gemini_start.py.tmpl` is rendered into the
consumer's own `scripts/gemini_start.py` so users invoke
`python scripts/gemini_start.py`.

Contract: docs/concepts/skills-distribution.md §5.1 (Gemini-specific start wrapper).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Make `from scripts...` resolve when run by path (`python .ai-playbook/scripts/...`), not just via -m.
_PLAYBOOK_ROOT = str(Path(__file__).resolve().parents[1])
if _PLAYBOOK_ROOT not in sys.path:
    sys.path.insert(0, _PLAYBOOK_ROOT)


# UTF-8 stdio — Windows cp1252 console safety.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


SCRIPT_BASENAME = "gemini_start.py"
INJECT_CONTEXT_REL = Path(".ai-playbook") / "scripts" / "inject_context.py"
MATERIALISE_SKILLS_REL = Path(".ai-playbook") / "scripts" / "materialise_skills.py"


def _resolve_bank_id(explicit: str | None, consumer_root: Path) -> str | None:
    """Resolve the bank-id from --bank-id flag, env, or the consumer's slug.

    Order:
    1. Explicit `--bank-id <slug>` flag.
    2. Env var `AIPLAYBOOK_BANK_ID`.
    3. Consumer directory name (as a fallback heuristic).
    Returns None when nothing matches — context injection is then skipped.
    """
    if explicit:
        return explicit
    env_value = os.environ.get("AIPLAYBOOK_BANK_ID")
    if env_value:
        return env_value.strip()
    # Heuristic: consumer dir name matches the projects-registry slug for
    # well-behaved consumers (acme-corp, consumer-c, acme-corp, etc.).
    name = consumer_root.name
    return name or None


def _run_skills_sync(consumer_root: Path) -> None:
    """Best-effort skills mirror sync. Failures warn but never block boot."""
    script = consumer_root / MATERIALISE_SKILLS_REL
    if not script.is_file():
        return
    try:
        subprocess.run(
            [sys.executable, str(script), "--quiet"],
            cwd=str(consumer_root),
            check=False,
        )
    except OSError as exc:
        print(
            f"⚠️ [Gemini Boot] skills materialiser failed ({exc}); continuing.",
            file=sys.stderr,
        )


def _run_inject_context(consumer_root: Path, bank_id: str | None) -> None:
    """Best-effort context injection. Failures warn but never block boot."""
    script = consumer_root / INJECT_CONTEXT_REL
    if not script.is_file():
        return
    if not bank_id:
        print(
            "⚠️ [Gemini Boot] no bank-id resolved; skipping context injection.",
            file=sys.stderr,
        )
        return
    cmd = [sys.executable, str(script), "--bank-id", bank_id]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(consumer_root),
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            print(
                "⚠️ [Gemini Boot] context injection returned non-zero "
                "(DEGRADED_CONTEXT). Continuing.",
                file=sys.stderr,
            )
    except OSError as exc:
        print(
            f"⚠️ [Gemini Boot] inject_context failed ({exc}); continuing.",
            file=sys.stderr,
        )


# npm's cmd-shim (what `npm install -g` writes as gemini.cmd) ends in a line
# that runs the package's target with the user's arguments, e.g.
#   ... & "%_prog%"  "%dp0%\node_modules\@google\gemini-cli\dist\index.js" %*
#   "%~dp0\node.exe"  "%~dp0\node_modules\...\index.js" %*      (older npm)
#   "%dp0%\node_modules\...\bin\tool.exe"   %*                  (native bin)
_SHIM_NODE_RE = re.compile(
    r'(?:"%_prog%"|"%~dp0\\node\.exe"|(?<![\w\\])node)\s+(?P<args>(?:[^\s"%]+\s+)*)'
    r'"%(?:dp0%|~dp0)\\(?P<rel>[^"%]+\.[cm]?js)"\s+%\*\s*$',
    re.IGNORECASE,
)
_SHIM_EXE_RE = re.compile(
    r'^\s*"%(?:dp0%|~dp0)\\(?P<rel>[^"%]+\.exe)"\s+%\*\s*$', re.IGNORECASE,
)
# The only SET lines a plain cmd-shim has. Any other (a shebang's env vars) is
# something only the shim knows how to apply, so it is not bypassed.
_SHIM_SET_RE = re.compile(r"^\s*@?SET\s", re.IGNORECASE)
_SHIM_SET_OK_RE = re.compile(
    r'^\s*@?SET\s+(?:dp0=%~dp0|"_prog=[^"]*"|PATHEXT=%PATHEXT:;\.JS;=;%)\s*$',
    re.IGNORECASE,
)


def _resolve_npm_shim(shim: str) -> list[str] | None:
    """The argv prefix that runs what an npm cmd-shim runs, without cmd.exe.

    Windows runs a .cmd through cmd.exe, which re-parses the command line
    list2cmdline built: `%VAR%` expands in every argument, and a `"` inside an
    argument flips cmd's quote pairing, so `&`, `|` and `>` after it run as
    shell syntax. Calling the shim's own target (node + the package's JS entry,
    or a native .exe) hands argv to CreateProcess unchanged. Returns None for
    anything that is not a recognised npm shim.
    """
    path = Path(shim)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if any(_SHIM_SET_RE.match(ln) and not _SHIM_SET_OK_RE.match(ln) for ln in lines):
        return None
    base = path.parent
    for line in lines:
        if "%*" not in line:
            continue
        m = _SHIM_NODE_RE.search(line)
        if m:
            script = base.joinpath(*m.group("rel").split("\\"))
            # Same choice as the shim: a node.exe beside it, else node.exe on
            # PATH (never bare `node`, which PATHEXT could resolve to node.js).
            beside = base / "node.exe"
            node = str(beside) if beside.is_file() else shutil.which("node.exe")
            if node is None or not script.is_file():
                return None
            return [node, *m.group("args").split(), str(script)]
        m = _SHIM_EXE_RE.match(line)
        if m:
            exe = base.joinpath(*m.group("rel").split("\\"))
            return [str(exe)] if exe.is_file() else None
        return None
    return None


def _cmd_would_reinterpret(args: list[str]) -> bool:
    """True when cmd.exe would not pass ``args`` through a .cmd verbatim.

    `%` expands and `"` flips the quote pairing anywhere; an argument without
    whitespace is left unquoted by list2cmdline, so its `&|<>^()!` are syntax.
    """
    for arg in args:
        if any(c in arg for c in '"%\r\n'):
            return True
        if not any(c in arg for c in " \t") and any(c in arg for c in "&|<>^()!"):
            return True
    return False


def _exec_gemini(args: list[str]) -> int:
    """Exec the `gemini` binary. POSIX uses os.execvp; Windows uses subprocess."""
    is_windows = os.name == "nt"
    gemini_args = ["gemini", *args]
    try:
        if is_windows:
            # On Windows `gemini` is usually npm's .cmd shim; shutil.which finds
            # it via PATHEXT. Never a shell string, and never cmd.exe when it
            # can be avoided: run the shim's node + JS entry directly so argv
            # reaches gemini verbatim. os.execvp does NOT cleanly replace the
            # parent process on Windows, so we wait + propagate the exit code.
            exe = shutil.which("gemini")
            if exe is None:
                raise FileNotFoundError("gemini")
            cmd = [exe, *args]
            if exe.lower().endswith((".cmd", ".bat")):
                target = _resolve_npm_shim(exe)
                if target is not None:
                    cmd = [*target, *args]
                elif _cmd_would_reinterpret(args):
                    print(
                        f"❌ refusing to pass these arguments through cmd.exe at "
                        f"{SCRIPT_BASENAME}:cmd-shim",
                        file=sys.stderr,
                    )
                    print(
                        f"   FIX: `gemini` resolved to {exe}, which is not an npm shim "
                        "this launcher can bypass, and cmd.exe would expand `%` or run "
                        "`&`, `|`, `>` in them. Run `gemini` from your shell directly, "
                        "or reinstall it with `npm install -g @google/gemini-cli`.",
                        file=sys.stderr,
                    )
                    print("   OVERRIDE: none", file=sys.stderr)
                    return 1
            try:
                return subprocess.run(cmd).returncode
            except KeyboardInterrupt:
                return 130
        # POSIX: replace the wrapper process in memory so Gemini takes the
        # terminal cleanly.
        os.execvp("gemini", gemini_args)
    except FileNotFoundError:
        print(
            f"❌ `gemini` not found on PATH at {SCRIPT_BASENAME}:exec",
            file=sys.stderr,
        )
        print(
            "   FIX: install Gemini CLI (see https://github.com/google-gemini/"
            "gemini-cli) and ensure `gemini` is on PATH.",
            file=sys.stderr,
        )
        print("   OVERRIDE: none", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gemini_start",
        description=__doc__.split("\n\n", 1)[0],
        add_help=False,  # forward --help to gemini if user wants
    )
    parser.add_argument(
        "--bank-id",
        default=None,
        help="Memory bank id for inject_context.py (defaults to cwd basename).",
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Skip the skills materialise step (use when in-sync is already certain).",
    )
    parser.add_argument(
        "--no-inject",
        action="store_true",
        help="Skip inject_context (use for tests / offline / no-bank-id scenarios).",
    )
    parser.add_argument(
        "--ai-playbook-help",
        action="store_true",
        help="Print this wrapper's help (instead of forwarding --help to gemini).",
    )
    # parse_known_args so user args (e.g. `gemini --model foo`) pass through.
    ns, gemini_args = parser.parse_known_args(argv)

    if ns.ai_playbook_help:
        parser.print_help()
        return 0

    consumer_root = Path.cwd().resolve()
    print("🚀 [Gemini Boot] Loading playbook context...")

    if not ns.no_sync:
        _run_skills_sync(consumer_root)

    if not ns.no_inject:
        bank_id = _resolve_bank_id(ns.bank_id, consumer_root)
        _run_inject_context(consumer_root, bank_id)

    print("✨ [Gemini Boot] Starting Gemini CLI...")
    return _exec_gemini(gemini_args)


if __name__ == "__main__":
    sys.exit(main())
