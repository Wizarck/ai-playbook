# Design — slice-6-telemetry

## Architectural overview

```
┌──────────────────────────┐    PreToolUse / PostToolUse
│  Claude Code / Gemini CLI │ ───────────────────────────┐
└──────────────────────────┘                            ▼
                                       ┌──────────────────────────────┐
                                       │  scripts/hook_dispatcher.py  │
                                       │  (≤50ms SLA per D10)         │
                                       └─────────────┬────────────────┘
                                                     │  log_event()
                                                     ▼
                            ┌────────────────────────────────────────┐
                            │ scripts/telemetry/rule_event_logger.py │
                            │  → JSONL append                        │
                            └──────────────┬─────────────────────────┘
                                           ▼
                       <consumer>/.ai-playbook-state/rule-events.jsonl
                                           │
                                           │ daemon-rotated weekly
                                           ▼
                            ┌────────────────────────────────────────┐
                            │ scripts/telemetry/report.py            │
                            │  monthly / weekly / custom subcommands │
                            │  Absorbs cost_report / lifecycle_check │
                            │     / budget_disable / deprecation /   │
                            │     simulate_model_migration           │
                            │  Inputs: pricing.yaml, retirement.yaml │
                            └──────────────┬─────────────────────────┘
                                           ▼
                               docs/telemetry.md (mkdocs)
```

## Event schema (`schemas/schema-rule-event-v1.json`)

| Field | Type | Required | Description |
|---|---|---|---|
| `schema` | string | yes | Literal `"rule-event/v1"`. |
| `timestamp` | string (date-time) | yes | ISO 8601 UTC, `2026-05-19T14:23:55Z` form. |
| `slug` | string | yes | The rule slug (`^[a-z][a-z0-9-]{1,40}$`). |
| `llm` | string | yes | `claude-opus-4-7`, `claude-sonnet-4-6`, `gemini-2.5-pro`, etc. |
| `verdict` | enum | yes | One of `allow`, `block`, `warn`. |
| `latency_ms` | number | yes | Total time the rule took to evaluate, in milliseconds. |
| `session_id_hash` | string (8 hex) | yes | sha256(session_id)[:8] — one-way. |
| `trigger` | string | yes | Hook trigger, e.g. `PreToolUse:Edit`, `PostToolUse:Bash`. |
| `self_check` | boolean | yes | True when the LLM self-validated per the rule's `## Process supervision`. |
| `tokens_in` | integer | no | Input tokens for the LLM call that triggered the event. |
| `tokens_out` | integer | no | Output tokens for the LLM call. |
| `cache_read_tokens` | integer | no | Anthropic prompt-cache reads. |
| `escape_hatch` | string | no | `"[no-doc-impact]"`, `"AIPLAYBOOK_X_SKIP"`, or absent. |

Token fields stay OPTIONAL because PreToolUse hooks do not know the token spend yet (that lands on PostToolUse / log_event). `report.py` ignores cost for events without tokens.

## Dispatcher integration

`scripts/hook_dispatcher.py::dispatch(rules, trigger, event)` already iterates over matching rules. The Slice 6 patch adds a `log_event(slug=r.slug, llm=..., verdict=..., latency_ms=..., trigger=trigger, ...)` call inside the iteration. Latency is measured per rule. The event log is **append-only**, **fail-safe** (logger swallows IO errors so it never breaks the hook), and **path-resolved** via `os.environ['AI_PLAYBOOK_STATE_DIR']` (default: `<cwd>/.ai-playbook-state/`).

## Anonymization (`scripts/telemetry/anonymize.py`)

- `hash_session_id(session_id: str) -> str` — `hashlib.sha256(session_id.encode()).hexdigest()[:8]`. Tested for collision-resistance over typical session ID populations.
- `scrub_event(event: dict) -> dict` — defense-in-depth shape lint. Removes any key whose name matches the file-path / diff-content / user-message regex. The logger writes the SCRUBBED event, never the raw one.

Privacy invariants enforced by tests:

1. No `file_path`, `path`, `directory` keys land in the event.
2. No `diff`, `content`, `body`, `message` keys land in the event.
3. `session_id_hash` is exactly 8 hex chars.
4. The unhashed `session_id` is never present in any event line.
5. `pricing.yaml` cost computation is correct (regression test against a fixture set).

## 5-CLI absorption plan

| Original | Logic destination in `report.py` |
|---|---|
| `scripts/cost_report.py` | `_compute_cost_per_rule()`, `_compute_cost_per_session()`, `_compute_spend_over_time()` + `PricingCatalog`. |
| `scripts/lifecycle_check.py` | `_check_retirement_window()`, `_check_openspec_staleness()`, `_count_memory_decay()`, `_compute_break_glass_summary()`. |
| `scripts/budget_disable_check.py` | `_check_budget_breach(provider)` — sentinel-flag check kept identical. |
| `scripts/deprecation_watcher.py` | `_check_openspec_staleness()` (stale retros) + `_check_v0_schema_drift()`. |
| `scripts/simulate_model_migration.py` | `_simulate_model_migration()` — dry-run model migration walker. |

