# migration-slot-reservation.md

> **Status**: v1.0.0 (new in v0.11.0). Defines the universal contract for **how monotonic / append-only namespace slots are reserved across parallel slices** — covering DB migration revision numbers, append-only doc IDs (gotchas, ADRs), seed entity IDs, and any other monotonic-counter resource that multiple parallel-wave slices write into. Closes the gap surfaced by **6 consecutive migration-slot collisions in iguanatrader Wave 2-3** (R1/R2/R5/R3/T2/O2 all picked slot `0007`/`0008` independently and collided at rebase) and parallel m2 collisions in openTrattOS.
>
> **Companion to**: [release-management.md](release-management.md) §6.4.1 (gotcha numbering ranges) and §6.4.2 (verbose-form revision strings) — this spec subsumes and generalises both.

## 1. Why this spec

The gotcha-numbering rule in `release-management.md` §6.4.1 already says "declare a numeric range per slice for `gotchas.md`". §6.4.2 says "use verbose `<NNNN>_<topic>` revision strings from scaffold". Both are necessary but not sufficient: the **range allocation is informal** ("recommended convention" in a table) and **enforcement is social** ("declared in proposal.md `Out of scope` section").

Reality from 2026-04-29 → 2026-05-06 (iguanatrader Wave 2 + Wave 3):

- **6 consecutive migration revision collisions**: R1, R2, R5, R3, T2, O2 each chose `0007_*` (then `0008_*`, `0009_*`...) independently because each slice was scaffolded in isolation off `main`. By the time slice N rebased, N-1 had already taken N-1's expected slot. The visible artefact in retros: `0010_research_sources_tier_b_c.py` had a header note "tasks.md called for 0004; ended up at 0010 due to 4 prior collisions".
- **Each retro flagged it as a carry-forward**: by retro #4, the carry-forward read "ai-playbook v0.11 should reserve slots at scaffold time". The slicing artefact was modified retroactively after each collision, but the cost was real (rebase tax: ~10 min/slice × 6 slices + cognitive overhead).
- **Same pattern in openTrattOS**: m2-data-model + cost-rollup retros document parallel m2 schema-slot races, resolved by hand each time.

The cost of **getting the slot reserved at scaffold time** is one CLI flag. The cost of **resolving the collision at rebase time** is bigger every iteration.

This spec turns the informal convention into a normative contract: slots are claimed in `docs/openspec-slice.md` at Gate C, validated by the `openspec-propose` skill at scaffold time, and enforced by a CI gate.

---

## 2. Resources covered by this spec

A "slot resource" is any namespace where:

- The IDs are **monotonic** (next available = max + 1) OR **range-bounded** (each owner gets a range);
- Multiple parallel slices may write into the same namespace;
- A collision is **not detected at write time** (file scaffolds happily; collision surfaces only at rebase or at chain-walk time).

Canonical resources in scope:

| Resource | Typical layout | Failure mode |
|---|---|---|
| **DB migrations** | `apps/api/src/migrations/<NNNN>_<topic>.py` (Alembic) / `prisma/migrations/<NNNN>_*` / `db/migrations/V<N>__*.sql` (Flyway) | Two slices pick `0007`; second-merger's chain breaks at `down_revision`. Latent if no `walk_revisions()` test runs. |
| **Append-only doc IDs** | `docs/gotchas.md` `[#42] Title`, `decisions/INDEX.md` `ADR-027`, `CHANGELOG.md` (rare; usually time-ordered) | Two slices both write `[#42]`; rebase produces duplicate IDs. |
| **Seed entity IDs (string)** | `research_sources.id = "finnhub"` (low risk — string namespace) | Low collision rate; not in scope unless a project uses numeric seed IDs. |
| **Test fixture numeric IDs** | `tenant_id=42` hardcoded across N tests | Not slot-collision per se; covered by AGENTS.md test-isolation rules. |
| **Sequential CHANGELOG items, RFC numbers, slice plan row numbers** | `RFC-007`, `slice 4/20` | Each edited by exactly one slice → not in scope. |
| **API route numeric IDs / port numbers** | `:8081`, `:8082` | Compile-time error if duplicated → out of scope. |

