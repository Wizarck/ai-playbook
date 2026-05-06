---
name: bmad-extract-lessons-from-adrs
description: Mine architecture decision records (ADRs), gotcha files, runbooks, and docs/archive for cross-project lessons that warrant ai-playbook canonical specs. Use when a project lacks a populated retros/ directory but has equivalent material in other forms.
license: MIT
compatibility: Requires read access to the consumer's docs tree; emits a structured lessons digest.
metadata:
  author: ai-playbook
  version: "1.0"
  generatedBy: "0.11.0"
---

# bmad-extract-lessons-from-adrs

Mine alternative retro-equivalent surfaces (ADRs, gotchas, runbooks, post-mortems, docs/archive) for cross-project patterns that warrant inclusion in the next ai-playbook release.

## When to use

Use this skill when:

- A project has **no populated `retros/` directory** but has an extensive ADR set (e.g. `eligia-core` with 28 ADRs).
- A project has retros but they're **terse / project-specific** and you want a second pass against alternative surfaces.
- You're authoring an `ai-playbook` release that consolidates cross-project lessons (e.g. v0.11.0) and want to verify coverage across all consumers.

Don't use when:

- The project has comprehensive retros that already capture the lessons (e.g. `iguanatrader/retros/` after Wave 3 — read those directly).
- You want a quick lookup for a specific topic (just `Grep` the relevant directory).

## Inputs

- **Consumer project root** (cwd or explicit path).
- **Optional**: a "filter focus" — a topic to bias the mining toward (e.g. "DI patterns", "secret rotation", "cascade failures"). If absent, the skill returns broad coverage.

## Mining strategy

The skill walks the consumer's docs tree in this order, sampling each surface for retro-equivalent content:

### 1. ADRs

Path: `decisions/`, `docs/adr/`, `architecture/decisions/` (whichever exists).

Read each ADR's:
- "Context" / "Problem" sections — usually contains the failure mode that motivated the decision.
- "Why NOT X" / "Rejected alternatives" sections — the lessons-learned of approaches that failed.
- "Consequences" section — the durable trade-off the team accepted.

Skip ADRs about pure tech selection (e.g. "ADR-009: PostgreSQL over MySQL") unless the rationale section lists incident-driven motivations.

### 2. Gotchas

Path: `gotchas.md`, `docs/gotchas.md`, or per-bounded-context `<bc>/gotchas.md`.

Each gotcha is implicitly a one-line postmortem. Read the *why* (often only 1-2 sentences); cross-reference if it recurs in other surfaces.

### 3. Runbooks

Path: `runbooks/`, `docs/runbooks/`.

Filter by name patterns suggesting incident response:
- `runbook-*-down-*.md`
- `runbook-*-cascade.md`
- `runbook-*-recovery.md`
- `runbook-*-emergency.md`

Read these for cascade graphs + failure-mode taxonomies.

### 4. docs/archive (or equivalent)

Path: `docs/archive/`, `docs/_archived/`, `archive/`.

Look for files with audit / TODO / context titles:
- `*-AUDIT.md` — security audits, often containing concrete incident chains.
- `TODO-*.md` — abandoned features (the *why* abandoned is the lesson).
- `CONTEXT.md` — historical decisions written when memory was fresh.

### 5. CHANGELOGs

Path: `CHANGELOG.md`, `.ai-playbook/CHANGELOG.md`.

Look for notes on hotfixes / rollbacks. Pattern: a sequence of small patch releases close in time (`v0.10.0 → v0.10.1 → v0.10.2` within a week) usually means real-world gaps surfaced post-merge — extract the gap.

### 6. Postmortems (if present)

Path: `docs/postmortems/`, `postmortems/`.

These are the canonical retro surface; read each entirely.

## Output structure

Emit a structured digest as a single markdown document:

