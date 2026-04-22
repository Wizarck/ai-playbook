# break-glass.md

> **Status**: v1.0.0. Supersedes T02-pre stub. Populated in T07b.

Contract for the `--force-with-reason="<text>"` flag that every blocking check in a playbook script MUST support. Break-glass is the *explicit, logged, justified* escape hatch — not a convenience shortcut.

---

## The contract

Every playbook script that can block (exit non-zero on a validation or safety gate) MUST:

1. Accept `--force-with-reason="<text>"` on its CLI (argparse-registered, visible in `--help`).
2. Reject the override if the reason is `None`, whitespace-only, or under **10 characters**. The check refuses to proceed with a meaningless reason.
3. Emit an OpenTelemetry span with:
   - `ai_playbook.override=true`
   - `ai_playbook.override_reason="<text verbatim>"`
   - `ai_playbook.override_actor="<git user.email at invocation>"`
   - `ai_playbook.override_script="<script basename>"`
   - `ai_playbook.override_gate="<the check name being bypassed>"`
4. Append a single-line entry to `<repo>/.ai-playbook/overrides.log` (gitignored — see `.gitignore`). Format: `YYYY-MM-DDTHH:MM:SS±ZZ <actor> <script> <gate> "<reason>"`.
5. Print the original error **unchanged** before proceeding. Break-glass does not silence the error; it annotates it with an `OVERRIDE APPLIED` banner and exits 0.

### CLI shape (reference)

```bash
python scripts/schema_validate.py AGENTS.md \
    --force-with-reason="bootstrapping acme-shop, .ai-playbook/ submodule not added yet"
```

### What the output looks like

```
❌ AGENTS.md missing required field `inherits_from` at C:/Projects/acme-shop/AGENTS.md:1
   FIX: add `inherits_from: [github.com/Wizarck/ai-playbook@v0.1.0]` to the YAML frontmatter.
   OVERRIDE: python scripts/schema_validate.py AGENTS.md --force-with-reason="..."

⚠️ OVERRIDE APPLIED: bootstrapping acme-shop, .ai-playbook/ submodule not added yet
   actor: jane@acme.example
   logged: .ai-playbook/overrides.log
```

Exit code: `0`.

---

## What break-glass is NOT

- **Not a convenience flag.** Using it leaves a permanent audit trail that retros surface (T14i lifecycle-check). Chronic users of break-glass get flagged as a systemic signal, not as individuals.
- **Not a bypass for `settings.json` `deny` rules.** Those are enforced by the CLI harness before the script ever runs. If a command is denied, no `--force-with-reason` inside the script can rescue it.
- **Not a bypass for `OVERRIDE: none` errors.** Scripts that protect credentials, safety invariants, or data loss declare `OVERRIDE: none` in their canonical error (see [error-message-standard.md](error-message-standard.md)); those scripts do NOT accept `--force-with-reason` at all.
- **Not a way to commit over a failing pre-commit hook without a trace.** `pre-commit run` uses the script's normal CLI; if you want to bypass, you pass `--force-with-reason` to the script. `git commit --no-verify` is a separate (deprecated) path that bypasses pre-commit entirely — forbidden by global guardrails, surfaces as an `S1` in any review.
- **Not inheritable between sessions.** The next session re-evaluates the gate; the previous override doesn't persist.

---

## Scripts that MUST support break-glass

As of v1.0.0 of the playbook, every blocking check in the table below accepts `--force-with-reason`:

| Script | Gate | `OVERRIDE: none` conditions |
|---|---|---|
| `scripts/schema_validate.py` | AGENTS.md frontmatter contract | never — always overridable |
| `scripts/openspec_validate.py` | OpenSpec change shape | never |
| `scripts/verdict_lint.py` | Verdict + severity shape | never |
| `scripts/block_manual_spec_edit.py` | `openspec/specs/*.md` hand-edit guard | never (the override intentionally records "manually patched archive marker") |
| `scripts/mcp/validate.py` | MCP SSOT drift | never |
| `scripts/mcp/render.py` | render diff against committed configs | never |
| `scripts/prompt_injection_filter.py` | layer-1 regex + layer-2 LLM judge | **when a layer-2 judge fires on known-safe content** (e.g. a doc about injection); otherwise override-refused |
| `scripts/drift_check.py` | playbook ↔ consumer AGENTS.md duplication | never |
| `scripts/secrets_scan.py` | regex + gitleaks match | **OVERRIDE: none always** — there is no legitimate reason to commit a plaintext secret |
| `scripts/doctor.py` | prereq + env var checks | never (doctor warnings are advisory) |

A new blocking script that doesn't follow this contract fails the `verdict_lint.py --shape script-cli` CI check (**TODO: clarify with maintainer** — this CLI check lands in T05 alongside the verdict linter).

---

## Python helper (shared)

All blocking scripts use a single shared helper `scripts/_break_glass.py` so the contract is uniform. Intended interface (populated as scripts land content):

