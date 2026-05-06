# protocol-fake-deferred-install.md

> **Status**: v1.0.0 (new in v0.11.0). Defines the canonical pattern for **isolating heavy / security-sensitive / vendor-locked external SDKs from the slice that needs them**, by shipping the slice with a Protocol interface + an in-tree fake adapter, and deferring the production-SDK install + adapter to a later "deployment" slice. Closes the gap surfaced by **6+ consecutive consumer-e Wave 3 slices** (R5, T2, R3-tier-2/3/4, T2 fake-broker, O2 SchedulerProtocol) all using this pattern ad-hoc + cross-confirmed by consumer-c-legacy Wave 1.7 (recipes service IoC) + consumer-d ADR-018 / ADR-028 (HMAC-sidecar isolation).

## 1. Why this spec

A repeated pattern across consumer-e, consumer-c-legacy, and consumer-d: a slice needs to interact with an external SDK / service / vendor — `anthropic`, `ib_async`, `apscheduler`, `playwright`, `camoufox`, NestJS service-locator, k8s sidecar — but **shipping the production dependency in the same slice is a bad idea** because:

- The dep brings in a security-review surface (API keys, network egress, CSP changes, license-boundary review) that is bigger than the slice's logic.
- The dep blocks local dev / CI on credentialed services (no Anthropic key in PR CI; no IBKR paper account on every dev's laptop).
- The dep is **non-portable** across environments (Playwright needs browser binaries; Camoufox needs MCP stdio; APScheduler needs SQLAlchemy job-store).
- The dep often has heavy install footprint (Playwright = 600 MB browser binaries; reportlab = AGPL transitive concerns).

The pragmatic answer that has emerged across **3 projects + 6+ slices**: ship the slice with **only the Protocol + an in-tree fake**, defer the real SDK + production adapter to a dedicated `deployment-foundation` slice that lands after all consumers of the Protocol exist. The slice ships fully tested against the fake; production install is one PR, one CI gate, one secret-rotation runbook.

The pattern is canonical enough to deserve a named spec + skill template. This document codifies it.

---

## 2. The pattern in three sentences

1. The slice that *needs* the external capability defines a `Protocol` (Python `typing.Protocol`, TypeScript `interface`, or Elixir `behaviour`) capturing the minimal surface it consumes.
2. The slice ships a **single** in-tree fake implementation of that Protocol — deterministic, no I/O, used in tests and in any local-dev path that doesn't need real data.
3. A separate `deployment-foundation` (or similarly-named) slice — landing after all Protocol consumers exist — installs the production SDK, writes a thin adapter satisfying the Protocol, and wires secret-handling. The Protocol → real-adapter swap is the only surface that slice touches in the Protocol's domain.

---

## 3. When the pattern applies

Use the pattern when ALL of the following hold:

| Condition | Why it matters |
|---|---|
| The dep brings in **credentials**, **network egress**, or **filesystem-mutating** behaviour. | These are the surfaces that need security review; isolating them lets the review happen once at install time, not N times across N consumer slices. |
| The dep has **>1 in-tree consumer** OR is expected to grow consumers within the project's roadmap. | If only ONE slice ever uses the dep, an in-tree fake is overhead — just install the dep in that slice. |
| The dep is **vendor-specific** (i.e. a Protocol could plausibly be satisfied by a different vendor in v2). | Protocol gives swap-room; if the slice will *always* use vendor X, the abstraction is premature. |
| The dep's **production install adds CI minutes / image size / license-boundary checks** that you don't want on every consumer slice's PR. | Think Playwright (600 MB browser binaries), reportlab (BSD but AGPL-transitive), ib_async (paper-account requirement). |

**Don't use the pattern when:**

- The dep is a pure-Python utility library with no I/O (e.g. `pydantic`, `httpx` for one-off internal calls — just import it).
- The dep is already the project's framework (e.g. don't wrap `FastAPI` in a Protocol; FastAPI IS the framework).
- There's exactly one consumer and no plan for a second — you'd be paying the indirection cost for nothing.

