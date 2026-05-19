"""Aggregate token spend / LLM cost per project / model / task_class.

Populated in T14f. Reads JSONL events written by ``scripts/log_event.py``
(default ``<repo>/.ai-playbook/events.jsonl``) and rolls them up into a
human-friendly table or a machine-readable JSON array.

Only events that look like LLM calls are counted. An event qualifies if:

- its ``name`` contains ``llm.call``; OR
- its ``attrs`` carries a ``gen_ai.usage.input_tokens`` value.

Pricing is **not** hardcoded. When ``<playbook>/configs/pricing.yaml`` exists,
its per-model ``input_per_1k`` / ``output_per_1k`` / ``cache_read_per_1k``
numbers are applied; otherwise ``estimated_cost_usd`` is ``None`` and a note
lands in the summary row (see ``docs/concepts/model-routing.md`` §Cost).

CLI
---
    python -m scripts.cost_report [--events PATH] [--dir PATH]
                                  [--period daily|weekly|monthly]
                                  [--by project|model|task_class]
                                  [--since YYYY-MM-DD] [--json]

Exit codes
----------
    0  success
    1  malformed JSONL line (canonical error with line number)
    2  missing events file
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

# Force UTF-8 stdio — table rendering may carry non-ASCII.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_EVENTS_PATH = _REPO_ROOT / ".ai-playbook" / "events.jsonl"
_DEFAULT_PRICING_PATH = _REPO_ROOT / "configs" / "pricing.yaml"

DEFAULT_SINCE_DAYS = 90


@dataclass
class Aggregate:
    """Per-group roll-up. Matches the JSON output shape."""

    key: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    estimated_cost_usd: float | None = None

    def cache_hit_pct(self) -> float:
        if self.input_tokens <= 0:
            return 0.0
        return 100.0 * self.cache_read_tokens / self.input_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_hit_pct": round(self.cache_hit_pct(), 2),
            "estimated_cost_usd": (
                round(self.estimated_cost_usd, 4)
                if self.estimated_cost_usd is not None
                else None
            ),
        }


# ---------------------------------------------------------------------------
# Canonical error emission
# ---------------------------------------------------------------------------


def _emit_error(*, why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_iso_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _parse_event_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    s = raw
    # Accept trailing Z.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _is_llm_event(event: dict[str, Any]) -> bool:
    name = str(event.get("name") or "")
    if "llm.call" in name:
        return True
    attrs = event.get("attrs") or {}
    if not isinstance(attrs, dict):
        return False
    return "gen_ai.usage.input_tokens" in attrs


def _group_key(event: dict[str, Any], by: str) -> str:
    attrs = event.get("attrs") or {}
    if not isinstance(attrs, dict):
        return "unknown"
    match by:
        case "project":
            return str(attrs.get("project") or attrs.get("ai_playbook.project") or "unknown")
        case "model":
            return str(
                attrs.get("gen_ai.response.model")
                or attrs.get("gen_ai.request.model")
                or attrs.get("model")
                or "unknown"
            )
        case "task_class":
            return str(
                attrs.get("ai_playbook.task_class")
                or attrs.get("task_class")
                or "unknown"
            )
    return "unknown"


def _int_attr(attrs: dict[str, Any], *keys: str) -> int:
    for k in keys:
        v = attrs.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


# ---------------------------------------------------------------------------
# Pricing catalog
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
        inp = row.get("input_per_1k", 0.0)
        outp = row.get("output_per_1k", 0.0)
        cache = row.get("cache_read_per_1k", 0.0)
        return (
            (input_tokens / 1000.0) * inp
            + (output_tokens / 1000.0) * outp
            + (cache_read_tokens / 1000.0) * cache
        )


def _load_pricing(path: Path) -> PricingCatalog:
    if not path.is_file():
        return PricingCatalog()
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — pricing is optional.
        return PricingCatalog(loaded=False, source=path)
    if not isinstance(data, dict):
        return PricingCatalog(loaded=False, source=path)
    rows_raw = data.get("models") if isinstance(data.get("models"), dict) else data
    rows: dict[str, dict[str, float]] = {}
    if isinstance(rows_raw, dict):
        for k, v in rows_raw.items():
            if isinstance(v, dict):
                rows[str(k)] = {str(kk): float(vv) for kk, vv in v.items() if isinstance(vv, (int, float))}
    return PricingCatalog(rows=rows, loaded=bool(rows), source=path)


# ---------------------------------------------------------------------------
# Event loading + aggregation
# ---------------------------------------------------------------------------


def _iter_event_files(events: Path | None, directory: Path | None) -> list[Path]:
    files: list[Path] = []
    if events is not None:
        files.append(events)
    if directory is not None and directory.is_dir():
        for p in sorted(directory.glob("**/*.jsonl")):
            files.append(p)
    return files


def load_events(paths: Iterable[Path]) -> tuple[list[dict[str, Any]], int, tuple[Path, int] | None]:
    """Load events from every path. Return ``(events, count, first_error)``.

    On the first malformed JSON line, returns ``first_error=(path, line_no)``
    so main() can emit a canonical error. Other lines after that line are not
    processed for that file.
    """
    events: list[dict[str, Any]] = []
    count = 0
    for path in paths:
        try:
            with path.open("r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        return events, count, (path, line_no)
                    if isinstance(obj, dict):
                        events.append(obj)
                        count += 1
        except FileNotFoundError:
            continue
    return events, count, None


def aggregate(
    events: list[dict[str, Any]],
    *,
    by: str,
    since: datetime | None,
    pricing: PricingCatalog,
) -> list[Aggregate]:
    buckets: dict[str, Aggregate] = defaultdict(lambda: Aggregate(key=""))
    for ev in events:
        if not _is_llm_event(ev):
            continue
        ts = _parse_event_ts(ev.get("ts"))
        if since is not None and ts is not None and ts < since:
            continue
        attrs = ev.get("attrs") or {}
        if not isinstance(attrs, dict):
            continue
        key = _group_key(ev, by)
        agg = buckets.setdefault(key, Aggregate(key=key))
        agg.key = key
        agg.calls += 1
        agg.input_tokens += _int_attr(attrs, "gen_ai.usage.input_tokens", "input_tokens")
        agg.output_tokens += _int_attr(attrs, "gen_ai.usage.output_tokens", "output_tokens")
        agg.cache_read_tokens += _int_attr(
            attrs,
            "gen_ai.usage.cache_read_input_tokens",
            "cache_read_tokens",
        )

    # Second pass: cost estimation per group when pricing loaded + grouping by
    # model (otherwise we'd need per-event model tags, which we don't track here).
    if pricing.loaded:
        for ev in events:
            if not _is_llm_event(ev):
                continue
            ts = _parse_event_ts(ev.get("ts"))
            if since is not None and ts is not None and ts < since:
                continue
            attrs = ev.get("attrs") or {}
            if not isinstance(attrs, dict):
                continue
            model = str(
                attrs.get("gen_ai.response.model")
                or attrs.get("gen_ai.request.model")
                or attrs.get("model")
                or ""
            )
            if not model:
                continue
            key = _group_key(ev, by)
            agg = buckets.get(key)
            if agg is None:
                continue
            in_toks = _int_attr(attrs, "gen_ai.usage.input_tokens", "input_tokens")
            out_toks = _int_attr(attrs, "gen_ai.usage.output_tokens", "output_tokens")
            cache_toks = _int_attr(
                attrs,
                "gen_ai.usage.cache_read_input_tokens",
                "cache_read_tokens",
            )
            delta = pricing.cost_for(
                model=model,
                input_tokens=in_toks,
                output_tokens=out_toks,
                cache_read_tokens=cache_toks,
            )
            if delta is None:
                continue
            agg.estimated_cost_usd = (agg.estimated_cost_usd or 0.0) + delta

    return sorted(buckets.values(), key=lambda a: a.key)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_table(rows: list[Aggregate], *, by: str, pricing_loaded: bool) -> str:
    headers = ["group", "calls", "in_tokens", "out_tokens", "cache_hit_%", "est_cost_usd"]
    data: list[list[str]] = [headers]
    for r in rows:
        cost = (
            f"{r.estimated_cost_usd:.4f}"
            if r.estimated_cost_usd is not None
            else "—"
        )
        data.append(
            [
                r.key,
                str(r.calls),
                str(r.input_tokens),
                str(r.output_tokens),
                f"{r.cache_hit_pct():.1f}",
                cost,
            ]
        )
    # Column widths.
    widths = [max(len(row[i]) for row in data) for i in range(len(headers))]
    out: list[str] = []
    out.append(f"# cost_report — grouped by {by}")
    out.append("")
    for i, row in enumerate(data):
        line = " | ".join(cell.ljust(widths[j]) for j, cell in enumerate(row))
        out.append(line)
        if i == 0:
            out.append("-+-".join("-" * w for w in widths))
    out.append("")
    if not pricing_loaded:
        out.append(
            "Note: pricing catalog not configured — see docs/concepts/model-routing.md. "
            "Populate <playbook>/configs/pricing.yaml to enable estimated_cost_usd."
        )
    if not rows:
        out.append("(no qualifying LLM events in window)")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cost_report",
        description=(
            "Aggregate LLM token/cost spend from playbook events.jsonl into a "
            "daily / weekly / monthly rollup."
        ),
    )
    parser.add_argument(
        "--events",
        type=Path,
        default=None,
        help=f"Events JSONL path (default: {_DEFAULT_EVENTS_PATH}).",
    )
    parser.add_argument(
        "--dir",
        dest="directory",
        type=Path,
        default=None,
        help="Directory of *.jsonl files (recursive) for multi-project rollups.",
    )
    parser.add_argument(
        "--period",
        choices=("daily", "weekly", "monthly"),
        default="monthly",
        help="Reporting period (default: monthly). Currently advisory; "
             "filtering uses --since.",
    )
    parser.add_argument(
        "--by",
        choices=("project", "model", "task_class"),
        default="project",
        help="Aggregation axis (default: project).",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="ISO date (YYYY-MM-DD) — events before this are dropped. "
             f"Default: {DEFAULT_SINCE_DAYS} days ago.",
    )
    parser.add_argument(
        "--pricing",
        type=Path,
        default=None,
        help=f"Pricing catalog YAML path (default: {_DEFAULT_PRICING_PATH}).",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit JSON array to stdout instead of a table.",
    )
    return parser


def _resolve_since(arg: str | None, *, period: str) -> datetime:
    if arg:
        try:
            d = _parse_iso_date(arg)
        except ValueError as exc:
            raise SystemExit(1) from exc
        return datetime(d.year, d.month, d.day, tzinfo=UTC)
    # period-aware defaults; period is advisory but we honour it for the
    # common "give me the last month/week/day" shortcut.
    today = datetime.now(UTC)
    match period:
        case "daily":
            return today - timedelta(days=1)
        case "weekly":
            return today - timedelta(days=7)
        case _:
            return today - timedelta(days=DEFAULT_SINCE_DAYS)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)

    events_path = args.events
    directory = args.directory

    # Default events path only when --dir is not supplied either.
    if events_path is None and directory is None:
        events_path = _DEFAULT_EVENTS_PATH

    paths = _iter_event_files(events_path, directory)
    # When the user explicitly pointed at a missing file, fail 2.
    if args.events is not None and not args.events.is_file():
        _emit_error(
            why=f"events file not found: {args.events}",
            where=str(args.events),
            fix="pass --events=<path> pointing at a valid JSONL, "
                "or omit to use the default .ai-playbook/events.jsonl.",
        )
        return 2
    if events_path is not None and args.events is None and not events_path.exists():
        # Default path missing — emit error 2 (consumers need a signal they
        # haven't started emitting events yet).
        _emit_error(
            why=f"default events file not found: {events_path}",
            where=str(events_path),
            fix="emit at least one event (e.g. "
                "`python -m scripts.log_event --name llm.call --attrs '{}'`) "
                "or pass --events=<path>.",
        )
        return 2
    if args.directory is not None and not args.directory.is_dir():
        _emit_error(
            why=f"events directory not found: {args.directory}",
            where=str(args.directory),
            fix="pass an existing directory to --dir.",
        )
        return 2

    try:
        since_dt = _resolve_since(args.since, period=args.period)
    except SystemExit:
        _emit_error(
            why=f"invalid --since value: {args.since!r}",
            where="cost_report.py:--since",
            fix="use ISO date format, e.g. --since 2026-03-01.",
        )
        return 1

    events, _count, err = load_events(paths)
    if err is not None:
        path, line_no = err
        _emit_error(
            why=f"malformed JSON on line {line_no}",
            where=f"{path}:{line_no}",
            fix=f"inspect {path} line {line_no}; truncate corrupted tail and rerun.",
        )
        return 1

    pricing_path = args.pricing or _DEFAULT_PRICING_PATH
    pricing = _load_pricing(pricing_path)

    rows = aggregate(events, by=args.by, since=since_dt, pricing=pricing)

    if args.as_json:
        payload = {
            "by": args.by,
            "period": args.period,
            "since": since_dt.date().isoformat(),
            "pricing_loaded": pricing.loaded,
            "rows": [r.to_dict() for r in rows],
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        sys.stdout.write(render_table(rows, by=args.by, pricing_loaded=pricing.loaded))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
