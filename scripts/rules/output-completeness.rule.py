"""L1 hardrule: output-completeness.

Paired with docs/rules/output-completeness.rule.md.

Scans an artefact for banned placeholder patterns: TODO/FIXME left in
delivered code, `// ... existing code ...`, "for brevity", `<TBD>`,
`pass  # TODO`, `throw new Error("not implemented")`, etc.

CLI:
    python scripts/rules/output-completeness.rule.py validate <artefact-path>

Exit codes:
    0 — clean.
    1 — placeholder pattern detected.
    2 — schema break.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

BANNED_PATTERNS = [
    (re.compile(r"^\s*(?:#|//)\s*TODO\b", re.MULTILINE), "TODO comment"),
    (re.compile(r"^\s*(?:#|//)\s*FIXME\b", re.MULTILINE), "FIXME comment"),
    (re.compile(r"\bpass\s*#\s*TODO\b", re.IGNORECASE), "pass # TODO"),
    (re.compile(r"\bthrow new Error\(['\"](?:not implemented|TBD)"), "throw not-implemented"),
    (re.compile(r"\braise NotImplementedError\b"), "raise NotImplementedError"),
    (re.compile(r"<TBD>|<TODO>|\[placeholder\]"), "explicit placeholder marker"),
    (re.compile(r"//\s*\.\.\.\s*existing code\s*\.\.\.", re.IGNORECASE), "ellipsis-existing-code marker"),
    (re.compile(r"\bfor brevity\b", re.IGNORECASE), "'for brevity' abbreviation"),
    (re.compile(r"\bas before\b\s*(?:\.\.\.|…)"), "'as before...' shorthand"),
    (re.compile(r"\[example here\]", re.IGNORECASE), "unfilled '[example here]'"),
]


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def _is_code_file(path: Path) -> bool:
    return path.suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".rb", ".cs"}


def validate_text(text: str, where: str) -> int:
    is_code = _is_code_file(Path(where))
    for pat, label in BANNED_PATTERNS:
        if label in ("TODO comment", "FIXME comment") and not is_code:
            continue  # Markdown frequently mentions TODO/FIXME in prose; only fail on code files.
        m = pat.search(text)
        if m:
            line_no = text[: m.start()].count("\n") + 1
            _emit_error(
                why=f"placeholder pattern found: {label}",
                where=f"{where}:{line_no}",
                fix="ship the work done or halt with `❓ CLARIFICATION NEEDED` per verdict-contract.",
            )
            return 1
    return 0


def validate(paths: list[str]) -> int:
    if os.environ.get("AIPLAYBOOK_OUTPUT_COMPLETENESS_SKIP"):
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
    parser = argparse.ArgumentParser(prog="output-completeness")
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
    raise SystemExit(cli_emit("output-completeness", main))