---

## 4. The four artefacts of the pattern

For each Protocol-isolated capability, the slice that introduces it produces exactly four things:

### 4.1 The Protocol

A minimal interface capturing **only the methods the consumers actually call**. Examples:

```python
# apps/api/src/consumer-e/contexts/research/synthesis/llm_client.py
from typing import Protocol

class LLMClient(Protocol):
    async def generate(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> str: ...
```

Discipline:

- **No transitive types** from the vendor SDK in the Protocol signature (no `anthropic.types.MessageParam`; use `str` / `dict[str, str]` / project-local DTOs).
- **No vendor-specific kwargs** that aren't usable from the fake (e.g. `top_p`, `stop_sequences` only if the fake honours them; otherwise out).
- **One method per logical operation**, not one method per SDK call (the Protocol describes the slice's intent, not the SDK's API).

### 4.2 The in-tree fake

A single deterministic implementation living under the slice's bounded context:

```python
# apps/api/tests/_fakes/llm_client.py
from typing import Mapping

class FakeLLMClient:
    def __init__(self, canned: Mapping[str, str] | None = None) -> None:
        self._canned = canned or {}

    async def generate(self, prompt: str, *, model: str, max_tokens: int, temperature: float = 0.0) -> str:
        for key, value in self._canned.items():
            if key in prompt:
                return value
        return f"<fake-llm-response model={model} prompt-hash={hash(prompt) & 0xffff:04x}>"
```

Discipline:

- **No I/O**: no HTTP, no filesystem writes (a fake that writes a tmp file is harder to parallelise and slower than an in-memory one).
- **Deterministic**: same inputs → same outputs. If randomness is needed (e.g. simulating retry-after), accept a `seed` constructor arg.
- **Failure injection** is explicit: `connect_failures: int = 0`, `heartbeat_failures: int = 0`, etc. The Protocol's production adapter has retry logic; the fake lets tests exercise that retry logic.
- **One fake per Protocol**, not "FakeLLMClient + FakeAnthropicClient + FakeOpenAIClient". The Protocol is single-vendor at the surface even if the production adapter could swap vendors.

### 4.3 The DeferredProductionInstall marker

Every slice that introduces a Protocol + fake MUST add a marker entry to the project's `docs/openspec-slice.md` "Deferred installs" section (new in v0.11). Schema:

```markdown
## Deferred installs

| Protocol | Defining slice | Production slice | Production dep | License | Notes |
|---|---|---|---|---|---|
| `LLMClient` | research-brief-synthesis | deployment-foundation | `anthropic ^0.40` | MIT | Wraps `AsyncAnthropic.messages.create()` with `@cost_meter`. |
| `IBClient` | ibkr-adapter-resilient | deployment-foundation | `ib_async ^1.0` | MIT | No `@cost_meter` (broker calls unbilled). |
| `SchedulerProtocol` | orchestration-scheduler-routines | deployment-foundation | `apscheduler ^3.10` | MIT | `AsyncIOScheduler` + SQLAlchemyJobStore. |
| ... |
```

The defining slice's `proposal.md` MUST cite the row in its "Out of scope" section ("Production wiring deferred to deployment-foundation per docs/openspec-slice.md Deferred installs row 1"). The deployment slice's `proposal.md` reads the table top-down and ships one adapter per row.

This makes the deferred work **discoverable**: the deployment-slice author doesn't need to grep for `Protocol` declarations across the codebase.

### 4.4 The production adapter (lands in deployment slice)

When the deployment slice runs, it ships **one adapter per Deferred-installs row**:

```python
# apps/api/src/consumer-e/contexts/research/synthesis/anthropic_client.py
from anthropic import AsyncAnthropic
from consumer-e.observability.cost_meter import cost_meter

class AnthropicLLMClient:
    """Production LLMClient adapter wrapping Anthropic SDK with cost-metering."""

    def __init__(self, api_key: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)

    @cost_meter("anthropic")
    async def generate(self, prompt: str, *, model: str, max_tokens: int, temperature: float = 0.0) -> str:
        msg = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
```

