# event-and-data-patterns.md

> **Status**: v1.0.0. New in ai-playbook v0.10.0. Codifies cross-project
> patterns surfaced by openTrattOS Wave 1.7-1.9 (rag-proxy + ai-suggestions
> + audit-log) and iguanatrader Wave 1-2 (shared kernel + 6 bounded
> contexts). The patterns are **stack-agnostic** (NestJS event-emitter,
> Python message bus, Go channels — same shapes apply).
>
> **Enforcement**: 📋 spec-only — see [enforcement-status.md](enforcement-status.md).
> No automated linter detects departures; reviewer rejects on PR if a
> proposal violates a pattern without explicit ADR justification.

## 1. Why this spec

Three event-driven and data-shape patterns appeared independently in
openTrattOS and iguanatrader during 2026-Q2. Each pattern paid off enough
that the *next* slice in the same project reused it without re-discovery,
and each is **the kind of decision the spec layer should anchor** so future
consumer projects don't reinvent it.

The patterns are:

1. **Hybrid translation** — extracting a cross-cutting concern (audit log,
   metrics, cost meter) without forcing N upstream emitters to migrate.
2. **Two-name pattern** — bus channel name preserves module ownership
   while persisted/external name is module-agnostic.
3. **Same-transaction migration with backfill** — schema + data atomic.
4. **`hasTable`/`hasColumn` guards on backfill SELECTs** — same migration
   runs on greenfield AND on legacy schemas.
5. **Open-enum text columns + CHECK over native enums** — extension
   without migrations.
6. **Stateless proxy + stateful caller** — bridge a 3rd-party service to
   a canonical contract without inheriting its statefulness.
7. **Failure-collapse-to-null** — external service contracts where every
   failure mode (network / 4xx / 5xx / parse / timeout / abort) surfaces
   as one canonical "no result" sentinel.

Each is documented below with: when it applies, the failure mode it
prevents, and a concrete reference implementation.

## 2. Hybrid translation pattern

### 2.1 When it applies

You're extracting a cross-cutting concern (audit log, telemetry, cost
meter, rate limiter, …) out of N existing bounded contexts that already
emit events with **per-BC ad-hoc payloads**. The naïve approach — migrate
every emitter to a new typed envelope — touches N services + their existing
`@OnEvent` subscribers + their tests. Blast radius scales with N.

### 2.2 The pattern

Add a single subscriber that **translates** legacy payloads into the
canonical envelope at receive time. Emitters stay unchanged. Existing
subscribers that read legacy field names stay unchanged.

```ts
// audit-log.subscriber.ts
@Injectable()
export class AuditLogSubscriber {
  // 3 NEW envelope-shape events: persist as-is.
  @OnEvent("ai.suggestion-accepted")
  async onAiAccept(env: AuditEventEnvelope) { await this.audit.record("AI_SUGGESTION_ACCEPTED", env); }

  // 6 LEGACY ad-hoc events: translate per-type.
  @OnEvent("cost.ingredient-override-changed")
  async onIngOverride(legacy: IngredientOverrideChangedEvent) {
    const env: AuditEventEnvelope = {
      organizationId: legacy.organizationId,
      aggregateType: "ingredient",
      aggregateId: legacy.ingredientId,
      actorUserId: legacy.appliedBy ?? null,
      reason: legacy.reason,
      payloadAfter: { [legacy.field]: legacy.newValue },
    };
    try { await this.audit.record("INGREDIENT_OVERRIDE_CHANGED", env); }
    catch (err) { this.log.warn("audit drop", { err }); }
  }
}
```

The subscriber's `try/catch` swallows DB failures so a missing audit row
never propagates to the emitter (fire-and-forget bus semantics).

### 2.3 The trade-off

You retain N translators in the subscriber forever (one per legacy
emitter shape). The migration debt is *deferred*, not eliminated. File
a follow-up slice (`<concern>-emitter-migration`) so future readers see
the architectural intent: "envelope is canonical for new events; legacy
events get translated until migrated".

