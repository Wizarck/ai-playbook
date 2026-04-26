"""Monthly lifecycle check.

Populated in T14i. Produces a markdown report at
``<repo>/reports/lifecycle/<YYYY-MM>.md`` surfacing:

- Break-glass usages (per actor / gate / script) over the last 30 days.
  Gates overridden >= 3 times flagged as systemic.
- Unresolved ``❓ CLARIFICATION NEEDED`` blocks in ``openspec/changes/`` whose
  oldest mtime is > 7 days old.
- OpenSpec changes not archived within 30 days (no ``archive/`` child dir).
- Memory-decay candidates: ``hindsight.retain`` events older than 90 days in
  ``<repo>/.ai-playbook/events.jsonl``.
- Deprecation watchers: entries in ``~/.ai-playbook/migration-pending.log``
  (see ``specs/migration-guide.md``).

CLI
---
    python -m scripts.lifecycle_check [--month YYYY-MM] [--consumer-root PATH]
                                      [--output PATH] [--dry-run] [--strict]

Exit codes
----------
    0  success, no systemic findings (or ``--strict`` disabled)
    1  ``--strict`` + at least one systemic finding
    2  setup error (unreadable consumer root)
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# Force UTF-8 stdio — markdown carries non-ASCII sigils.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


SYSTEMIC_OVERRIDE_THRESHOLD = 3  # overrides per gate in 30 days → systemic flag
OLD_CLARIFY_DAYS = 7
STALE_OPENSPEC_DAYS = 30
MEMORY_DECAY_DAYS = 90
BREAK_GLASS_WINDOW_DAYS = 30
CLARIFY_MARKER = "❓ CLARIFICATION NEEDED"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class OverrideEntry:
    ts: datetime
    actor: str
    script: str
    gate: str
    reason: str


@dataclass
class ClarifyFinding:
    path: Path
    oldest_mtime: datetime
    age_days: int


@dataclass
class StaleChangeFinding:
    change_id: str
    path: Path
    oldest_mtime: datetime
    age_days: int


@dataclass
class LifecycleReport:
    month: str  # YYYY-MM
    now: datetime
    overrides: list[OverrideEntry] = field(default_factory=list)
    systemic_gates: list[tuple[str, int]] = field(default_factory=list)
    clarifies: list[ClarifyFinding] = field(default_factory=list)
    stale_changes: list[StaleChangeFinding] = field(default_factory=list)
    memory_decay_count: int = 0
    pending_migrations: list[str] = field(default_factory=list)

    def systemic_count(self) -> int:
        return (
            len(self.systemic_gates)
            + len(self.clarifies)
            + len(self.stale_changes)
        )


# ---------------------------------------------------------------------------
# Break-glass log parsing
# ---------------------------------------------------------------------------


def _parse_iso_ts(raw: str) -> datetime | None:
    s = raw.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def parse_overrides_log(path: Path) -> list[OverrideEntry]:
    """Parse ``.ai-playbook/overrides.log``.

    Line format: ``<iso-ts> <actor> <script> <gate> "<reason>"``.
    Lines that don't match the shape are skipped silently.
    """
    entries: list[OverrideEntry] = []
    if not path.is_file():
        return entries
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return entries
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            tokens = shlex.split(line, posix=True)
        except ValueError:
            continue
        if len(tokens) < 5:
            continue
        ts = _parse_iso_ts(tokens[0])
        if ts is None:
            continue
        actor, script, gate = tokens[1], tokens[2], tokens[3]
        reason = " ".join(tokens[4:])
        entries.append(OverrideEntry(ts=ts, actor=actor, script=script, gate=gate, reason=reason))
    return entries


def _filter_within_window(entries: list[OverrideEntry], *, now: datetime, days: int) -> list[OverrideEntry]:
    cutoff = now - timedelta(days=days)
    return [e for e in entries if e.ts >= cutoff]


def _systemic_gates(entries: list[OverrideEntry]) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter(e.gate for e in entries)
    flagged = [(gate, n) for gate, n in counts.items() if n >= SYSTEMIC_OVERRIDE_THRESHOLD]
    return sorted(flagged, key=lambda x: (-x[1], x[0]))


# ---------------------------------------------------------------------------
# OpenSpec walking — CLARIFY + stale changes
# ---------------------------------------------------------------------------


def scan_openspec_changes(openspec_dir: Path, *, now: datetime) -> tuple[list[ClarifyFinding], list[StaleChangeFinding]]:
    clarifies: list[ClarifyFinding] = []
    stale: list[StaleChangeFinding] = []
    changes_dir = openspec_dir / "changes"
    if not changes_dir.is_dir():
        return clarifies, stale

    for change_dir in sorted(changes_dir.iterdir()):
        if not change_dir.is_dir():
            continue
        change_id = change_dir.name
        # Skip the canonical "archive" container itself if a repo uses one at
        # the changes/ level; real archived changes have an ``archive/`` child.
        if change_id in {"_template", "archive"}:
            continue

        # 1) Oldest file mtime in this change dir — used for stale-change detection.
        oldest_mtime: datetime | None = None
        has_archive = (change_dir / "archive").is_dir()
        for p in change_dir.rglob("*"):
            if not p.is_file():
                continue
            try:
                m = datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)
            except OSError:
                continue
            if oldest_mtime is None or m < oldest_mtime:
                oldest_mtime = m

        # 2) CLARIFY scanning — per file.
        for p in change_dir.rglob("*.md"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if CLARIFY_MARKER not in text:
                continue
            try:
                m = datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)
            except OSError:
                continue
            age = (now - m).days
            if age > OLD_CLARIFY_DAYS:
                clarifies.append(ClarifyFinding(path=p, oldest_mtime=m, age_days=age))

        if oldest_mtime is not None and not has_archive:
            age = (now - oldest_mtime).days
            if age > STALE_OPENSPEC_DAYS:
                stale.append(
                    StaleChangeFinding(
                        change_id=change_id,
                        path=change_dir,
                        oldest_mtime=oldest_mtime,
                        age_days=age,
                    )
                )

    clarifies.sort(key=lambda c: c.path)
    stale.sort(key=lambda s: (-s.age_days, s.change_id))
    return clarifies, stale


# ---------------------------------------------------------------------------
# Memory decay — events.jsonl
# ---------------------------------------------------------------------------


def count_memory_decay_candidates(events_path: Path, *, now: datetime) -> int:
    if not events_path.is_file():
        return 0
    cutoff = now - timedelta(days=MEMORY_DECAY_DAYS)
    count = 0
    try:
        with events_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                if obj.get("name") != "hindsight.retain":
                    continue
                ts = _parse_iso_ts(str(obj.get("ts") or ""))
                if ts is None:
                    continue
                if ts < cutoff:
                    count += 1
    except OSError:
        return 0
    return count


# ---------------------------------------------------------------------------
# Deprecation watcher — ~/.ai-playbook/migration-pending.log
# ---------------------------------------------------------------------------


def read_migration_pending(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        return [
            line.rstrip("\n")
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except OSError:
        return []


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_break_glass(report: LifecycleReport) -> list[str]:
    lines: list[str] = ["## Break-glass summary", ""]
    if not report.overrides:
        lines.append("_No overrides recorded in the last 30 days._")
        lines.append("")
        return lines

    by_gate: Counter[str] = Counter(e.gate for e in report.overrides)
    by_script: Counter[str] = Counter(e.script for e in report.overrides)
    by_actor: Counter[str] = Counter(e.actor for e in report.overrides)

    lines.append("| axis | key | count |")
    lines.append("|---|---|---|")
    for gate, n in sorted(by_gate.items(), key=lambda x: (-x[1], x[0])):
        marker = " **(systemic)**" if n >= SYSTEMIC_OVERRIDE_THRESHOLD else ""
        lines.append(f"| gate | `{gate}`{marker} | {n} |")
    for script, n in sorted(by_script.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"| script | `{script}` | {n} |")
    for actor, n in sorted(by_actor.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"| actor | `{actor}` | {n} |")
    lines.append("")
    return lines


def _render_clarifies(report: LifecycleReport) -> list[str]:
    lines: list[str] = ["## Unresolved CLARIFY", ""]
    if not report.clarifies:
        lines.append("_No unresolved `❓ CLARIFICATION NEEDED` markers > 7 days old._")
        lines.append("")
        return lines
    for c in report.clarifies:
        lines.append(f"- `{c.path}` — {c.age_days}d old (mtime {c.oldest_mtime.date().isoformat()})")
    lines.append("")
    return lines


def _render_stale_changes(report: LifecycleReport) -> list[str]:
    lines: list[str] = ["## Stale OpenSpec changes (>30 days, not archived)", ""]
    if not report.stale_changes:
        lines.append("_No stale OpenSpec changes._")
        lines.append("")
        return lines
    for s in report.stale_changes:
        lines.append(f"- `{s.change_id}` — {s.age_days}d old ({s.path})")
    lines.append("")
    return lines


def _render_memory_decay(report: LifecycleReport) -> list[str]:
    lines: list[str] = ["## Memory decay candidates", ""]
    lines.append(
        f"{report.memory_decay_count} `hindsight.retain` events older than "
        f"{MEMORY_DECAY_DAYS} days — consider a decay sweep."
    )
    lines.append("")
    return lines


def _render_migrations(report: LifecycleReport) -> list[str]:
    lines: list[str] = ["## Pending v0→v1 migrations", ""]
    if not report.pending_migrations:
        lines.append("_No pending migrations in `~/.ai-playbook/migration-pending.log`._")
        lines.append("")
        return lines
    for m in report.pending_migrations:
        lines.append(f"- {m}")
    lines.append("")
    return lines


def _render_actions(report: LifecycleReport) -> list[str]:
    lines: list[str] = ["## Actions", ""]
    actions: list[str] = []
    for gate, n in report.systemic_gates:
        actions.append(
            f"- investigate: gate `{gate}` overridden {n}x in 30 days "
            f"(threshold {SYSTEMIC_OVERRIDE_THRESHOLD}) — calibrate or RFC."
        )
    for s in report.stale_changes:
        actions.append(
            f"- archive: OpenSpec change `{s.change_id}` is {s.age_days}d old and unarchived."
        )
    for c in report.clarifies:
        actions.append(
            f"- resolve: CLARIFY in `{c.path}` is {c.age_days}d old."
        )
    if report.memory_decay_count > 0:
        actions.append(
            f"- decay: sweep {report.memory_decay_count} stale `hindsight.retain` memories."
        )
    for m in report.pending_migrations:
        actions.append(f"- migrate: {m}")
    if not actions:
        actions.append("_No actions — lifecycle clean._")
    lines.extend(actions)
    lines.append("")
    return lines


def render_markdown(report: LifecycleReport) -> str:
    out: list[str] = []
    out.append(f"# Lifecycle report — {report.month}")
    out.append("")
    out.append(f"> Generated at {report.now.isoformat(timespec='seconds')}.")
    out.append("")
    out.extend(_render_break_glass(report))
    out.extend(_render_clarifies(report))
    out.extend(_render_stale_changes(report))
    out.extend(_render_memory_decay(report))
    out.extend(_render_migrations(report))
    out.append("## Systemic flags")
    out.append("")
    out.append(f"{report.systemic_count()} systemic finding(s).")
    out.append("")
    out.extend(_render_actions(report))
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def _previous_month(today: date) -> str:
    first_of_this_month = date(today.year, today.month, 1)
    last_prev = first_of_this_month - timedelta(days=1)
    return f"{last_prev.year:04d}-{last_prev.month:02d}"


def build_report(
    *,
    consumer_root: Path,
    month: str,
    now: datetime,
    migration_log: Path,
) -> LifecycleReport:
    overrides_log = consumer_root / ".ai-playbook" / "overrides.log"
    events_log = consumer_root / ".ai-playbook" / "events.jsonl"
    openspec_dir = consumer_root / "openspec"

    all_overrides = parse_overrides_log(overrides_log)
    recent_overrides = _filter_within_window(all_overrides, now=now, days=BREAK_GLASS_WINDOW_DAYS)
    systemic = _systemic_gates(recent_overrides)

    clarifies, stale = scan_openspec_changes(openspec_dir, now=now)
    decay = count_memory_decay_candidates(events_log, now=now)
    pending = read_migration_pending(migration_log)

    return LifecycleReport(
        month=month,
        now=now,
        overrides=recent_overrides,
        systemic_gates=systemic,
        clarifies=clarifies,
        stale_changes=stale,
        memory_decay_count=decay,
        pending_migrations=pending,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_migration_log() -> Path:
    return Path.home() / ".ai-playbook" / "migration-pending.log"


def _default_output(consumer_root: Path, month: str) -> Path:
    return consumer_root / "reports" / "lifecycle" / f"{month}.md"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lifecycle_check",
        description=(
            "Produce the monthly lifecycle report: break-glass summary, stale "
            "OpenSpec changes, unresolved CLARIFYs, memory decay, pending migrations."
        ),
    )
    parser.add_argument(
        "--month",
        default=None,
        help="Report month YYYY-MM (default: previous month).",
    )
    parser.add_argument(
        "--consumer-root",
        type=Path,
        default=None,
        help="Consumer repo root (default: cwd).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path (default: <consumer>/reports/lifecycle/<month>.md).",
    )
    parser.add_argument(
        "--migration-log",
        type=Path,
        default=None,
        help="Override the deprecation watcher log path.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the report to stdout; don't write.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any systemic finding is present.",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="Override 'now' as ISO datetime (testing hook).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)

    consumer_root = (args.consumer_root or Path.cwd()).expanduser().resolve()
    if not consumer_root.is_dir():
        print(f"❌ consumer root not found at {consumer_root}", file=sys.stderr)
        print("   FIX: pass --consumer-root=<valid path> or run from a consumer repo.",
              file=sys.stderr)
        print("   OVERRIDE: none", file=sys.stderr)
        return 2

    if args.now:
        parsed_now = _parse_iso_ts(args.now)
        now = parsed_now or datetime.now(UTC)
    else:
        now = datetime.now(UTC)

    month = args.month or _previous_month(now.date())
    migration_log = args.migration_log or _default_migration_log()

    report = build_report(
        consumer_root=consumer_root,
        month=month,
        now=now,
        migration_log=migration_log,
    )
    body = render_markdown(report)

    if args.dry_run:
        sys.stdout.write(body)
    else:
        output_path = args.output or _default_output(consumer_root, month)
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(body, encoding="utf-8")
        except OSError as exc:
            print(f"❌ cannot write lifecycle report: {exc}", file=sys.stderr)
            print(f"   FIX: check write permissions for {output_path.parent}.",
                  file=sys.stderr)
            print("   OVERRIDE: none", file=sys.stderr)
            return 2
        print(f"✅ lifecycle report written: {output_path}", file=sys.stderr)

    if args.strict and report.systemic_count() > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
