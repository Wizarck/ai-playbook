"""Unified telemetry report (Slice 6, v0.18.2).

Absorbs five standalone CLIs:

- scripts/cost_report.py             → _compute_cost_per_*()
- scripts/lifecycle_check.py         → _check_retirement_window(), _check_openspec_staleness()
- scripts/budget_disable_check.py    → _check_budget_breach()
- scripts/deprecation_watcher.py     → _check_v0_schema_drift(), _check_openspec_staleness()
- scripts/simulate_model_migration.py → _simulate_model_migration()

CLI:

    python -m scripts.telemetry.report monthly
    python -m scripts.telemetry.report weekly  --json
    python -m scripts.telemetry.report custom  --window-days 14
    python -m scripts.telemetry.report custom  --window-days 30 --json

The report reads from `<state-dir>/rule-events.jsonl` (gitignored at the
consumer). Empty / missing log returns exit 0 with a graceful zero-data report.

Sections:

1. Obey-rate per rule × LLM
2. Cost per rule-fire (uses configs/pricing.yaml)
3. Cost per session (aggregated by session_id_hash)
4. Total spend over time (per-day buckets)
5. Models nearing retirement (uses configs/anthropic-retirement-list.yaml)
6. Break-glass usage (escape_hatch events)
7. OpenSpec staleness (proposals not advancing within N days)
8. Memory decay (stub — full implementation deferred to Slice 7)

All eight sections render even on zero data, with explicit "no events" copy.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover — pyyaml ships in dev deps.
    yaml = None  # type: ignore[assignment]

from .rule_event_logger import EVENTS_FILENAME, resolve_state_dir

# UTF-8 stdio for Windows cp1252 consoles.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PRICING_PATH = REPO_ROOT / "configs" / "pricing.yaml"
DEFAULT_RETIREMENT_PATH = REPO_ROOT / "configs" / "anthropic-retirement-list.yaml"
DEFAULT_OPENSPEC_DIR = REPO_ROOT / "openspec" / "changes"
MODEL_RETIREMENT_HORIZON_DAYS = 90
STALE_OPENSPEC_DAYS = 30
MEMORY_DECAY_DAYS = 90
BUDGET_FLAG_DIR_DEFAULT = "/var/lib/consumer-d"


# ---------------------------------------------------------------------------
# Canonical error emission (error-message-standard.rule.md)
# ---------------------------------------------------------------------------


def _emit_error(*, why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


# ---------------------------------------------------------------------------
# Pricing catalog (absorbed from cost_report.py)
# ---------------------------------------------------------------------------


@dataclass
class PricingCatalog:
    rows: dict[str, dict[str, float]] = field(default_factory=dict)
    loaded: bool = False
    source: Path | None = None

    def cost_for(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
    ) -> float | None:
        if not self.loaded:
            return None
        row = self.rows.get(model)
        if not row:
            return None
        return (
            (input_tokens / 1000.0) * row.get("input_per_1k", 0.0)
            + (output_tokens / 1000.0) * row.get("output_per_1k", 0.0)
            + (cache_read_tokens / 1000.0) * row.get("cache_read_per_1k", 0.0)
        )


def load_pricing(path: Path) -> PricingCatalog:
    if not path.is_file() or yaml is None:
        return PricingCatalog()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return PricingCatalog(loaded=False, source=path)
    if not isinstance(data, dict):
        return PricingCatalog(loaded=False, source=path)
    rows: dict[str, dict[str, float]] = {}
    for k, v in data.items():
        if isinstance(v, dict):
            rows[str(k)] = {
                str(kk): float(vv)
                for kk, vv in v.items()
                if isinstance(vv, (int, float))
            }
    return PricingCatalog(rows=rows, loaded=bool(rows), source=path)


# ---------------------------------------------------------------------------
# Event loading
# ---------------------------------------------------------------------------


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    s = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def load_events(path: Path) -> list[dict[str, Any]]:
    """Load events from a JSONL file. Skip malformed lines silently."""
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    print(f"warn: malformed JSONL line skipped in {path}", file=sys.stderr)
                    continue
                if isinstance(obj, dict):
                    events.append(obj)
    except OSError:
        return []
    return events


def filter_by_window(
    events: list[dict[str, Any]], *, since: datetime
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in events:
        ts = _parse_ts(ev.get("timestamp") or ev.get("ts"))
        if ts is None or ts >= since:
            out.append(ev)
    return out


# ---------------------------------------------------------------------------
# Compute helpers
# ---------------------------------------------------------------------------


def compute_obey_rate(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per (slug, llm): allow / block / warn counts and obey_rate."""
    buckets: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for ev in events:
        slug = str(ev.get("slug") or "unknown")
        llm = str(ev.get("llm") or ev.get("model") or "unknown")
        verdict = str(ev.get("verdict") or "allow")
        buckets[(slug, llm)][verdict] += 1
    rows: list[dict[str, Any]] = []
    for (slug, llm), counts in sorted(buckets.items()):
        total = sum(counts.values())
        allow = counts.get("allow", 0)
        block = counts.get("block", 0)
        warn = counts.get("warn", 0)
        obey_rate = (allow / total) if total else 1.0
        rows.append(
            {
                "slug": slug,
                "llm": llm,
                "total": total,
                "allow": allow,
                "block": block,
                "warn": warn,
                "obey_rate": round(obey_rate, 4),
            }
        )
    return rows


