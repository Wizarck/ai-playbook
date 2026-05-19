"""Tests for scripts/notify.py — the shared notification emitter.

The helper must never raise. Every test that exercises a failure path asserts
that (a) the caller returns normally, (b) a JSONL line was written, and (c) no
email was sent when SMTP env is absent or below threshold.
"""
from __future__ import annotations

import json
import smtplib
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import notify as notify_mod


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Clear per-process dedup + rate state before each test."""
    notify_mod._reset_state_for_tests()


@pytest.fixture
def jsonl_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / ".ai-playbook" / "notifications.jsonl"
    monkeypatch.setenv("AIPLAYBOOK_NOTIFICATIONS_FILE", str(path))
    # Clear SMTP env so tests don't accidentally send mail.
    for var in ("SMTP_USER", "SMTP_PASSWORD", "SMTP_HOST", "SMTP_PORT",
                "AIPLAYBOOK_NOTIFICATIONS_FROM", "AIPLAYBOOK_NOTIFICATIONS_TO",
                "AIPLAYBOOK_NOTIFICATIONS_EMAIL_MIN_SEVERITY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "tester@example.com")
    return path


def _read_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_notify_appends_jsonl_line(jsonl_path: Path) -> None:
    notify_mod.notify(event="demo.happy", severity="info", summary="ok")
    lines = _read_lines(jsonl_path)
    assert len(lines) == 1
    assert lines[0]["event"] == "demo.happy"
    assert lines[0]["severity"] == "info"
    assert lines[0]["actor"] == "tester@example.com"
    assert lines[0]["ts"].endswith("+00:00") or "+" in lines[0]["ts"] or "-" in lines[0]["ts"]


def test_notify_preserves_attrs_and_trace_id(jsonl_path: Path) -> None:
    notify_mod.notify(
        event="demo.attrs", severity="warn", summary="s",
        attrs={"key": "value", "n": 3}, trace_id="deadbeef",
    )
    lines = _read_lines(jsonl_path)
    assert lines[0]["attrs"] == {"key": "value", "n": 3}
    assert lines[0]["trace_id"] == "deadbeef"


def test_notify_explicit_actor_wins_over_env(jsonl_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "env@example.com")
    notify_mod.notify(event="demo.actor", severity="info", summary="s", actor="explicit@x.com")
    lines = _read_lines(jsonl_path)
    assert lines[0]["actor"] == "explicit@x.com"


def test_notify_creates_parent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deep = tmp_path / "a" / "b" / "c" / "notifications.jsonl"
    monkeypatch.setenv("AIPLAYBOOK_NOTIFICATIONS_FILE", str(deep))
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    notify_mod.notify(event="demo.mkdir", severity="info", summary="s")
    assert deep.is_file()


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


def test_notify_dedups_same_event_summary_trace_within_window(jsonl_path: Path) -> None:
    notify_mod.notify(
        event="demo.dup", severity="info", summary="same",
        trace_id="t", now=1000.0,
    )
    notify_mod.notify(
        event="demo.dup", severity="info", summary="same",
        trace_id="t", now=1001.0,
    )
    lines = _read_lines(jsonl_path)
    assert len(lines) == 1


def test_notify_does_not_dedup_after_window(jsonl_path: Path) -> None:
    notify_mod.notify(
        event="demo.dup2", severity="info", summary="same",
        trace_id="t", now=1000.0,
    )
    notify_mod.notify(
        event="demo.dup2", severity="info", summary="same",
        trace_id="t", now=1000.0 + notify_mod.DEDUP_WINDOW_S + 1,
    )
    lines = _read_lines(jsonl_path)
    assert len(lines) == 2


def test_notify_dedup_ignores_different_trace_id(jsonl_path: Path) -> None:
    notify_mod.notify(event="demo.td", severity="info", summary="s", trace_id="a", now=1000.0)
    notify_mod.notify(event="demo.td", severity="info", summary="s", trace_id="b", now=1000.5)
    lines = _read_lines(jsonl_path)
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def test_notify_rate_limits_info_bursts(jsonl_path: Path) -> None:
    # 10 unique emissions within the same second should yield
    # RATE_LIMIT_MAX_PER_WINDOW writes + the burst summary.
    for i in range(10):
        notify_mod.notify(
            event="demo.rl", severity="info", summary=f"s{i}",
            now=2000.0 + i * 0.01,
        )
    lines = _read_lines(jsonl_path)
    infos = [line for line in lines if line["severity"] == "info"]
    bursts = [line for line in lines if line["event"] == "notification.burst"]
    assert len(infos) == notify_mod.RATE_LIMIT_MAX_PER_WINDOW
    assert len(bursts) >= 1
    assert bursts[0]["severity"] == "warn"
    assert "rate-limited" in bursts[0]["summary"]


def test_notify_does_not_rate_limit_warn(jsonl_path: Path) -> None:
    for i in range(10):
        notify_mod.notify(
            event="demo.warn_flood", severity="warn", summary=f"s{i}",
            now=3000.0 + i * 0.01,
        )
    warns = [line for line in _read_lines(jsonl_path) if line["severity"] == "warn"]
    assert len(warns) == 10


def test_notify_rate_limit_recovers_after_window(jsonl_path: Path) -> None:
    for i in range(notify_mod.RATE_LIMIT_MAX_PER_WINDOW + 2):
        notify_mod.notify(
            event="demo.rl2", severity="info", summary=f"s{i}",
            now=4000.0 + i * 0.01,
        )
    # Advance past the window.
    notify_mod.notify(
        event="demo.rl2", severity="info", summary="after-window",
        now=4000.0 + notify_mod.RATE_LIMIT_WINDOW_S + 5.0,
    )
    infos = [line for line in _read_lines(jsonl_path) if line["severity"] == "info"]
    assert any(line["summary"] == "after-window" for line in infos)


# ---------------------------------------------------------------------------
# Severity normalisation
# ---------------------------------------------------------------------------


def test_notify_unknown_severity_falls_back_to_info(jsonl_path: Path) -> None:
    notify_mod.notify(event="demo.sev", severity="URGENT", summary="s")
    lines = _read_lines(jsonl_path)
    assert lines[0]["severity"] == "info"


def test_notify_silent_bypasses_rate_limit(jsonl_path: Path) -> None:
    for i in range(20):
        notify_mod.notify(
            event="demo.silent", severity="silent", summary=f"s{i}",
            now=5000.0 + i * 0.01,
        )
    lines = _read_lines(jsonl_path)
    assert len(lines) == 20


# ---------------------------------------------------------------------------
# Email transport
# ---------------------------------------------------------------------------


class _FakeSMTP:
    instances: list[_FakeSMTP] = []

    def __init__(self, host: str, port: int, timeout: float = 10.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sent: list[Any] = []
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *a) -> None:
        return None

    def ehlo(self) -> None:
        pass

    def starttls(self) -> None:
        pass

    def login(self, user: str, password: str) -> None:
        self.login_user = user

    def send_message(self, msg) -> None:
        self.sent.append(msg)


@pytest.fixture
def smtp_enabled(monkeypatch: pytest.MonkeyPatch) -> type[_FakeSMTP]:
    _FakeSMTP.instances.clear()
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "bot@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setattr(notify_mod.smtplib, "SMTP", _FakeSMTP)
    return _FakeSMTP


def test_email_sent_on_warn_when_smtp_configured(
    jsonl_path: Path, smtp_enabled: type[_FakeSMTP],
) -> None:
    notify_mod.notify(event="demo.email", severity="warn", summary="warn-me")
    assert len(smtp_enabled.instances) == 1
    assert len(smtp_enabled.instances[0].sent) == 1
    msg = smtp_enabled.instances[0].sent[0]
    assert "WARN" in msg["Subject"]
    assert "demo.email" in msg["Subject"]


def test_email_sent_on_error(
    jsonl_path: Path, smtp_enabled: type[_FakeSMTP],
) -> None:
    notify_mod.notify(event="demo.err", severity="error", summary="boom")
    assert len(smtp_enabled.instances[0].sent) == 1


def test_email_suppressed_below_threshold(
    jsonl_path: Path, smtp_enabled: type[_FakeSMTP], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIPLAYBOOK_NOTIFICATIONS_EMAIL_MIN_SEVERITY", "error")
    notify_mod.notify(event="demo.thr", severity="warn", summary="warn")
    # No SMTP instance should even be constructed.
    assert smtp_enabled.instances == []


def test_email_disabled_by_never(
    jsonl_path: Path, smtp_enabled: type[_FakeSMTP], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIPLAYBOOK_NOTIFICATIONS_EMAIL_MIN_SEVERITY", "never")
    notify_mod.notify(event="demo.never", severity="error", summary="x")
    assert smtp_enabled.instances == []


def test_email_disabled_when_password_missing(
    jsonl_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_USER", "bot@example.com")
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)

    fake_calls: list[Any] = []

    class _BoomSMTP:
        def __init__(self, *a, **kw) -> None:
            fake_calls.append(("ctor", a, kw))
        def __enter__(self):  # pragma: no cover
            return self
        def __exit__(self, *a):  # pragma: no cover
            return None

    monkeypatch.setattr(notify_mod.smtplib, "SMTP", _BoomSMTP)
    notify_mod.notify(event="demo.nosmtp", severity="warn", summary="s")
    # SMTP.__init__ should never be called.
    assert fake_calls == []


def test_email_failure_does_not_raise(
    jsonl_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "bot@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")

    class _BoomSMTP:
        def __init__(self, *a, **kw) -> None:
            raise smtplib.SMTPException("fake")

    monkeypatch.setattr(notify_mod.smtplib, "SMTP", _BoomSMTP)
    # Must not raise.
    notify_mod.notify(event="demo.boom", severity="error", summary="s")
    lines = _read_lines(jsonl_path)
    # Envelope still written despite SMTP failure.
    assert any(line["event"] == "demo.boom" for line in lines)


# ---------------------------------------------------------------------------
# Durable queue transport (Phase 5 Change B — `add-durable-notification-queue`)
# ---------------------------------------------------------------------------


def _install_fake_queue(
    monkeypatch: pytest.MonkeyPatch,
    *,
    raise_on_enqueue: bool = False,
) -> list[tuple[dict, str, str]]:
    """Inject a fake ``notifications.queue`` module that records enqueue calls.

    Returns the list that captures ``(envelope, channel, severity)`` tuples.
    """
    captured: list[tuple[dict, str, str]] = []

    fake_queue_pkg = type(sys)("notifications")
    fake_queue_mod = type(sys)("notifications.queue")

    def _fake_enqueue(envelope, channel, severity, **_kw):  # noqa: ANN001
        if raise_on_enqueue:
            raise RuntimeError("simulated DB lock")
        captured.append((envelope, channel, severity))
        return len(captured)

    fake_queue_mod.enqueue = _fake_enqueue  # type: ignore[attr-defined]
    fake_queue_pkg.queue = fake_queue_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "notifications", fake_queue_pkg)
    monkeypatch.setitem(sys.modules, "notifications.queue", fake_queue_mod)
    return captured


def test_warn_routes_through_queue_when_enabled_skips_smtp(
    jsonl_path: Path,
    smtp_enabled: type[_FakeSMTP],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONSUMER_D_NOTIFICATIONS_QUEUE_ENABLED", "1")
    captured = _install_fake_queue(monkeypatch)

    notify_mod.notify(event="demo.queue", severity="warn", summary="via-queue")

    # Enqueued via Telegram per severity → channel mapping.
    assert len(captured) == 1
    envelope, channel, severity = captured[0]
    assert channel == "telegram"
    assert severity == "warn"
    assert envelope["event"] == "demo.queue"
    assert envelope["severity"] == "warn"
    # SMTP must NOT be invoked when the queue claims the message.
    assert smtp_enabled.instances == []


def test_error_routes_through_queue_when_enabled(
    jsonl_path: Path,
    smtp_enabled: type[_FakeSMTP],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONSUMER_D_NOTIFICATIONS_QUEUE_ENABLED", "1")
    captured = _install_fake_queue(monkeypatch)

    notify_mod.notify(event="demo.err", severity="error", summary="boom")

    assert len(captured) == 1
    assert captured[0][1] == "telegram"
    assert captured[0][2] == "error"
    assert smtp_enabled.instances == []


def test_queue_disabled_falls_through_to_smtp(
    jsonl_path: Path,
    smtp_enabled: type[_FakeSMTP],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default (no env var) keeps the legacy SMTP behaviour."""
    monkeypatch.delenv("CONSUMER_D_NOTIFICATIONS_QUEUE_ENABLED", raising=False)
    captured = _install_fake_queue(monkeypatch)

    notify_mod.notify(event="demo.legacy", severity="warn", summary="smtp")

    # Queue not consulted; SMTP fired.
    assert captured == []
    assert len(smtp_enabled.instances) == 1
    assert len(smtp_enabled.instances[0].sent) == 1


