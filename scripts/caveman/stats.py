"""Session-token stats from Claude Code transcripts.

Walks ``~/.claude/projects/<slug>/`` for the consumer project, sums
input/output/cache tokens across every ``assistant`` event in the JSONL
session logs, and computes an *extrapolated* "tokens saved by caveman"
figure. Optionally writes a one-line statusline suffix.

Honest accounting
-----------------
The "saved" figure is extrapolated, not measured. Without a counterfactual
(what the model WOULD have said without caveman), we cannot directly
measure savings. We assume caveman delivers ``SAVINGS_RATE = 0.65``
average output reduction (from the upstream JuliusBrussee/caveman
benchmark + our own eval scaffold) and report::

    saved_tokens = actual_output × SAVINGS_RATE / (1 - SAVINGS_RATE)

i.e. if caveman cut output by 65%, the un-compressed version would have
been ``output / 0.35``, so the difference is ``output × 0.65 / 0.35 =
output × 1.857``. Apply only to sessions during which caveman was
actually enabled — that gating is done by reading ``caveman.json``
``applied_at`` and ignoring older session events.

Output formats
--------------
- ``stats``                  — human-readable report
- ``stats --json``           — JSON dict for UI consumers
- ``stats --update-statusline`` — also write ``<project>/.ai-playbook/
                                  .caveman-statusline-suffix`` with the
                                  short ``⛏ 12.4k`` form
"""
from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


SAVINGS_RATE = 0.65  # average output reduction (caveman vs un-caveman)

# Rough cost estimate per million tokens (USD). Updated 2026-Q2.
COST_PER_M_INPUT_USD = 3.0
COST_PER_M_OUTPUT_USD = 15.0


@dataclass
class SessionStats:
    sessions: int = 0
    events: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    first_event_at: str | None = None
    last_event_at: str | None = None
    models: dict[str, int] = field(default_factory=dict)


def _slugify_project_path(project_root: Path) -> str:
    """Match Claude Code's session-log directory naming convention.

    Examples (observed on Windows):
        ``c:/Projects/ai-playbook``        → ``c--Projects-ai-playbook``
        ``C:/Users/Arturo``                → ``C--Users-Arturo``

    The convention is: replace ``:``, ``/``, and ``\\`` all with ``-``.
    No lowercase normalization (the drive letter case is preserved as
    typed in the Claude Code launch).
    """
    s = str(project_root)
    return s.replace(":", "-").replace("/", "-").replace("\\", "-")


def session_logs_dir(project_root: Path) -> Path:
    """Return the directory holding session JSONLs for ``project_root``."""
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return home / "projects" / _slugify_project_path(project_root)


def iter_assistant_events(jsonl_path: Path) -> Iterator[dict]:
    """Yield every ``assistant`` event from a session JSONL."""
    try:
        text = jsonl_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            yield ev


def _toggle_applied_at(project_root: Path) -> str | None:
    """Read ``.ai-playbook/caveman.json`` and return ``applied_at`` iff enabled."""
    p = project_root / ".ai-playbook" / "caveman.json"
    if not p.is_file():
        return None
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not state.get("enabled"):
        return None
    if not (state.get("components") or {}).get("response_style"):
        return None
    return state.get("applied_at")


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def collect_stats(project_root: Path, *, since: str | None = None) -> SessionStats:
    """Aggregate token usage across every assistant event in every session log.

    ``since`` (ISO 8601 string): if provided, only events at-or-after this
    timestamp are counted (used to scope stats to "while caveman was ON").
    """
    stats = SessionStats()
    log_dir = session_logs_dir(project_root)
    if not log_dir.is_dir():
        return stats

    since_dt = _parse_iso(since)

    for log_file in sorted(log_dir.glob("*.jsonl")):
        any_event = False
        for ev in iter_assistant_events(log_file):
            ts_str = ev.get("timestamp")
            ts_dt = _parse_iso(ts_str)
            if since_dt and ts_dt and ts_dt < since_dt:
                continue
            msg = ev.get("message")
            if not isinstance(msg, dict):
                continue
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            any_event = True
            stats.events += 1
            stats.input_tokens += int(usage.get("input_tokens") or 0)
            stats.output_tokens += int(usage.get("output_tokens") or 0)
            stats.cache_creation_tokens += int(usage.get("cache_creation_input_tokens") or 0)
            stats.cache_read_tokens += int(usage.get("cache_read_input_tokens") or 0)
            model = msg.get("model")
            if isinstance(model, str):
                stats.models[model] = stats.models.get(model, 0) + 1
            if ts_str:
                if not stats.first_event_at or ts_str < stats.first_event_at:
                    stats.first_event_at = ts_str
                if not stats.last_event_at or ts_str > stats.last_event_at:
                    stats.last_event_at = ts_str
        if any_event:
            stats.sessions += 1
    return stats


def extrapolated_savings(output_tokens: int) -> int:
    """Apply ``SAVINGS_RATE`` to estimate tokens that caveman saved.

    If caveman cut output by ``r``, un-compressed output would have been
    ``output / (1 - r)``. Savings = ``output × r / (1 - r)``.
    """
    if output_tokens <= 0:
        return 0
    return int(output_tokens * SAVINGS_RATE / (1.0 - SAVINGS_RATE))


def estimated_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000.0) * COST_PER_M_INPUT_USD + (
        output_tokens / 1_000_000.0
    ) * COST_PER_M_OUTPUT_USD


def _short_count(n: int) -> str:
    """Format an integer like ``12400`` → ``12.4k``, ``2_500_000`` → ``2.5M``."""
    abs_n = abs(n)
    if abs_n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if abs_n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def statusline_suffix(saved_tokens: int) -> str:
    return f"⛏ {_short_count(saved_tokens)}"


def write_statusline_suffix(project_root: Path, saved_tokens: int) -> Path:
    target = project_root / ".ai-playbook" / ".caveman-statusline-suffix"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(statusline_suffix(saved_tokens), encoding="utf-8")
    return target


def render_report(stats: SessionStats, *, project_root: Path, since: str | None) -> str:
    """Plain-text report (used by `caveman stats` without --json)."""
    saved = extrapolated_savings(stats.output_tokens)
    cost_actual = estimated_cost_usd(stats.input_tokens, stats.output_tokens)
    cost_saved = (saved / 1_000_000.0) * COST_PER_M_OUTPUT_USD

    lines = [
        f"caveman stats — {project_root}",
        f"  scope:           {'since ' + since if since else 'all sessions'}",
        f"  sessions:        {stats.sessions}",
        f"  assistant turns: {stats.events}",
        f"  input tokens:    {stats.input_tokens:,}",
        f"  output tokens:   {stats.output_tokens:,}",
        f"  cache (creation): {stats.cache_creation_tokens:,}",
        f"  cache (read):     {stats.cache_read_tokens:,}",
        f"  estimated cost:  ${cost_actual:.2f}",
        "",
        f"  ⛏  extrapolated tokens saved by caveman: {saved:,}",
        f"     (assumes {int(SAVINGS_RATE * 100)}% output reduction; honest only when caveman was active)",
        f"     estimated savings: ${cost_saved:.2f}",
    ]
    if stats.models:
        top_model = max(stats.models.items(), key=lambda kv: kv[1])[0]
        lines.append(f"  most-used model: {top_model}")
    return "\n".join(lines) + "\n"


__all__ = [
    "SAVINGS_RATE",
    "SessionStats",
    "session_logs_dir",
    "iter_assistant_events",
    "collect_stats",
    "extrapolated_savings",
    "estimated_cost_usd",
    "statusline_suffix",
    "write_statusline_suffix",
    "render_report",
]