def compute_cost_per_rule(
    events: list[dict[str, Any]], pricing: PricingCatalog
) -> list[dict[str, Any]]:
    """Per slug: aggregate token spend + cost using pricing catalog."""
    if not pricing.loaded:
        return []
    buckets: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "fires": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "cache_read_tokens": 0,
            "cost_usd": 0.0,
        }
    )
    for ev in events:
        if "tokens_in" not in ev and "tokens_out" not in ev:
            continue
        slug = str(ev.get("slug") or "unknown")
        model = str(ev.get("model") or ev.get("llm") or "")
        ti = int(ev.get("tokens_in") or 0)
        to = int(ev.get("tokens_out") or 0)
        cr = int(ev.get("cache_read_tokens") or 0)
        cost = pricing.cost_for(
            model=model,
            input_tokens=ti,
            output_tokens=to,
            cache_read_tokens=cr,
        )
        row = buckets[slug]
        row["fires"] += 1
        row["tokens_in"] += ti
        row["tokens_out"] += to
        row["cache_read_tokens"] += cr
        if cost is not None:
            row["cost_usd"] += cost
    out: list[dict[str, Any]] = []
    for slug, row in sorted(buckets.items()):
        out.append(
            {
                "slug": slug,
                "fires": int(row["fires"]),
                "tokens_in": int(row["tokens_in"]),
                "tokens_out": int(row["tokens_out"]),
                "cache_read_tokens": int(row["cache_read_tokens"]),
                "cost_usd": round(row["cost_usd"], 4),
            }
        )
    return out


def compute_cost_per_session(
    events: list[dict[str, Any]], pricing: PricingCatalog
) -> list[dict[str, Any]]:
    if not pricing.loaded:
        return []
    buckets: dict[str, dict[str, float]] = defaultdict(
        lambda: {"events": 0, "cost_usd": 0.0}
    )
    for ev in events:
        if "tokens_in" not in ev and "tokens_out" not in ev:
            continue
        sid = str(ev.get("session_id_hash") or "unknown")
        model = str(ev.get("model") or ev.get("llm") or "")
        ti = int(ev.get("tokens_in") or 0)
        to = int(ev.get("tokens_out") or 0)
        cr = int(ev.get("cache_read_tokens") or 0)
        cost = pricing.cost_for(
            model=model, input_tokens=ti, output_tokens=to, cache_read_tokens=cr
        )
        row = buckets[sid]
        row["events"] += 1
        if cost is not None:
            row["cost_usd"] += cost
    return [
        {"session_id_hash": sid, "events": int(r["events"]), "cost_usd": round(r["cost_usd"], 4)}
        for sid, r in sorted(buckets.items(), key=lambda x: -x[1]["cost_usd"])
    ]


