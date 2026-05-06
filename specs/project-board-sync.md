# project-board-sync.md

> **Status**: v1.0.0. New in ai-playbook v0.10.0. Authored 2026-05-06 after the
> iguanatrader Wave 2 retro surfaced that the AI agent silently drifted from the
> GH Project board state — slices merged with `Status=Backlog`, `Branch` field
> empty, no audit trail of progression. This spec codifies a defense-in-depth
> contract that makes board drift **structurally impossible** rather than
> "the AI should remember to update it".
>
> **Enforcement**: 🟡 partial — L1 (built-in workflows) and L2 (custom Actions
> workflow) ship as templates; L3 (required status check), L4 (state machine
> validator), and L7 (skill-level archive gate) ship as templates pending
> consumer adoption; L5 (telemetry) ships as a separate spec
> ([agent-telemetry.md](agent-telemetry.md)); L6 (companion script extension)
> ships as a v0.10.1 follow-up. See `enforcement-status.md` for the live matrix.

## 1. Why this spec

`release-management.md` §5 codifies the **schema** of the GH Project board
(Status, custom fields, item-per-change). It does **not** codify the
**transitions** between Status values, the **proof** that a transition
happened, or the **audit** of the worker AI's compliance with the contract.

The iguanatrader Wave 2 retro (2026-05-06) surfaced three concrete drift modes:

1. **Silent skip**: AI merged a slice without ever moving `Status=In Progress`.
   The board reported `Backlog` for a Done slice; humans tracking velocity from
   the board saw zero progress on a fully-shipped wave.
2. **Custom field drift**: `Branch` and `Base SHA` fields (per §5.5) were never
   populated despite the AI working on `slice/<change-id>`. Diagnostics
   ("which commit was this slice based on?") required `git log` archaeology.
3. **AI hallucinating proof**: when later asked "did you update the board?",
   the AI fabricated plausible-sounding but unverified claims. Retro found no
   evidence of a `gh project item-edit` call in the session transcript.

The OWASP AI Security and Privacy Guide (2026) is explicit on this:
*"Responsible AI is enforced at runtime, not in policy documents. No single
guardrail technique is sufficient; combine input validation, output filtering,
and system-level controls in defense-in-depth with at least three independent
layers."* See [AI Agent Guardrails: Production Guide for 2026](https://authoritypartners.com/insights/ai-agent-guardrails-production-guide-for-2026/).