def test_queue_package_missing_falls_through_to_smtp(
    jsonl_path: Path,
    smtp_enabled: type[_FakeSMTP],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env var set but the consumer-side package is absent (e.g. a non-consumer-d
    consumer with the env var inadvertently exported) — must NOT crash; falls
    through to SMTP."""
    monkeypatch.setenv("CONSUMER_D_NOTIFICATIONS_QUEUE_ENABLED", "1")
    # Ensure neither real nor fake `notifications` module is importable.
    monkeypatch.delitem(sys.modules, "notifications", raising=False)
    monkeypatch.delitem(sys.modules, "notifications.queue", raising=False)

    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if name == "notifications" or name.startswith("notifications."):
            raise ImportError("notifications package not vendored on this consumer")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    notify_mod.notify(event="demo.no-pkg", severity="warn", summary="x")

    # SMTP fired since the queue path was unavailable.
    assert len(smtp_enabled.instances) == 1


def test_queue_enqueue_failure_falls_back_to_smtp(
    jsonl_path: Path,
    smtp_enabled: type[_FakeSMTP],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If enqueue raises (DB lock, disk full), the helper logs + falls back
    to SMTP — never re-raises."""
    monkeypatch.setenv("CONSUMER_D_NOTIFICATIONS_QUEUE_ENABLED", "1")
    _install_fake_queue(monkeypatch, raise_on_enqueue=True)

    notify_mod.notify(event="demo.dblock", severity="error", summary="locked")

    err = capsys.readouterr().err
    assert "queue enqueue failed" in err
    assert "queue-error:RuntimeError" in err
    # SMTP fallback fired.
    assert len(smtp_enabled.instances) == 1


def test_queue_does_not_route_info_severity(
    jsonl_path: Path,
    smtp_enabled: type[_FakeSMTP],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per D2.5: info-level bypasses the queue entirely."""
    monkeypatch.setenv("CONSUMER_D_NOTIFICATIONS_QUEUE_ENABLED", "1")
    captured = _install_fake_queue(monkeypatch)

    notify_mod.notify(event="demo.info", severity="info", summary="ignore-me")

    assert captured == []  # info doesn't reach the queue path
    assert smtp_enabled.instances == []  # SMTP also doesn't fire for info


# ---------------------------------------------------------------------------
# Non-raising contract
# ---------------------------------------------------------------------------


def test_notify_never_raises_on_append_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    # Point at a path we cannot write to (a file-as-parent trick).
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    forbidden = blocker / "inside.jsonl"  # blocker is a file, so mkdir must fail
    monkeypatch.setenv("AIPLAYBOOK_NOTIFICATIONS_FILE", str(forbidden))
    # Must not raise.
    notify_mod.notify(event="demo.nofile", severity="info", summary="s")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_writes_jsonl(jsonl_path: Path) -> None:
    rc = notify_mod.main([
        "--event", "cli.test", "--severity", "info", "--summary", "cli-summary",
        "--attrs", json.dumps({"k": "v"}),
    ])
    assert rc == 0
    lines = _read_lines(jsonl_path)
    assert lines[0]["event"] == "cli.test"
    assert lines[0]["attrs"] == {"k": "v"}


def test_cli_rejects_malformed_attrs(jsonl_path: Path) -> None:
    rc = notify_mod.main([
        "--event", "cli.bad", "--severity", "info", "--summary", "s",
        "--attrs", "{not-json",
    ])
    assert rc == 1


def test_cli_rejects_non_object_attrs(jsonl_path: Path) -> None:
    rc = notify_mod.main([
        "--event", "cli.arr", "--severity", "info", "--summary", "s",
        "--attrs", "[1,2,3]",
    ])
    assert rc == 1


def test_cli_requires_event(jsonl_path: Path) -> None:
    with pytest.raises(SystemExit):
        notify_mod.main(["--severity", "info", "--summary", "s"])


def test_cli_rejects_invalid_severity(jsonl_path: Path) -> None:
    with pytest.raises(SystemExit):
        notify_mod.main([
            "--event", "x", "--severity", "urgent", "--summary", "s",
        ])