### 2.4 Reference implementation

openTrattOS `m2-audit-log` (PR #90, 2026-05-06):
`apps/api/src/audit-log/application/audit-log.subscriber.ts` — single
class with 9 `@OnEvent` handlers (3 envelope-shape passthroughs + 6
legacy translators). 27 tests across 3 spec files validate every
translator independently.

## 3. Two-name pattern (channel name vs persisted/wire name)

### 3.1 When it applies

You have an event bus where channel names follow a module-prefixed
convention (`cost.ingredient-override-changed`, `agent.action-executed`)
AND a persisted store / external API where names should be
module-agnostic (`INGREDIENT_OVERRIDE_CHANGED` — the cost module doesn't
own ingredient overrides; that prefix leaks ownership).

### 3.2 The pattern

Maintain two names with an explicit map:

```ts
// audit-log/application/types.ts
export const AuditEventType = {
  AI_SUGGESTION_ACCEPTED:    "ai.suggestion-accepted",
  INGREDIENT_OVERRIDE_CHANGED: "cost.ingredient-override-changed",
  // ...
} as const;

export const AuditEventTypeName: Record<keyof typeof AuditEventType, string> = {
  AI_SUGGESTION_ACCEPTED:    "AI_SUGGESTION_ACCEPTED",
  INGREDIENT_OVERRIDE_CHANGED: "INGREDIENT_OVERRIDE_CHANGED",
  // ...
};
```

The bus channel name (`cost.ingredient-override-changed`) preserves module
routing. The persisted `event_type` text column carries the
module-agnostic public name.

### 3.3 Why both

- **Bus channel** is internal infrastructure; module prefix helps
  routing, debugging, and per-module wildcards (`cost.*`).
- **Persisted name** is a public contract (audit consumers, BI exports,
  external integrations); should not change if the event moves to a
  different module.

The two-name pattern lets each name evolve on its own timeline.

## 4. Same-transaction migration with backfill

### 4.1 When it applies

You ship a new table that should be populated at deploy time from
existing legacy sources (e.g. canonical `audit_log` backfilled from 5
per-BC ad-hoc tables; canonical `events` backfilled from `*_history`
tables; etc.).

### 4.2 The pattern

Issue `CREATE TABLE` + every `INSERT INTO ... SELECT FROM legacy` + every
`CREATE INDEX` in **one migration, one transaction**. The operator never
sees a moment where the table exists but is empty.

```typescript
// 0017_audit_log.ts (Knex; same shape applies to alembic, sqlx, prisma)
export async function up(knex: Knex): Promise<void> {
  await knex.transaction(async (trx) => {
    await trx.schema.createTable("audit_log", (t) => { /* columns */ });

    if (await trx.schema.hasTable("ai_suggestions")) {
      await trx.raw(`INSERT INTO audit_log (...) SELECT ... FROM ai_suggestions WHERE accepted_at IS NOT NULL`);
    }
    // ... more backfills with hasTable/hasColumn guards

    await trx.schema.alterTable("audit_log", (t) => {
      t.index(["organization_id", "aggregate_id"]);
      // ...
    });
  });
}
```

### 4.3 Down migration is destructive on purpose

`down` drops the table. The `audit_log`'s data is reconstructable from
the legacy sources during the period the legacy sources still exist; if
you rollback the migration AND drop the legacy sources later, the audit
trail for the transition window is lost. Document this trade-off in the
migration's docstring + ADR.

### 4.4 Reference implementations

- openTrattOS `m2-audit-log` migration `0017_audit_log.ts` — 4 backfill
  sources in one transaction.
- iguanatrader `0003_research_tables` (R1 slice, 2026-05-06) — bitemporal
  fact table created with the same atomic pattern (no backfill in R1
  because there's no legacy source, but the same migration shape lands
  the L2 BEFORE-trigger DDL atomically with table creation).

## 5. `hasTable` / `hasColumn` guards on backfill SELECTs

### 5.1 When it applies

A migration that backfills from legacy sources will be run on:

- **Production**: legacy sources exist; backfill executes.
- **Fresh dev** / **CI**: legacy sources don't exist; backfill must
  silently skip without raising "relation does not exist".

### 5.2 The pattern

```typescript
if (await trx.schema.hasTable("ai_suggestions")) {
  if (await trx.schema.hasColumn("ai_suggestions", "accepted_at")) {
    await trx.raw(`INSERT INTO audit_log ... SELECT ... FROM ai_suggestions WHERE accepted_at IS NOT NULL`);
  }
}
```

Equivalent for SQLAlchemy / alembic:

```python
inspector = inspect(connection)
if "ai_suggestions" in inspector.get_table_names():
    columns = {c["name"] for c in inspector.get_columns("ai_suggestions")}
    if "accepted_at" in columns:
        op.execute("INSERT INTO audit_log (...) SELECT ... FROM ai_suggestions WHERE accepted_at IS NOT NULL")
```

### 5.3 Why guards instead of "fresh-vs-prod" branching

Branching by environment (`if process.env.NODE_ENV === "production"`)
couples migration logic to deploy environment. Guards are environment-
agnostic: the migration introspects what's actually present.

## 6. Open-enum text columns + CHECK over native enums

### 6.1 When it applies

A column that will gain new allowed values across multiple future
migrations (`event_type`, `actor_kind`, `provider`, `tier`, …). Native
Postgres `CREATE TYPE ... AS ENUM` requires a migration to extend; an
open-enum text column requires zero schema change.

### 6.2 The pattern

```sql
CREATE TABLE audit_log (
  ...,
  event_type TEXT NOT NULL CHECK (LENGTH(event_type) BETWEEN 1 AND 100),
  actor_kind TEXT NOT NULL CHECK (actor_kind IN ('user', 'agent', 'system')),
  ...
);
```

Two CHECK styles:

- **Length-only** (`event_type`): the column can hold *any* string of
  reasonable length. New values are added by emitting them. Constants
  file in app code is the source of truth.
- **Value-set with explicit list** (`actor_kind`): the values are
  bounded by a known small set; CHECK lists them exactly. New values
  require a migration to extend the CHECK.

Pick **length-only** when extension is expected per release. Pick
**value-set** when the set is intrinsically bounded (e.g. role in a
3-role RBAC).

### 6.3 The trade-off

App-side typo resistance is the only safety net; the database accepts
`'AI_SUGGESTION_ACCEPETED'` (typo) as valid. Mitigations:

- Constants file (`AuditEventType` / `Role`) is the single emit-side
  truth; tests assert every emit goes through the constants.
- Code review is the rest of the gate.

The trade-off is explicit — pick this pattern *because* you're
trading DB-enforced typo-resistance for migration-free extension.

## 7. Stateless proxy + stateful caller

### 7.1 When it applies

You're integrating a third-party service (LLM router, RAG index, search
engine, …) that:

- Speaks a *different* contract than your application's canonical one.
- Has *its own* state (vector DB, cache, sessions, …) that you don't
  want to inherit, replicate, or audit.

### 7.2 The pattern

Write a thin proxy in front of the third-party that:

1. **Speaks your canonical contract** (`{value, citationUrl, snippet}`,
   `{decision, rationale}`, etc.).
2. **Translates upstream responses** into that contract.
3. **Holds zero application state** — every audit / cache row lives in
   the canonical caller's existing tables.

```python
# tools/rag-proxy/src/rag_proxy/main.py — outline
@app.post("/query")
async def query(req: QueryRequest, auth: AuthDep) -> QueryResponse | NoneResponse:
    # 1. Try authoritative path
    result = await lightrag_client.query(req.prompt)
    extracted = extract_canonical(result)  # translate upstream → contract
    if iron_rule_passes(extracted):
        return QueryResponse(**extracted)

    # 2. Fallback path
    fallback = await brave_client.query(req.prompt) if brave_enabled else None
    if fallback and iron_rule_passes(fallback):
        return QueryResponse(**fallback)

    # 3. Failure-collapse-to-null
    return NoneResponse(reason="no_authoritative_match")
```

The caller (`apps/api`) keeps:

- The audit table (`ai_suggestions` rows for every prompt + response).
- The retry / cache logic at the application layer.
- The discriminator for "manual entry only" UX vs "AI-suggested".

