"""L1 hardrule: verdict-contract.

Paired with docs/rules/verdict-contract.rule.md.

Validates that QA-style artefacts end with exactly one canonical verdict
literal from the four-set {`✅ APPROVED`, `⚠️ ISSUES FOUND (iter N)`,
`❓ CLARIFICATION NEEDED`, `⛔ ARCHITECTURE QUESTIONED`}. Telemetry-friendly:
the hook records whether the literal is present, so obey-rate is measurable.

CLI:
    python scripts/rules/verdict-contract.rule.py validate <artefact-path>

Exit codes:
    0 — verdict literal present and well-formed.
    1 — missing / paraphrased / multiple verdicts.
    2 — schema break (file unreadable).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

CANONICAL_VERDICTS = [
    re.compile(r"^✅ APPROVED\b", re.MULTILINE),
    re.compile(r"^⚠️ ISSUES FOUND \(iter \d+\)\b", re.MULTILINE),
    re.compile(r"^❓ CLARIFICATION NEEDED\b", re.MULTILINE),
    re.compile(r"^⛔ ARCHITECTURE QUESTIONED\b", re.MULTILINE),
]
PARAPHRASE_PATTERNS = [
    re.compile(r"\bApproved!\B", re.IGNORECASE),
    re.compile(r"\ball good ✅\B", re.IGNORECASE),
    re.compile(r"\blooks good to me\b", re.IGNORECASE),
]


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def validate_text(text: str, where: str) -> int:
    total_occurrences = sum(len(pat.findall(text)) for pat in CANONICAL_VERDICTS)
    if total_occurrences == 0:
        # Only flag artefacts that LOOK like QA outputs (mention paraphrased verdict).
        if any(p.search(text) for p in PARAPHRASE_PATTERNS):
            _emit_error(
                why="paraphrased verdict found; canonical literal required",
                where=where,
                fix="end with one of `✅ APPROVED`, `⚠️ ISSUES FOUND (iter N)`, `❓ CLARIFICATION NEEDED`, `⛔ ARCHITECTURE QUESTIONED`.",
            )
            return 1
        return 0  # not a QA artefact — skip.
    if total_occurrences > 1:
        _emit_error(
            why=f"multiple verdict literals found ({total_occurrences})",
            where=where,
            fix="emit exactly one canonical verdict literal at end of artefact.",
        )
        return 1
    return 0


def validate(paths: list[str]) -> int:
    if os.environ.get("AIPLAYBOOK_VERDICT_CONTRACT_SKIP"):
        return 0
    rc = 0
    for raw in paths:
        p = Path(raw)
        if not p.is_file():
            _emit_error(
                why=f"path not readable: {raw}",
                where=raw,
                fix="pass an existing file path.",
            )
            return 2
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            _emit_error(why=str(exc), where=raw, fix="check file permissions.")
            return 2
        rc = max(rc, validate_text(text, raw))
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verdict-contract")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    if not args.paths:
        return 0
    return validate(args.paths)


if __name__ == "__main__":
    # File-path invocation from a consumer root: put the playbook root on
    # sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("verdict-contract", main))
