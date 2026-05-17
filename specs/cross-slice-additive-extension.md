# cross-slice-additive-extension.md

> **Status**: v1.0.0 (new in v0.11.0). Defines the canonical pattern for **adding fields to a shared entity across multiple slices** without forcing a single slice to own the entity OR forcing the schema migration into a sequential bottleneck. Closes the gap surfaced by **4+ iguanatrader slices** (R2 dedupe_key, R5 audit_trail FK, R3 source_id extensions, T1 client_order_id) + nexandro Wave 1.7-1.9 (m2-data-model `text[]` allergens, `jsonb nutrition`, `NOT NULL DEFAULT '{}'`-style additive ALTERs).

## 1. Why this spec

A shared entity (e.g. `research_facts`, `orders`, `users`) is owned conceptually by one bounded context, but multiple slices in the same wave need to add fields to it:

- Slice A: `research_facts` needs a new `dedupe_key` column for idempotency.
- Slice B: `research_facts` needs a new `audit_trail_id` FK for citation tracking.
- Slice C: `research_facts` needs a new `effective_to` column for bitemporal closure.

Three failed approaches:

1. **Sequential ownership** — slice A merges first, slice B rebases on A, slice C rebases on A+B. Migration chain is clean but parallelism is lost; Wave-N planning is reduced to a single train of slices.
2. **Big-bang slice** — one slice owns "all schema changes for research_facts in Wave 2". Couples unrelated work (B's audit-trail design has nothing to do with A's idempotency); the slice is large, hard to review, and breaks Wave-N parallelism.
3. **Per-slice tables** — each slice creates a sister table (`research_facts_dedupe`, `research_facts_audit`, `research_facts_temporal`). Joins multiply; the canonical entity is fragmented; queries become 4-way joins.

The pattern that has **emerged organically** across iguanatrader Wave 2-3 + nexandro Wave 1.7-1.9 is:

> Each slice ships its OWN additive migration that adds ITS field(s) to the shared entity, with the field declared as **nullable OR `NOT NULL DEFAULT <sentinel>`**, claimed in the slicing artefact's slot reservations table. Migration order is determined by the slot reservation, not by inter-slice coordination.

Done correctly, the pattern produces:

- A clean migration chain (no `down_revision` drift, no missing predecessors).
- Independent PR review (each slice's diff only touches its field).
- Backward-compatible reads (existing rows have `NULL` or the sentinel default).
- Forward-compatible writes (new code writes the field; old code ignores it).

This spec codifies the rules that make the pattern work in practice.

---

## 2. The pattern in three sentences

1. The shared entity is owned by **one** slice (the "introducing slice" — typically Wave 1 or early Wave 2). Subsequent slices that need to add fields **never** redefine the entity; they only ship `ALTER TABLE` migrations adding their own columns.
2. Every additive column is either **nullable** OR **`NOT NULL DEFAULT <sentinel>`** — never `NOT NULL` without a default, because that breaks reads of pre-existing rows.
3. The **migration slot for the additive ALTER** is reserved per [migration-slot-reservation.md](migration-slot-reservation.md), so multiple parallel slices' ALTERs claim disjoint slots and the chain is well-formed at rebase time.

---

## 3. Three additive shapes (when to use which)

The choice of shape depends on the field's nullability semantics, the entity's size, and the read patterns. Three canonical shapes have proven out across both projects:

### 3.1 Shape A: Nullable column (default; cheapest)

```sql
ALTER TABLE research_facts ADD COLUMN dedupe_key TEXT;
CREATE INDEX ix_research_facts_dedupe_key ON research_facts(dedupe_key) WHERE dedupe_key IS NOT NULL;
```

Use when:
- The field is genuinely optional (e.g. `dedupe_key` only applies to rows from sources that opt into idempotency).
- Existing rows have no meaningful default (NULL is the truthful representation).
- Read code is willing to handle `Optional[str]`.

Reference implementations:
- iguanatrader R2 → R3: added `dedupe_key TEXT NULL` to `research_facts` for source-side idempotency. Existing rows pre-R2 don't have it; reads check `dedupe_key IS NOT NULL` before applying the ON CONFLICT clause.
- iguanatrader T1 → T2: added `client_order_id UUID NULL` to `orders` because pre-T2 orders predate the idempotency contract.

### 3.2 Shape B: `NOT NULL DEFAULT <sentinel>` (single-step backfill)

```sql
ALTER TABLE research_facts
  ADD COLUMN provenance_chain TEXT[] NOT NULL DEFAULT '{}';
```

Use when:
- The field is logically required, but there's a **safe sentinel** for pre-existing rows (`'{}'` for arrays, `'unknown'` for enums, `0` for counters).
- The entity is small enough that the rewrite cost (Postgres rewrites the whole table when adding a `NOT NULL DEFAULT` column on `< 11` versions; on `>= 11` it's a metadata-only operation for non-volatile defaults).
- Read code expects a non-null value but can interpret the sentinel as "pre-feature row".

Reference implementations:
- nexandro m2-data-model: added `text[] NOT NULL DEFAULT '{}'` for `allergens` and `categories` on the recipes table. Pre-feature rows read as "no allergens declared" (truthful, since the feature didn't exist).
- iguanatrader R5: added `audit_trail_id UUID NULL` (not Shape B because the FK can't have a sentinel — see Shape C limitations below).

**Caveat**: on Postgres < 11 (and on most other RDBMS), `ADD COLUMN ... NOT NULL DEFAULT <volatile>` rewrites the entire table. For tables > a few million rows, prefer Shape A + a follow-up backfill in a later migration.

### 3.3 Shape C: JSON / JSONB column (schema flex)

```sql
ALTER TABLE research_facts
  ADD COLUMN extension_payload JSONB NOT NULL DEFAULT '{}';
```

Use when:
- The shared entity is being extended by **multiple unrelated slices** with **disjoint sub-schemas** (e.g. R5 adds `synthesis_metadata`, R3 adds `scrape_metadata`, T2 adds `broker_metadata` — none of them share keys).
- The sub-schemas are evolving fast; promoting each sub-key to its own column would mean a stream of ALTERs.
- Reads can tolerate a JSON-roundtrip cost (single-row reads are fine; bulk analytics over `extension_payload->>'key'` are slower than indexed columns).

Reference implementations:
- nexandro m2-cost-rollup-and-audit: `nutrition` JSONB column on recipes — sub-keys vary by recipe type (Spanish-only recipes ship `kcal` + `proteins`; international recipes ship the full Open Food Facts payload). Promoting sub-keys to columns would have produced 30+ mostly-NULL columns.
- eligia-core ADR-014 multi-tenant plugin pattern: per-tenant config payload is JSONB, not a wide column set, because the tenant schema is open-ended.

**Caveat**: JSONB is the wrong call when the extension is structurally fixed and analytics-heavy. Use Shape A or B for "this slice adds 1 column with a known shape"; reserve Shape C for "N slices add disjoint sub-payloads we don't want to coordinate".

---

## 4. The slot-reservation cross-tie

This pattern is **only safe** when each slice's additive migration claims a reserved slot per [migration-slot-reservation.md](migration-slot-reservation.md). Without slot reservation, two parallel slices both claim slot `0007` for their respective ALTERs and the migration chain breaks at rebase.

The slicing artefact's "Slot reservations" table makes the additive sequence explicit:

```markdown
| Slice ID | Migrations | What it ALTERs |
|---|---|---|
| `research-bitemporal-schema` | 0005-0007 | Creates `research_facts` + indexes (introducing slice). |
| `research-edgar-fred-adapters` | 0008 | `ALTER TABLE research_facts ADD COLUMN dedupe_key`. |
| `research-news-catalysts-adapters` | 0010 | `ALTER TABLE research_facts ADD COLUMN dedupe_key` (extends Tier-A's index). |
| `research-brief-synthesis` | 0009 | `ALTER TABLE research_facts ADD COLUMN audit_trail_id` + new `research_audit_trail` table. |
```

The "What it ALTERs" column is a v0.11 extension to the slot table — at slicing time, each slice that touches a shared entity declares it. Reviewer verifies at Gate C that no two slices alter the same column with conflicting types.

---

## 5. Read-side discipline

Adding a column is half the contract; reading it correctly is the other half.

### 5.1 The introducing slice owns the entity's read model

The slice that creates the entity (`research-bitemporal-schema` for `research_facts`) ships:
- The ORM mapper / Pydantic model.
- The repository / DAO.
- The canonical "what does a row of this entity look like?" type definition.

Subsequent slices that ADD fields **DO NOT** rewrite the read model. They:
- ADD the field to the ORM mapper / Pydantic model — `Optional[T]` for Shape A, `T = field(default=...)` for Shape B, `dict[str, Any]` for Shape C.
- ADD a method to the repository if a new query pattern is needed (`find_by_dedupe_key`).
- DO NOT change existing methods unless the new field changes their semantics (in which case it's not additive — it's a breaking change requiring a migration spec discussion).

### 5.2 Reading pre-feature rows

For Shape A (nullable): code checks `if row.dedupe_key is not None: ...` before using it.

For Shape B (NOT NULL DEFAULT sentinel): code distinguishes "true value" from "sentinel"; the sentinel is documented in the column's ADD COLUMN comment AND in the entity's read model's docstring.

```python
# apps/api/src/iguanatrader/contexts/research/models.py
@dataclass(frozen=True)
class ResearchFact:
    """Canonical research fact row. See migration 0005_research_bitemporal_schema.

    Fields ADDED by later slices:
      - dedupe_key (Optional[str], slice R2): idempotency key from source adapter.
        None for pre-R2 rows (sources without idempotency contract).
      - audit_trail_id (Optional[UUID], slice R5): FK to research_audit_trail.
        None for facts NOT cited in any synthesis brief.
      - provenance_chain (list[str], slice R3): source-tier chain, e.g. ["finnhub", "openfda"].
        Empty list for pre-R3 rows; the empty-list sentinel means "single-source fact, chain trivially {source_id}".
    """
```

### 5.3 Writing pre-feature rows from new code

When new code writes a row of the entity, it MUST populate every field defined by every additive slice that has merged. Even if the new code's slice doesn't care about R5's `audit_trail_id` (it doesn't write briefs), the write path passes `None` (Shape A) or omits the column (Shape B/C with default).

This is enforced by the type checker: the entity's dataclass requires the field; pre-feature code that doesn't pass it fails mypy. New slices opt into "I require all current additive fields" by depending on the latest entity version (which is the current `main`).

---

## 6. Migration chain discipline

### 6.1 Migration revisions are NOT a build-graph

Each slice's additive migration has a `down_revision` pointing at the slot it was reserved against. **Migrations do NOT depend on slices being merged in dependency order** — they depend on `main`'s migration head being whatever it is when the slice rebases.

If slice A reserves slot `0008` and slice B reserves slot `0010`, B's `down_revision` is `0009_*` (whatever lands at 0009, which might be slice C reserved at `0009`). B does NOT know in advance who 0009 is — it just trusts the slot reservation table.

### 6.2 Empty-DDL slices reserve their slot too

Sometimes a slice is reserved a migration slot but ships no DDL (e.g. R3 sources spec slot `0010` but only writes seed rows via INSERT, not ALTER TABLE). The slice still ships a migration file at `0010_*` containing empty `upgrade()` / `downgrade()` bodies — preserves the chain integrity. The retro carry-forward MAY note "consider tightening the slot reservation in next slicing iteration" if many empty migrations are appearing.

### 6.3 Walk-revisions test

A CI gate `test_migration_chain_walks.py` runs `ScriptDirectory.walk_revisions()` on every push to fail loud if the chain has any unresolvable `down_revision`. This catches:
- Renamed migration files (revision string ≠ filename).
- Deleted migration files (down_revision points at nothing).
- Cyclic `down_revision` (rare, but possible if two slices race and both rebase off each other).

The gate template ships in `templates/new-project/tests/test_migration_chain_walks.py.tmpl` (added in v0.11; the template was tracked for v0.10.1 and slipped to v0.11 per CHANGELOG.md).

---

## 7. Anti-patterns

- **Single slice owns "all schema for entity X"**: forbidden. Big-bang slices break Wave-N parallelism. Each slice owns its OWN additive migration.
- **`NOT NULL` without default**: forbidden. Pre-existing rows can't be read; the migration fails on a non-empty table.
- **Adding a `UNIQUE` constraint across multiple slices**: forbidden. Multi-slice UNIQUE coordination is harder than the additive-column pattern can support; if a UNIQUE constraint is needed, it ships in the introducing slice OR in a single follow-up slice that owns the constraint surface.
- **Promoting a JSONB sub-key to a column in a later slice without migrating data**: forbidden. The sub-key extraction is a separate slice with its own backfill migration.
- **Reading an additive field without checking its slot's merge status**: forbidden. Cross-slice writes are eventually-consistent; a write-path that assumes "field X was added by slice Y" must check the entity's schema (or have slice Y as a hard dep declared in the slicing artefact).
- **Renaming an additive column in a follow-up slice**: forbidden. Renames are breaking changes. Either ship a separate ADD + UPDATE + DROP migration sequence (requires Wave coordination) OR live with the original name.
- **Recycling a deleted slice's reserved slot for an additive ALTER**: forbidden per [migration-slot-reservation.md](migration-slot-reservation.md) §4.3.

---

## 8. Cross-references

- [migration-slot-reservation.md](migration-slot-reservation.md) — the slot reservation contract this spec relies on.
- [release-management.md](release-management.md) §6.4 — anti-collision contract; this spec is a sub-pattern.
- [event-and-data-patterns.md](event-and-data-patterns.md) §3 (same-transaction migration with backfill) — sibling pattern for transactional migrations.
- [protocol-fake-deferred-install.md](protocol-fake-deferred-install.md) — sister pattern for cross-slice external-dep extensions.

---

## 9. Reference implementations

| Project | Slice | Entity | Field added | Shape |
|---|---|---|---|---|
| iguanatrader | R2 (research-edgar-fred-adapters) | `research_facts` | `dedupe_key TEXT NULL` | A |
| iguanatrader | R3 (research-news-catalysts-adapters) | `research_facts` | extends R2's `dedupe_key` index | (no DDL change) |
| iguanatrader | R5 (research-brief-synthesis) | `research_facts` | `audit_trail_id UUID NULL` | A |
| iguanatrader | T1 (trading-models-interfaces) | `orders` | `client_order_id UUID NULL` | A |
| nexandro | m2-data-model | `recipes` | `allergens TEXT[] NOT NULL DEFAULT '{}'` | B |
| nexandro | m2-cost-rollup-and-audit | `recipes` | `nutrition JSONB NOT NULL DEFAULT '{}'` | C |
| nexandro | m2-ingredients-extension | `ingredients` | `categories TEXT[] NOT NULL DEFAULT '{}'` | B |
