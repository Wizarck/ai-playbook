# proposal — `project-board-sync-and-agent-telemetry`

> **Status**: in-flight (slice/`project-board-sync-and-agent-telemetry`).
> **Wave**: ai-playbook v0.10.0 candidate.
> **Authored**: 2026-05-06.

## Problem

Two adjacent retros surfaced complementary gaps in the playbook:

1. **iguanatrader Wave 2** (2026-05-06, 6 slices merged): the worker AI
   silently drifted from the GitHub Project board state. Slices merged
   with `Status=Backlog`, `Branch` field empty, and no audit trail of
   progression. The "AI should remember to update the board" expectation
   is unenforceable.

2. **nexandro Wave 1.7-1.9** (2026-05-06, 3 slices merged):
   ~14 cross-project patterns + gotchas surfaced (event-bus translation,
   migration backfill discipline, cross-language tooling layout, Windows
   dev-loop quirks, gitleaks history-scan + markdown style trap, BMAD
   process refinements). All applied uniformly across every consumer the
   playbook serves; should live in the playbook layer rather than per-
   consumer auto-memory or retros.

Without a written contract, future consumer projects re-discover these
patterns one-by-one.

## Proposed change

Land **v0.10.0** as an additive minor release that:

1. Codifies the **7-layer defense-in-depth contract** for GH Project
   board sync as a new normative spec
   (`specs/project-board-sync.md`). 5 truly-independent layers (L1
   built-in workflows, L2 custom Actions workflow, L3 required status
   check, L4 state-machine validator, L5 OTLP telemetry) + 2
   tool-level reinforcers (L6 companion `--enforce-board`, L7 archive
   skill verification).

2. Codifies the **Claude Code OTLP → Langfuse telemetry pattern** as a
   new normative spec (`specs/agent-telemetry.md`). Plug-and-play 4
   environment variables; reuses existing project Langfuse instances
   (eligia stack for Arturo-personal consumers; Langfuse Cloud free
   tier for greenfield).

3. Codifies the **cross-project pattern catalog**: hybrid translation,
   two-name pattern, same-tx migration with backfill, hasTable/hasColumn
   guards, open-enum text columns, stateless proxy + stateful caller,
   failure-collapse-to-null. New spec
   (`specs/event-and-data-patterns.md`).

4. Codifies the **`tools/<name>/` peer-subdirectory convention** for
   non-primary-language tools. New spec
   (`specs/cross-language-tooling.md`).

5. Adds the **Windows dev-environment runbook**
   (`runbooks/windows-dev-environment.md`) with 4 concrete gotchas.

6. Updates **existing specs** with retro-proven additions:
   - `verification-before-completion.md §4.1` — broadest-scope rule +
     tool-exit-code-over-text rule.
   - `release-management.md §4.4` — gitleaks history scan + markdown
     style guide.
   - `release-management.md §6.4` — append-only doc-file numbering
     ranges + verbose migration revision strings from scaffold.
   - `release-management.md §6.6` — refined "when NOT" guidance for
     intra-slice parallelism (cross-BC verification gates).
   - `release-management.md §9.5` — cross-ref to project-board-sync.md.
   - `runbook-bmad-openspec.md §3.7.1` — design-mock HTML for dense
     designs.
   - `runbook-bmad-openspec.md §4.1` — forward-authored retros.

7. **Implements** the L2 / L3 / L4 workflow templates,
   `verify_board_state.py` helper script (L7), the
   `opsx_apply_companion.py --enforce-board` extension (L6), the
   `openspec-archive-change` skill Step 0 hookup, and tests.

## Capability coverage

| Capability | New spec / location |
|---|---|
| Defense-in-depth board sync | `specs/project-board-sync.md` (NEW) |
| Agent runtime telemetry | `specs/agent-telemetry.md` (NEW) |
| Event-bus + data patterns | `specs/event-and-data-patterns.md` (NEW) |
| Cross-language tools | `specs/cross-language-tooling.md` (NEW) |
| Windows dev gotchas | `runbooks/windows-dev-environment.md` (NEW) |
| Verification posture | `specs/verification-before-completion.md` §4.1 (UPDATED) |
| CI gates + style | `specs/release-management.md` §4.4 (UPDATED) |
| Anti-collision (append-only docs + migration strings) | `specs/release-management.md` §6.4 (UPDATED) |
| Intra-slice parallelism guidance | `specs/release-management.md` §6.6 (UPDATED) |
| BMAD+OpenSpec runbook | `specs/runbook-bmad-openspec.md` §3.7.1, §4.1 (UPDATED) |

## Prerequisites

- ai-playbook v0.9.3 (current `main`).
- No external blocking dependencies; all retro lessons are
  observational + ready to codify.

## Non-goals

- **NOT** in this slice: ship the v0.10.1 follow-up of `gen_indexes.py`
  improvements / additional OTLP collector configurations / per-consumer
  bumps. v0.10.0 is the contract; v0.10.1 will be the iterative
  refinement after consumers (iguanatrader Wave 3) exercise it.
- **NOT** in this slice: deprecate or rename any existing spec. Pure
  additions + cross-references.

## References

- iguanatrader retros: `retros/risk-engine-protections.md`,
  `retros/approval-channels-multichannel.md`,
  `retros/observability-cost-meter.md`,
  `retros/dashboard-svelte-skeleton.md`.
- nexandro retros: `retros/m2-ai-yield-corpus.md`,
  `retros/m2-wrap-up.md`, `retros/m2-audit-log.md`.
- External research:
  - [GitHub Projects v2 built-in automations](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-built-in-automations)
  - [gh-aw ProjectOps pattern](https://github.github.com/gh-aw/patterns/projectops/)
  - [OWASP AI Security and Privacy Guide 2026](https://owasp.org/www-project-ai-security-and-privacy-guide/)
  - [Claude Code monitoring docs](https://code.claude.com/docs/en/monitoring-usage)
  - [Langfuse OpenTelemetry integration](https://langfuse.com/integrations/native/opentelemetry)
  - [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
