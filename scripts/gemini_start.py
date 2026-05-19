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
import subprocess
import sys
from pathlib import Path

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


def _exec_gemini(args: list[str]) -> int:
    """Exec the `gemini` binary. POSIX uses os.execvp; Windows uses subprocess."""
    is_windows = os.name == "nt"
    gemini_args = ["gemini", *args]
    if is_windows:
        # On Windows, `gemini` is usually a .cmd/.bat shim on PATH; shell=True
        # resolves it. os.execvp does NOT cleanly replace the parent process
        # on Windows, so we wait + propagate the exit code.
        try:
            return subprocess.run(" ".join(gemini_args), shell=True).returncode
        except KeyboardInterrupt:
            return 0
    # POSIX: replace the wrapper process in memory so Gemini takes the
    # terminal cleanly.
    try:
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
