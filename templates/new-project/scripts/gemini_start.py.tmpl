"""Cross-platform wrapper to start Gemini CLI with playbook context injection.

Rendered template — installs at `<consumer>/scripts/gemini_start.py` by the
playbook bootstrap (`templates/new-project/scripts/install-playbook-hooks.sh.tmpl`).

This template is a thin pointer to the upstream wrapper at
`.ai-playbook/scripts/gemini_start.py`. The upstream wrapper is the
authoritative implementation; per D2 (scripts not mirrored), consumers do
NOT copy the logic — they invoke the upstream path.

Usage from the consumer root:

    python scripts/gemini_start.py [--bank-id <slug>] [gemini-args...]

Or, after PATH wiring:

    gemini_start [--bank-id <slug>] [gemini-args...]

Bank-id resolution order:
1. `--bank-id <slug>` CLI flag
2. `AIPLAYBOOK_BANK_ID` env var
3. cwd basename (fallback heuristic)

See `.ai-playbook/specs/skills-distribution.md` §5.1.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

UPSTREAM_REL = Path(".ai-playbook") / "scripts" / "gemini_start.py"


def _main() -> int:
    consumer_root = Path(__file__).resolve().parent.parent
    upstream = consumer_root / UPSTREAM_REL
    if not upstream.is_file():
        print(
            f"❌ upstream gemini_start not found at {upstream}\n"
            f"   FIX: run `git submodule update --init .ai-playbook` from "
            f"{consumer_root}.\n"
            f"   OVERRIDE: none",
            file=sys.stderr,
        )
        return 2
    # runpy preserves __name__ semantics so the wrapper's argparse + execvp
    # behaviour matches direct invocation.
    sys.argv = [str(upstream), *sys.argv[1:]]
    runpy.run_path(str(upstream), run_name="__main__")
    return 0  # unreachable on POSIX (execvp replaces process); explicit on Windows


if __name__ == "__main__":
    sys.exit(_main())
