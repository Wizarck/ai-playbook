"""Deterministic fixture generator for the telemetry-dashboard test suite.

Run via ``python tests/fixtures/telemetry-dashboard/generate.py`` to (re)produce
the seeded JSONL fixtures consumed by the dashboard aggregator tests. The
seeded RNG is fixed (seed=42); the same Python version produces byte-identical
output, so the resulting ``.jsonl`` files are committed to the repo.

Outputs (relative to this directory):
- ``rule-events-5k.jsonl``    — ~5000 well-formed rule-event/v2 events over 30 days.
- ``rule-events-empty.jsonl`` — 42 events (below the 100-event empty-state threshold).
- ``rule-events-torn.jsonl``  — 250 events with a deliberately truncated final line.
- ``caveman-stats.json``      — the JSON output shape of ``caveman/stats.py --json``
                                for a representative ``on / full`` session.

Distribution targets in ``rule-events-5k.jsonl``:
- 3 LLMs (claude, gemini, cursor) with deliberately staggered obey-rates so the
  rule x LLM matrix exhibits at least one cross-LLM drift flag.
- 10 rule slugs.
- ~93% allow / ~5% block / ~2% warn.
- ~15% of blocks carry ``override_reason`` (these are excluded from the hero).
- ~25% of blocks are PreToolUse:Bash with ``bash_pattern_kind`` set (counted
  toward ``prompt_injection_blocks``).
- ~5% of blocks carry ``escape_hatch`` (also counted toward LLM01).
- ``self_check`` agreement rate per LLM mirrors the obey-rate ordering so the
  honesty meter shows ranking parity with the matrix.
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

SEED = 42

LLMS = [
    "claude-opus-4-7",
    "gemini-2.5-pro",
    "cursor-3",
]

# Per-LLM bias (allow probability when no rule violation):
# Cursor lower than the others so the matrix exhibits cross-LLM drift.
LLM_OBEY_BIAS = {
    "claude-opus-4-7": 0.97,
    "gemini-2.5-pro": 0.93,
    "cursor-3": 0.86,
}

# Per-LLM honesty (self_check accuracy on the events the LLM actually breaks):
LLM_HONESTY = {
    "claude-opus-4-7": 0.96,
    "gemini-2.5-pro": 0.91,
    "cursor-3": 0.78,
}

RULE_SLUGS = [
    "no-cmd-injection",
    "citations-mandatory",
    "validate-pairing",
    "no-secrets-in-logs",
    "schema-first",
    "link-integrity",
    "data-handling",
    "verdict-contract",
    "caveman-reinforce",
    "dispatcher-routing",
]

# Realistic block_class enum values for non-``none`` allow rows.
BLOCK_CLASS_NONE = "none"
BLOCK_CLASS_NONBLOCKING = [
    "outside_project",
    "change_own_folder",
    "flag_disabled",
    "helper_missing",
    "rule_disabled",
]

BASH_PATTERN_KINDS = [
    "redirect-write",
    "redirect-append",
    "tee",
    "sed-i",
    "awk-i-inplace",
    "perl-i",
    "python-c-open",
    "python-c-write-text",
    "node-e-writeFile",
    "mv-into-write-path",
    "heredoc-redirect",
    "powershell-outfile",
    "powershell-setcontent",
    "powershell-addcontent",
    "powershell-newitem",
]

# All glob form — never raw paths.
TARGET_GLOBS = [
    "*.py",
    "*.md",
    "*.env",
    "**/secrets/*",
    "**/credentials/*",
    "*.yaml",
    "*.json",
    "docs/**/*.md",
    "scripts/**/*.py",
    "tests/**/*.py",
]

OVERRIDE_REASONS = [
    "legitimate test fixture, not a real secret",
    "redaction in progress, scrubbed in next commit",
    "internal-only dev script, never shipped",
    "documented exception per ADR-021",
    "false positive on the bash heuristic, command is safe",
]

TRIGGERS_EDIT = ["PreToolUse:Edit", "PreToolUse:Write", "PreToolUse:MultiEdit"]
TRIGGERS_BASH = ["PreToolUse:Bash", "PostToolUse:Bash"]


def _session_id_hash(session_seed: int) -> str:
    """Stable 8-hex session id hash from a session seed."""
    raw = f"session-{session_seed}".encode()
    return hashlib.sha256(raw).hexdigest()[:8]


def _gen_event(rng: random.Random, ts: datetime, session_seed: int) -> dict:
    llm = rng.choice(LLMS)
    slug = rng.choice(RULE_SLUGS)
    obey_p = LLM_OBEY_BIAS[llm]

    is_bash = rng.random() < 0.20  # ~20% of events come from a Bash hook.
    trigger = rng.choice(TRIGGERS_BASH if is_bash else TRIGGERS_EDIT)
    block_tool = "Bash" if is_bash else rng.choice(["Edit", "Write", "MultiEdit"])

    # Decide verdict driven by the LLM's obey bias.
    roll = rng.random()
    if roll < obey_p:
        verdict = "allow"
    elif roll < obey_p + 0.02:
        verdict = "warn"
    else:
        verdict = "block"

    event = {
        "schema": "rule-event/v2",
        "timestamp": ts.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "slug": slug,
        "llm": llm,
        "verdict": verdict,
        "latency_ms": round(rng.uniform(2.0, 180.0), 2),
        "session_id_hash": _session_id_hash(session_seed),
        "trigger": trigger,
        "self_check": False,  # set below
        "block_tool": block_tool,
    }

    # self_check: honest LLMs report violations honestly more often.
    if verdict == "allow":
        # On allow, self_check is true the vast majority of the time.
        event["self_check"] = rng.random() < 0.98
    else:
        # On block/warn, the LLM should ideally have self_check=False (admit it).
        # Honesty rate per LLM.
        admits = rng.random() < LLM_HONESTY[llm]
        event["self_check"] = not admits  # admits → self_check=False

    # Optional token counts on PostToolUse events.
    if trigger.startswith("PostToolUse"):
        event["tokens_in"] = rng.randint(120, 4200)
        event["tokens_out"] = rng.randint(40, 1800)
        if rng.random() < 0.45:
            event["cache_read_tokens"] = rng.randint(0, 2400)

    # target_rel scrubbed (glob form) on Edit/Write/MultiEdit allows and blocks.
    if not is_bash and rng.random() < 0.55:
        event["target_rel"] = rng.choice(TARGET_GLOBS)

    if verdict == "allow":
        event["block_class"] = BLOCK_CLASS_NONE
        return event

    # Block / warn enrichments.
    if verdict == "block":
        # Some blocks come with override_reason (excluded from hero).
        if rng.random() < 0.15:
            event["override_reason"] = rng.choice(OVERRIDE_REASONS)
            event["escape_hatch"] = "AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE"

        # On Bash-triggered blocks, surface bash_pattern_kind ~70% of the time.
        if is_bash and rng.random() < 0.70:
            event["bash_pattern_kind"] = rng.choice(BASH_PATTERN_KINDS)

        # Some Edit blocks claim an escape_hatch (and so are counted into LLM01).
        if not is_bash and rng.random() < 0.10:
            event["escape_hatch"] = rng.choice(
                ["[no-doc-impact]", "AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE"]
            )

        # block_class assignment: most blocks have no enforcement-class disposition,
        # so leave block_class absent. A small fraction are non-blocking dispositions.
        if rng.random() < 0.12:
            event["block_class"] = rng.choice(BLOCK_CLASS_NONBLOCKING)

    return event


def _spread_timestamps(rng: random.Random, n: int, days: int) -> list[datetime]:
    """Produce n monotonically-sortable timestamps over the last `days` days."""
    end = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)
    start = end - timedelta(days=days)
    span_seconds = int((end - start).total_seconds())
    offsets = sorted(rng.randint(0, span_seconds) for _ in range(n))
    return [start + timedelta(seconds=o) for o in offsets]


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for event in events:
            fh.write(json.dumps(event, sort_keys=True))
            fh.write("\n")


def _build_caveman_stats(rng: random.Random) -> dict:
    """Match the shape of `python -m scripts.caveman.stats --json` output."""
    return {
        "caveman_state": "on",
        "mode": "full",
        "components": {
            "response_style": True,
            "compress_docs": True,
            "subagents_cavecrew": True,
            "commit_caveman": True,
            "review_caveman": True,
            "mcp_shrink": True,
        },
        "activation_rate": 0.83,
        "tokens_in_total": 482300,
        "tokens_out_total": 196100,
        "tokens_in_delta": -12450,
        "tokens_out_delta": -41680,
        "savings_rate": 0.65,
        "cost_per_m_input_usd": 3.0,
        "cost_per_m_output_usd": 15.0,
        "cost_saved_usd": 38.20,
        "session_count": 47,
    }


def main() -> None:
    here = Path(__file__).resolve().parent

    rng = random.Random(SEED)

    # Main 5k fixture over 30 days.
    n = 5000
    timestamps = _spread_timestamps(rng, n, days=30)
    events_5k = [
        _gen_event(rng, ts, session_seed=rng.randint(0, 9999))
        for ts in timestamps
    ]
    _write_jsonl(here / "rule-events-5k.jsonl", events_5k)

    # Empty-state fixture (42 events, intentionally below the 100 threshold).
    rng_e = random.Random(SEED + 1)
    timestamps_e = _spread_timestamps(rng_e, 42, days=7)
    events_empty = [
        _gen_event(rng_e, ts, session_seed=rng_e.randint(0, 999))
        for ts in timestamps_e
    ]
    _write_jsonl(here / "rule-events-empty.jsonl", events_empty)

    # Torn-line fixture (250 events with the last line truncated).
    rng_t = random.Random(SEED + 2)
    timestamps_t = _spread_timestamps(rng_t, 250, days=14)
    events_torn = [
        _gen_event(rng_t, ts, session_seed=rng_t.randint(0, 999))
        for ts in timestamps_t
    ]
    torn_path = here / "rule-events-torn.jsonl"
    torn_path.parent.mkdir(parents=True, exist_ok=True)
    with torn_path.open("w", encoding="utf-8", newline="\n") as fh:
        for i, event in enumerate(events_torn):
            line = json.dumps(event, sort_keys=True)
            if i == len(events_torn) - 1:
                # Truncate the final event at ~40% of its serialised length so the
                # JSONL parser hits a torn line and must skip it.
                truncate_at = max(20, int(len(line) * 0.4))
                fh.write(line[:truncate_at])
                # No trailing newline on the torn line.
            else:
                fh.write(line)
                fh.write("\n")

    # Caveman stats fixture.
    cstats = _build_caveman_stats(random.Random(SEED + 3))
    cstats_path = here / "caveman-stats.json"
    cstats_path.write_text(json.dumps(cstats, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Tiny summary so a human can sanity-check the regeneration.
    counts = {
        "rule-events-5k.jsonl": sum(1 for _ in events_5k),
        "rule-events-empty.jsonl": sum(1 for _ in events_empty),
        "rule-events-torn.jsonl": f"{len(events_torn)} (last line torn)",
        "caveman-stats.json": "1 object",
    }
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
