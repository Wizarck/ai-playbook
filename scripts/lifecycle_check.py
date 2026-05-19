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
  (see ``docs/concepts/migration-guide.md``).

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

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover — playbook ships PyYAML in dev deps
    yaml = None  # the activation-trigger detectors short-circuit if yaml absent

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

# Activation-trigger detectors (Phase 5 P5.6 / P5.7 — see
# docs/concepts/incident-response.md §2 and docs/concepts/model-migration.md §2).
PAYING_CLIENT_RECENCY_DAYS = 30  # sla_signed within last N days fires the trigger
MODEL_RETIREMENT_HORIZON_DAYS = 90  # retirement within N days fires the trigger


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
class PayingClientFinding:
    """`first_paying_client_detected` row.

    Fires when a `consumers.yaml` entry has both `paying_tier` AND `sla_signed`
    set within the last `PAYING_CLIENT_RECENCY_DAYS` (default 30) days.
    """
    consumer_id: str
    paying_tier: str
    sla_signed: date
    days_since_signed: int


@dataclass
class ModelRetirementFinding:
    """`model_retirement_detected` row.

    Fires when an entry in `configs/anthropic-retirement-list.yaml` has a
    `retirement_date` within `MODEL_RETIREMENT_HORIZON_DAYS` (default 90).
    """
    model_id: str
    provider: str
    retirement_date: date
    days_remaining: int
    successor: str
    deprecation_url: str


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
    paying_clients: list[PayingClientFinding] = field(default_factory=list)
    model_retirements: list[ModelRetirementFinding] = field(default_factory=list)

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


def scan_openspec_changes(
    openspec_dir: Path, *, now: datetime,
) -> tuple[list[ClarifyFinding], list[StaleChangeFinding]]:
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
# Activation triggers — first_paying_client_detected, model_retirement_detected
# ---------------------------------------------------------------------------