The proxy keeps:

- Zero rows. Restart-safe. Rollback-safe (kill container → caller's
  null path → "manual entry" UX).

### 7.3 Why this beats a fat client library

A fat client lib pulls third-party LLM-prose-parsing + arbitrary HTTP
I/O + retry policy into the canonical caller's process. The proxy
isolates all of that in a separate deployable; the caller's test surface
stays small (mock the proxy, not the underlying service).

### 7.4 Reference implementation

openTrattOS `tools/rag-proxy/` (Wave 1.8, PR #88, 2026-05-06): FastAPI
service translating LightRAG (RAG over corpus) prose responses into the
canonical `{value, citationUrl, snippet}` contract that
`GptOssRagProvider` already expects in `apps/api`. Net TypeScript LOC
change in the apps/api workspace for the integration: **0**.

## 8. Failure-collapse-to-null

### 8.1 When it applies

You're calling an external service from a service whose UX has a
graceful "no result available" state (manual entry, default value,
deferred ask).

### 8.2 The pattern

Every failure mode of the call collapses to **one canonical sentinel**:
`null`, `None`, `Optional.empty`, `null | undefined`, etc. The caller
doesn't need a discriminated error union, doesn't need exception
hierarchy, doesn't need retry policy: just `result | null`.

```typescript
// types.ts
export type AiSuggestion = { value: number; citationUrl: string; snippet: string };

// provider.ts (caller doesn't see error details)
async function getSuggestion(req: Request): Promise<AiSuggestion | null> {
  try {
    const r = await fetch(proxyUrl, { signal: AbortSignal.timeout(5000) });
    if (!r.ok) return null;
    const body = await r.json();
    if (!ironRulePasses(body)) return null;
    return body;
  } catch { return null; }  // network, timeout, abort, parse → all null
}
```

### 8.3 Why this beats a discriminated error union

For UI flows where every failure path leads to the same user state
(e.g. "manual entry only"), discriminating between "network error" /
"4xx" / "5xx" / "parse failed" / "timeout" creates **5 paths that are
visually identical**. The discrimination has no UX value and high
maintenance cost.

The proxy / external service is responsible for **logging the
discriminator server-side** for ops debugging. The caller is responsible
for the user-facing flow, which doesn't need it.

### 8.4 When NOT to apply

- **Critical paths** (payment confirmation, kill-switch deactivation):
  the caller MUST distinguish "service unavailable" from "explicit no".
- **APIs that need retry-with-backoff**: the discriminator informs
  whether retry is correct (5xx retry, 4xx don't). Move the retry to
  the proxy if you want to keep the caller simple.

## 9. Cross-references

- [release-management.md](release-management.md) §6.4 (anti-collision contract for shared files; this spec covers the *shape* of the shared schemas)
- [project-board-sync.md](project-board-sync.md) (audit table is one consumer of these patterns)
- [agent-telemetry.md](agent-telemetry.md) (telemetry traces follow §2 hybrid translation pattern when consuming legacy spans)
- [taxonomy.md](taxonomy.md) (event-bus / channel / envelope canonical names)
- [enforcement-status.md](enforcement-status.md) (live adoption matrix)
- External: openTrattOS retros `m2-audit-log` (Wave 1.9), `m2-ai-yield-corpus` (Wave 1.8), `m2-ai-yield-suggestions` (Wave 1.7) — case studies for §2-§8.
- External: iguanatrader retros `risk-engine-protections`, `approval-channels-multichannel` — pure-engine + canonical-contract case studies for §7-§8.
