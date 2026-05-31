"""L1 hardrule: english-only-docs (paired with docs/rules/english-only-docs.rule.md).

Thin wrapper around `scripts/check_doc_language.py`. Default target is
`docs/`; extra paths may be passed positionally to the underlying check.

CLI:
    python scripts/rules/english-only-docs.rule.py validate [paths...]

Exit codes:
    0 — all clean (English-dominant prose).
    1 — non-English content detected (violation).
    2 — schema break / fatal (checker missing).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CHECKER = REPO_ROOT / "scripts" / "check_doc_language.py"


def validate(paths: list[str]) -> int:
    if os.environ.get("AIPLAYBOOK_DOC_LANG_SKIP"):
        return 0
    if not CHECKER.is_file():
        print(f"error: check_doc_language.py missing at {CHECKER}", file=sys.stderr)
        return 2
    cmd = [sys.executable, str(CHECKER), *paths]
    rc = subprocess.call(cmd)
    return 1 if rc != 0 else 0


def pretooluse(event: dict):
    """In-process L1 hook: refuse a full-file Write that introduces non-English docs.

    Scoped to full-content ``Write`` of a ``.md`` under ``docs/`` — partial
    ``Edit`` events carry incomplete prose (false positives), so they are left to
    the tree/PR ``validate`` backstop. Mirrors ``check_doc_language.check_file``
    on the new content, in-process (no subprocess on the hot path).
    OVERRIDE: AIPLAYBOOK_DOC_LANG_SKIP.
    """
    from scripts.rules._hook_contract import allow, block, edited_path, edited_text, tool_name

    if os.environ.get("AIPLAYBOOK_DOC_LANG_SKIP"):
        return None
    if tool_name(event) != "Write":
        return None
    path = edited_path(event)
    p = Path(path)
    if p.suffix != ".md" or "docs" not in p.parts:
        return None
    text = edited_text(event)
    try:
        from scripts import check_doc_language as C
        prose = C._strip_code_and_frontmatter(text)
        if not prose.strip():
            return None
        detected = C._try_langdetect(prose)
        ok = (detected == "en") if detected is not None else C._is_english_heuristic(prose)
    except Exception:  # noqa: BLE001 — checker unavailable → fail open.
        return None
    if not ok:
        return block(
            f"non-English prose detected in {path}. ai-playbook docs are English-only "
            "(code and your own comments may stay in your language). "
            "OVERRIDE: set AIPLAYBOOK_DOC_LANG_SKIP."
        )
    return allow()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="english-only-docs")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("paths", nargs="*", default=["docs"])
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate(args.paths)
    return 2


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("english-only-docs", main))
