"""Lint an artefact for verdict + severity compliance.

Populated in T09. Supersedes the T05 stub.

Contract: `docs/rules/verdict-contract.rule.md` (verdict literals + severity codes) and
`docs/rules/error-message-standard.rule.md` (error shape).

CLI
---
    python -m scripts.verdict_lint <path>... [--shape artifact|error|script-cli]
                                              [--audit] [--force-with-reason TEXT]

Shapes
------
- `artifact` (default): enforces exactly ONE verdict literal
  (`✅ APPROVED` / `⚠️ ISSUES FOUND (iter N)` / `❓ CLARIFICATION NEEDED`) on
  its own line. If `⚠️`, every finding must carry a bracketed severity token
  `[S1]`..`[S4]`. `[S0]` only with `--audit`.
- `error`: enforces the WHY / WHERE / FIX / OVERRIDE shape from
  `docs/rules/error-message-standard.rule.md`. Reads from stdin if no path given.
- `script-cli`: CI-side lint for script CLIs that must support break-glass.
  Placeholder — emits a warning and exits 0 (populated in a future track).

Override
--------
This gate protects a structural invariant. `--force-with-reason` is REJECTED;
the script exits 3 when a reason is passed (per docs/rules/break-glass.rule.md table row
"never overridable").

Exit codes
----------
    0 success
    1 lint failure (canonical error was emitted)
    3 `--force-with-reason` supplied on a gate that declares OVERRIDE: none
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Force UTF-8 stdio.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts._break_glass import add_break_glass_flag, apply_break_glass  # noqa: E402

SCRIPT_BASENAME = "verdict_lint.py"
GATE_NAME = "verdict-shape"

VERDICT_APPROVED = "✅ APPROVED"
VERDICT_CLARIFY = "❓ CLARIFICATION NEEDED"
ISSUES_RE = re.compile(r"^⚠️\s+ISSUES FOUND \(iter (\d+)\)\s*$")
SEVERITY_RE = re.compile(r"\[(S[0-4])\]")
FINDING_START_RE = re.compile(r"^\s*-\s+\[(S[0-4])\]")

ERROR_HEADER_RE = re.compile(r"^❌ (?P<why>[^\n]+?) at (?P<where>[^\n]+)$")
FIX_RE = re.compile(r"^\s{3}FIX:\s+.+$")
OVERRIDE_RE = re.compile(r"^\s{3}OVERRIDE:\s+(none|--force-with-reason=.*)$")


def emit_error(
    *, why: str, where: str, fix: str, override_invocation: str | None
) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    if override_invocation is None:
        print("   OVERRIDE: none", file=sys.stderr)
    else:
        print(f"   OVERRIDE: {override_invocation}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Shape: artifact
# ---------------------------------------------------------------------------


def lint_artifact(file_path: Path, *, audit: bool) -> int:
    """Return 0 if valid, 1 if invalid."""
    if not file_path.is_file():
        emit_error(
            why="artefact not found",
            where=file_path.resolve().as_posix(),
            fix="create the file or pass an existing path to `verdict_lint.py`.",
            override_invocation=None,
        )
        return 1
    text = file_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = text.split("\n")

    approved_lines = [i for i, line in enumerate(lines) if line.strip() == VERDICT_APPROVED]
    clarify_lines = [i for i, line in enumerate(lines) if line.strip() == VERDICT_CLARIFY]
    issues_matches: list[tuple[int, int]] = []
    for i, line in enumerate(lines):
        m = ISSUES_RE.match(line.strip())
        if m:
            issues_matches.append((i, int(m.group(1))))

    verdict_count = len(approved_lines) + len(clarify_lines) + len(issues_matches)

    where = f"{file_path.resolve().as_posix()}:1"
    if verdict_count == 0:
        emit_error(
            why="artefact missing verdict line",
            where=where,
            fix=(
                "append exactly one of `✅ APPROVED`, "
                "`⚠️ ISSUES FOUND (iter N)`, or `❓ CLARIFICATION NEEDED` on its "
                "own line. See docs/rules/verdict-contract.rule.md §1."
            ),
            override_invocation=None,
        )
        return 1
    if verdict_count > 1:
        emit_error(
            why=f"artefact has {verdict_count} verdict lines; expected exactly 1",
            where=where,
            fix=(
                "remove the extra verdict line(s); only the final top-level "
                "verdict should remain. See docs/rules/verdict-contract.rule.md §1."
            ),
            override_invocation=None,
        )
        return 1

    if issues_matches:
        iter_line, iter_n = issues_matches[0]
        if iter_n < 1:
            emit_error(
                why=f"`⚠️ ISSUES FOUND (iter {iter_n})` must have N >= 1",
                where=f"{file_path.resolve().as_posix()}:{iter_line + 1}",
                fix="start the counter at `iter 1` for the first review pass.",
                override_invocation=None,
            )
            return 1

        findings = [
            (i, m.group(1))
            for i, line in enumerate(lines)
            for m in [FINDING_START_RE.match(line)]
            if m
        ]
        if not findings:
            emit_error(
                why="`⚠️ ISSUES FOUND` artefact has no `[Sx]` findings listed",
                where=where,
                fix=(
                    "list each finding on its own line starting `- [S1] <title>` "
                    "(or S2/S3/S4). See docs/rules/verdict-contract.rule.md §2."
                ),
                override_invocation=None,
            )
            return 1
        for line_idx, sev in findings:
            if sev == "S0" and not audit:
                emit_error(
                    why="`[S0]` is audit-only and rejected in normal verdict lint",
                    where=f"{file_path.resolve().as_posix()}:{line_idx + 1}",
                    fix=(
                        "use S1..S4 per docs/rules/verdict-contract.rule.md §2; "
                        "S0 is reserved for retros run with `--audit`."
                    ),
                    override_invocation=None,
                )
                return 1

    print(f"✅ {file_path.resolve().as_posix()} verdict shape valid.")
    return 0


# ---------------------------------------------------------------------------
# Shape: error
# ---------------------------------------------------------------------------


def lint_error_shape_text(text: str, where: str) -> int:
    """Lint a block of text (file or stdin) for the canonical error shape."""
    text = text.replace("\r\n", "\n").rstrip()
    if not text:
        emit_error(
            why="empty input for --shape error",
            where=where,
            fix="pass a file or pipe stderr into this lint with `--shape error`.",
            override_invocation=None,
        )
        return 1
    lines = text.split("\n")

    header_matches = [
        i for i, line in enumerate(lines) if ERROR_HEADER_RE.match(line)
    ]
    if len(header_matches) != 1:
        emit_error(
            why=(
                f"error block must have exactly one `❌ WHY at WHERE` line "
                f"(found {len(header_matches)})"
            ),
            where=where,
            fix="see docs/rules/error-message-standard.rule.md for the canonical shape.",
            override_invocation=None,
        )
        return 1
    header_idx = header_matches[0]
    # FIX + OVERRIDE should be the next two non-empty lines
    remaining = lines[header_idx + 1 : header_idx + 3]
    if len(remaining) < 2:
        emit_error(
            why="error block missing FIX/OVERRIDE continuation lines",
            where=where,
            fix="add `   FIX: ...` and `   OVERRIDE: ...` on the two lines after the `❌` header.",
            override_invocation=None,
        )
        return 1
    if not FIX_RE.match(remaining[0]):
        emit_error(
            why="FIX line missing or misindented (must be `   FIX: <text>`)",
            where=where,
            fix="use exactly 3 leading spaces + `FIX: ` + imperative remediation.",
            override_invocation=None,
        )
        return 1
    if not OVERRIDE_RE.match(remaining[1]):
        emit_error(
            why=(
                "OVERRIDE line missing or malformed "
                "(must be `   OVERRIDE: none` or `   OVERRIDE: --force-with-reason=...`)"
            ),
            where=where,
            fix="see docs/rules/error-message-standard.rule.md and docs/rules/break-glass.rule.md.",
            override_invocation=None,
        )
        return 1
    print(f"✅ {where} error shape valid.")
    return 0


def lint_error_shape(file_path: Path | None) -> int:
    if file_path is None:
        return lint_error_shape_text(sys.stdin.read(), "<stdin>")
    if not file_path.is_file():
        emit_error(
            why="error artefact not found",
            where=file_path.resolve().as_posix(),
            fix="pass a valid path or omit to read stdin.",
            override_invocation=None,
        )
        return 1
    return lint_error_shape_text(
        file_path.read_text(encoding="utf-8"), file_path.resolve().as_posix()
    )


# ---------------------------------------------------------------------------
# Shape: script-cli (future track)
# ---------------------------------------------------------------------------


def lint_script_cli(_paths: list[Path]) -> int:
    print(
        "⚠️ `--shape script-cli` is a placeholder; full implementation lands in a "
        "future track. Skipping.",
        file=sys.stderr,
    )
    return 0


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verdict_lint",
        description=(
            "Lint QA artefacts for verdict + severity shape. See "
            "docs/rules/verdict-contract.rule.md and docs/rules/error-message-standard.rule.md."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files to lint. For --shape error, omit to read stdin.",
    )
    parser.add_argument(
        "--shape",
        choices=["artifact", "error", "script-cli"],
        default="artifact",
        help="What to lint. Default: artifact.",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Allow `[S0]` severity (retro-only, per verdict-contract.md §2.1).",
    )
    add_break_glass_flag(parser)
    args = parser.parse_args(argv)

    # Break-glass is REJECTED for this gate (OVERRIDE: none).
    if args.force_reason is not None:
        apply_break_glass(
            gate=GATE_NAME,
            script=SCRIPT_BASENAME,
            reason=args.force_reason,
            override_allowed=False,
            repo_root=Path.cwd(),
        )
        # apply_break_glass exited already if we got here with reason and
        # override_allowed=False; defensive fall-through:
        return 3

    if args.shape == "artifact":
        if not args.paths:
            emit_error(
                why="no artefact path(s) given for --shape artifact",
                where=f"{SCRIPT_BASENAME}:argv",
                fix="pass one or more file paths, e.g. `verdict_lint.py review.md`.",
                override_invocation=None,
            )
            return 1
        overall = 0
        for p in args.paths:
            rc = lint_artifact(p, audit=args.audit)
            if rc != 0:
                overall = rc
        return overall

    if args.shape == "error":
        path = args.paths[0] if args.paths else None
        return lint_error_shape(path)

    return lint_script_cli(args.paths)


if __name__ == "__main__":
    from scripts.rules._telemetry import script_emit
    raise SystemExit(script_emit("verdict-lint", main))
