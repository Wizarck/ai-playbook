"""Single-process L1 dispatcher (D10).

Loads all rule definitions ONCE per session into memory. Routes incoming
PreToolUse / PostToolUse events to matching rules based on their `triggers:`
frontmatter field. Hard SLA: p50 ≤50ms total hook overhead per tool call on
Windows.

CLI modes:

    python -m scripts.hook_dispatcher --list        # show loaded rules
    python -m scripts.hook_dispatcher --benchmark   # measure p50/p95/p99
    python -m scripts.hook_dispatcher dispatch <trigger> <slug-or-stdin>

Production usage (planned in Slice 5): consumer-side claude `.claude/hooks/`
config invokes this as `python -m scripts.hook_dispatcher dispatch <trigger>`
and pipes the event JSON via stdin.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


class Rule:
    __slots__ = ("slug", "doc_path", "hardrule_path", "triggers", "frontmatter")

    def __init__(self, slug: str, doc_path: Path, frontmatter: dict[str, Any]):
        self.slug = slug
        self.doc_path = doc_path
        self.frontmatter = frontmatter
        ph = frontmatter.get("paired_hardrule")
        self.hardrule_path: Path | None = REPO_ROOT / ph if isinstance(ph, str) else None
        triggers = frontmatter.get("triggers")
        self.triggers: list[str] = triggers if isinstance(triggers, list) else []

    def matches(self, trigger: str) -> bool:
        if not self.triggers:
            return True  # no triggers = fires on everything
        return trigger in self.triggers


def _parse_frontmatter(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        data = yaml.safe_load(text[3:end].strip())
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def load_rules(root: Path = REPO_ROOT) -> list[Rule]:
    rules: list[Rule] = []
    for doc in sorted((root / "docs" / "rules").glob("*.rule.md")):
        fm = _parse_frontmatter(doc)
        if fm is None:
            continue
        slug = fm.get("slug")
        if not isinstance(slug, str):
            continue
        rules.append(Rule(slug, doc, fm))
    return rules


def dispatch(rules: list[Rule], trigger: str, event: dict[str, Any]) -> list[str]:
    """Return slugs of rules whose triggers match. Stub for Slice 6 telemetry."""
    return [r.slug for r in rules if r.matches(trigger)]


def benchmark(rules: list[Rule], n: int = 1000) -> dict[str, float]:
    """Measure dispatch latency in microseconds; report p50/p95/p99 in ms."""
    samples: list[float] = []
    event = {"trigger": "Edit", "tool": "Edit", "params": {"file_path": "/tmp/x"}}
    for _ in range(n):
        t0 = time.perf_counter_ns()
        dispatch(rules, "Edit", event)
        t1 = time.perf_counter_ns()
        samples.append((t1 - t0) / 1e6)
    samples.sort()
    return {
        "n": float(n),
        "p50_ms": statistics.median(samples),
        "p95_ms": samples[int(0.95 * n) - 1] if n >= 20 else samples[-1],
        "p99_ms": samples[int(0.99 * n) - 1] if n >= 100 else samples[-1],
        "mean_ms": statistics.mean(samples),
        "max_ms": max(samples),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="L1 hook dispatcher (D10 — ≤50ms SLA).")
    parser.add_argument("--list", action="store_true", help="List loaded rules.")
    parser.add_argument("--benchmark", action="store_true", help="Run p50/p95/p99 benchmark.")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("trigger", nargs="?", help="Tool trigger name (Edit, Bash, Write, ...).")
    parser.add_argument("--event-json", help="Inline event JSON; otherwise read from stdin.")
    args = parser.parse_args(argv)

    rules = load_rules(Path(args.root))

    if args.list:
        for r in rules:
            ts = ",".join(r.triggers) if r.triggers else "*"
            print(f"{r.slug}\ttriggers={ts}\tpaired_hardrule={r.hardrule_path}")
        return 0

    if args.benchmark:
        stats = benchmark(rules)
        print(json.dumps(stats, indent=2))
        # SLA gate.
        return 2 if stats["p50_ms"] > 50 else 0

    if args.trigger is None:
        parser.print_help()
        return 0

    event: dict[str, Any] = {}
    if args.event_json:
        event = json.loads(args.event_json)
    elif not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            event = json.loads(raw)

    fired = dispatch(rules, args.trigger, event)
    print(json.dumps({"trigger": args.trigger, "fired": fired}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
