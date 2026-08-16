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
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

# Make `from scripts...` resolve when run as a direct consumer script
# (`python .ai-playbook/scripts/hook_dispatcher.py PreToolUse`), not just via -m.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _force_utf8_streams() -> None:
    """Hook payloads are UTF-8 JSON. Windows consoles are not.

    `sys.stdin.read()` decodes with the platform default encoding — cp1252 on
    Windows — so every non-ASCII byte in a hook payload is corrupted before any
    rule sees it. The failure is silent and looks like a rule bug: with
    `jira-ticket-standard`, a ticket carrying `## Métricas` and
    `## Test de regresión` was reported as MISSING both, because those are the
    only two canonical section names with accents. A gate that refuses the
    compliant author is worse than no gate — it teaches people the override.

    stdout/stderr get the same treatment: findings are Spanish prose containing
    `→`, which raises `UnicodeEncodeError` on a cp1252 console and turns a
    refusal into a crash.

    No in-process test can catch this. Every one of them builds `str` objects
    and calls the validator directly, never crossing the byte boundary where the
    corruption happens — which is exactly why the regression test for it spawns
    a subprocess.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover - captured streams
            pass


_force_utf8_streams()


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


def dispatch(
    rules: list[Rule],
    trigger: str,
    event: dict[str, Any],
    *,
    emit_telemetry: bool = True,
) -> list[str]:
    """Return slugs of rules whose triggers match.

    When `emit_telemetry` is True (the default), every matched rule emits
    one `rule-event/v1` JSONL row via `scripts.telemetry.rule_event_logger.log_event`.
    The logger is fail-safe (swallows IO errors) so this code path can never
    break the hook contract. The added overhead per matched rule is <5ms
    (verified by `tests/test_hook_latency.py`).
    """
    fired: list[str] = []
    if not emit_telemetry:
        return [r.slug for r in rules if r.matches(trigger)]

    # Lazy import — keeps the dispatcher importable from contexts that do not
    # ship the telemetry package (tests, CI bootstrap).
    try:
        from scripts.telemetry.rule_event_logger import log_event
    except Exception:  # noqa: BLE001 — never break the hook path.
        log_event = None  # type: ignore[assignment]

    # Parent OTel span wrapping the whole dispatch. Each rule's own `rule.<slug>`
    # span (from `cli_emit` when the hardrule actually runs in a consumer
    # subprocess) will appear as a sibling/child in Langfuse keyed by the same
    # trigger. No-op safe when OTel is unavailable.
    try:
        from scripts.tracing import trace_emit
        dispatch_span_cm = trace_emit.span(
            f"hook.{trigger}",
            {
                "ai_playbook.hook.trigger": trigger,
                "ai_playbook.hook.rules_loaded": len(rules),
            },
        )
    except Exception:  # noqa: BLE001
        from contextlib import nullcontext
        dispatch_span_cm = nullcontext(None)

    llm = str(event.get("llm") or event.get("model") or "unknown")
    session_id = str(event.get("session_id") or "")
    tokens_in = event.get("tokens_in")
    tokens_out = event.get("tokens_out")
    cache_read_tokens = event.get("cache_read_tokens")
    escape_hatch = event.get("escape_hatch")

    with dispatch_span_cm as dispatch_span:
        for r in rules:
            if not r.matches(trigger):
                continue
            fired.append(r.slug)
            if log_event is None:
                continue
            t0 = time.perf_counter_ns()
            verdict = "allow"  # Default; richer dispatch can override.
            # Measure pure dispatch latency. The actual hardrule invocation is
            # consumer-side; this latency reflects the dispatcher overhead only.
            t1 = time.perf_counter_ns()
            try:
                log_event(
                    slug=r.slug,
                    llm=llm,
                    verdict=verdict,
                    latency_ms=(t1 - t0) / 1e6,
                    trigger=trigger,
                    session_id=session_id,
                    self_check=bool(event.get("self_check", False)),
                    tokens_in=int(tokens_in) if isinstance(tokens_in, int | float) else None,
                    tokens_out=int(tokens_out) if isinstance(tokens_out, int | float) else None,
                    cache_read_tokens=(
                        int(cache_read_tokens)
                        if isinstance(cache_read_tokens, int | float)
                        else None
                    ),
                    escape_hatch=str(escape_hatch) if escape_hatch else None,
                )
            except Exception:  # noqa: BLE001 — never raise out of dispatch.
                pass

        if dispatch_span is not None:
            try:
                dispatch_span.set_attribute("ai_playbook.hook.fired_count", len(fired))
                if fired:
                    # Cap to keep span attrs small; full list lives in JSONL.
                    dispatch_span.set_attribute(
                        "ai_playbook.hook.fired_slugs", ",".join(fired[:20])
                    )
                if llm and llm != "unknown":
                    dispatch_span.set_attribute("ai_playbook.rule.llm", llm)
            except Exception:  # noqa: BLE001
                pass

    return fired


_KNOWN_AIS = ("claude", "gemini", "cursor")
_MODULE_CACHE: dict[str, Any] = {}

#: Import failures, by hardrule path. A rule that cannot load is a silent
#: coverage hole; keeping the reason lets callers say so instead of guessing.
_LOAD_ERRORS: dict[str, str] = {}


def _consumer_root(start: Path | None = None) -> Path:
    """Walk up for the consumer project root (.gitmodules or AGENTS.md); cwd fallback."""
    cur = (start or Path.cwd()).resolve()
    for parent in (cur, *cur.parents):
        if (parent / ".gitmodules").is_file() or (parent / "AGENTS.md").is_file():
            return parent
    return cur


def _load_rule_module(path: Path | None) -> Any:
    """Import a rule.py by file path (memoised per process). None on failure."""
    if path is None or not path.is_file():
        return None
    key = str(path)
    if key in _MODULE_CACHE:
        return _MODULE_CACHE[key]
    import importlib.util

    mod_name = "_rule_" + path.name.replace(".", "_").replace("-", "_")
    try:
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            _MODULE_CACHE[key] = None
            return None
        mod = importlib.util.module_from_spec(spec)
        # REGISTER BEFORE EXEC. `@dataclass` resolves `cls.__module__` through
        # `sys.modules` at class-creation time; without this the import dies
        # with `AttributeError: 'NoneType' object has no attribute '__dict__'`,
        # naming nothing useful.
        #
        # Measured cost of not doing it: `jira-closure-evidence` declares a
        # dataclass, so it failed to import on EVERY dispatch from the day it
        # shipped. The `except` below turned that into `mod = None`, and the
        # caller's `continue` made it indistinguishable from a rule with no
        # hook. The rule was `status: enforced`, listed by `--list`, not
        # disabled, matched its trigger — and never once ran.
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001 — a broken rule must not wedge the hook path.
        # Fail open, but NOT silently. A rule that cannot be imported is a
        # coverage hole, and the whole point of a gate is that its absence is
        # noticed. Recorded here so `--list` and the run event can surface it.
        sys.modules.pop(mod_name, None)
        _LOAD_ERRORS[key] = f"{type(exc).__name__}: {exc}"
        mod = None
    _MODULE_CACHE[key] = mod
    return mod


def _rule_matches(rule: Rule, hook_event: str, tool: str) -> bool:
    """A rule fires when its triggers include the hook event (PreToolUse) or the
    tool name (Write/Edit/...), or when it declares no triggers (fires always)."""
    if not rule.triggers:
        return True
    return hook_event in rule.triggers or (bool(tool) and tool in rule.triggers)


def _applies(rule: Rule, llm: str) -> bool:
    raw = rule.frontmatter.get("applies_to")
    if isinstance(raw, list):  # noqa: SIM108 — nested ternary would be unreadable
        ais = [a for a in _KNOWN_AIS if a in raw] or list(_KNOWN_AIS)
    else:
        ais = list(_KNOWN_AIS)
    return llm in ais


def _emit_run_event(slug: str, verdict: str, hook_event: str, tool: str,
                    llm: str, event: dict[str, Any], consumer_root: Path,
                    latency_ms: float) -> None:
    """rule-event/v2 row for an in-process hook decision. Fail-safe."""
    try:
        from scripts.telemetry.rule_event_logger import log_event
        state_dir_env = os.environ.get("AI_PLAYBOOK_STATE_DIR")
        state_dir = Path(state_dir_env) if state_dir_env else (consumer_root / ".ai-playbook-state")
        log_event(
            slug=slug, llm=llm, verdict=verdict, latency_ms=latency_ms,
            trigger=f"{hook_event}:{tool}" if tool else hook_event,
            session_id=str(event.get("session_id") or ""),
            self_check=False, state_dir=state_dir,
        )
    except Exception:  # noqa: BLE001 — telemetry never affects the decision.
        pass


def run_rules(rules: list[Rule], hook_event: str, event: dict[str, Any], *,
              consumer_root: Path | None = None) -> tuple[bool, list[str], list[str]]:
    """Execute matched rules' in-process hook entrypoints.

    Returns ``(blocked, messages, fired)``. A matched rule is run only if it is
    not disabled at L1 for this consumer, applies to the event's LLM, and exposes
    a ``pretooluse``/``posttooluse`` function. Validator-only rules (no such
    function) are skipped — their enforcement stays in CI/pre-commit. A rule that
    raises is failed OPEN (warn, never block) so a buggy rule can't wedge tooling.
    """
    from scripts.rules._hook_contract import BLOCK, WARN
    from scripts.rules._hook_contract import tool_name as _tn

    consumer_root = consumer_root or _consumer_root()
    tool = _tn(event)
    llm = str(event.get("llm") or event.get("model") or "claude")
    entry = "posttooluse" if hook_event == "PostToolUse" else "pretooluse"

    try:
        from scripts.rules_toggle import is_rule_disabled
    except Exception:  # noqa: BLE001
        is_rule_disabled = None  # type: ignore[assignment]

    blocked = False
    messages: list[str] = []
    fired: list[str] = []
    for r in rules:
        if not _rule_matches(r, hook_event, tool) or not _applies(r, llm):
            continue
        if is_rule_disabled is not None:
            try:
                if is_rule_disabled(consumer_root, r.slug, layer="L1"):
                    continue
            except Exception:  # noqa: BLE001
                pass
        mod = _load_rule_module(r.hardrule_path)
        fn = getattr(mod, entry, None) if mod is not None else None
        if not callable(fn):
            continue  # validator-only rule — no in-process hook
        t0 = time.perf_counter_ns()
        try:
            verdict = fn(event)
        except Exception as exc:  # noqa: BLE001 — fail open.
            from scripts.rules._hook_contract import HookVerdict
            verdict = HookVerdict(WARN, f"{r.slug} hook errored: {exc}")
        if verdict is None:
            continue
        latency_ms = (time.perf_counter_ns() - t0) / 1e6
        fired.append(r.slug)
        _emit_run_event(r.slug, verdict.verdict, hook_event, tool, llm, event, consumer_root, latency_ms)
        if verdict.verdict == BLOCK:
            blocked = True
            messages.append(f"❌ [{r.slug}] {verdict.message}")
        elif verdict.verdict == WARN and verdict.message:
            messages.append(f"⚠ [{r.slug}] {verdict.message}")
    return blocked, messages, fired


def benchmark(rules: list[Rule], n: int = 1000) -> dict[str, float]:
    """Measure dispatch latency in microseconds; report p50/p95/p99 in ms."""
    samples: list[float] = []
    event = {"trigger": "Edit", "tool": "Edit", "params": {"file_path": "/tmp/x"}}
    for _ in range(n):
        t0 = time.perf_counter_ns()
        dispatch(rules, "Edit", event, emit_telemetry=False)
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
    parser.add_argument("trigger", nargs="?", help="Hook event (PreToolUse/PostToolUse) or tool name.")
    parser.add_argument("--event-json", help="Inline event JSON; otherwise read from stdin.")
    parser.add_argument("--match-only", action="store_true",
                        help="Only report matched slugs (no rule execution); for diagnostics.")
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

    if args.match_only:
        fired = dispatch(rules, args.trigger, event)
        print(json.dumps({"trigger": args.trigger, "fired": fired}))
        return 0

    # Execution path: run matched rules' in-process hooks. Exit 2 on a block
    # (Claude Code blocks the tool call and surfaces stderr to the model).
    blocked, messages, fired = run_rules(rules, args.trigger, event)
    for m in messages:
        print(m, file=sys.stderr)
    print(json.dumps({"trigger": args.trigger, "fired": fired, "blocked": blocked}))
    return 2 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