Discipline:

- **Adapter only**: no business logic. If the slice that consumed the Protocol pushed business logic INTO the Protocol (e.g. retry decisions in the Protocol method body), refactor: business logic stays in the consumer; the adapter is mechanical SDK translation.
- **One file per adapter**, named `<vendor>_<protocol>.py` (e.g. `anthropic_client.py`, `ib_async_client.py`).
- **Cost metering / observability decorators applied here**, not in the Protocol or the fake. The decorator stack is a deployment-slice concern.
- **Secret reading happens at construction**, never at method-call time. The deployment slice's DI wires `os.environ["ANTHROPIC_API_KEY"]` (or SOPS-decrypted equivalent) into the adapter once at startup.

---

## 5. Cross-language guidance

The pattern is language-agnostic. Concrete recipes per stack:

### 5.1 Python (Protocol via `typing.Protocol`)

- Protocol: `class LLMClient(Protocol): ...` with `...`-bodied method signatures.
- Fake: plain class implementing the Protocol's methods. No `@runtime_checkable` decorator (we don't `isinstance` against the Protocol — we use mypy --strict structural subtyping).
- Production adapter: plain class with explicit constructor accepting credentials.
- DI wiring: `Annotated[LLMClient, Depends(...)]` in FastAPI, or a `@dataclass` service composition root for non-web entrypoints.

### 5.2 TypeScript / NestJS (interface + DI token)

- Protocol: `interface LLMClient { ... }`.
- Fake: `class FakeLLMClient implements LLMClient { ... }`.
- Production adapter: `class AnthropicLLMClient implements LLMClient { ... }`.
- DI: NestJS `useFactory` / `useExisting` with a string DI token (`'LLM_CLIENT'`) or `Symbol`. Inject via `@Inject('LLM_CLIENT')`.
- **Critical**: per the consumer-c-legacy m2-mcp-write-capabilities retro, `@Global()` modules do NOT prevent re-declaration in `TestingModule` overrides — the local declaration wins. **Always import the providing module** (e.g. `imports: [SharedModule]`); never re-declare `@Global()` providers in a consumer module. See [dependency-injection-patterns.md](dependency-injection-patterns.md) for the full rule.

### 5.3 Elixir (behaviour + DI via Application config)

- Protocol: `@callback generate(String.t(), keyword()) :: String.t()` in a `behaviour`.
- Fake: a module with `@behaviour LLMClient` implementing the callbacks.
- Production adapter: same pattern, against the production SDK.
- DI: `Application.get_env(:my_app, :llm_client, FakeLLMClient)` — the production environment overrides the fake via release config.

### 5.4 Cross-language: the pattern is the same

Regardless of language, the four artefacts (Protocol / fake / DeferredInstall row / production adapter) and their disciplines (no transitive types, deterministic fake, adapter-only production code) are stable. Only the language-specific syntax for "interface" and "DI" changes.

---

## 6. The deployment slice

A single `deployment-foundation` (or similarly-named) slice consolidates all production adapter installs. Its `proposal.md` is structured around the "Deferred installs" table:

- **Why** — N Protocol-consuming slices have shipped without their production deps; this slice unblocks production deploy.
- **What changes** — one bullet per Deferred-installs row: install dep in `pyproject.toml` / `package.json`; ship adapter at `<consumer>/<...>/<vendor>_<protocol>.py`; wire DI binding from Protocol to adapter.
- **Capabilities** — none new; pure-wiring slice (the consumer slices already shipped the capability).
- **Impact** — deps audit (license check, image-size delta), secret-handling primitives, license-boundary CI verifies all new deps are non-AGPL (or correctly isolated to AGPL-allowed boundaries).
- **Acceptance** — every Protocol → ProductionAdapter swap lands AND its construction is tested with mocked secret env AND any license-boundary CI is green AND a secret-rotation runbook exists.