Out of scope: anything where the namespace is alphabetic (component file names), the resource is a single-writer surface (CHANGELOG entries are appended by the release process, not by parallel slices), or the resource auto-allocates at runtime (DB serial PKs, UUID seeds).

---

## 3. Slot allocation contract

### 3.1 Where slots are declared

All slot allocations live in **one place per consumer project**: `docs/openspec-slice.md`, in a new mandatory section called **"Slot reservations"**. The section is a table where every row is a slice, and each column is a slot resource the project manages.

Example (iguanatrader-shaped):

```markdown
## Slot reservations

| Slice ID | Migrations | Gotchas | ADR-INDEX |
|---|---|---|---|
| `bootstrap-monorepo` | 0001 | 1-9 | ADR-001..009 |
| `shared-primitives` | — | 10-19 | — |
| `persistence-tenant` | 0002-0003 | 20-29 | ADR-010..019 |
| `auth-jwt-cookie` | 0004 | 30-39 | — |
| `api-foundation-rfc7807` | — | 40-49 | ADR-020 |
| `research-bitemporal-schema` | 0005-0007 | 50-59 | ADR-021 |
| `trading-models-interfaces` | 0008 | 60-69 | — |
| `risk-engine-protections` | 0009 | 70-79 | — |
| `research-edgar-fred-adapters` | 0010 | 80-89 | — |
| `research-brief-synthesis` | 0011-0012 | 90-99 | ADR-022..023 |
| (...) |
```

Conventions:

- **One row per slice**, even if the slice owns no slots in any column. Empty cells = `—`.
- **Single integer** for a one-revision slice (`0004`); **range** for a multi-revision slice (`0005-0007`). Ranges are inclusive.
- **Range size guidance**: foundation/bootstrap → 9 slots; bounded-context introduction → 10 slots; adapter / strategy slices → 20 slots; consolidation slices → 10 slots. Reserved slots that go unused are NOT recycled to a sibling — they remain free for that slice's future amendments. The cost of unused slots is zero; the cost of recycling is collision risk.
- **Wave 0–1 reservations are dense** (foundation slices ship close together); **Wave 2+ reservations are sparse** (parallel slices need spacing for in-flight amendments).

### 3.2 When slots are claimed

The project's slicing artefact is approved at **Gate C** (per `runbook-bmad-openspec.md` §2.4). Slot reservations are part of that approval — the human reviewer at Gate C explicitly verifies:

- No two rows reserve overlapping ranges in the same column.
- Every slice that the proposal-author expects to write a migration / gotcha / ADR has a non-empty entry in the corresponding column.
- The total reserved range is large enough to absorb all known slices; if a new slice gets added later, it claims unused space (not stealing from a sibling).

The skill `bmad-create-epics-and-stories` (or whichever skill produces the slicing artefact) MUST emit the "Slot reservations" section pre-populated with the project's resources discovered from `<consumer>/AGENTS.md` (which lists migration tooling + append-only doc files). The human edits the suggested ranges before approving Gate C.

### 3.3 What `openspec-propose` enforces

When the worker AI runs `/opsx:propose <change-id>` (or the underlying `openspec-propose` skill), the skill MUST:

1. Read `docs/openspec-slice.md` and locate the `<change-id>` row in the "Slot reservations" table.
2. Pass the reserved slots to the artefact-generation step as **`reserved_slots`** metadata. The generated `proposal.md` and `tasks.md` MUST cite the reserved slots verbatim (e.g. `tasks.md` step 1: "Generate Alembic migration with revision string `0010_research_sources_tier_b_c`" — the `0010` is the reserved slot, not a guess).
3. **Refuse** to scaffold if the slice's row is missing or has empty cells where the slice's `proposal.md` clearly will need a slot (heuristic: proposal mentions `Migration:` / `migrations/` / `gotchas.md` / `ADR-` and the corresponding column is empty). Refusal message:

   ```
   ⚠ Slot reservation missing
   Slice 'research-edgar-fred-adapters' has 'Migrations: —' in docs/openspec-slice.md
   but proposal.md mentions migration work. Either:
     1. Re-open Gate C and add a Migrations slot reservation, OR
     2. Pass --no-slot-check to bypass (logged as a deviation in retro carry-forward).
   ```