```markdown
# Lessons mined from <project> — <YYYY-MM-DD>

> Source surfaces walked:
> - decisions/ (N files read)
> - gotchas.md (M lines read)
> - runbooks/ (P files read)
> - docs/archive/ (Q files read)
> - postmortems/ (R files read; or "none present")

## Cross-project patterns (recurring; warrant ai-playbook canonical spec)

### Pattern: <name>
- **Severity**: HIGH / MED / LOW
- **Sources**: <ADR-N>, <gotcha-line>, <runbook>
- **Symptom**: one sentence
- **Suggested ai-playbook deliverable**: spec / skill / runbook / template

## Project-specific patterns (informational; NOT for ai-playbook)

- <pattern>: <one-line summary>; reason it's project-specific.

## Surfaces NOT walked (if any)

- <surface>: skipped because <reason>.
```

Constraint: the output is **never written automatically** to `<project>/retros/`. The operator decides which patterns to keep + where they land. The skill emits to stdout / a transient file; the operator copies what they want.

## Steps

1. **Locate the project root** — cwd unless explicitly provided.
2. **Walk surface 1 (ADRs)** — list ADR files, sample each (read first 50 lines + grep for "incident" / "outage" / "broke" / "failed" / "rolled back" / "rejected because"). Tag findings with the ADR number.
3. **Walk surface 2 (gotchas)** — read fully (gotcha files are typically <100 lines). Tag findings with line numbers.
4. **Walk surface 3 (runbooks)** — list runbook files, filter by incident-pattern names, sample each.
5. **Walk surface 4 (docs/archive)** — list files, sample those with audit/TODO/context titles.
6. **Walk surface 5 (CHANGELOGs)** — read; flag patch-release sequences.
7. **Walk surface 6 (postmortems)** — read all if present.
8. **Cross-reference** — patterns appearing in ≥2 surfaces become "recurring" candidates; one-source patterns become "project-specific".
9. **Write the digest** per the output schema above.
10. **Show the digest to the operator** + suggest next steps (which patterns to promote, which to defer).

## Fluid workflow integration

This skill pairs with:

- **`bmad-retrospective`** — when the project has `retros/`, prefer that; this skill is for projects without retros.
- **`openspec-propose`** for an ai-playbook release — after mining, the recurring patterns become draft `proposal.md` content.
- **`bmad-distillator`** — sister skill that consolidates BMAD planning artefacts; this skill consolidates post-implementation lessons.

## Anti-patterns

- **Auto-writing to `<project>/retros/`**: forbidden. The operator's project doesn't necessarily want a synthesised retro; let them decide.
- **Skipping CHANGELOG on the assumption it's purely descriptive**: forbidden. Patch-release cadence is a strong signal.
- **Treating every "Rejected alternative" in an ADR as a lesson**: avoid. Some are simple "didn't fit" with no incident behind them; keep the lesson list to incident-driven rejections.
- **Promoting a pattern based on one surface**: forbidden. Cross-project canonical specs need ≥2 surfaces (within or across projects).

## Reference invocation

```
/bmad-extract-lessons-from-adrs

# With filter focus:
/bmad-extract-lessons-from-adrs --focus="cascade failures"

# Against a specific project (when cwd is elsewhere):
/bmad-extract-lessons-from-adrs --project=/path/to/eligia-core
```

## Validation

The skill is validated by reproducing the v0.11.0 mining session:

1. Ran against `eligia-core` (28 ADRs + gotchas.md + 19 runbooks).
2. Ran against `palafito-b2b` (no ADRs; docs/archive only).
3. Output: 3 NEW patterns + 2 reinforced patterns vs the prior iguanatrader+openTrattOS baseline. Direct input to v0.11.0 specs `multi-layer-defense-single-operator.md`, `cascade-failure-template.md`, and the HITL section in `hitl-approval-pattern.md`.

Each subsequent ai-playbook release SHOULD invoke this skill against every consumer in [`consumers.yaml`](../../consumers.yaml) where `retros/` is empty.
