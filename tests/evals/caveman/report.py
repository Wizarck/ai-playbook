"""Offline report renderer for caveman eval snapshots.

Reads a snapshot JSON (from ``run.py --emit-snapshot``) and emits a
markdown table comparing arms by output tokens. The honest delta column
shows ``caveman vs terse``.

CLI
---
    python tests/evals/caveman/report.py <snapshot.json>

Library
-------
    from tests.evals.caveman.report import render_table
    print(render_table(snapshot_dict))
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _pct(numerator: float, denominator: float) -> str:
    if denominator <= 0:
        return "—"
    return f"{100.0 * numerator / denominator:.1f}%"


def render_table(snapshot: dict) -> str:
    """Render a snapshot dict as a markdown comparison table."""
    rows: list[str] = []
    rows.append("| # | Prompt (first 60 chars) | Baseline | Terse | Caveman | Caveman vs Terse |")
    rows.append("|---|---|---:|---:|---:|---:|")

    totals = {"baseline": 0, "terse": 0, "caveman": 0}
    counts = {"baseline": 0, "terse": 0, "caveman": 0}

    for i, entry in enumerate(snapshot.get("prompts", []), 1):
        prompt = entry.get("prompt", "")
        prompt_short = prompt[:60] + ("…" if len(prompt) > 60 else "")
        arms = entry.get("arms", {})
        bl = (arms.get("baseline") or {}).get("output_tokens")
        ts = (arms.get("terse") or {}).get("output_tokens")
        cv = (arms.get("caveman") or {}).get("output_tokens")

        delta = "—"
        if isinstance(ts, int) and isinstance(cv, int) and ts > 0:
            delta = _pct(ts - cv, ts)

        rows.append(
            f"| {i} | {prompt_short} | "
            f"{bl if bl is not None else '—'} | "
            f"{ts if ts is not None else '—'} | "
            f"{cv if cv is not None else '—'} | "
            f"{delta} |"
        )

        for k, v in (("baseline", bl), ("terse", ts), ("caveman", cv)):
            if isinstance(v, int):
                totals[k] += v
                counts[k] += 1

    # Averages row
    def _avg(k: str) -> str:
        if counts[k] == 0:
            return "—"
        return f"{totals[k] // counts[k]}"

    delta_total = "—"
    if counts["terse"] > 0 and counts["caveman"] > 0:
        avg_ts = totals["terse"] / counts["terse"]
        avg_cv = totals["caveman"] / counts["caveman"]
        if avg_ts > 0:
            delta_total = _pct(avg_ts - avg_cv, avg_ts)

    rows.append(
        f"| **avg** | — | "
        f"**{_avg('baseline')}** | **{_avg('terse')}** | **{_avg('caveman')}** | **{delta_total}** |"
    )

    header = [
        f"Caveman 3-arm eval — snapshot from {snapshot.get('ran_at', 'unknown')}",
        f"Model (first observed): {snapshot.get('model_actual', 'unknown')}",
        "",
        "Honest delta = `caveman vs terse`. Baseline is for context only —",
        "claiming `caveman vs baseline` conflates the skill with generic terseness.",
        "",
    ]
    return "\n".join(header + rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    if not args:
        print("usage: python tests/evals/caveman/report.py <snapshot.json>", file=sys.stderr)
        return 2
    path = Path(args[0])
    if not path.is_file():
        print(f"❌ not found: {path}", file=sys.stderr)
        return 2
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    print(render_table(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