Each subroutine is a self-contained helper. The CLI dispatch (subcommands `weekly` / `monthly` / `custom`) invokes them, composes the report.

The five standalone CLIs DELETED in this slice. Their tests are also deleted; their coverage is ported to `tests/test_telemetry.py`.

## 14-hardrule pickup plan

Each hardrule below ships as `scripts/rules/<slug>.rule.py` with the standard CLI shape (`validate [args...]`, exit 0 on pass, exit 1 on violation, exit 2 on schema break). Slugs marked **advisory** (none in this slice — all 14 are full hardrules) would set `paired_hardrule: null` + `status: advisory` in the rule doc.

| Slug | Validation rubric (≤1-line summary) |
|---|---|
| `verdict-contract` | grep for canonical verdict literal at end of artefact. |
| `output-completeness` | scan for banned patterns (`TODO`, `TBD`, `<placeholder>`, `// ... existing ...`, "for brevity"). |
| `verification-before-completion` | regex: `✅ APPROVED` preceded within 50 lines by a fenced code block or synthesis-audit structure. |
| `error-message-standard` | regex: 4-line canonical shape `❌` / `FIX:` / `OVERRIDE:` (+ exit code 0/1/2/3). |
| `apply-skill-enforcement` | shell-out to `openspec_apply_marker.py session_started --change-id <id>`. |
| `bootstrap-directive` | grep AGENTS.md §0 for canonical 4-step block. |
| `ai-reviewer-signoff` | grep PR body for §4.5.3 markers (`L1 self-review`, `Actionable comments`, `Gate F`). |
| `auto-merge-discipline` | precondition gate: §4.5 satisfied before `gh pr merge --auto`. |
| `auto-pr-stream-closure` | `gh pr list --search head:<prefix>` count must be ≤1 before opening new. |
| `delegated-shipping-prompt` | grep spawn envelope for §4.5.3 markers + `release-management §4.5` literal. |
| `doc-drift-enforcement` | wrapper around `scripts/check_doc_drift.py`. |
| `github-project-board-schema` | `gh api graphql` schema check: 5 Status options + Slice ID + Last Update. |
| `pr-tracker-reference` | regex `(Closes \|Fixes \|Resolves )#\d+\|[A-Z]+-\d+` in PR title/body. |
| `subagent-envelope-schema` | jsonschema-validate against `schemas/schema-agent-contract.json`. |

After this slice, `scripts/rules/deferred-hardrules.txt` shrinks from 24 to 10 slugs (Slice 7 absorbs the remaining 10: migrations, notifications, apply-fix-contract, break-glass, hitl-approval-pattern).

## Mkdocs Telemetry page

`docs/telemetry.md` is committed as a hand-authored static page. The page documents the metric definitions + a "first real data lands once consumers adopt v0.18.2" placeholder. Slice 7 polish converts this to a generator (`python -m scripts.telemetry.report --json | python tools/render_telemetry_md.py`); for Slice 6 the static page is sufficient to register the nav entry and validate the link-integrity sweep.

## Best-practice survey references

The `docs/concepts/telemetry-design.md` doc cites:

- arXiv 2310.13361 — "Evaluating LLM Rule Compliance under Prompt Injection" (Wei et al., 2023). Methodology basis for per-rule obey-rate metric.
- OWASP LLM Top 10 (2025) — LLM01 prompt injection. Telemetry as detection layer.
- IFEval — Zhou et al., 2023. Instruction-following benchmark; calibrates length/format-of-instruction effects on compliance, motivating rule-length cap (≤60 lines).
- OpenTelemetry GenAI semantic conventions (v1.36, 2025) — `gen_ai.usage.input_tokens` etc. naming alignment with existing `log_event.py`.
- Honeycomb 2024 "Observability for AI" — JSONL-first event shape + privacy patterns.

## Privacy invariants

1. No file paths in any event.
2. No diff content.
3. No raw user messages.
4. `session_id` always hashed (8 hex; one-way; collision-tested).
5. Event log path is gitignored at consumer (`<consumer>/.ai-playbook-state/`).
6. Logger NEVER raises into the hook (privacy AND uptime invariant).

## Failure modes

- **Empty event log**: `report.py monthly` returns exit 0 with a placeholder "no events in window" body. This is the default state when consumers have not yet adopted v0.18.2.
- **Malformed JSONL line**: skipped with a stderr warning; report continues. The line is NOT a fatal error per `error-message-standard.rule.md` exit-code 1 contract (no user action — just stale data).
- **Missing pricing.yaml**: cost columns render as `—`; the report still emits the obey-rate + spend-count columns.
- **Missing retirement.yaml**: the "models nearing retirement" section reports "no retirement catalog configured" and continues.