4. **Cross-validate** by walking the project's existing migration / gotcha files and asserting no in-tree file already uses a reserved slot from the table. (Catches the case where the slot was recycled accidentally.)

### 3.4 What CI enforces

A new CI gate `slot-reservation-check.yml` (template in `templates/new-project/.github/workflows/`) walks the slicing artefact and:

- Fails if any two rows reserve overlapping ranges in the same column.
- Fails if any in-tree migration / gotcha file uses a slot NOT reserved by any slice (orphan slot — likely a leftover from a deleted slice or a hand-edit).
- Warns if a reserved range is half-empty (utilisation < 30%) — signal that the range can be tightened in a future Gate C revision.

Soft-warning by default; opt-in to hard-fail via `required_status_checks` on protected branches.

---

## 4. Migration-revision-string contract (subsumes §6.4.2)

`release-management.md` §6.4.2 already requires verbose-form revision strings (`0007_observability_tables`, not `0007`). This spec extends with:

### 4.1 Slot is the integer prefix; topic is the slice's choice

The slot from §3 is the **integer prefix**. The slice author chooses the `<topic>` suffix; it is NOT enforced (a typo in the topic doesn't break the chain).

### 4.2 `down_revision` must reference the predecessor's verbose form

Already required by §6.4.2; restated here because slot reservation makes this self-checking: if slot `N` always exists in exactly one slice's row and slot `N-1` in exactly one (possibly different) slice's row, then `down_revision="<N-1>_<predecessor-topic>"` is uniquely determined. The skill `openspec-propose` MAY pre-populate `down_revision` from the slot table.

### 4.3 Skipping a slot is allowed, recycling is not

If slice X reserves slot `0010` but never ships (deleted at re-slicing), `0010` is **never re-used**. The chain absorbs the gap (`0009 → 0011`). The CI gate from §3.4 emits an info-level note ("Slot 0010 reserved but unused") but does not fail.

Reason: re-using a slot risks `down_revision` confusion if the deleted slice's commits ever resurface (cherry-pick from an abandoned branch, partial revert, etc.). The cost of a sparse chain is purely visual; the cost of a corrupt chain is real.

---

## 5. Append-only doc ID contract (subsumes §6.4.1)

`release-management.md` §6.4.1 already declares ranges per slice for `gotchas.md` IDs. This spec:

- Moves the canonical range table from `release-management.md` §6.4.1 into the per-project `docs/openspec-slice.md` "Slot reservations" section (so each project tunes the ranges to its own slice count).
- Keeps the convention defaults in `release-management.md` §6.4.1 as **starting suggestions** for new projects (foundation 1-29, etc.).
- Adds the same scaffold-time validation: `openspec-propose` reads the project's reserved range and refuses to emit a `gotcha #42` line in tasks.md if the slice's row reserves `30-39`.

ADR indexes follow the same pattern: each slice that ADDS one or more ADRs reserves an ADR range; the slicing artefact's "Slot reservations" table has an `ADR-INDEX` column. Slices that don't add ADRs leave the cell empty.

---

## 6. Failure modes this spec prevents

### 6.1 Latent migration-chain breakage

Without slot reservation: slice X ships `revision="0007_foo"`, slice Y ships `revision="0007_bar"` (same slot, different topic). Both pass local mypy / pytest because each test file imports its own migration in isolation. The conflict surfaces at the first `alembic upgrade head` run that tries to apply both — typically in CI of the second-merging slice, OR at deploy time on a clean database. Cost: rollback + re-coordinate, often hours.

With slot reservation: Y's `openspec-propose` refuses because `0007` is already X's. Y is forced to claim `0008` from its row (or re-open Gate C if Y needs more than one slot).

### 6.2 Gotcha-ID collision at rebase

Without slot reservation: parallel slices both pick `[#42]`. Rebase produces a doc with two `[#42]` entries; the human reviewer either renumbers one (silent loss of cross-referencing) or accepts the duplication (broken cross-references in linked runbooks).

With slot reservation: the cell `30-39` makes it physically impossible for slice X (range `40-49`) to pick `42`.

### 6.3 Silent ADR-INDEX drift

Without slot reservation: ADR-021 and ADR-022 both ship in the same wave; rebase silently applies whichever lands second to the existing INDEX, leaving cross-references in the OTHER slice's prose pointing at the wrong ADR.

With slot reservation: each slice's `ADR-INDEX` cell ensures their ADRs occupy disjoint slots from scaffold time.

### 6.4 Recycled slots

Without slot reservation: slice X (deleted at re-slicing) had reserved `0010`; later slice Y picks `0010` because it's "the next free one in the file system". A future cherry-pick of X's old branch resurfaces `revision="0010_*"` → chain corruption.

With slot reservation: the slicing artefact retains X's row even after deletion (marked `~~deleted~~ 0010`). Y must claim a different slot.

---

## 7. Migration for existing projects (v0.11 adoption)

Projects on v0.10.x adopting v0.11 follow:

1. **Audit current slot usage**: list all in-tree migration files, gotcha IDs, ADR numbers.
2. **Backfill the slicing artefact**: add the "Slot reservations" section to `docs/openspec-slice.md`. For already-archived slices, reserve the slots they used (so the table reflects current truth). For pending slices, claim ranges per §3.1 conventions.
3. **Re-open Gate C** if the slicing artefact has been rubber-stamped — slot reservations are a material change to the contract.
4. **Bump submodule pointer** to v0.11.0 (the propagate-bump bot opens the PR; on first re-propose, the worker AI sees the new validation and emits warnings on any slice missing reservations — fix iteratively).
5. **Add the CI gate** to required-status-checks once the audit pass clears.

Migration is non-destructive: existing slot assignments are preserved; only future scaffolds get the new validation.

---

## 8. Cross-references

- [release-management.md](release-management.md) §6.4.1 — append-only doc numbering ranges (this spec subsumes + generalises).
- [release-management.md](release-management.md) §6.4.2 — verbose-form migration revision strings (this spec extends).
- [bmad-openspec-bridge.md](bmad-openspec-bridge.md) §3 — slicing artefact schema, extended here with the "Slot reservations" section.
- [runbook-bmad-openspec.md](runbook-bmad-openspec.md) §2.4 — Gate C slicing approval, extended to verify slot reservations.
- [`skills/openspec-propose/SKILL.md`](../skills/openspec-propose/SKILL.md) — scaffolds artefacts; updated in v0.11 to read + enforce reserved slots.
- [`templates/new-project/.github/workflows/slot-reservation-check.yml.tmpl`](../templates/new-project/.github/workflows/slot-reservation-check.yml.tmpl) — CI gate template (added in v0.11).

---

## 9. Anti-patterns

- **Choosing a slot at `tasks.md`-write time**: forbidden. Slot is reserved at Gate C; `tasks.md` cites the reserved slot, never picks `next-available`.
- **Recycling a deleted slice's slot**: forbidden per §4.3 / §6.4. The slicing artefact records the deleted row; the slot stays burnt.
- **Letting `openspec-propose` proceed past a slot warning with `--no-slot-check`** without recording the deviation in retro carry-forward: forbidden. The `--no-slot-check` flag exists for genuine emergencies; the deviation is logged so the next retro can fix the slicing artefact.
- **Ranging slices "tightly" to save space**: forbidden. Sparse ranges (10/20 slots per slice) are cheap; tight ranges become a different kind of collision once a slice needs an unexpected second migration.
