# design — `project-board-sync-and-agent-telemetry`

> Architecture notes, alternatives considered, and invariants for the
> v0.10.0 spec bundle. Companion to `proposal.md` and `tasks.md`.

## D1 — Why 7 layers (defense-in-depth)

OWASP AI Security Guide 2026 recommends ≥3 truly-independent guardrail
layers. My initial proposal had 4 layers but only 1 was independent of
AI behavior (server-side workflow); the rest were skill instructions
(AI-readable) or pre-commit hooks (AI-bypassable via `--no-verify`).
Research identified two more independent surfaces:

- **Required status check** (L3) backed by a GraphQL query — server-side
  pure, blocks merge button via branch protection.
- **State-machine validator** (L4) using gh-aw's ProjectOps pattern —
  webhook-driven, reverts illegal transitions automatically.

OpenTelemetry traces (L5) provide post-hoc audit, complementing the
preventive layers. The two tool-level reinforcers (L6 + L7) are weaker
but cheap to add; they catch the case where L1-L4 fail silently
(e.g. workflow misconfigured, custom field missing).

**Alternative considered**: lean entirely on L1 + L3 (built-in + branch
protection). **Rejected** because L3 alone doesn't surface drift early
(only at merge time), and audit (L5) was too valuable to skip given
Claude Code's native OTLP support.

## D2 — Why reuse existing Langfuse over standing up a collector

Three alternatives evaluated:

1. **Stand up an OpenTelemetry Collector (otelcol)** in front of a
   project-specific backend. Generic, vendor-neutral.
2. **Write a custom JSONL audit log** the AI emits during slice work.
   Self-contained, no external service.
3. **Reuse the existing project Langfuse instance** (Arturo's personal
   stack at eligia-core, or any consumer's existing Langfuse Cloud
   project).

**Picked (3)** because:

- Claude Code natively supports OTLP (4 env vars, no code).
- Langfuse natively ingests OTLP at `/api/public/otel`.
- Existing eligia dashboard widgets (`dashboard.palafitofood.com`) work
  unchanged once traces start landing — they query Langfuse generically.
- Zero new infrastructure to operate.

**Rejected (1)** because: the collector is yak-shaving for a
single-backend, single-developer-AI workflow. Justified only when
fan-out, redaction, or offline buffering are needed.

**Rejected (2)** because: forces custom dashboards, custom search
tooling, custom retention policies, and a future migration to OTel
anyway.

## D3 — Why open the spec catalog as 4 separate specs vs one big one

Considered bundling (project-board-sync + agent-telemetry +
event-and-data-patterns + cross-language-tooling) into one spec. Rejected
because the four cover **orthogonal concerns** with **different
audiences**:

- `project-board-sync.md`: maintainers + reviewers (governance).
- `agent-telemetry.md`: ops + on-call (observability).
- `event-and-data-patterns.md`: implementers (architectural recipes).
- `cross-language-tooling.md`: any contributor introducing a non-primary
  language tool.

Cross-references handle the connections (`project-board-sync.md` L5
links to `agent-telemetry.md`; `event-and-data-patterns.md` §7 links to
`cross-language-tooling.md`). Each spec stays focused enough to read in
one sitting.

## D4 — Why retro-proven patterns over speculative ones

Every pattern + gotcha + rule in this PR has a **specific concrete
incident** in the iguanatrader or openTrattOS retros. None are
speculative "this might happen". The cost of including a pattern that
doesn't generalize is concrete confusion for future readers; the
retro-proven filter prevents this.

The two items intentionally **deferred** (NestJS-specific subscriber
pattern + Python `str.format` JSON brace gotcha) failed this filter —
they're real but too narrow for the canonical playbook layer. Documented
as cross-references in their nearest applicable spec instead of getting
their own section.

## D5 — Why land documentation + implementation in one slice (option C)

Original plan was two PRs: docs as v0.10.0, implementation as v0.10.1.
Switched to one PR after Master pointed out that "documenting the plan"
without the templates/scripts doesn't actually produce the property
"AI doesn't drift from the board". A consumer adopting v0.10.0 docs
would still have to write the workflow YAML themselves.

Single PR is bigger (~2.1 kLOC mixed docs + code) but closes the
contract → implementation gap. Commits within the PR are split
thematically:

1. Docs (specs + runbook + spec updates) — **already landed in commit
   `cde2a13`**.
2. L2 / L3 / L4 workflow templates (3 separate commits, one per layer).
3. L6 companion script extension.
4. L7 helper script + skill update.
5. Tests for L6 + L7.
6. Final CHANGELOG sweep + INDEX.md regen.

This keeps each commit reviewable independently while landing one
coherent unit.

## D6 — Versioning: v0.10.0 minor bump

Additive specs + new normative pattern catalog → semver minor.
No breaking changes to existing specs (every modification is purely
additive). Existing consumers don't need to adopt v0.10.0 layers
immediately; adoption is graded per `release-management.md` §5.6
visibility profile.

iguanatrader will bump submodule to v0.10.0 as part of Wave 3 kickoff;
openTrattOS + eligia + palafito-b2b adopt opportunistically.

## Invariants

- **No spec deletions or breaking edits** in v0.10.0; pure additions.
- **No code changes outside templates/ + scripts/ + skills/** in v0.10.0
  implementation. Specifically, no edits to `apps/`, `lib/`, `configs/`,
  `pyproject.toml` (other than CHANGELOG entry).
- **Every new spec carries an `enforcement-status.md` row** at appropriate
  level (📋 spec-only for the catalog specs; 🟡 partial for
  project-board-sync until consumers adopt the workflows).
- **Every code addition has a test**. The verify_board_state.py script
  + the companion's `--enforce-board` flag get pytest coverage.
