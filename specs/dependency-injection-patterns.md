# dependency-injection-patterns.md

> **Status**: v1.0.0 (new in v0.11.0). Defines two cross-language DI patterns surfaced as recurring failures across projects: (1) **provider deduplication** (NestJS `@Global()` doesn't prevent re-declaration in `TestingModule` overrides; Python equivalent: re-binding `Depends(...)` in test fixtures shadows the global), and (2) **seam-then-consume DI tokens** (slice A introduces a DI token + binding; slice B implements without editing slice A). Cross-validated by nexandro m2-mcp-write-capabilities (`payload_before: null` bug), m2-cost-rollup-and-audit (`INVENTORY_COST_RESOLVER` token pattern), and eligia-core ADR-028 (singleton-per-action-class for `request_approval(mode=apply)`).

## 1. Why this spec

DI is not a language-specific concept; the same hazards appear in NestJS, FastAPI, Phoenix, Spring, etc. Two specific failures have **shipped bugs in production code paths** across the projects:

### 1.1 Failure 1: silent provider duplication

nexandro m2-mcp-write-capabilities had a `SharedModule` marked `@Global()` exporting `AuditResolverRegistry`. A `TestAppModule` (used in integration tests) re-declared the registry in its `providers` array — the local declaration won, creating two instances. The MCP server registered handlers to instance A, but route handlers read from instance B. Result: `payload_before: null` for every agent mutation, with no error. Surfaced only when an integration test asserted on the audit row's content.

Lesson: **`@Global()` makes the export visible everywhere but does NOT prevent re-declaration**. The same hazard exists in Python (re-binding a `Depends` callable in `app.dependency_overrides` for tests + forgetting to clear it leaks into adjacent tests) and Phoenix (re-defining a behaviour adapter at runtime via `Application.put_env/3`).

### 1.2 Failure 2: tight coupling at seam introduction

A common cross-slice pattern: slice A introduces a service that slice B will need to extend. The naive approach — "slice A defines the class; slice B inherits + overrides" — produces hard coupling: B can't ship without editing A.

The fluent approach is to ship a **DI token + factory** in slice A, and have slice B provide its own implementation bound to the same token. nexandro m2-cost-rollup-and-audit shipped this as the `INVENTORY_COST_RESOLVER` DI token: m1 introduced the token + a default `M1InventoryCostResolver` implementation; m2 dropped a new `M2InventoryCostResolver` into the cost BC and rebound the token via `useExisting`, with **zero edits to m1's code**.

This spec codifies both patterns + their cross-language equivalents.

---

## 2. Pattern A: Provider deduplication (the `@Global()` rule)

### 2.1 The rule (NestJS)

> **A consumer module that needs a global provider MUST import the providing module, NOT re-declare the provider.**

```ts
// ❌ Forbidden: re-declares the provider locally; local instance wins;
//    global instance becomes unreachable from this consumer.
@Module({
  providers: [AuditResolverRegistry, OrderService],
})
export class TestOrderModule {}

// ✅ Required: imports the providing module; the @Global()-exported
//    provider is the singleton.
@Module({
  imports: [SharedModule],  // SharedModule is @Global() and exports AuditResolverRegistry
  providers: [OrderService],
})
export class TestOrderModule {}
```

### 2.2 Test-setup checklist

In integration tests using `Test.createTestingModule(...)`:

1. **Import the global module** in the test module's `imports` (not the providers list).
2. **Override only providers that need test doubles**, via `.overrideProvider(TOKEN).useValue(fake)`. Don't re-declare the original provider in the same module's `providers`.
3. **Reset between tests**: `AuditResolverRegistry.reset()` (or equivalent) in an `afterEach` hook, OR mark the test module with `imports: [...]` such that NestJS instantiates a fresh module per test (slower but isolation-safe).
4. **Assert the provider is a singleton** by reading the same token from two different modules in a smoke test:
   ```ts
   it('AuditResolverRegistry is a singleton', () => {
     const fromOrder = orderModule.get(AuditResolverRegistry);
     const fromInvoice = invoiceModule.get(AuditResolverRegistry);
     expect(fromOrder).toBe(fromInvoice);  // same instance
   });
   ```

### 2.3 Python equivalent (FastAPI `Depends`)

```python
# Provider definition
@lru_cache
def get_audit_registry() -> AuditRegistry: ...

# ❌ Forbidden: shadowing in test fixture without cleanup
def test_X(client):
    app.dependency_overrides[get_audit_registry] = lambda: FakeAuditRegistry()
    # ... test runs; override leaks to the next test ...

# ✅ Required: scoped override + cleanup
def test_X(client, fake_audit_registry):
    app.dependency_overrides[get_audit_registry] = lambda: fake_audit_registry
    try:
        # ... test runs ...
    finally:
        del app.dependency_overrides[get_audit_registry]
```

The pytest-canonical form is a fixture that yields the override and cleans up:

```python
@pytest.fixture
def override_audit_registry(fake_audit_registry):
    app.dependency_overrides[get_audit_registry] = lambda: fake_audit_registry
    yield fake_audit_registry
    del app.dependency_overrides[get_audit_registry]
```

### 2.4 Class-level cache reset (autouse fixture pattern)

A frequent issue: a singleton holds a per-class cache (e.g. `lru_cache` on a method, or a class-level `_instances: dict`). Test 1 populates the cache; test 2 reads stale data. The autouse fixture pattern:

```python
@pytest.fixture(autouse=True)
def _reset_audit_registry():
    AuditRegistry._cache.clear()
    yield
    AuditRegistry._cache.clear()
```

Drop into the test module; every test in the module gets a fresh cache. Variant for entire test sessions: scope `session` and clear in a `conftest.py`.

This pattern was tracked as a Tier-3 v0.11 deliverable per the iguanatrader retros' carry-forward; codified here in §2.4.

### 2.5 Phoenix / Elixir equivalent (Application config)

```elixir
# config.exs
config :my_app, audit_registry: MyApp.AuditRegistry

# In test_helper.exs or per-test
Application.put_env(:my_app, :audit_registry, MyApp.FakeAuditRegistry)
# ... runs leak across tests in the same VM unless reset ...

# ✅ Reset on test exit
on_exit(fn ->
  Application.put_env(:my_app, :audit_registry, MyApp.AuditRegistry)
end)
```

Phoenix's hazard is identical: global config persists across tests in the same VM. The `on_exit/1` callback is the equivalent of the autouse fixture.

---

## 3. Pattern B: Seam-then-consume DI tokens

### 3.1 The rule

> **When a slice introduces a service that a future slice will replace or extend, define a DI token in the introducing slice; the future slice binds its implementation to the same token, without editing the introducing slice.**

### 3.2 Reference (NestJS)

```ts
// Slice A (m1-cost): defines the token + a default impl
export const INVENTORY_COST_RESOLVER = Symbol('INVENTORY_COST_RESOLVER');

@Injectable()
export class M1InventoryCostResolver implements InventoryCostResolver {
  resolve(itemId: string): Decimal { ... }
}

@Module({
  providers: [
    { provide: INVENTORY_COST_RESOLVER, useClass: M1InventoryCostResolver },
  ],
  exports: [INVENTORY_COST_RESOLVER],
})
export class M1CostModule {}

// Consumer (any slice that needs cost resolution)
@Injectable()
export class RecipeCostingService {
  constructor(@Inject(INVENTORY_COST_RESOLVER) private resolver: InventoryCostResolver) {}
}

// Slice B (m2-cost-rollup-and-audit): drops a new impl, rebinds the token
@Injectable()
export class M2InventoryCostResolver implements InventoryCostResolver {
  resolve(itemId: string): Decimal { ... }  // walks the BOM tree, applies overrides
}

@Module({
  imports: [M1CostModule],  // pulls in the original token + default
  providers: [
    M2InventoryCostResolver,
    {
      provide: INVENTORY_COST_RESOLVER,  // SAME TOKEN; rebinding is the seam
      useExisting: M2InventoryCostResolver,
    },
  ],
  exports: [INVENTORY_COST_RESOLVER],
})
export class M2CostModule {}
```

The consumer (`RecipeCostingService`) is unchanged. Its constructor still receives whatever is bound to `INVENTORY_COST_RESOLVER` — at app boot, M2's binding wins because M2CostModule imports come last. Slice A's code is **never edited** in slice B's PR.

### 3.3 Python equivalent (FastAPI Depends + dependency_overrides)

```python
# Slice A
def get_cost_resolver() -> CostResolver:
    return M1CostResolver()

# Consumer
def costing_service(resolver: CostResolver = Depends(get_cost_resolver)) -> CostingService: ...

# Slice B: drops a new impl + override at app composition time
def get_cost_resolver_v2() -> CostResolver:
    return M2CostResolver()

# In app composition (NOT in slice A's code):
app.dependency_overrides[get_cost_resolver] = get_cost_resolver_v2
```

The override is **not** in the test fixture pattern from §2.3 (which is for tests). For production, the override happens once at app composition root, before `app.run()`. Consumer code is unchanged.

### 3.4 Anti-pattern: inheritance chain instead of token rebinding

```ts
// ❌ Slice B inherits from A's impl + ships
export class M2InventoryCostResolver extends M1InventoryCostResolver { ... }

// ❌ AND THEN edits M1CostModule to use the M2 class:
@Module({
  providers: [
    { provide: INVENTORY_COST_RESOLVER, useClass: M2InventoryCostResolver },  // edit in M1's slice
  ],
})
export class M1CostModule {}
```

Why it's wrong:
- M2's PR diff now spans M1 + M2. Reviewers can't audit M2's logic without parsing M1 changes.
- Reverting M2 requires reverting M1's edit too.
- Tests for M1 now have to mock M2's dependencies because M1's "default" is M2.
- The token was the seam; inheritance hides it inside the class hierarchy.

The token-rebinding pattern keeps slice diffs local and makes the seam structurally visible.

### 3.5 When to introduce a DI token preemptively

Heuristic: **introduce a DI token when a service is plausibly extensible AND has cross-slice consumers.** Don't preemptively token-ify every internal helper. Concrete signals:

- The service is a Protocol per [protocol-fake-deferred-install.md](protocol-fake-deferred-install.md) — already canonical pattern.
- The service is a "policy" (cost resolver, risk evaluator, rate limiter) — likely to evolve.
- The service is consumed by ≥2 bounded contexts.
- The slicing artefact lists a future slice that will "extend" or "replace" this service.

If none of those apply, ship the concrete class — premature DI tokens are overhead.

---

## 4. Singleton-per-action-class (eligia-core ADR-028 pattern)

A specific application of pattern B: the `request_approval(mode=apply)` HITL gating function in eligia-core ADR-028 is a singleton across all rollout actions, but its implementation is bound differently per action class (deploy / secret-rotation / emergency-override).

The pattern:

```python
# Token + base
class ApprovalDispatcher(Protocol):
    async def request_approval(self, action_class: str, payload: dict) -> ApprovalDecision: ...

# Per-action-class implementations
class DeployApprovalDispatcher: ...   # routes via WhatsApp
class SecretRotationApprovalDispatcher: ...  # routes via Hermes pager
class EmergencyOverrideApprovalDispatcher: ...  # routes to on-call

# DI binding (per-tenant or per-environment)
APPROVAL_DISPATCHERS: dict[str, ApprovalDispatcher] = {
    "deploy": DeployApprovalDispatcher(),
    "secret_rotation": SecretRotationApprovalDispatcher(),
    "emergency_override": EmergencyOverrideApprovalDispatcher(),
}

def get_dispatcher(action_class: str) -> ApprovalDispatcher:
    return APPROVAL_DISPATCHERS[action_class]
```

The composition root wires the dictionary; consumers receive the right dispatcher per action class. Adding a new action class is a one-line dict entry, not a class-hierarchy change.

This pattern combines [hitl-approval-pattern.md](hitl-approval-pattern.md) (the HITL contract) with §3 (token rebinding) — different action classes are different "slices" in a logical sense even when they all live in one bounded context.

---

## 5. Anti-patterns

- **Re-declaring `@Global()` providers in consumer module's `providers` array**: forbidden per §2.1.
- **Forgetting `del app.dependency_overrides[X]` after a test override**: forbidden per §2.3.
- **Inheritance chain instead of DI token for cross-slice extension**: forbidden per §3.4.
- **Preemptively token-ifying internal helpers**: forbidden per §3.5 (over-DI is a real cost).
- **Mutating a global registry from a consumer module's constructor**: forbidden — registry mutations are composition-root work, not per-consumer.
- **Different DI tokens for the same logical operation across slices** (`COST_RESOLVER_M1` + `COST_RESOLVER_M2`): forbidden — the token IS the seam; one token per logical operation.

---

## 6. Cross-references

- [protocol-fake-deferred-install.md](protocol-fake-deferred-install.md) — sister pattern: Protocol = the *type* contract; DI token = the *binding* contract.
- [event-and-data-patterns.md](event-and-data-patterns.md) §9 — async event ordering for services that emit events; DI seams often emit on bind/unbind.
- [hitl-approval-pattern.md](hitl-approval-pattern.md) §3 — the approval channel Protocol is the canonical case of this spec applied to HITL gating.
- [release-management.md](release-management.md) §6.6 — intra-slice subagent parallelism; DI seams that are clean across BCs let subagents work independently.

---

## 7. Reference implementations

| Project | Surface | Pattern | Notes |
|---|---|---|---|
| nexandro | `AuditResolverRegistry` | Pattern A (provider dedup) | `@Global()` + `imports: [SharedModule]` discipline; `payload_before:null` bug fixed v0.11 |
| nexandro | `INVENTORY_COST_RESOLVER` | Pattern B (token rebinding) | m1 default → m2 BOM-walking impl; m1 untouched |
| iguanatrader | `LLMClient` | Both | Protocol per `protocol-fake-deferred-install`; `@lru_cache` factory in FastAPI |
| eligia-core | ADR-028 `request_approval` | §4 (singleton-per-action-class) | Action-class-keyed dispatcher dict; routes per class |
| iguanatrader | (P1) `ApprovalChannel` | §4 (singleton-per-channel) | Same pattern, applied to multi-channel HITL routing |
