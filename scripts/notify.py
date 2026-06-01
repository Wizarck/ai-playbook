"""Shared notification emitter for playbook automations.

Implements the JSONL-queue + SMTP-email contract from
``docs/concepts/notification-queue.md`` (the spec this module realises) and the severity
matrix from ``docs/concepts/notification-policy.md``.

Zero-touch contract
-------------------
- Every automation emits a notification at every step it cares about. The
  helper is non-fatal: a transport hiccup never raises to the caller.
- ``silent`` → JSONL only (machine audit).
- ``info`` → JSONL + (later) dashboard SSE. Rate-limited to 5/min per
  ``event``+``actor``; excess is coalesced into a single ``notification.burst``
  summary.
- ``warn`` / ``error`` → JSONL + (a) durable queue (when
  ``CONSUMER_D_NOTIFICATIONS_QUEUE_ENABLED=1`` AND a consumer-side
  ``notifications.queue`` package is importable — Phase 5 Change B); OR
  (b) synchronous SMTP email when the queue is disabled / unavailable AND
  SMTP env vars are set AND severity meets
  ``AIPLAYBOOK_NOTIFICATIONS_EMAIL_MIN_SEVERITY`` (default ``warn``).
  When the queue path activates the SMTP path is skipped — the queue's
  worker handles delivery via Telegram/WhatsApp.
- Dedup window: the same ``event`` + ``summary`` + ``trace_id`` emitted twice
  within 60s is written once (the second emission returns silently).

Public API
----------
``notify(*, event, severity, summary, detail="", attrs=None, trace_id=None,
actor=None) -> None``

See module-level docstring in ``docs/concepts/notification-queue.md`` for the envelope
shape; each JSONL line carries:

    {"ts": ISO8601, "event": "...", "severity": "silent|info|warn|error",
     "summary": "...", "detail": "...", "attrs": {...},
     "trace_id": "...", "actor": "..."}

CLI
---
    python -m scripts.notify --event EVENT --severity info --summary TEXT \\
        [--detail TEXT] [--attrs JSON] [--trace-id HEX] [--actor EMAIL]

Exit codes: always ``0``. The helper swallows transport errors; the CLI only
returns non-zero for argparse/JSON-parse failures (``1``/``2``).
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import subprocess
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

# Force UTF-8 stdio — notifications can carry ✅/⚠️/❌ sigils.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

SEVERITY_LEVELS = ("silent", "info", "warn", "error")
_SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITY_LEVELS)}

RATE_LIMIT_WINDOW_S = 60.0
RATE_LIMIT_MAX_PER_WINDOW = 5  # per (event, actor), per window
DEDUP_WINDOW_S = 60.0
DEFAULT_EMAIL_MIN_SEVERITY = "warn"

# Per-process state (test-friendly: expose reset helper below).
_LOCK = threading.Lock()
_RATE_BUCKET: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_RATE_DROPPED: dict[tuple[str, str], int] = defaultdict(int)
_DEDUP_CACHE: dict[tuple[str, str, str | None], float] = {}


def _reset_state_for_tests() -> None:
    """Clear in-process rate/dedup caches. Test-only helper."""
    with _LOCK:
        _RATE_BUCKET.clear()
        _RATE_DROPPED.clear()
        _DEDUP_CACHE.clear()


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _repo_root_from_cwd(start: Path | None = None) -> Path:
    """Walk up from ``start`` (default cwd) looking for a .git or pyproject.toml
    marker. Fall back to ``start`` if no marker is found."""
    start = (start or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists() or (candidate / "pyproject.toml").exists():
            return candidate
    return start


def default_notifications_path() -> Path:
    """Resolve the JSONL queue path.

    Precedence: ``AIPLAYBOOK_NOTIFICATIONS_FILE`` env → ``<repo>/.ai-playbook/notifications.jsonl``.
    """
    env = os.environ.get("AIPLAYBOOK_NOTIFICATIONS_FILE", "").strip()
    if env:
        return Path(env).expanduser()
    return _repo_root_from_cwd() / ".ai-playbook" / "notifications.jsonl"


# ---------------------------------------------------------------------------
# Actor resolution
# ---------------------------------------------------------------------------


def _resolve_actor(explicit: str | None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("GIT_AUTHOR_EMAIL", "").strip()
    if env:
        return env
    # best-effort `git config user.email`; never raise on failure.
    try:
        out = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# Severity / rate-limit / dedup plumbing
# ---------------------------------------------------------------------------


def _normalise_severity(severity: str) -> str:
    s = (severity or "").lower().strip()
    if s not in _SEVERITY_RANK:
        return "info"
    return s


def _severity_geq(a: str, b: str) -> bool:
    return _SEVERITY_RANK.get(a, -1) >= _SEVERITY_RANK.get(b, -1)


def _rate_limit_check(event: str, actor: str, *, now: float) -> tuple[bool, int]:
    """Return (allowed, dropped_so_far).

    For ``info`` emissions we cap at RATE_LIMIT_MAX_PER_WINDOW per (event, actor)
    per RATE_LIMIT_WINDOW_S. When over the cap, we increment the drop counter
    and return (False, drop_count).
    """
    key = (event, actor)
    bucket = _RATE_BUCKET[key]
    cutoff = now - RATE_LIMIT_WINDOW_S
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_MAX_PER_WINDOW:
        _RATE_DROPPED[key] += 1
        return False, _RATE_DROPPED[key]
    bucket.append(now)
    return True, 0


def _dedup_check(event: str, summary: str, trace_id: str | None, *, now: float) -> bool:
    """Return True if this emission should proceed (not a recent dupe)."""
    key = (event, summary, trace_id)
    last = _DEDUP_CACHE.get(key)
    if last is not None and (now - last) < DEDUP_WINDOW_S:
        return False
    _DEDUP_CACHE[key] = now
    # Prune stale entries to keep the map bounded.
    stale = [k for k, ts in _DEDUP_CACHE.items() if (now - ts) > DEDUP_WINDOW_S * 10]
    for k in stale:
        _DEDUP_CACHE.pop(k, None)
    return True


# ---------------------------------------------------------------------------
# SMTP transport
# ---------------------------------------------------------------------------


def _smtp_config() -> dict[str, str] | None:
    """Return SMTP config dict when all required vars are set, else None."""
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip() or "smtp.gmail.com"
    port_raw = os.environ.get("SMTP_PORT", "587").strip() or "587"
    try:
        port = int(port_raw)
    except ValueError:
        return None
    user = (os.environ.get("SMTP_USER") or os.environ.get("GIT_AUTHOR_EMAIL", "")).strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    if not user or not password:
        return None
    from_addr = os.environ.get("AIPLAYBOOK_NOTIFICATIONS_FROM", "").strip() or user
    to_addr = os.environ.get("AIPLAYBOOK_NOTIFICATIONS_TO", "").strip() or user
    return {
        "host": host,
        "port": str(port),
        "user": user,
        "password": password,
        "from": from_addr,
        "to": to_addr,
    }


def _build_email(
    *, cfg: dict[str, str], event: str, severity: str, summary: str,
    detail: str, attrs: dict[str, Any], actor: str, ts: str,
) -> MIMEText:
    subject_summary = summary[:60]
    subject = f"[ai-playbook] {severity.upper()} {event} — {subject_summary}"
    body_lines = [
        f"Severity : {severity}",
        f"Time     : {ts}",
        f"Event    : {event}",
        f"Actor    : {actor}",
        "",
        "Summary:",
        summary,
        "",
    ]
    if detail:
        body_lines += ["Detail:", detail, ""]
    body_lines += [
        "Attrs:",
        json.dumps(attrs, indent=2, sort_keys=True, default=str),
        "",
        "---",
        "To disable these emails set AIPLAYBOOK_NOTIFICATIONS_EMAIL_MIN_SEVERITY=never",
    ]
    msg = MIMEText("\n".join(body_lines), _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = cfg["from"]
    msg["To"] = cfg["to"]
    return msg


def _send_email(
    *, event: str, severity: str, summary: str, detail: str,
    attrs: dict[str, Any], actor: str, ts: str,
) -> tuple[bool, str]:
    """Best-effort SMTP send. Never raises. Returns (ok, reason)."""
    cfg = _smtp_config()
    if cfg is None:
        return False, "smtp-disabled"

    min_sev = (
        os.environ.get("AIPLAYBOOK_NOTIFICATIONS_EMAIL_MIN_SEVERITY", DEFAULT_EMAIL_MIN_SEVERITY)
        .strip().lower()
    )
    if min_sev == "never":
        return False, "disabled-by-env"
    if min_sev not in _SEVERITY_RANK:
        min_sev = DEFAULT_EMAIL_MIN_SEVERITY
    if not _severity_geq(severity, min_sev):
        return False, f"below-threshold:{min_sev}"

    try:
        msg = _build_email(
            cfg=cfg, event=event, severity=severity, summary=summary,
            detail=detail, attrs=attrs, actor=actor, ts=ts,
        )
        with smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=10) as smtp:
            smtp.ehlo()
            try:
                smtp.starttls()
                smtp.ehlo()
            except smtplib.SMTPException:
                # plain SMTP (test servers, local relays)
                pass
            try:
                smtp.login(cfg["user"], cfg["password"])
            except smtplib.SMTPException:
                # some local relays don't need auth; swallow and continue
                pass
            smtp.send_message(msg)
        return True, "sent"
    except (OSError, smtplib.SMTPException) as exc:
        return False, f"smtp-error:{exc.__class__.__name__}"


# ---------------------------------------------------------------------------
# Durable queue transport (Phase 5 Change B — `add-durable-notification-queue`)
# ---------------------------------------------------------------------------
#
# The durable queue lives in the consumer (acme-corp) under
# `langgraph-aiops/notifications/`. When it's importable AND
# `CONSUMER_D_NOTIFICATIONS_QUEUE_ENABLED=1`, warn/error notifications are
# enqueued to a SQLite-backed retry layer instead of fired through SMTP
# synchronously. Other consumers (consumer-b, consumer-c, consumer-e,
# livekit) that lack the queue package fall through to SMTP unchanged.

# Default channel per severity per `notification-policy.md` §3.1 + Change B
# proposal §"notification-policy.md respect": warn/error → telegram in v1.
_QUEUE_CHANNEL_BY_SEVERITY: dict[str, str] = {
    "warn": "telegram",
    "error": "telegram",
}


def _try_enqueue(*, envelope: dict[str, Any], severity: str) -> tuple[bool, str]:
    """Best-effort enqueue to the consumer's durable queue.

    Returns ``(enqueued, reason)``:
        - ``(True, "ok")`` when the row landed in the queue (worker will
          dispatch on its next 10s poll). Caller MUST skip SMTP in this case.
        - ``(False, "<reason>")`` otherwise — caller falls through to the
          legacy SMTP path. Reasons are stable for tests:
          ``"queue-disabled"`` (env var not set),
          ``"queue-package-missing"`` (consumer does not vendor the package),
          ``"queue-error:<exc-class>"`` (enqueue raised — never re-raised).
    """
    if os.environ.get("CONSUMER_D_NOTIFICATIONS_QUEUE_ENABLED", "").strip() != "1":
        return False, "queue-disabled"
    try:
        from notifications import queue as _queue  # type: ignore
    except ImportError:
        return False, "queue-package-missing"

    channel = _QUEUE_CHANNEL_BY_SEVERITY.get(severity, "telegram")
    try:
        _queue.enqueue(envelope, channel=channel, severity=severity)
        return True, "ok"
    except Exception as exc:  # noqa: BLE001 — never raise from the notify helper
        return False, f"queue-error:{exc.__class__.__name__}"


# ---------------------------------------------------------------------------
# JSONL append
# ---------------------------------------------------------------------------


def _append_jsonl(path: Path, envelope: dict[str, Any]) -> tuple[bool, str]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(envelope, ensure_ascii=False, default=str) + "\n")
        return True, "ok"
    except OSError as exc:
        return False, f"io:{exc}"


def _append_failure_breadcrumb(path: Path, reason: str) -> None:
    """Write a minimal fallback JSONL line when something upstream broke."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
                "event": "ai_playbook.notify.failed",
                "severity": "error",
                "summary": f"notify helper failed: {reason}",
                "attrs": {"ai_playbook.notify.failed": 1},
            }) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def notify(
    *,
    event: str,
    severity: str,
    summary: str,
    detail: str = "",
    attrs: dict[str, Any] | None = None,
    trace_id: str | None = None,
    actor: str | None = None,
    notifications_file: Path | None = None,
    now: float | None = None,
) -> None:
    """Emit a structured notification. Never raises to the caller.

    ``notifications_file`` / ``now`` are test-hook parameters.
    """
    try:
        sev = _normalise_severity(severity)
        actor_resolved = _resolve_actor(actor)
        attrs_final: dict[str, Any] = dict(attrs or {})
        now_ts = now if now is not None else time.time()
        ts_iso = datetime.fromtimestamp(now_ts, tz=UTC).astimezone().isoformat(
            timespec="seconds"
        )
        path = notifications_file or default_notifications_path()

        # Dedup — same event+summary+trace within 60s is a no-op.
        with _LOCK:
            if not _dedup_check(event, summary, trace_id, now=now_ts):
                return

            # Rate-limit info emissions (per event+actor).
            if sev == "info":
                allowed, dropped = _rate_limit_check(event, actor_resolved, now=now_ts)
                if not allowed:
                    # Coalesce drops: every 5th drop, emit a burst summary
                    # so the retro can see it.
                    if dropped == 1 or dropped % 5 == 0:
                        burst_env = {
                            "ts": ts_iso,
                            "event": "notification.burst",
                            "severity": "warn",
                            "summary": (
                                f"rate-limited {dropped} info emissions for "
                                f"{event} by {actor_resolved}"
                            ),
                            "detail": "",
                            "attrs": {
                                "ai_playbook.notification.source_event": event,
                                "ai_playbook.notification.drop_count": dropped,
                                "ai_playbook.notification.actor": actor_resolved,
                            },
                            "trace_id": trace_id,
                            "actor": actor_resolved,
                        }
                        _append_jsonl(path, burst_env)
                    return

        envelope = {
            "ts": ts_iso,
            "event": event,
            "severity": sev,
            "summary": summary,
            "detail": detail,
            "attrs": attrs_final,
            "trace_id": trace_id,
            "actor": actor_resolved,
        }

        ok, reason = _append_jsonl(path, envelope)
        if not ok:
            print(f"notify: JSONL append failed: {reason}", file=sys.stderr)
            _append_failure_breadcrumb(path, reason)

        # warn / error transport: prefer durable queue (Change B) when
        # available; fall through to synchronous SMTP otherwise.
        if sev in ("warn", "error"):
            enqueued, queue_reason = _try_enqueue(envelope=envelope, severity=sev)
            if enqueued:
                # Worker will dispatch via Telegram/WhatsApp on next poll.
                # SMTP path skipped — the queue is the canonical retryable
                # transport; double-sending would duplicate alerts.
                pass
            else:
                if queue_reason.startswith("queue-error"):
                    # Enqueue itself failed (DB locked, etc.) — log; SMTP
                    # fallback below still attempts delivery.
                    print(
                        f"notify: queue enqueue failed ({queue_reason}); "
                        "falling back to SMTP",
                        file=sys.stderr,
                    )
                sent_ok, sent_reason = _send_email(
                    event=event, severity=sev, summary=summary, detail=detail,
                    attrs=attrs_final, actor=actor_resolved, ts=ts_iso,
                )
                if not sent_ok and sent_reason not in (
                    "smtp-disabled", "disabled-by-env",
                ) and not sent_reason.startswith("below-threshold"):
                    print(
                        f"notify: email transport failure: {sent_reason}",
                        file=sys.stderr,
                    )

        # Best-effort OTel: emit BOTH a standalone span (so the notification is
        # visible in Langfuse/Tempo even when no parent trace exists) AND an
        # event on the current span (so it groups with the triggering
        # operation when one is open). add_event is a no-op when no span is
        # active, so the dual emission is safe.
        try:
            from scripts.tracing import trace_emit  # type: ignore

            otel_attrs = {
                "ai_playbook.notification.event": event,
                "ai_playbook.notification.severity": sev,
                "ai_playbook.notification.actor": actor_resolved,
                "ai_playbook.notification.summary": summary[:200],
            }
            otel_attrs.update({
                f"ai_playbook.notification.attrs.{k}": v
                for k, v in attrs_final.items()
                if isinstance(v, str | int | float | bool)
            })
            with trace_emit.span(f"notification.{event}", otel_attrs):
                pass
            trace_emit.add_event(name=event, attrs=otel_attrs)
        except Exception:  # noqa: BLE001 — OTel is best-effort.
            pass

    except Exception as exc:  # noqa: BLE001 — helper must never raise.
        try:
            print(f"notify: unexpected failure: {exc}", file=sys.stderr)
            _append_failure_breadcrumb(
                notifications_file or default_notifications_path(),
                f"{exc.__class__.__name__}:{exc}",
            )
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="notify",
        description="Emit a structured notification to the JSONL queue + optional email.",
    )
    p.add_argument("--event", required=True, help="Event name (e.g. issue_sync.created).")
    p.add_argument("--severity", required=True, choices=SEVERITY_LEVELS)
    p.add_argument("--summary", required=True, help="One-line human summary.")
    p.add_argument("--detail", default="", help="Optional multi-paragraph detail.")
    p.add_argument("--attrs", default="{}", help="JSON object of structured attrs.")
    p.add_argument("--trace-id", default=None, help="Optional OTel trace id for correlation.")
    p.add_argument("--actor", default=None, help="Override actor (default: git user.email).")
    p.add_argument(
        "--notifications-file", type=Path, default=None,
        help="Override JSONL path (default: AIPLAYBOOK_NOTIFICATIONS_FILE or <repo>/.ai-playbook/notifications.jsonl).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        attrs = json.loads(args.attrs) if args.attrs else {}
        if not isinstance(attrs, dict):
            print("❌ --attrs must be a JSON object.", file=sys.stderr)
            return 1
    except json.JSONDecodeError as exc:
        print(f"❌ --attrs is not valid JSON: {exc}", file=sys.stderr)
        return 1

    notify(
        event=args.event,
        severity=args.severity,
        summary=args.summary,
        detail=args.detail,
        attrs=attrs,
        trace_id=args.trace_id,
        actor=args.actor,
        notifications_file=args.notifications_file,
    )
    return 0


__all__ = [
    "SEVERITY_LEVELS",
    "RATE_LIMIT_MAX_PER_WINDOW",
    "RATE_LIMIT_WINDOW_S",
    "DEDUP_WINDOW_S",
    "default_notifications_path",
    "notify",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
