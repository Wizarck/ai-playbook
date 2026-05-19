# curriculum.md

> **Status**: v1.0.0.

A 4-week structured learning path for a new dev onboarding to `ai-playbook` (or for future Arturo returning after 6 months away from the repo). Sits one layer above [quickstart.md](quickstart.md): quickstart is what you do on day 1; this curriculum is what you internalise across weeks 1–4 so you operate the playbook, then review it, then contribute to it, then maintain it.

This is not a replacement for any existing doc. Every week points at docs and specs that already exist; the value is in the **sequence** and the **exit criteria**.

---

## Prereqs (before week 1)

- Python 3.11+ installed (per [quickstart.md](quickstart.md) §Prereqs).
- git 2.40+, Node.js 20+, pipx, pre-commit, gh CLI authenticated, sops + age.
- A GitHub account with access to the `Wizarck` org.
- Willingness to write prose alongside code. The playbook is a documentation product first; engineers who reject writing won't enjoy it.
- ~4–6 hours per week set aside for the curriculum. Less than that stretches to 6–8 weeks; don't skip weeks to compress it.

---

## Week 1 — Operator

**Goal**: you can bootstrap a fresh consumer project and run every pre-commit hook green.

**Read** (in order):

1. [start-here.md](start-here.md) — 60-second orientation + the 3-level dispatcher diagram.
2. [quickstart.md](quickstart.md) — the 25–40-min walkthrough, end-to-end.
3. [../AGENTS.md](../AGENTS.md) — the playbook's own project dispatcher (dogfooding example).
4. In a consumer repo: `CLAUDE.md` / `GEMINI.md` / `.cursor/rules/*.mdc` — thin LLM-specific routers that point at AGENTS.md. (The playbook itself has no `CLAUDE.md`; it dogfoods AGENTS.md only.)
5. [../docs/concepts/dispatcher-chain.md](../docs/concepts/dispatcher-chain.md) — the 3-level contract.
6. [../docs/concepts/projects-registry.md](../docs/concepts/projects-registry.md) — how `~/.ai-playbook/projects.yaml` is populated and consumed.

**Do**:

- Run `python .ai-playbook/scripts/doctor.py`; fix every `fail` finding until clean.
- Follow [quickstart.md](quickstart.md) Steps 1–8 against a throwaway scratch repo.
- Install pre-commit hooks; run `pre-commit run --all-files` to green.

**Exit criteria**:

- You can recite the 3 levels of the dispatcher chain from memory.
- You can bootstrap a fresh consumer project in <40 min without referring to the doc.
- All pre-commit hooks run green on your scratch project.

---

## Week 2 — Reviewer

**Goal**: you can review a PR using the playbook's parallel-review discipline and articulate why a finding is S1 vs S3.

**Read** (any order, but all five):

1. [../docs/rules/verdict-contract.rule.md](../docs/rules/verdict-contract.rule.md) — the verdict literals, severity taxonomy, max-2-rework rule.
2. [../docs/concepts/parallel-review.md](../docs/concepts/parallel-review.md) — the 3-layer review model (Blind Hunter / Edge Case Hunter / Acceptance Auditor).
3. [../docs/concepts/agent-contract.md](../docs/concepts/agent-contract.md) — the machine-shaped envelope that carries verdicts between agents.
4. [../docs/concepts/model-routing.md](../docs/concepts/model-routing.md) — why reviewer layers use specific models.
5. [../docs/rules/break-glass.rule.md](../docs/rules/break-glass.rule.md) — when an override is legitimate and when it's not.

**Do**:

- Invoke the `bmad-code-review` skill on a fictitious diff (a deliberately buggy PR from a scratch branch).
- Produce a review artefact ending with the exact `⚠️ ISSUES FOUND (iter 1)` verdict literal.
- Include at least one `S1`, one `S2`, and one `S3` finding; explain the severity rationale in-line.

**Exit criteria**:

- You can articulate why an S1 blocks unconditionally and an S3 batches (verdict-contract.md §2).
- Your review artefact passes `scripts/verdict_lint.py` without warnings.
- You can name one scenario where `--force-with-reason` is appropriate and one where it is not.

---

## Week 3 — Contributor

**Goal**: you can land a small spec or script PR that passes CI and triages a FEEDBACK.md bullet.

**Read** (end-to-end, including comments):

1. `scripts/schema_validate.py` — the frontmatter validator.
2. `scripts/mcp/validate.py` — the MCP SSOT validator.
3. `scripts/discover_projects.py` — the registry builder.

**Do**:

- Open a small spec PR (e.g. add a row to [../docs/concepts/taxonomy.md](../docs/concepts/taxonomy.md), or fix a cross-ref).
- Follow [contributing.md](contributing.md) §4 commit style and §5 test discipline.
- Triage one open bullet in [../FEEDBACK.md](../FEEDBACK.md): turn it into an issue, an RFC, or a rejection with rationale.

**Exit criteria**:

- One PR merged.
- One FEEDBACK.md bullet moved to an issue or RFC.
- You can point to the ruff, type-hint, and pathlib rules in [contributing.md](contributing.md) §4 from memory.

---

## Week 4 — Maintainer candidate

**Goal**: you can run a full weekly retro and cut a patch release unassisted.

**Read** (in order):

1. [../docs/concepts/rollout-strategy.md](../docs/concepts/rollout-strategy.md) — breaking-change workflow.
2. [../docs/concepts/slos.md](../docs/concepts/slos.md) — the targets that define "is the playbook healthy".
3. `docs/concepts/data-retention.md` (owned by Subagent A, T22 track — if not yet populated when you reach week 4, read [../docs/concepts/retrospective-cadence.md](../docs/concepts/retrospective-cadence.md) §3 Outputs as the interim pointer).
4. `docs/concepts/incident-response.md` (owned by Subagent A, T22 track — same interim pointer).
5. [../docs/concepts/retrospective-cadence.md](../docs/concepts/retrospective-cadence.md) — the three cadences and their templates.

**Do**:

- Run a full weekly retro using [../templates/retro/weekly.md.tmpl](../templates/retro/weekly.md.tmpl). Commit it to `reports/retros/`.
- Cut a patch release: bump version in the appropriate source file, add a CHANGELOG entry, tag the commit, open the GH Release.
- Read one currently-open RFC end-to-end. Write a reviewer comment of ≥200 words with concrete questions or approval rationale.

**Exit criteria**:

- Your retro passes `scripts/lifecycle_check.py` (no "copy-paste retro" or "retro-as-blame" flags).
- Your patch release tag appears in `git tag -l` and the CHANGELOG entry follows the existing voice.
- You can name the deprecation window rule (1 minor cycle OR 90 days, whichever is longer) from memory.

---

## Ongoing — past week 4

- **Weekly retro attendance**: observer for 2 weeks, participant for 4 weeks, facilitator thereafter. The maintainer decides when you cross each threshold.
- **Monthly lifecycle check review**: read the monthly retro output, propose at least one systemic-flag fix per quarter.
- **One RFC per quarter**: either write one, or serve as the named reviewer on one.
- **Per-quarter spec rotation**: pick one spec, re-read it cold, file an issue for any line you struggle to follow. Ambiguity rot (per [slos.md](../docs/concepts/slos.md)) depends on fresh eyes to surface.

---

## Do NOT

- **Skip weeks.** Week 3 assumes week 2's reviewer instincts. Week 4 assumes week 3's contributor discipline. A contributor who never operated the playbook writes specs that don't survive contact with consumers.
- **Compress the curriculum into a weekend.** You can read all the docs in a weekend; you cannot internalise the dispatcher chain, the verdict contract, and the rollout strategy in a weekend. Time-in-tool matters more than read-throughs.
- **Treat this as a checklist.** Exit criteria are minimums, not targets. If week 2 took you 3 weeks because you wanted to read five more specs, that's fine.

---

## Cross-references

- [start-here.md](start-here.md) — orientation.
- [quickstart.md](quickstart.md) — the operator-layer walkthrough.
- [contributing.md](contributing.md) — roles, RFC SLAs, code style.
- [../docs/concepts/dispatcher-chain.md](../docs/concepts/dispatcher-chain.md), [../docs/rules/verdict-contract.rule.md](../docs/rules/verdict-contract.rule.md), [../docs/concepts/parallel-review.md](../docs/concepts/parallel-review.md), [../docs/concepts/agent-contract.md](../docs/concepts/agent-contract.md), [../docs/concepts/model-routing.md](../docs/concepts/model-routing.md), [../docs/rules/break-glass.rule.md](../docs/rules/break-glass.rule.md) — week-by-week reading list.
- [../docs/concepts/rollout-strategy.md](../docs/concepts/rollout-strategy.md), [../docs/concepts/slos.md](../docs/concepts/slos.md), [../docs/concepts/retrospective-cadence.md](../docs/concepts/retrospective-cadence.md) — week 4 governance reading.
- [../FEEDBACK.md](../FEEDBACK.md) — week 3 triage target.
- [../templates/retro/](../templates/retro/) — retro templates used in weeks 3–4 and ongoing.