def compute_spend_over_time(
    events: list[dict[str, Any]], pricing: PricingCatalog
) -> list[dict[str, Any]]:
    if not pricing.loaded:
        return []
    buckets: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for ev in events:
        ts = _parse_ts(ev.get("timestamp"))
        if ts is None:
            continue
        if "tokens_in" not in ev and "tokens_out" not in ev:
            continue
        day = ts.date().isoformat()
        model = str(ev.get("model") or ev.get("llm") or "")
        cost = pricing.cost_for(
            model=model,
            input_tokens=int(ev.get("tokens_in") or 0),
            output_tokens=int(ev.get("tokens_out") or 0),
            cache_read_tokens=int(ev.get("cache_read_tokens") or 0),
        )
        counts[day] += 1
        if cost is not None:
            buckets[day] += cost
    return [
        {"day": day, "events": counts[day], "cost_usd": round(buckets[day], 4)}
        for day in sorted(buckets)
    ]


def compute_break_glass_usage(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    total = 0
    for ev in events:
        eh = ev.get("escape_hatch")
        if not eh:
            continue
        counts[str(eh)] += 1
        total += 1
    rows = [{"escape_hatch": k, "count": v} for k, v in counts.most_common()]
    return rows


# ---------------------------------------------------------------------------
# Absorbed: lifecycle_check — model retirements
# ---------------------------------------------------------------------------


def check_retirement_window(
    retirement_yaml_path: Path = DEFAULT_RETIREMENT_PATH,
    *,
    now: datetime | None = None,
    horizon_days: int = MODEL_RETIREMENT_HORIZON_DAYS,
) -> list[dict[str, Any]]:
    if yaml is None or not retirement_yaml_path.is_file():
        return []
    try:
        data = yaml.safe_load(retirement_yaml_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(data, dict):
        return []
    items = data.get("retirements") or []
    if not isinstance(items, list):
        return []
    today = (now or datetime.now(UTC)).date()
    findings: list[dict[str, Any]] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("model_id")
        ret_raw = entry.get("retirement_date")
        if not model_id or not ret_raw:
            continue
        try:
            if isinstance(ret_raw, date):
                ret_date = ret_raw
            else:
                ret_date = date.fromisoformat(str(ret_raw))
        except ValueError:
            continue
        days_remaining = (ret_date - today).days
        if days_remaining > horizon_days:
            continue
        findings.append(
            {
                "model_id": str(model_id),
                "provider": str(entry.get("provider", "")),
                "retirement_date": ret_date.isoformat(),
                "days_remaining": days_remaining,
                "successor": str(entry.get("successor", "")),
                "deprecation_url": str(entry.get("deprecation_url", "")),
            }
        )
    findings.sort(key=lambda f: (f["days_remaining"], f["model_id"]))
    return findings


# ---------------------------------------------------------------------------
# Absorbed: budget_disable_check
# ---------------------------------------------------------------------------


def _budget_flag_path(provider: str, flag_dir: str | None = None) -> Path:
    base = flag_dir or os.environ.get("CONSUMER_D_FLAG_DIR", BUDGET_FLAG_DIR_DEFAULT)
    return Path(base) / f"budget-disabled-{provider}.flag"


def check_budget_breach(
    providers: Iterable[str], *, flag_dir: str | None = None
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for prov in providers:
        rows.append(
            {
                "provider": prov,
                "disabled": _budget_flag_path(prov, flag_dir).is_file(),
            }
        )
    return rows


def is_budget_disabled(provider: str, flag_dir: str | None = None) -> bool:
    """Library-shaped helper preserved from budget_disable_check.py."""
    return _budget_flag_path(provider, flag_dir).is_file()


# ---------------------------------------------------------------------------
# Absorbed: lifecycle_check + deprecation_watcher — OpenSpec staleness
# ---------------------------------------------------------------------------


def check_openspec_staleness(
    openspec_dir: Path = DEFAULT_OPENSPEC_DIR,
    *,
    now: datetime | None = None,
    stale_days: int = STALE_OPENSPEC_DAYS,
) -> list[dict[str, Any]]:
    if not openspec_dir.is_dir():
        return []
    now = now or datetime.now(UTC)
    findings: list[dict[str, Any]] = []
    for child in sorted(openspec_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name in {"_template", "archive"}:
            continue
        if (child / "archive").is_dir():
            continue
        oldest_mtime: datetime | None = None
        for p in child.rglob("*"):
            if not p.is_file():
                continue
            try:
                m = datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)
            except OSError:
                continue
            if oldest_mtime is None or m < oldest_mtime:
                oldest_mtime = m
        if oldest_mtime is None:
            continue
        age_days = (now - oldest_mtime).days
        if age_days > stale_days:
            findings.append(
                {
                    "change_id": child.name,
                    "path": str(child),
                    "age_days": age_days,
                    "oldest_mtime": oldest_mtime.date().isoformat(),
                }
            )
    findings.sort(key=lambda f: -f["age_days"])
    return findings


# ---------------------------------------------------------------------------
# Memory decay (Slice 7 will flesh out; stub returns placeholder)
# ---------------------------------------------------------------------------


def check_memory_decay(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Stub. Slice 7 will hindsight-walk; for now we report a TODO marker."""
    return {
        "status": "deferred-to-slice-7",
        "candidates": 0,
        "note": (
            "Memory-decay scan is a Slice 7 deliverable. The metric is "
            "computable from hindsight.retain events older than 90 days but "
            "the implementation is intentionally a stub in v0.18.2."
        ),
    }


# ---------------------------------------------------------------------------
# Absorbed: simulate_model_migration — dry-run walker
# ---------------------------------------------------------------------------


def simulate_model_migration(
    *,
    from_model: str | None = None,
    to_model: str | None = None,
    retirement_yaml_path: Path = DEFAULT_RETIREMENT_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Dry-run model migration. Returns a JSON-shaped result dict.

    Trigger source: explicit `from_model:to_model`, OR env var
    `MODEL_MIGRATION_REQUESTED=<from>:<to>`, OR the first qualifying entry
    from `configs/anthropic-retirement-list.yaml`.
    """
    if from_model is None or to_model is None:
        env = os.environ.get("MODEL_MIGRATION_REQUESTED", "")
        if env and ":" in env:
            from_model, to_model = env.split(":", 1)
    if from_model is None or to_model is None:
        retirements = check_retirement_window(retirement_yaml_path, now=now)
        if not retirements:
            return {"status": "no-trigger", "from": None, "to": None}
        from_model = retirements[0]["model_id"]
        to_model = retirements[0]["successor"] or "unknown"
    return {
        "status": "simulated",
        "from": from_model,
        "to": to_model,
        "note": "Dry-run only. No git diff, no PR. Replace successor manually.",
    }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@dataclass
class Report:
    window_days: int
    since: datetime
    until: datetime
    events_path: Path
    events_count: int
    obey_rate: list[dict[str, Any]]
    cost_per_rule: list[dict[str, Any]]
    cost_per_session: list[dict[str, Any]]
    spend_over_time: list[dict[str, Any]]
    retirements: list[dict[str, Any]]
    budget_breach: list[dict[str, Any]]
    openspec_staleness: list[dict[str, Any]]
    break_glass_usage: list[dict[str, Any]]
    memory_decay: dict[str, Any]
    pricing_loaded: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_days": self.window_days,
            "since": self.since.isoformat(),
            "until": self.until.isoformat(),
            "events_path": str(self.events_path),
            "events_count": self.events_count,
            "pricing_loaded": self.pricing_loaded,
            "obey_rate": self.obey_rate,
            "cost_per_rule": self.cost_per_rule,
            "cost_per_session": self.cost_per_session,
            "spend_over_time": self.spend_over_time,
            "retirements": self.retirements,
            "budget_breach": self.budget_breach,
            "openspec_staleness": self.openspec_staleness,
            "break_glass_usage": self.break_glass_usage,
            "memory_decay": self.memory_decay,
        }


def render_markdown(report: Report) -> str:
    lines: list[str] = []
    lines.append(f"# Telemetry report — last {report.window_days} days")
    lines.append("")
    lines.append(
        f"> Window: {report.since.date().isoformat()} → {report.until.date().isoformat()}"
    )
    lines.append(f"> Events file: `{report.events_path}` (count: {report.events_count})")
    lines.append(f"> Pricing loaded: {'yes' if report.pricing_loaded else 'no'}")
    lines.append("")

    # 1. Obey rate
    lines.append("## 1. Obey rate (per rule × LLM)")
    lines.append("")
    if not report.obey_rate:
        lines.append("_No rule-event data in window._")
    else:
        lines.append("| slug | llm | total | allow | block | warn | obey_rate |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in report.obey_rate:
            lines.append(
                f"| `{r['slug']}` | `{r['llm']}` | {r['total']} | {r['allow']} | "
                f"{r['block']} | {r['warn']} | {r['obey_rate']:.2%} |"
            )
    lines.append("")

    # 2. Cost per rule
    lines.append("## 2. Cost per rule-fire")
    lines.append("")
    if not report.pricing_loaded:
        lines.append("_Pricing catalog not loaded — see `configs/pricing.yaml`._")
    elif not report.cost_per_rule:
        lines.append("_No cost-bearing events in window._")
    else:
        lines.append("| slug | fires | tokens_in | tokens_out | cache_read | cost_usd |")
        lines.append("|---|---|---|---|---|---|")
        for r in report.cost_per_rule:
            lines.append(
                f"| `{r['slug']}` | {r['fires']} | {r['tokens_in']} | "
                f"{r['tokens_out']} | {r['cache_read_tokens']} | "
                f"${r['cost_usd']:.4f} |"
            )
    lines.append("")

    # 3. Cost per session
    lines.append("## 3. Cost per session")
    lines.append("")
    if not report.cost_per_session:
        lines.append("_No session-level cost data in window._")
    else:
        lines.append("| session_id_hash | events | cost_usd |")
        lines.append("|---|---|---|")
        for r in report.cost_per_session:
            lines.append(
                f"| `{r['session_id_hash']}` | {r['events']} | ${r['cost_usd']:.4f} |"
            )
    lines.append("")

    # 4. Spend over time
    lines.append("## 4. Total spend over time")
    lines.append("")
    if not report.spend_over_time:
        lines.append("_No spend data in window._")
    else:
        lines.append("| day | events | cost_usd |")
        lines.append("|---|---|---|")
        for r in report.spend_over_time:
            lines.append(f"| {r['day']} | {r['events']} | ${r['cost_usd']:.4f} |")
    lines.append("")

    # 5. Retirements
    lines.append("## 5. Models nearing retirement")
    lines.append("")
    if not report.retirements:
        lines.append("_No model retirements within horizon._")
    else:
        lines.append("| model | retirement_date | days_remaining | successor |")
        lines.append("|---|---|---|---|")
        for r in report.retirements:
            lines.append(
                f"| `{r['model_id']}` | {r['retirement_date']} | "
                f"{r['days_remaining']} | `{r['successor'] or '—'}` |"
            )
    lines.append("")

    # 6. Break-glass
    lines.append("## 6. Break-glass usage")
    lines.append("")
    if not report.break_glass_usage:
        lines.append("_No escape-hatch usage in window._")
    else:
        total_eh = sum(r["count"] for r in report.break_glass_usage)
        total_evt = max(report.events_count, 1)
        ratio = total_eh / total_evt
        flag = " **(systemic — >20%)**" if ratio > 0.2 else ""
        lines.append(
            f"Total escape-hatch fires: {total_eh} "
            f"({ratio:.1%} of all events){flag}"
        )
        lines.append("")
        lines.append("| escape_hatch | count |")
        lines.append("|---|---|")
        for r in report.break_glass_usage:
            lines.append(f"| `{r['escape_hatch']}` | {r['count']} |")
    lines.append("")

    # 7. OpenSpec staleness
    lines.append("## 7. OpenSpec staleness")
    lines.append("")
    if not report.openspec_staleness:
        lines.append("_No stale OpenSpec changes (>30 days, not archived)._")
    else:
        lines.append("| change_id | age_days | oldest_mtime |")
        lines.append("|---|---|---|")
        for r in report.openspec_staleness:
            lines.append(
                f"| `{r['change_id']}` | {r['age_days']} | {r['oldest_mtime']} |"
            )
    lines.append("")

    # 8. Memory decay
    lines.append("## 8. Memory decay")
    lines.append("")
    md = report.memory_decay
    lines.append(f"Status: `{md.get('status', 'unknown')}`")
    lines.append("")
    if md.get("note"):
        lines.append(md["note"])
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Build + CLI
# ---------------------------------------------------------------------------


def build_report(
    *,
    window_days: int,
    state_dir: Path | None = None,
    pricing_path: Path = DEFAULT_PRICING_PATH,
    retirement_path: Path = DEFAULT_RETIREMENT_PATH,
    openspec_dir: Path = DEFAULT_OPENSPEC_DIR,
    now: datetime | None = None,
    budget_providers: Iterable[str] = ("anthropic",),
) -> Report:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=window_days)
    events_path = resolve_state_dir(state_dir) / EVENTS_FILENAME
    all_events = load_events(events_path)
    in_window = filter_by_window(all_events, since=since)
    pricing = load_pricing(pricing_path)

    return Report(
        window_days=window_days,
        since=since,
        until=now,
        events_path=events_path,
        events_count=len(in_window),
        obey_rate=compute_obey_rate(in_window),
        cost_per_rule=compute_cost_per_rule(in_window, pricing),
        cost_per_session=compute_cost_per_session(in_window, pricing),
        spend_over_time=compute_spend_over_time(in_window, pricing),
        retirements=check_retirement_window(retirement_path, now=now),
        budget_breach=check_budget_breach(budget_providers),
        openspec_staleness=check_openspec_staleness(openspec_dir, now=now),
        break_glass_usage=compute_break_glass_usage(in_window),
        memory_decay=check_memory_decay(),
        pricing_loaded=pricing.loaded,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts.telemetry.report",
        description=(
            "Unified telemetry report (Slice 6, v0.18.2). "
            "Absorbs cost_report, lifecycle_check, budget_disable_check, "
            "deprecation_watcher, simulate_model_migration."
        ),
    )
    parser.add_argument(
        "subcommand",
        choices=["weekly", "monthly", "custom"],
        help="Reporting window: weekly (7d), monthly (30d), or custom (--window-days N).",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=None,
        help="Custom window in days (only meaningful with subcommand=custom).",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help=(
            "Override the state directory (default: $AI_PLAYBOOK_STATE_DIR "
            "or <cwd>/.ai-playbook-state/)."
        ),
    )
    parser.add_argument(
        "--pricing",
        type=Path,
        default=DEFAULT_PRICING_PATH,
        help=f"Pricing catalog YAML (default: {DEFAULT_PRICING_PATH}).",
    )
    parser.add_argument(
        "--retirement",
        type=Path,
        default=DEFAULT_RETIREMENT_PATH,
        help=f"Retirement YAML (default: {DEFAULT_RETIREMENT_PATH}).",
    )
    parser.add_argument(
        "--openspec-dir",
        type=Path,
        default=DEFAULT_OPENSPEC_DIR,
        help=f"OpenSpec changes dir (default: {DEFAULT_OPENSPEC_DIR}).",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit JSON instead of markdown.",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="Override `now` (ISO datetime, testing only).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "weekly":
        window = 7
    elif args.subcommand == "monthly":
        window = 30
    else:  # custom
        if args.window_days is None or args.window_days <= 0:
            _emit_error(
                why="custom subcommand requires --window-days N (N > 0)",
                where="scripts.telemetry.report:custom",
                fix="pass --window-days 14 (or another positive integer).",
            )
            return 1
        window = int(args.window_days)

    now = None
    if args.now:
        now = _parse_ts(args.now) or _parse_ts(args.now + "Z")
        if now is None:
            _emit_error(
                why=f"invalid --now value {args.now!r}",
                where="scripts.telemetry.report:--now",
                fix="use ISO datetime, e.g. --now 2026-05-19T12:00:00Z.",
            )
            return 1

    report = build_report(
        window_days=window,
        state_dir=args.state_dir,
        pricing_path=args.pricing,
        retirement_path=args.retirement,
        openspec_dir=args.openspec_dir,
        now=now,
    )

    if args.as_json:
        sys.stdout.write(json.dumps(report.to_dict(), indent=2) + "\n")
    else:
        sys.stdout.write(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
