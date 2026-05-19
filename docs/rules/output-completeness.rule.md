# output-completeness.md

> **Status**: v1.0.0. New in ai-playbook v0.7.0. Cross-cutting discipline that applies to every artefact an agent produces — code, specs, plans, mocks, doc edits. Defends against the "skeleton output" failure mode where an agent emits placeholders, ellipses, or stub returns to skip work it judged tedious.
>
> **Pattern adopted from** `Leonxlnx/taste-skill`'s `output-skill` (see [github.com/Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill)). Adapted for the BMAD+OpenSpec hybrid flow. The original is task-agnostic; this spec localises the rules to the gates and verdicts of our pipeline.

## 1. The principle

When an agent produces a deliverable, the deliverable is **complete** — the work is actually done, not gestured at. Skeleton patterns where the agent inserts placeholder code/text/mock with the implicit assumption that "the human will finish it" are forbidden. If a deliverable cannot be completed, the agent says so explicitly via the `❓ CLARIFICATION NEEDED` verdict (per [verdict-contract.md](verdict-contract.md)) — never by emitting a half-baked artefact and claiming `✅ APPROVED`.

This is not about effort — it is about the contract between worker and reviewer. A reviewer who reads `// TODO: implement` after a worker emitted `✅ APPROVED` cannot trust any future approval from that worker, and the parallel-review framework collapses.

## 2. Banned patterns

The following patterns are **forbidden** in any agent-emitted deliverable, with no exceptions short of the explicit deferral protocol in §4:

### 2.1 Placeholder text in prose

- `<TODO>` / `<TBD>` / `<insert X here>` / `<replace with Y>` left in a doc.
- "..." used as a substitute for actual content (e.g. `1. Step one. 2. ... 3. Step three.`).
- "for brevity" / "as before" / "you get the idea" / "etc.".
- "[example here]" / "[concrete numbers needed]" without a follow-up to fill them in.

### 2.2 Skeleton code

- `function foo() { return null; }` when `foo` should compute something.
- `// TODO: implement` / `// FIXME: complete this` left in delivered code.
- `pass` in Python or `;` in C-like languages used as a body where logic was specified.
- `throw new Error("not implemented")` left in a delivered method.
- Imports added but unused, "ready for the implementation" — implementation never lands.

### 2.3 Mock / dummy returns where real values were specified

- `return { foo: "TODO" }` when the test/spec required a real shape.
- `const result = []` followed by no population logic when the spec said "return the matches".
- "Sample" output strings in a deliverable that the spec said should be real (e.g. an actual rendered email, an actual SQL query, an actual JSON response shape).

### 2.4 Truncation / ellipses in code

- `// ... rest of the file ...` in an emitted file — agents emit complete files, not deltas with ellipses.
- `case 'A': // ... case 'B': // ...` style truncation.
- "... [50 more lines like this] ..." in code.

### 2.5 Self-narration as substitute for work

- "I would normally do X, Y, Z, but..." followed by no X, Y, Z.
- "The implementation would be straightforward — just call this and that."
- "Below is the structure you'd want" — but the structure is empty.

## 3. Required posture

Every deliverable an agent submits MUST be:

- **Self-contained**: a reader (human or downstream agent) can act on it without asking the author for missing pieces.
- **Concrete**: numbers, names, paths, identifiers are real, not symbolic.
- **Complete relative to the contract**: if the task says "produce N items", the artefact has N items. If the task says "include scenarios A, B, C", scenarios A, B, C are present and full.

If the work is genuinely large, the agent **completes a slice** rather than skeletoning the whole. A complete tasks.md for the data-model change beats a skeleton tasks.md for all 11 changes.

## 4. The deferral protocol (the only legitimate exit)

There are exactly two ways an agent legitimately stops short of full completion:

### 4.1 Out-of-scope deferral (deliverable is complete; future work named)

The deliverable is **done for the contract it accepted**, but it names follow-up work that's intentionally out-of-scope. Acceptable phrasings:

- "Out of scope for this change: <thing>. Tracked as <future-change-id> in `docs/openspec-slice.md`."
- "Deferred to <future-milestone> per [ADR-N](path)."

This is fine. The work submitted is fully done; the *next* work is just identified.

### 4.2 Blocked deferral (deliverable cannot complete — explicit halt)

The agent literally cannot complete the deliverable in good faith — ambiguous spec, missing dependency, undecided architectural call. The verdict is `❓ CLARIFICATION NEEDED` per [verdict-contract.md](verdict-contract.md) §4, with a `## Question for human` section.

The artefact at this point is incomplete **and labelled as incomplete**. There is no skeleton. There is the partial work + the explicit question + the verdict literal.

## 5. The PAUSED protocol (mid-execution check-in)

For long-running tasks, an agent may emit a PAUSED checkpoint instead of a final verdict, when:

- The work is iterative and the agent has finished a slice.
- The agent wants the human to confirm direction before the next slice.

Format:

```markdown
## PAUSED — <one-line: what was completed, what's next>

<concrete progress: what's done, with references>

To continue: reply with the next direction (or `continue` to proceed with the agent's plan).
```

PAUSED is **not a verdict** and does not satisfy a Gate. It is an intermediate check. The final deliverable still ends with a verdict literal.

## 6. CI lint (future)

`scripts/check_output_completeness.py` (planned for v0.8.0) will scan emitted deliverables for the banned patterns of §2 and emit warnings. It will run on:

- Files under `openspec/changes/*/proposal.md`, `design.md`, `tasks.md`, `specs/*.md`.
- Files under `_bmad-output/planning-artifacts/*.md`.
- Diff hunks in PR descriptions.

The first version is opt-in (warning only). Hardening to CI-blocking will come once consumers have had a release to migrate.

## 7. Interaction with other specs

- [verdict-contract.md](verdict-contract.md) — output-completeness reinforces the contract: only emit `✅ APPROVED` for actually-complete work.
- [verification-before-completion.md](verification-before-completion.md) — the companion: verifies that the completed work *actually runs / passes / matches spec* before declaring it done.
- [agentic-failures.md](agentic-failures.md) — `premature_completion` and `effort_evasion` are the failure modes this spec defends against.
- [break-glass.md](break-glass.md) — never a justification for skeleton output. Break-glass overrides a gate; it does not authorise incomplete deliverables.

## 8. Worked examples

### 8.1 Complete (acceptable)

```markdown
## tasks.md — m2-recipes-core

- [ ] Create RecipeService with `create(input: CreateRecipeDto)` returning `Recipe`. Acceptance: spec scenario WHEN-1 covered.
- [ ] Create RecipeService.addIngredient with cycle detection. Acceptance: scenario WHEN-2 + edge cases EC-1, EC-2.
- [ ] Wire DI in RecipesModule. Acceptance: smoke test passes.
- [ ] Add OpenAPI annotations on POST /recipes. Acceptance: ADR-002.
- [ ] Update CHANGELOG. Acceptance: matches Conventional Commits.

✅ APPROVED
```

### 8.2 Skeleton (rejected)

```markdown
## tasks.md — m2-recipes-core

- [ ] Create RecipeService with various methods.
- [ ] Add tests.
- [ ] Update CHANGELOG.
- [ ] ... (more tasks as needed)

✅ APPROVED
```

The second emits a verdict on placeholders. The reviewer cannot act. Linter rejects; verdict invalidated.

### 8.3 Legitimate deferral

```markdown
## tasks.md — m2-recipes-core

- [ ] Create RecipeService.create(...). Acceptance: WHEN-1.
- [ ] Cycle detection on addIngredient. Acceptance: WHEN-2.

Out of scope for this change: cost rollup (deferred to `m2-cost-rollup-and-audit` per `docs/openspec-slice.md`). The Recipe entity here only exposes the schema cost will hang off; no rollup logic.

✅ APPROVED
```

The agent is honest about what's done vs deferred. The verdict is valid because the contract was about Recipe core, not cost.