```python
# scripts/_break_glass.py (populated in T07b + T09)
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MIN_REASON_LEN = 10


@dataclass
class OverrideResult:
    applied: bool
    reason: str


def add_break_glass_flag(parser: argparse.ArgumentParser) -> None:
    """Register the canonical --force-with-reason flag."""
    parser.add_argument(
        "--force-with-reason",
        dest="force_reason",
        metavar="TEXT",
        default=None,
        help="Override a blocking gate with an audit trail. Reason must be ≥10 non-whitespace chars.",
    )


def apply_break_glass(
    *,
    gate: str,
    script: str,
    reason: str | None,
    override_allowed: bool,
    repo_root: Path,
    git_user_email: str | None = None,
) -> OverrideResult:
    """Validate reason, log the override, return whether to proceed.

    Caller has already printed the canonical error. If this returns
    applied=True, caller prints the OVERRIDE APPLIED banner and exits 0.
    """
    if not override_allowed:
        # The gate declares OVERRIDE: none; refuse even if user passed the flag.
        if reason:
            print("❌ This gate declares OVERRIDE: none. --force-with-reason is refused.", file=sys.stderr)
            sys.exit(3)
        return OverrideResult(applied=False, reason="")

    if reason is None:
        return OverrideResult(applied=False, reason="")

    stripped = reason.strip()
    if len(stripped) < MIN_REASON_LEN:
        print(
            f"❌ --force-with-reason must be ≥{MIN_REASON_LEN} non-whitespace chars. Got: {len(stripped)}.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Log to overrides.log
    log_path = repo_root / ".ai-playbook" / "overrides.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    actor = git_user_email or os.environ.get("GIT_AUTHOR_EMAIL", "unknown")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f'{ts} {actor} {script} {gate} "{stripped}"\n')

    # Emit OTel span (populated in T07c alongside tracing bootstrap).
    # For v1.0.0 of this spec, the tracing call is a TODO; the log file
    # is the source of truth until OTel is wired in.

    return OverrideResult(applied=True, reason=stripped)
```

Real implementation lands alongside the first script that needs it (probably `schema_validate.py` in T03a or `secrets_scan.py` in T10). The helper is stable API; scripts call it.

---

## Audit trail

### Local (always)

`<repo>/.ai-playbook/overrides.log` — append-only, one line per override, gitignored. Readable with any text editor. Useful for a dev to self-audit before a retro.

### Durable (T07c onward)

OTel spans with the `ai_playbook.override.*` attributes flow to the observability backend (Langfuse for LLM-side traces, OTel Collector + Tempo for infra-side). Cross-project queries possible (e.g. "all overrides across all projects in the last 14 days").

### Retro surface (T14i)

`scripts/lifecycle_check.py` runs monthly and reports:

- Total overrides per script per project per month.
- Any `gate` that was overridden ≥3× in 30 days → flagged as a systemic signal: either the gate is miscalibrated, or the team has a process gap. Dispose via RFC or process fix, never by permanently loosening the gate.
- Individual actors with top-N override counts — informational only, not a performance metric.

---

## Interaction with other specs

- [error-message-standard.md](error-message-standard.md) — the canonical error shape names the exact `--force-with-reason` invocation in the `OVERRIDE:` line, so the override syntax is always discoverable from the error itself.
- [verdict-contract.md](verdict-contract.md) — a `⚠️ ISSUES FOUND` verdict produced by QA is not overridable by break-glass. Break-glass is for *tool gates*, not for *review judgments*. If QA says S1, the worker reworks; they don't `--force-with-reason` past a human-in-the-loop verdict.
- [agentic-failures.md](agentic-failures.md) — an agent attempting to invoke `--force-with-reason` on a gate that declared `OVERRIDE: none` is a "goal drift" signal (or "over-confidence" depending on context). Detectors in T17 (live docs) / T22 (governance) watch for this pattern.
- [degradation-modes.md](degradation-modes.md) — a user can force a model choice despite `DEGRADED_QUALITY` state with `--force-with-reason="accept quality drop, must ship before 17:00"`. That's legitimate; the retro surfaces it as a degradation-forced-ship signal.
- [notification-policy.md](notification-policy.md) — every `OVERRIDE APPLIED` on an `error` or higher-severity gate emits a `warn`-level notification (rate-limited).

---

## Anti-patterns

- **Wrapping scripts.** `python wrapper.py && python gated.py` to skip the gate defeats the audit. Reviewers flag this as S2.
- **Re-running until it passes.** If a flaky gate passes on retry, the fix is to harden the gate, not to loop. Flakiness is a bug.
- **Splitting commits to hide overrides.** `git commit` doesn't see the overrides log directly; linters in T17 will.
- **Generic reasons.** `--force-with-reason="bypass"` fails the length check. Good reasons explain *what's unique about this moment* that justifies the bypass ("PR#84 landing migrates the column; validator can't see it yet").
- **Override chaining.** Using break-glass on one check to satisfy a precondition for another is a sign the precondition check is wrong — fix the check.
