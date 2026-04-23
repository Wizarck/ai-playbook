"""Tests for scripts/lifecycle_check.py (T14i)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import lifecycle_check as lc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)


def _write_overrides(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _set_mtime(path: Path, dt: datetime) -> None:
    ts = dt.timestamp()
    os.utime(path, (ts, ts))


# ---------------------------------------------------------------------------
# Parser unit tests
# ---------------------------------------------------------------------------


def test_parse_overrides_log_counts_entries(tmp_path: Path) -> None:
    log = tmp_path / "overrides.log"
    _write_overrides(log, [
        '2026-04-20T09:00:00+00:00 jane@example.com schema_validate.py agents-md "bootstrapping acme-shop project before submodule"',
        '2026-04-21T09:00:00+00:00 jane@example.com schema_validate.py agents-md "retry after fixing lint error"',
    ])
    entries = lc.parse_overrides_log(log)
    assert len(entries) == 2
    assert entries[0].actor == "jane@example.com"
    assert entries[0].gate == "agents-md"


def test_parse_overrides_log_missing_file(tmp_path: Path) -> None:
    entries = lc.parse_overrides_log(tmp_path / "none.log")
    assert entries == []


def test_parse_overrides_log_skips_malformed_lines(tmp_path: Path) -> None:
    log = tmp_path / "overrides.log"
    log.write_text(
        "not a log line\n"
        "2026-04-20T09:00:00+00:00 jane@example.com schema_validate.py agents-md \"valid reason here\"\n",
        encoding="utf-8",
    )
    entries = lc.parse_overrides_log(log)
    assert len(entries) == 1


def test_systemic_gates_triggers_on_threshold(tmp_path: Path) -> None:
    log = tmp_path / "overrides.log"
    lines = [
        f'2026-04-{20 + i:02d}T09:00:00+00:00 actor@example.com s.py gate-a "reason long enough"'
        for i in range(3)
    ]
    _write_overrides(log, lines)
    entries = lc.parse_overrides_log(log)
    flagged = lc._systemic_gates(entries)
    assert flagged == [("gate-a", 3)]


def test_systemic_gates_not_flagged_under_threshold(tmp_path: Path) -> None:
    log = tmp_path / "overrides.log"
    lines = [
        f'2026-04-{20 + i:02d}T09:00:00+00:00 actor@example.com s.py gate-a "reason long enough"'
        for i in range(2)
    ]
    _write_overrides(log, lines)
    entries = lc.parse_overrides_log(log)
    assert lc._systemic_gates(entries) == []


# ---------------------------------------------------------------------------
# OpenSpec scanning
# ---------------------------------------------------------------------------


def test_scan_openspec_empty_repo(tmp_path: Path) -> None:
    clarifies, stale = lc.scan_openspec_changes(tmp_path / "openspec", now=_now())
    assert clarifies == []
    assert stale == []


def test_scan_openspec_detects_stale_change(tmp_path: Path) -> None:
    change_dir = tmp_path / "openspec" / "changes" / "very-old-change"
    change_dir.mkdir(parents=True)
    fp = change_dir / "proposal.md"
    fp.write_text("# proposal\n", encoding="utf-8")
    _set_mtime(fp, _now() - timedelta(days=60))
    _, stale = lc.scan_openspec_changes(tmp_path / "openspec", now=_now())
    assert len(stale) == 1
    assert stale[0].change_id == "very-old-change"
    assert stale[0].age_days > lc.STALE_OPENSPEC_DAYS


def test_scan_openspec_skips_archived_change(tmp_path: Path) -> None:
    change_dir = tmp_path / "openspec" / "changes" / "archived-change"
    (change_dir / "archive").mkdir(parents=True)
    fp = change_dir / "proposal.md"
    fp.write_text("# proposal\n", encoding="utf-8")
    _set_mtime(fp, _now() - timedelta(days=60))
    _, stale = lc.scan_openspec_changes(tmp_path / "openspec", now=_now())
    assert stale == []


def test_scan_openspec_detects_old_clarify(tmp_path: Path) -> None:
    change_dir = tmp_path / "openspec" / "changes" / "needs-clarify"
    change_dir.mkdir(parents=True)
    fp = change_dir / "proposal.md"
    fp.write_text(
        "# proposal\n\n❓ CLARIFICATION NEEDED: figure out the thing\n",
        encoding="utf-8",
    )
    _set_mtime(fp, _now() - timedelta(days=10))
    clarifies, _ = lc.scan_openspec_changes(tmp_path / "openspec", now=_now())
    assert len(clarifies) == 1
    assert clarifies[0].age_days > lc.OLD_CLARIFY_DAYS


def test_scan_openspec_ignores_fresh_clarify(tmp_path: Path) -> None:
    change_dir = tmp_path / "openspec" / "changes" / "fresh-clarify"
    change_dir.mkdir(parents=True)
    fp = change_dir / "proposal.md"
    fp.write_text("❓ CLARIFICATION NEEDED: new\n", encoding="utf-8")
    _set_mtime(fp, _now() - timedelta(days=1))
    clarifies, _ = lc.scan_openspec_changes(tmp_path / "openspec", now=_now())
    assert clarifies == []


# ---------------------------------------------------------------------------
# Memory decay
# ---------------------------------------------------------------------------


def test_count_memory_decay_candidates(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    events.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        {"ts": (_now() - timedelta(days=120)).isoformat(), "name": "hindsight.retain", "attrs": {}},
        {"ts": (_now() - timedelta(days=100)).isoformat(), "name": "hindsight.retain", "attrs": {}},
        {"ts": (_now() - timedelta(days=10)).isoformat(), "name": "hindsight.retain", "attrs": {}},
        {"ts": (_now() - timedelta(days=150)).isoformat(), "name": "llm.call", "attrs": {}},  # wrong name
    ]
    events.write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")
    count = lc.count_memory_decay_candidates(events, now=_now())
    assert count == 2


def test_count_memory_decay_missing_file(tmp_path: Path) -> None:
    assert lc.count_memory_decay_candidates(tmp_path / "none.jsonl", now=_now()) == 0


# ---------------------------------------------------------------------------
# Migration log
# ---------------------------------------------------------------------------


def test_read_migration_pending(tmp_path: Path) -> None:
    log = tmp_path / "migration-pending.log"
    log.write_text("entry-1\nentry-2\n\n", encoding="utf-8")
    assert lc.read_migration_pending(log) == ["entry-1", "entry-2"]


def test_read_migration_pending_missing(tmp_path: Path) -> None:
    assert lc.read_migration_pending(tmp_path / "none.log") == []


# ---------------------------------------------------------------------------
# Full report rendering
# ---------------------------------------------------------------------------


def test_render_markdown_pristine_repo_has_all_sections(tmp_path: Path) -> None:
    report = lc.build_report(
        consumer_root=tmp_path,
        month="2026-03",
        now=_now(),
        migration_log=tmp_path / "migration.log",
    )
    body = lc.render_markdown(report)
    assert "# Lifecycle report — 2026-03" in body
    assert "## Break-glass summary" in body
    assert "## Unresolved CLARIFY" in body
    assert "## Stale OpenSpec changes" in body
    assert "## Memory decay candidates" in body
    assert "## Pending v0→v1 migrations" in body
    assert "## Systemic flags" in body
    assert "## Actions" in body


def test_render_markdown_with_systemic_flag(tmp_path: Path) -> None:
    # Seed 3 overrides on same gate within 30 days of _now.
    (tmp_path / ".ai-playbook").mkdir()
    log = tmp_path / ".ai-playbook" / "overrides.log"
    lines = [
        f'2026-04-{18 + i:02d}T09:00:00+00:00 actor@example.com s.py gate-a "reason long enough"'
        for i in range(3)
    ]
    _write_overrides(log, lines)

    report = lc.build_report(
        consumer_root=tmp_path,
        month="2026-04",
        now=_now(),
        migration_log=tmp_path / "none.log",
    )
    assert report.systemic_count() >= 1
    body = lc.render_markdown(report)
    assert "(systemic)" in body
    assert "gate-a" in body


# ---------------------------------------------------------------------------
# main() / CLI
# ---------------------------------------------------------------------------


def test_main_dry_run_prints_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = lc.main([
        "--consumer-root", str(tmp_path),
        "--month", "2026-03",
        "--now", "2026-04-23T12:00:00+00:00",
        "--migration-log", str(tmp_path / "none.log"),
        "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# Lifecycle report — 2026-03" in out
    assert not (tmp_path / "reports").exists()


def test_main_writes_report_by_default(tmp_path: Path) -> None:
    rc = lc.main([
        "--consumer-root", str(tmp_path),
        "--month", "2026-03",
        "--now", "2026-04-23T12:00:00+00:00",
        "--migration-log", str(tmp_path / "none.log"),
    ])
    assert rc == 0
    out_file = tmp_path / "reports" / "lifecycle" / "2026-03.md"
    assert out_file.is_file()
    assert "Lifecycle report" in out_file.read_text(encoding="utf-8")


def test_main_strict_exits_1_on_systemic(tmp_path: Path) -> None:
    (tmp_path / ".ai-playbook").mkdir()
    log = tmp_path / ".ai-playbook" / "overrides.log"
    lines = [
        f'2026-04-{18 + i:02d}T09:00:00+00:00 actor@example.com s.py gate-a "reason long enough"'
        for i in range(3)
    ]
    _write_overrides(log, lines)

    rc = lc.main([
        "--consumer-root", str(tmp_path),
        "--month", "2026-04",
        "--now", "2026-04-23T12:00:00+00:00",
        "--migration-log", str(tmp_path / "none.log"),
        "--strict",
        "--dry-run",
    ])
    assert rc == 1


def test_main_strict_exits_0_when_clean(tmp_path: Path) -> None:
    rc = lc.main([
        "--consumer-root", str(tmp_path),
        "--month", "2026-03",
        "--now", "2026-04-23T12:00:00+00:00",
        "--migration-log", str(tmp_path / "none.log"),
        "--strict",
        "--dry-run",
    ])
    assert rc == 0


def test_main_month_override(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = lc.main([
        "--consumer-root", str(tmp_path),
        "--month", "2025-12",
        "--now", "2026-04-23T12:00:00+00:00",
        "--migration-log", str(tmp_path / "none.log"),
        "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "2025-12" in out


def test_main_default_month_is_previous_month(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = lc.main([
        "--consumer-root", str(tmp_path),
        "--now", "2026-04-23T12:00:00+00:00",
        "--migration-log", str(tmp_path / "none.log"),
        "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    # When now is 2026-04-23, previous month = 2026-03.
    assert "2026-03" in out


def test_main_bad_consumer_root_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    rc = lc.main(["--consumer-root", "/definitely/not/a/real/path-xyz"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "consumer root not found" in err