The deployment slice is **necessarily late** in the wave order — after all Protocol consumers exist. consumer-e's roadmap puts it as Wave 4 (after Wave 3 ships R5/T2/R3/O2/T3); consumer-c-legacy's equivalent is the production-deploy phase post-MVP.

---

## 7. Anti-patterns

- **Defining a Protocol in slice X, importing it from slice Y BEFORE slice X merges**: forbidden. Y has a circular dependency on X via the Protocol. Either Y waits, or the Protocol moves to a shared `ports.py` module that both X and Y import (in which case the slice that owns `ports.py` is a Wave 0 / shared-primitives slice).
- **Production SDK referenced in any in-tree consumer test**: forbidden. Tests use the fake. If a test needs vendor-specific behaviour, that's an integration test in the deployment slice, not a unit test in the consumer slice.
- **Fake with hidden I/O (writing to /tmp, hitting localhost, etc.)**: forbidden. The fake's purpose is determinism + parallelisability; I/O kills both.
- **Multiple fakes per Protocol** (`FakeLLMClient` + `BrokenLLMClient` + `SlowLLMClient`): forbidden. One fake with explicit failure-injection knobs (`connect_failures`, `delay_ms`, etc.) covers all test scenarios.
- **Deferred-installs table missing rows**: forbidden. Every Protocol introduced by a slice MUST appear in the table at the time the slice's `proposal.md` is approved. Forgetting a row means the deployment slice's author doesn't know about the Protocol.
- **Deployment-slice adapter with business logic**: forbidden. If the production adapter feels like it's "doing more than mechanical translation", the consumer slice's Protocol is wrong — refactor the consumer to push the logic out of the Protocol.
- **Secret-handling logic in the Protocol or the fake**: forbidden. Secrets enter at adapter-construction time; the Protocol describes the operation, the fake is deterministic.

---

## 8. Cross-references

- [migration-slot-reservation.md](migration-slot-reservation.md) — the deployment slice often consolidates migration slots from N consumer slices; the slot reservations help track which are already in tree.
- [dependency-injection-patterns.md](dependency-injection-patterns.md) — DI conventions for wiring Protocol → adapter (especially the @Global() dedup rule from consumer-c-legacy).
- [hitl-approval-pattern.md](hitl-approval-pattern.md) — sister pattern: HITL gating for mutations is also Protocol-isolated (the approval channel is a Protocol; production wiring is per-channel).
- [release-management.md](release-management.md) §6.4 — anti-collision contract that the Deferred-installs table extends.
- [bmad-openspec-bridge.md](bmad-openspec-bridge.md) §3 — slicing artefact schema, extended with "Deferred installs" section.

---

## 9. Reference implementations

| Project | Slice | Protocol | Fake | Production adapter (deployed) |
|---|---|---|---|---|
| consumer-e | research-brief-synthesis | `LLMClient` | `FakeLLMClient` | `AnthropicLLMClient` (deployment-foundation) |
| consumer-e | ibkr-adapter-resilient | `IBClient` | `FakeIBClient` | `IbAsyncIBClient` (deployment-foundation) |
| consumer-e | orchestration-scheduler-routines | `SchedulerProtocol` | `InMemoryScheduler` | `APSchedulerAdapter` (deployment-foundation) |
| consumer-e | research-news-catalysts-adapters | `ScrapeTier2Port` (and 3/4) | `Tier2StubFake` (raises `ScrapeNotImplementedError`) | `Tier2PlaywrightClient` (deployment-foundation) |
| consumer-c-legacy | m2-recipes-core | `IngredientCostResolver` | (test stub) | `M1InventoryCostResolver` (m2-cost-rollup) |
| consumer-d | ADR-018 (sidecar webhook) | HMAC-validated webhook port | (mock HTTP server) | systemd-managed sidecar (operator-driven) |

The pattern compounds: each new project that adopts ai-playbook v0.11+ should expect 3-6 Protocol-isolated capabilities by Wave 3; the deployment slice resolves all of them in one PR.