def _coerce_date(value: object) -> date | None:
    """Accept date or ISO string; return None on anything else."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def scan_paying_clients(
    consumers_yaml_path: Path, *, now: datetime,
) -> list[PayingClientFinding]:
    """Scan a `consumers.yaml` for `paying_tier` + `sla_signed` rows.

    Returns rows where `sla_signed` is within `PAYING_CLIENT_RECENCY_DAYS`
    days of `now`. Empty list when the file is absent, malformed, or the
    fields are not yet populated (the solo-state default).
    """
    if yaml is None or not consumers_yaml_path.is_file():
        return []
    try:
        text = consumers_yaml_path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(data, dict):
        return []

    consumers = data.get("consumers") or {}
    if not isinstance(consumers, dict):
        return []

    findings: list[PayingClientFinding] = []
    cutoff_days = PAYING_CLIENT_RECENCY_DAYS
    today = now.date()
    for consumer_id, entry in consumers.items():
        if not isinstance(entry, dict):
            continue
        tier = entry.get("paying_tier")
        signed_raw = entry.get("sla_signed")
        if not tier or not signed_raw:
            continue
        signed = _coerce_date(signed_raw)
        if signed is None:
            continue
        delta = (today - signed).days
        if delta < 0 or delta > cutoff_days:
            # Future-dated SLA or older than recency window — both not the trigger.
            continue
        findings.append(
            PayingClientFinding(
                consumer_id=str(consumer_id),
                paying_tier=str(tier),
                sla_signed=signed,
                days_since_signed=delta,
            )
        )
    findings.sort(key=lambda f: (f.days_since_signed, f.consumer_id))
    return findings


def scan_model_retirements(
    retirement_yaml_path: Path,
    *,
    now: datetime,
    horizon_days: int = MODEL_RETIREMENT_HORIZON_DAYS,
) -> list[ModelRetirementFinding]:
    """Scan a `configs/anthropic-retirement-list.yaml` for upcoming retirements.

    Returns entries with `retirement_date - now <= horizon_days`. Entries with
    `retirement_date` in the past are also returned (operator must take action).
    Entries far in the future are silently dropped.
    """
    if yaml is None or not retirement_yaml_path.is_file():
        return []
    try:
        text = retirement_yaml_path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(data, dict):
        return []

    retirements = data.get("retirements") or []
    if not isinstance(retirements, list):
        return []

    findings: list[ModelRetirementFinding] = []
    today = now.date()
    for entry in retirements:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("model_id")
        retirement_raw = entry.get("retirement_date")
        successor = entry.get("successor", "")
        provider = entry.get("provider", "")
        url = entry.get("deprecation_url", "")
        if not model_id or not retirement_raw:
            continue
        retirement_date = _coerce_date(retirement_raw)
        if retirement_date is None:
            continue
        days_remaining = (retirement_date - today).days
        if days_remaining > horizon_days:
            # Retirement still beyond horizon — not yet a trigger.
            continue
        findings.append(
            ModelRetirementFinding(
                model_id=str(model_id),
                provider=str(provider),
                retirement_date=retirement_date,
                days_remaining=days_remaining,
                successor=str(successor),
                deprecation_url=str(url),
            )
        )
    findings.sort(key=lambda f: (f.days_remaining, f.model_id))
    return findings


# ---------------------------------------------------------------------------
# Trigger-state idempotency — ~/.ai-playbook/state/triggers.json
# ---------------------------------------------------------------------------


def default_trigger_state_path() -> Path:
    return Path.home() / ".ai-playbook" / "state" / "triggers.json"


def load_trigger_state(path: Path) -> dict[str, object]:
    """Load the trigger-state file. Returns {} if absent or malformed."""
    if not path.is_file():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_trigger_state(path: Path, state: dict[str, object]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, sort_keys=True, default=str),
                        encoding="utf-8")
    except OSError:
        # State persistence is best-effort — a write failure does not abort the
        # report. The cost is a duplicated notification on the next run.
        pass


def select_new_paying_clients(
    findings: list[PayingClientFinding], *, state: dict[str, object],
) -> list[PayingClientFinding]:
    """Return findings whose `consumer_id` is not in state['paying_clients']."""
    seen = set()
    raw = state.get("paying_clients")
    if isinstance(raw, list):
        seen = {str(x) for x in raw}
    return [f for f in findings if f.consumer_id not in seen]


def select_new_model_retirements(
    findings: list[ModelRetirementFinding], *, state: dict[str, object],
) -> list[ModelRetirementFinding]:
    """Return findings whose `model_id` is not in state['model_retirements']."""
    seen = set()
    raw = state.get("model_retirements")
    if isinstance(raw, list):
        seen = {str(x) for x in raw}
    return [f for f in findings if f.model_id not in seen]


def record_trigger_state(
    state: dict[str, object],
    *,
    paying: list[PayingClientFinding],
    retirements: list[ModelRetirementFinding],
) -> dict[str, object]:
    """Return new state dict with `paying` + `retirements` IDs accumulated."""
    out = dict(state)
    seen_paying = set()
    raw_paying = out.get("paying_clients")
    if isinstance(raw_paying, list):
        seen_paying = {str(x) for x in raw_paying}
    seen_paying.update(f.consumer_id for f in paying)
    out["paying_clients"] = sorted(seen_paying)

    seen_models = set()
    raw_models = out.get("model_retirements")
    if isinstance(raw_models, list):
        seen_models = {str(x) for x in raw_models}
    seen_models.update(f.model_id for f in retirements)
    out["model_retirements"] = sorted(seen_models)
    return out


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


def _render_triggers(report: LifecycleReport) -> list[str]:
    lines: list[str] = ["## Activation triggers", ""]
    if not report.paying_clients and not report.model_retirements:
        lines.append("_No activation triggers detected (`first_paying_client_detected`, "
                     "`model_retirement_detected`)._")
        lines.append("")
        return lines

    if report.paying_clients:
        lines.append("### `first_paying_client_detected`")
        lines.append("")
        lines.append("| consumer | tier | sla_signed | days_since | action |")
        lines.append("|---|---|---|---|---|")
        for f in report.paying_clients:
            lines.append(
                f"| `{f.consumer_id}` | {f.paying_tier} | {f.sla_signed.isoformat()} "
                f"| {f.days_since_signed} | flip `enforcement-status.md` row "
                f"`incident-response.md` from `wired-pending-trigger` to ✅ |"
            )
        lines.append("")

    if report.model_retirements:
        lines.append("### `model_retirement_detected`")
        lines.append("")
        lines.append("| model | provider | retirement_date | days_remaining | successor | url |")
        lines.append("|---|---|---|---|---|---|")
        for f in report.model_retirements:
            url = f.deprecation_url or "—"
            lines.append(
                f"| `{f.model_id}` | {f.provider} | {f.retirement_date.isoformat()} "
                f"| {f.days_remaining} | `{f.successor or '—'}` | {url} |"
            )
        lines.append("")
        lines.append("Recommended next step: `MODEL_MIGRATION_REQUESTED=<from>:<to>` "
                     "then `python -m scripts.simulate_model_migration` "
                     "(see `docs/concepts/model-migration.md` §3).")
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
    for f in report.paying_clients:
        actions.append(
            f"- activate-IR: paying tier `{f.paying_tier}` for `{f.consumer_id}` "
            f"signed {f.days_since_signed}d ago — flip "
            f"`enforcement-status.md::incident-response.md` to ✅."
        )
    for f in report.model_retirements:
        urgency = "OVERDUE" if f.days_remaining < 0 else f"{f.days_remaining}d"
        actions.append(
            f"- model-migration: `{f.model_id}` retires {f.retirement_date.isoformat()} "
            f"({urgency}) — set `MODEL_MIGRATION_REQUESTED={f.model_id}:"
            f"{f.successor or '<successor>'}` and run "
            f"`python -m scripts.simulate_model_migration`."
        )
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
    out.extend(_render_triggers(report))
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
    consumers_yaml: Path | None = None,
    retirement_yaml: Path | None = None,
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

    paying = scan_paying_clients(consumers_yaml, now=now) if consumers_yaml else []
    retirements = (
        scan_model_retirements(retirement_yaml, now=now) if retirement_yaml else []
    )

    return LifecycleReport(
        month=month,
        now=now,
        overrides=recent_overrides,
        systemic_gates=systemic,
        clarifies=clarifies,
        stale_changes=stale,
        memory_decay_count=decay,
        pending_migrations=pending,
        paying_clients=paying,
        model_retirements=retirements,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_migration_log() -> Path:
    return Path.home() / ".ai-playbook" / "migration-pending.log"


def _default_output(consumer_root: Path, month: str) -> Path:
    return consumer_root / "reports" / "lifecycle" / f"{month}.md"


def _default_consumers_yaml(consumer_root: Path) -> Path:
    """consumers.yaml lives at the playbook root; consumer mirrors it via submodule."""
    candidate = consumer_root / ".ai-playbook" / "consumers.yaml"
    if candidate.is_file():
        return candidate
    # Running from the playbook itself — `consumer_root` IS the playbook.
    return consumer_root / "consumers.yaml"


def _default_retirement_yaml(consumer_root: Path) -> Path:
    candidate = consumer_root / ".ai-playbook" / "configs" / "anthropic-retirement-list.yaml"
    if candidate.is_file():
        return candidate
    return consumer_root / "configs" / "anthropic-retirement-list.yaml"


def _emit_trigger_notifications(
    report: LifecycleReport,
    *,
    state: dict[str, object],
) -> None:
    """Fire notifications for activation triggers seen for the FIRST time.

    Uses `~/.ai-playbook/state/triggers.json` to dedupe across runs. Best-effort
    — if the notify import or the state file IO fails, we silently swallow.
    Subsequent runs may re-emit; that is the documented degraded behavior.
    """
    new_paying = select_new_paying_clients(report.paying_clients, state=state)
    new_retirements = select_new_model_retirements(report.model_retirements, state=state)
    if not new_paying and not new_retirements:
        return

    try:  # local import — keeps module import cheap and avoids cycles in tests
        from . import notify as _notify  # type: ignore[import-not-found]
    except ImportError:
        try:
            import notify as _notify  # type: ignore[import-not-found]
        except ImportError:
            return

    for f in new_paying:
        try:
            _notify.notify(
                event="lifecycle.first_paying_client_detected",
                severity="notice",
                summary=(
                    f"first paying tier `{f.paying_tier}` consumer "
                    f"`{f.consumer_id}` signed {f.days_since_signed}d ago"
                ),
                detail=(
                    "Recommend flipping enforcement-status.md row "
                    "incident-response.md from wired-pending-trigger to ✅."
                ),
                attrs={
                    "ai_playbook.trigger.kind": "first_paying_client_detected",
                    "ai_playbook.trigger.consumer_id": f.consumer_id,
                    "ai_playbook.trigger.paying_tier": f.paying_tier,
                    "ai_playbook.trigger.sla_signed": f.sla_signed.isoformat(),
                },
            )
        except Exception:  # noqa: BLE001 — notify must never break the report
            pass

    for f in new_retirements:
        try:
            _notify.notify(
                event="lifecycle.model_retirement_detected",
                severity="warn",
                summary=(
                    f"model `{f.model_id}` retires {f.retirement_date.isoformat()} "
                    f"({f.days_remaining}d remaining)"
                ),
                detail=(
                    f"Set MODEL_MIGRATION_REQUESTED={f.model_id}:"
                    f"{f.successor or '<successor>'} and run "
                    "`python -m scripts.simulate_model_migration`."
                ),
                attrs={
                    "ai_playbook.trigger.kind": "model_retirement_detected",
                    "ai_playbook.trigger.model_id": f.model_id,
                    "ai_playbook.trigger.provider": f.provider,
                    "ai_playbook.trigger.retirement_date": f.retirement_date.isoformat(),
                    "ai_playbook.trigger.days_remaining": f.days_remaining,
                    "ai_playbook.trigger.successor": f.successor,
                    "ai_playbook.trigger.deprecation_url": f.deprecation_url,
                },
            )
        except Exception:  # noqa: BLE001
            pass


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
        "--consumers-yaml",
        type=Path,
        default=None,
        help=(
            "Override the consumers.yaml path used by `first_paying_client_detected`. "
            "Default: <consumer>/.ai-playbook/consumers.yaml or <consumer>/consumers.yaml."
        ),
    )
    parser.add_argument(
        "--retirement-yaml",
        type=Path,
        default=None,
        help=(
            "Override the anthropic-retirement-list.yaml path used by "
            "`model_retirement_detected`. Default: <consumer>/.ai-playbook/configs/"
            "anthropic-retirement-list.yaml or <consumer>/configs/...yaml."
        ),
    )
    parser.add_argument(
        "--trigger-state",
        type=Path,
        default=None,
        help=(
            "Override the trigger-idempotency state file. Default: "
            "~/.ai-playbook/state/triggers.json."
        ),
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Skip notification emission for activation triggers (testing only).",
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
    consumers_yaml = args.consumers_yaml or _default_consumers_yaml(consumer_root)
    retirement_yaml = args.retirement_yaml or _default_retirement_yaml(consumer_root)
    trigger_state_path = args.trigger_state or default_trigger_state_path()

    report = build_report(
        consumer_root=consumer_root,
        month=month,
        now=now,
        migration_log=migration_log,
        consumers_yaml=consumers_yaml,
        retirement_yaml=retirement_yaml,
    )

    # Trigger notifications + state persistence (idempotent across runs).
    state = load_trigger_state(trigger_state_path)
    if not args.no_notify and not args.dry_run:
        _emit_trigger_notifications(report, state=state)
    new_state = record_trigger_state(
        state,
        paying=report.paying_clients,
        retirements=report.model_retirements,
    )
    if not args.dry_run:
        save_trigger_state(trigger_state_path, new_state)

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
