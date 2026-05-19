"""Shared break-glass helper for playbook scripts.

Implements the `--force-with-reason="<text>"` contract from `docs/rules/break-glass.rule.md`.
Every blocking playbook check that can be overridden uses this helper so the contract
is uniform: same flag, same minimum length, same log format, same exit codes.

Usage (caller pattern)
----------------------
    import argparse
    from scripts._break_glass import add_break_glass_flag, apply_break_glass

    parser = argparse.ArgumentParser()
    add_break_glass_flag(parser)
    args = parser.parse_args()

    if validation_failed:
        print(canonical_error_shape, file=sys.stderr)
        result = apply_break_glass(
            gate="my-gate",
            script="my_script.py",
            reason=args.force_reason,
            override_allowed=True,
            repo_root=Path.cwd(),
        )
        if result.applied:
            print(f"⚠️ OVERRIDE APPLIED: {result.reason}")
            return 0
        return 1

Exit-code contract (per `docs/rules/error-message-standard.rule.md`)
---------------------------------------------------------
    1 = reason provided but under MIN_REASON_LEN (or whitespace only)
    3 = reason provided but the gate declares OVERRIDE: none

Callers handle all other exits (0 on success, 1 on a regular block when no reason).
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Force UTF-8 stdio — Windows default cp1252 cannot encode the sigils we emit.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


MIN_REASON_LEN = 10


@dataclass
class OverrideResult:
    """Return value of `apply_break_glass`.

    `applied=True` means the caller should print the OVERRIDE APPLIED banner and
    exit 0. `applied=False` with `reason=""` means no override was requested and
    the caller should continue its normal block/exit path.
    """

    applied: bool
    reason: str


def add_break_glass_flag(parser: argparse.ArgumentParser) -> None:
    """Register the canonical `--force-with-reason` flag on an argparse parser."""
    parser.add_argument(
        "--force-with-reason",
        dest="force_reason",
        metavar="TEXT",
        default=None,
        help=(
            "Override a blocking gate with an audit trail. "
            f"Reason must be >= {MIN_REASON_LEN} non-whitespace chars. "
            "Logged to .ai-playbook/overrides.log."
        ),
    )


def _emit_refused_override_error(script: str, gate: str) -> None:
    """Emit the canonical error for `OVERRIDE: none` gates that refuse a reason."""
    print(
        "❌ This gate declares OVERRIDE: none; --force-with-reason is refused "
        f"at {script}:{gate}",
        file=sys.stderr,
    )
    print(
        "   FIX: fix the underlying issue rather than bypassing; this gate protects "
        "a safety/security invariant.",
        file=sys.stderr,
    )
    print("   OVERRIDE: none", file=sys.stderr)


def _emit_short_reason_error(script: str, got_len: int) -> None:
    """Emit the canonical error for reasons shorter than MIN_REASON_LEN."""
    print(
        f"❌ --force-with-reason must be >= {MIN_REASON_LEN} non-whitespace chars "
        f"at {script}:--force-with-reason",
        file=sys.stderr,
    )
    print(
        f"   FIX: re-run with a reason explaining what is unique about this moment "
        f"(got: {got_len} chars).",
        file=sys.stderr,
    )
    print("   OVERRIDE: none", file=sys.stderr)


def apply_break_glass(
    *,
    gate: str,
    script: str,
    reason: str | None,
    override_allowed: bool,
    repo_root: Path,
    git_user_email: str | None = None,
) -> OverrideResult:
    """Validate reason, log the override, return whether to proceed.

    Caller has already printed the canonical error. If this returns
    `applied=True`, caller should print the OVERRIDE APPLIED banner and exit 0.

    Parameters
    ----------
    gate : str
        Name of the blocking gate being bypassed (free text, logged verbatim).
    script : str
        Basename of the invoking script (e.g. `schema_validate.py`), logged verbatim.
    reason : str | None
        The `--force-with-reason` string from argparse (may be None).
    override_allowed : bool
        Whether this gate's canonical error declares `OVERRIDE: <invocation>`
        (True) or `OVERRIDE: none` (False).
    repo_root : Path
        Directory under which `.ai-playbook/overrides.log` is written.
    git_user_email : str | None
        Actor identifier. Falls back to `$GIT_AUTHOR_EMAIL`, then `"unknown"`.
    """
    if not override_allowed:
        if reason:
            _emit_refused_override_error(script, gate)
            sys.exit(3)
        return OverrideResult(applied=False, reason="")

    if reason is None:
        return OverrideResult(applied=False, reason="")

    stripped = reason.strip()
    if len(stripped) < MIN_REASON_LEN:
        _emit_short_reason_error(script, len(stripped))
        sys.exit(1)

    log_path = repo_root / ".ai-playbook" / "overrides.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
    actor = git_user_email or os.environ.get("GIT_AUTHOR_EMAIL") or "unknown"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f'{ts} {actor} {script} {gate} "{stripped}"\n')

    _emit_override_span(script=script, gate=gate, reason=stripped, actor=actor, ts=ts)
    _emit_escape_hatch_telemetry(gate=gate, script=script, reason=stripped)

    return OverrideResult(applied=True, reason=stripped)


def _emit_escape_hatch_telemetry(*, gate: str, script: str, reason: str) -> None:
    """Emit a `rule-event/v1` row with `escape_hatch` set (Slice 6 telemetry).

    Lets `scripts/telemetry/report.py` surface break-glass usage in §6 of the
    monthly report. Best-effort — never raises into the caller path.
    """
    try:
        from scripts.telemetry.rule_event_logger import log_event
    except Exception:  # noqa: BLE001 — telemetry never breaks override path.
        return
    try:
        log_event(
            slug=gate,
            llm="unknown",
            verdict="warn",
            latency_ms=0.0,
            trigger=f"BreakGlass:{script}",
            session_id=os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
            self_check=False,
            escape_hatch="--force-with-reason",
            extra={"reason_length": len(reason)},
        )
    except Exception:  # noqa: BLE001
        pass


def _emit_override_span(
    *, script: str, gate: str, reason: str, actor: str, ts: str
) -> None:
    """Emit `ai_playbook.override.*` span per `docs/rules/break-glass.rule.md`.

    No-op safe — tracing must never block a legitimate override. The log file
    written above is the durable source of truth; the span is for dashboards.
    """
    try:
        from scripts.tracing.trace_emit import override_attrs, span
    except Exception:  # noqa: BLE001 — tracing import optional
        return
    try:
        with span(
            "ai_playbook.override",
            override_attrs(gate=gate, reason=reason, actor=actor, script=script),
        ) as s:
            try:
                s.set_attribute("ai_playbook.override.ts", ts)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001 — never crash the caller
        return


__all__ = [
    "MIN_REASON_LEN",
    "OverrideResult",
    "add_break_glass_flag",
    "apply_break_glass",
]