This spec codifies that defense-in-depth in 7 layers, where **5 are truly
independent of AI behavior** (server-side workflows + external telemetry
collector) and 2 are tool-level (AI runs the script, but the script — not the
AI's text output — produces the verdict).

## 2. The 7 layers (failure-mode → layer matrix)

| Layer | Mechanism | Independence | Failure mode caught |
|---|---|---|---|
| **L1** | GH Projects v2 **built-in workflows** ([GitHub docs](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-built-in-automations)): Auto-add → `Status=Todo`; PR-merged → `Status=Done`; Issue-closed → `Status=Done` | Server-side autonomous | Item never on board; Status not `Done` post-merge |
| **L2** | Custom Actions workflow `project-status.yml` (per [`templates/workflows/project-status.yml`](../templates/workflows/project-status.yml)): `push slice/**` → set `Branch` field, `Base SHA`, `Status=In Progress`; `pr.opened` → `Status=Review`; `pr.synchronize` → refresh `Base SHA` | Server-side autonomous | Custom fields drift; In-Progress / Review transitions skipped |
| **L3** | New required status check `project-board-synced` (per [`templates/workflows/project-board-synced-check.yml`](../templates/workflows/project-board-synced-check.yml)): GraphQL query verifies Status / Branch / Base SHA match git state, fails CI if invalid | Server-side, **physical merge enforcement** via branch protection | Drift between branch state and board; bypass attempt blocked at the GH UI merge button |
| **L4** | State-machine validator workflow `project-state-machine.yml` (gh-aw [ProjectOps pattern](https://github.github.com/gh-aw/patterns/projectops/)): listens on `project_v2_item.edited`, validates transition graph (Backlog → Todo → In Progress → Review → Done; no skipping), reverts illegal transitions and posts an audit comment | Server-side autonomous | Status set to a value that violates the transition graph |
| **L5** | Agent telemetry — Claude Code OTLP exporter → existing project Langfuse instance (per [agent-telemetry.md](agent-telemetry.md)). Every tool call becomes a span with `slice=<id>` tag; the entire `/opsx:apply` lifecycle is one trace | Independent (collector outside the AI process) | Post-hoc audit "did the AI run companion before first commit?" without relying on AI testimony |
| **L6** | `opsx_apply_companion.py --enforce-board` flag: script queries GraphQL for the project item, exits non-zero if Status != In Progress or Branch field unset. AI invokes the script; the script — not AI text — produces the verdict | Tool-level (AI runs, script decides) | "AI claims it updated board" without proof; pre-flight rebase didn't fire |
| **L7** | `openspec-archive-change` skill Step 0 invokes `verify_board_state.py` (per [`scripts/verify_board_state.py`](../scripts/verify_board_state.py)): refuses archive if Status != Done; exit-code semantic, not skill-instruction language | Tool-level (script invoked by skill) | Archive with stale board (e.g. PR merged but L1 workflow failed silently) |

**Truly independent layers**: L1, L2, L3, L4, L5 (5 layers, exceeds OWASP ≥3).
**Tool-level reinforcers**: L6, L7 (defense in depth — even if AI ignores the
companion's exit code, L3 catches it server-side).

## 3. State machine (L4 transition graph)

```
            ┌─────────┐
            │ Backlog │  (initial)
            └────┬────┘
                 │  (L1: Auto-add to project)
                 ▼
             ┌──────┐
             │ Todo │
             └───┬──┘
                 │  (L2: push to slice/**)
                 ▼
          ┌─────────────┐
          │ In Progress │
          └──────┬──────┘
                 │  (L2: pr.opened against main)
                 ▼
             ┌────────┐
             │ Review │
             └────┬───┘
                 │  (L1: pr.merged)
                 ▼
              ┌──────┐
              │ Done │  (terminal)
              └──────┘
```

**Allowed transitions**: any forward arrow on the graph. **Reverse transitions
permitted only with audit comment** (e.g. Review → In Progress when CI fails
and a fix-commit lands). **Skipping forbidden** (e.g. Todo → Done direct);
L4 reverts and comments.

The skip-detection rule has one exception: an emergency hot-fix that bypasses
slice convention (per §6.4 of `release-management.md` "anti-patterns")
explicitly carries `--break-glass=<reason>` (per [break-glass.md](break-glass.md))
and the L4 workflow whitelists items with the `break-glass` label.

## 4. Why this layered approach (research justifications)

### 4.1 Pre-commit hooks alone are insufficient

The natural first instinct ("add a pre-commit hook that checks board state
before letting the AI commit") is **rejected** by this spec. Research cited in
[Pre-Commit Hooks vs CI](https://tildalice.io/pre-commit-hooks-vs-ci-when-to-skip-local-checks/)
and [Why Pre-Commit Hooks Fail at Stopping Secrets](https://xygeni.io/blog/why-pre-commit-hooks-fail-at-stopping-secrets/)
is explicit:

> *"The `--no-verify` flag bypasses all checks with a one-liner. Server-side
> hooks cannot be bypassed by individual developers, making them the more
> reliable enforcement layer for team-wide policies. Pre-commit hooks are
> advisory; branch protection is enforcement."*

For an AI-driven workflow this matters because (a) the AI can choose to call
git with `--no-verify`, (b) the hook file itself can be edited by the AI, and
(c) human contributors who eventually join the project will encounter the same
bypassability. The pre-commit-hook layer therefore **does not appear in the
table above** — it remains an *optional* fast-feedback convenience, not a
guarantee.

### 4.2 AI text output is not proof

A naïve enforcement option would require the AI's verdict message to include
the output of `gh project item-list ...`. This is **rejected** because LLM
structured outputs guarantee syntax, not semantics — see
[LLM Structured Outputs: Schema Validation 2026](https://collinwilkins.com/articles/structured-output):

> *"Structured output guarantees syntactically correct JSON, but does not
> guarantee the values are semantically correct. You must always validate the
> final output in your application code before using it."*

An AI can fabricate plausible JSON that looks like `gh project` output without
ever calling `gh`. The only reliable proof is **a tool exit code from a
non-AI-controlled process**. L6 and L7 therefore invoke a script and read
its exit code; L3 runs the same logic server-side as a required status check
where the AI has zero ability to influence the outcome.

### 4.3 Server-side workflows are the strongest layer

GitHub's own ProjectOps pattern ([gh-aw/patterns/projectops](https://github.github.com/gh-aw/patterns/projectops/))
codifies this — use Issues/Projects as a control plane and validate state
transitions via webhooks server-side. The pattern's own framing:

> *"Workflows listen on `project_v2_item.edited` events, validate state
> machine transitions (e.g., can't go Done → Review), revert illegal
> transitions automatically."*

L4 in this spec **is** that pattern, adapted to the OpenSpec slice model.
Adopting the canonical GitHub pattern (vs inventing one) means future GitHub
platform improvements compose naturally.

### 4.4 Telemetry audit, not AI testimony

Once L1-L4 enforce *correctness* server-side, the remaining question is
*audit*: when something goes wrong, can a human reconstruct what the AI did?
Relying on the AI's session transcript or its self-reported actions is
unreliable per §4.2. The right answer is **OpenTelemetry traces** — see
[OpenTelemetry for AI Systems: LLM and Agent Observability 2026](https://uptrace.dev/blog/opentelemetry-ai-systems)
and [AI Agent Observability — Evolving Standards](https://opentelemetry.io/blog/2025/ai-agent-observability/):

> *"The semantic conventions for generative AI — covering LLM calls, token
> usage, model parameters — landed as stable in early 2026. Auto-instrumentation
> packages exist for OpenAI, Anthropic, LangChain, and LlamaIndex. With just a
> few lines of code, auto-instrumentation libraries provide rich context
> out-of-the-box."*

Claude Code itself supports OTLP export natively (see [Claude Code monitoring
docs](https://code.claude.com/docs/en/monitoring-usage) and
[agent-telemetry.md](agent-telemetry.md) §2.1). Configuring the exporter to
emit to the project's existing Langfuse instance is **a 4-environment-variable
configuration**, no custom collector required. L5 captures this.

### 4.5 EU AI Act compliance vector

The EU AI Act enters force August 2, 2026 (per [EU regulation 2024/1689](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689)),
with high-risk system obligations active and penalties up to 7% of global
turnover. While most ai-playbook consumer projects are not "high-risk" under
the Act, **audit-trail completeness** for AI-driven decisions is a baseline
expectation regardless of risk classification. L5's Langfuse trace per
`/opsx:apply` invocation provides the canonical audit artefact: *"on date X,
agent Y took actions A1...An on resource R, producing outcome O"*.

This argument is forward-looking, not a v1.0 blocker — but the L5 design
intentionally produces an audit trail rich enough to satisfy the Act's
Article 12 logging requirements should a consumer enter scope.

## 5. Integration with `release-management.md`

This spec **extends** but does not replace `release-management.md`. The two
specs compose as follows:

| Concern | Authoritative spec |
|---|---|
| Project board schema (Status values, custom fields, item-per-change) | `release-management.md` §5 |
| Visibility profiles (A public, B private) | `release-management.md` §5.6 |
| Branch + Base SHA fields | `release-management.md` §5.5 |
| Pre-flight rebase before slice start | `release-management.md` §6.5 |
| **Status transition graph + enforcement** | **this spec §3 + §2 layers L1-L7** |
| **Drift detection + audit** | **this spec §2 layers L5-L6** |
| **Archive board-state verification** | **this spec §2 layer L7** |
| Append-only doc files numbering (gotchas.md, CHANGELOG) | `release-management.md` §6.4 (added v0.10.0) |
| Migration revision string convention | `release-management.md` §6.4 (added v0.10.0) |

A consumer adopting `release-management.md` v1.2.0 + `project-board-sync.md`
v1.0.0 has a complete contract. The two specs ship together in v0.10.0.

## 6. Per-layer adoption status

For the **iguanatrader v1** consumer (the spec's reference implementation):

| Layer | Adoption status | Notes |
|---|---|---|
| L1 | ✅ Active (default GH built-in workflows enabled by `bootstrap_gh_project.py` per `release-management.md` §7) | No action needed |
| L2 | ⏳ Planned for Wave 3 | Template ships in v0.10.0; consumer copies to `.github/workflows/` |
| L3 | ⏳ Planned for Wave 3 | Template ships in v0.10.0; consumer adds `project-board-synced` to required-status-checks list per `release-management.md` §4.1 |
| L4 | ⏳ Planned for Wave 3 | Template ships in v0.10.0 |
| L5 | ⏳ Planned for Wave 3 | Reuses existing eligia Langfuse instance per [agent-telemetry.md](agent-telemetry.md) |
| L6 | ⏳ Planned for v0.10.1 | Extension of `scripts/opsx_apply_companion.py` (already exists per `release-management.md` §6.5) |
| L7 | ⏳ Planned for Wave 3 | Modifies `skills/openspec-archive-change/SKILL.md` to invoke `verify_board_state.py` as Step 0 |

Other consumers (openTrattOS, palafito-b2b future onboarding) adopt
opportunistically; the spec is normative but adoption is graded per
`release-management.md` §5.6 visibility profile.

## 7. Open questions / future work

- **Q1 (v1.1.0?)**: should L4's state-machine validator support a configurable
  graph, or is the Backlog → Todo → In Progress → Review → Done sequence
  universal? Argument for configurability: some projects use Kanban-style
  WIP-limited columns. Argument against: divergence makes cross-project
  velocity comparisons useless.

- **Q2 (v1.1.0?)**: should L5 traces feed back into `bmad-retrospective` as a
  data source — e.g. retro auto-includes "average time-to-merge per slice",
  "tool-call distribution", "rework cycles" sourced from Langfuse queries?
  Currently retros are human-narrated; this would make them data-grounded
  while keeping the human framing.

- **Q3 (v2.0.0?)**: the L6 + L7 tool-level reinforcers depend on the AI
  invoking the script. A v2.0.0 evolution could embed the verification
  inside the openspec-CLI itself as an upstream contribution, making the AI's
  invocation of `openspec apply` itself the gate (no separate companion script).
  Tracked as RFC candidate in `v0.10.0-roadmap.md`.

## 8. Cross-references

- [release-management.md](release-management.md) §5 (project board schema), §6.4-§6.5 (anti-collision + pre-flight rebase)
- [agent-telemetry.md](agent-telemetry.md) — L5 OTLP-to-Langfuse pattern (sibling spec)
- [verification-before-completion.md](verification-before-completion.md) §4.1 (broadest-scope rule + tool-exit-code-over-text)
- [verdict-contract.md](verdict-contract.md) (verdict canonical literals)
- [break-glass.md](break-glass.md) (L4 emergency-bypass exception)
- [enforcement-status.md](enforcement-status.md) (live adoption matrix)
- [`templates/workflows/project-status.yml`](../templates/workflows/project-status.yml) (L2 reference implementation)
- [`templates/workflows/project-board-synced-check.yml`](../templates/workflows/project-board-synced-check.yml) (L3 reference implementation)
- [`templates/workflows/project-state-machine.yml`](../templates/workflows/project-state-machine.yml) (L4 reference implementation)
- [`scripts/verify_board_state.py`](../scripts/verify_board_state.py) (L7 helper script)
- External: [GitHub Projects v2 built-in automations](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-built-in-automations)
- External: [gh-aw ProjectOps pattern](https://github.github.com/gh-aw/patterns/projectops/)
- External: [OWASP AI Security and Privacy Guide](https://owasp.org/www-project-ai-security-and-privacy-guide/)
- External: [EU AI Act regulation 2024/1689](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689)
