"""Offline table renderer for ponytail eval snapshots.

Reads a snapshot produced by ``run.py`` and prints a markdown table of code
lines (LOC) per arm, with the honest delta highlighted: **ponytail vs minimal**,
never ponytail vs baseline.

Usage
-----
    python tests/evals/ponytail/report.py snapshots/results.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

DASH = "—"


def _loc(arm: dict | None) -> int | None:
    if not arm:
        return None
    v = arm.get("code_lines")
    return v if isinstance(v, int) else None


def _cell(value: int | None) -> str:
    return str(value) if value is not None else DASH


def _delta_pct(minimal: int | None, ponytail: int | None) -> float | None:
    if minimal is None or ponytail is None or minimal <= 0:
        return None
    return (minimal - ponytail) / minimal * 100.0


def render_table(snapshot: dict) -> str:
    rows = snapshot.get("prompts", [])
    model = snapshot.get("model_actual") or "(unknown)"
    ran_at = snapshot.get("ran_at", "(unknown)")

    lines: list[str] = []
    lines.append("# Ponytail eval — code lines (LOC) per arm")
    lines.append("")
    lines.append(f"Model: `{model}` · ran: {ran_at}")
    lines.append("")
    lines.append("Honest delta: **ponytail vs minimal** (not vs baseline — baseline is")
    lines.append("context only; comparing vs baseline would conflate ponytail with the")
    lines.append("generic \"write minimal code\" instruction).")
    lines.append("")
    lines.append("| # | Prompt | Baseline LOC | Minimal LOC | Ponytail LOC | Ponytail vs Minimal |")
    lines.append("| --- | --- | --- | --- | --- | --- |")

    sum_min = 0
    sum_pony = 0
    n_delta = 0
    for i, row in enumerate(rows, 1):
        arms = row.get("arms", {})
        b = _loc(arms.get("baseline"))
        m = _loc(arms.get("minimal"))
        p = _loc(arms.get("ponytail"))
        delta = _delta_pct(m, p)
        if delta is not None:
            sum_min += m  # type: ignore[arg-type]
            sum_pony += p  # type: ignore[arg-type]
            n_delta += 1
        delta_cell = f"{delta:.1f}%" if delta is not None else DASH
        prompt = str(row.get("prompt", "")).replace("|", "\\|")
        if len(prompt) > 60:
            prompt = prompt[:59] + "…"
        lines.append(f"| {i} | {prompt} | {_cell(b)} | {_cell(m)} | {_cell(p)} | {delta_cell} |")

    avg_delta = _delta_pct(sum_min, sum_pony) if n_delta else None
    avg_cell = f"{avg_delta:.1f}%" if avg_delta is not None else DASH
    lines.append(f"| | **average** | | {sum_min or DASH} | {sum_pony or DASH} | **{avg_cell}** |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python report.py <snapshot.json>", file=sys.stderr)
        return 2
    path = Path(args[0])
    if not path.is_file():
        print(f"❌ snapshot not found: {path}", file=sys.stderr)
        return 2
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    print(render_table(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
