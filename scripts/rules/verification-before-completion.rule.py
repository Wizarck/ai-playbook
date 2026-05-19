"""L1 hardrule: verification-before-completion.

Paired with docs/rules/verification-before-completion.rule.md.

Scans an artefact for `✅ APPROVED` and confirms it is preceded within the
last 50 non-empty lines by either:
- a fenced code block with recognisable test-runner / tool output, OR
- a synthesis-audit structure (quote / cite headings).

CLI:
    python scripts/rules/verification-before-completion.rule.py validate <artefact-path>

Exit codes:
    0 — verified.
    1 — `✅ APPROVED` without fresh verification.
    2 — schema break.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

APPROVED_RE = re.compile(r"^✅ APPROVED\b", re.MULTILINE)
FENCE_RE = re.compile(r"```")
TOOL_OUTPUT_HINTS = [
    re.compile(r"\bexit\s*(?:code\s*)?[:=]?\s*0\b", re.IGNORECASE),
    re.compile(r"\bpassed\s*=\s*\d+\b"),
    re.compile(r"\d+\s+passed\b"),
    re.compile(r"\bSuccess:\s*no issues", re.IGNORECASE),
    re.compile(r"^=+\s*\d+\s+passed.*=+$", re.MULTILINE),
    re.compile(r"\$\s+\w+"),  # CLI invocation echo
]
SYNTHESIS_HINTS = [
    re.compile(r"^#+\s*(?:Audit|Synthesis|Verification|Evidence)\b", re.MULTILINE | re.IGNORECASE),
    re.compile(r"Covers\s+(?:AC[- ]\d+|FR[- ]\d+|spec\s+§)", re.IGNORECASE),
]


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def _has_tool_output(window: str) -> bool:
    if FENCE_RE.search(window) and any(h.search(window) for h in TOOL_OUTPUT_HINTS):
        return True
    return False


def _has_synthesis_structure(window: str) -> bool:
    return any(h.search(window) for h in SYNTHESIS_HINTS)


def validate_text(text: str, where: str) -> int:
    for m in APPROVED_RE.finditer(text):
        before = text[: m.start()]
        # 50 trailing non-empty lines window.
        lines = [ln for ln in before.splitlines() if ln.strip()]
        window = "\n".join(lines[-50:])
        if not (_has_tool_output(window) or _has_synthesis_structure(window)):
            line_no = before.count("\n") + 1
            _emit_error(
                why="`✅ APPROVED` without fresh verification output in same message",
                where=f"{where}:{line_no}",
                fix="include the verbatim tool output (exit code cited) or a synthesis-audit structure before the verdict.",
            )
            return 1
    return 0


def validate(paths: list[str]) -> int:
    if os.environ.get("AIPLAYBOOK_VERIFICATION_BEFORE_COMPLETION_SKIP"):
        return 0
    for raw in paths:
        p = Path(raw)
        if not p.is_file():
            _emit_error(why=f"path not readable: {raw}", where=raw, fix="pass an existing file.")
            return 2
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            _emit_error(why=str(exc), where=raw, fix="check file permissions.")
            return 2
        rc = validate_text(text, raw)
        if rc:
            return rc
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verification-before-completion")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    if not args.paths:
        return 0
    return validate(args.paths)


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("verification-before-completion", main))
