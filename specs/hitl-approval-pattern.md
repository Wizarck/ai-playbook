# hitl-approval-pattern.md

> **Status**: v1.0.0 (new in v0.11.0). Defines the canonical pattern for **human-in-the-loop (HITL) gating of state-mutating actions in single-operator AI-driven systems** — covering broker order submission, production deploys, secret rotations, kill-switch toggles, and any other "action that humans must approve before the AI commits". Cross-validated by **iguanatrader P1 (Telegram order-approval channel)** + **eligia-core ADR-028 (HITL-gated CI/CD rollouts via WhatsApp/WABA-MCP)** + **palafito-b2b CONTEXT.md (no auto-deploy to production; operator-gated)** = 3 projects converging on the same pattern.

## 1. Why this spec

Single-operator AI systems (no team to peer-review, no multi-tenant blast radius diluted by N customers' usage patterns) face a specific risk class: **the AI takes a mutating action that the operator would have caught**. Examples seen in retros:

- An IBKR order with the wrong side (BUY when the strategy emitted SELL) because the proposal serialiser swapped fields.
- A k8s rollout to production with a half-baked image because the build pipeline marked "ready" prematurely.
- A secret rotation that left the previous credential active beyond its rotation window because the cleanup step failed silently.
- An auto-deploy that bypassed a known-broken env (`VERIFACTU_ENABLED=true` on a tenant with no AEAT registration).

In each case, the AI's local check (typecheck, unit test, dry-run) said "OK"; what was missing was an operator's eyeball confirming "yes, this is what I asked for". The pattern that has emerged across the three projects is:

> **Gate state-mutating actions on an asynchronous human approval delivered via a chat channel (Telegram / WhatsApp / Slack / Hermes) with HMAC-validated reply correlation.**

This spec codifies the contract — channels, payload schema, HMAC, TTL, fallback ladder, telemetry — so that any future project (or any new mutation class within an existing project) can adopt it as a drop-in pattern.

This is **NOT** a CI/CD review-gate spec. Branch protection + AI-reviewer + CodeRabbit + human Gate F (per [release-management.md](release-management.md) §4.5) cover the *code change* side. This spec covers the **runtime mutation** side, which kicks in after the code has merged.

---

## 2. The pattern in three sentences

1. The AI service produces an **approval request** (a fully-formed payload describing the proposed mutation: type, target, parameters, expected effect) and writes it to the project's `approvals` (or equivalently named) durable table.
2. The approval is delivered to the operator via **a primary chat channel** with an HMAC-signed correlation token and **a fallback channel** (different transport) for primary-channel failure.
3. The operator's reply (Approve / Reject / Defer) is HMAC-validated, persisted as the `approval_decision`, and triggers the AI's next step: execute on Approve, drop on Reject, re-queue on Defer (with TTL-bounded re-asks).

The AI **never** mutates production state without an approved decision row. If the TTL expires without a decision, the request escalates per a project-defined ladder (page on-call, email, ticket).

---

## 3. The five Protocol artefacts

For each HITL-gated mutation class, the project ships:

### 3.1 The mutation request DTO

A typed payload describing the proposed mutation, designed to be **read on a phone screen**:

```python
@dataclass(frozen=True)
class TradeProposalRequest:
    proposal_id: UUID
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: Decimal
    order_type: Literal["MARKET", "LIMIT", "STOP"]
    limit_price: Decimal | None
    risk_eval_summary: str   # 1-2 line human-readable risk evaluation
    strategy_name: str
    expected_effect: str     # "Enter long position; risk: $250 max-loss; ATR-based stop @ $142.50"
    requested_at: datetime   # UTC ISO 8601
    ttl_seconds: int         # how long the operator has to decide; 600 typical, 7200 max
```

Discipline:

- **Self-contained**: the operator approving on a phone walk has no terminal access; the payload alone must be enough to decide.
- **No internal IDs without context**: `proposal_id` is fine because the reply correlates by ID, but `model_id=42` without a name is not actionable.
- **Money fields are `Decimal`, not `float`**, per AGENTS.md universal rule across all projects.
- **Dates are ISO 8601 UTC**, per AGENTS.md universal rule.

### 3.2 The approval channel Protocol

Per [protocol-fake-deferred-install.md](protocol-fake-deferred-install.md), the channel is a Protocol with a fake for tests:

```python
class ApprovalChannel(Protocol):
    async def request_approval(
        self,
        request: TradeProposalRequest,
        *,
        correlation_token: str,  # HMAC-signed
    ) -> None: ...
    # Replies arrive asynchronously via webhook → call decision-router; not method-call API.
```

Production adapters: `TelegramApprovalChannel` (iguanatrader P1), `WABAMcpApprovalChannel` (eligia-core ADR-028), `SlackApprovalChannel` (potential future).

Fakes: `InMemoryApprovalChannel` for tests, configurable to auto-approve / auto-reject / hang-until-TTL for failure-mode tests.

### 3.3 The HMAC-validated reply correlation

The correlation token is the HMAC-SHA256 of `proposal_id + nonce + project_secret`. The reply payload (Telegram callback_query, WhatsApp interactive button, Slack action) carries the token; the decision router validates the HMAC before persisting.

This prevents:
- **Replay attacks**: an attacker who saw a past Approve message can't reuse it for a new proposal (different proposal_id → different token).
- **Forgery**: a third party who knows the bot's chat_id can't forge an Approve without the project_secret.
- **Cross-tenant leakage**: in multi-tenant deployments, the project_secret is per-tenant; tokens from tenant A don't validate in tenant B.

The shared secret is stored encrypted (SOPS / Kubernetes Secret / project-specific KMS) and rotated on a defined schedule (operator runbook).

### 3.4 The decision persistence

Every request has an `approval_decisions` row created on reply (or on TTL expiry). Schema:

```sql
CREATE TABLE approval_decisions (
    id UUID PRIMARY KEY,
    request_id UUID NOT NULL REFERENCES approval_requests(id),
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected', 'deferred', 'expired')),
    decided_by TEXT,        -- the operator's chat handle, email, or 'system' for expiry
    decided_at TIMESTAMPTZ NOT NULL,
    rationale TEXT,         -- optional free-text from the reply (Telegram allows reply-text on inline-keyboard via bot conversation; WhatsApp via subsequent message)
    correlation_token_hmac TEXT NOT NULL  -- the validated HMAC; archived for audit
);
```

Append-only. No `UPDATE`s; if the operator wants to reverse a decision, they emit a *new* request (compensating action), not an edit of the past row.

### 3.5 The TTL + escalation ladder

Each request type declares a TTL. On expiry:

1. **Default ladder**: re-ask once (re-publish to primary channel). If still no reply within `TTL/2`, fall back to secondary channel.
2. **Hard expiry**: persist `decision='expired'`. The mutation does NOT proceed. The AI MUST log `approval.request.expired` telemetry and emit an alert (project-defined: PagerDuty page, email, or Hermes-routed message to on-call).
3. **Project-specific overrides**: high-risk mutations (e.g. live broker orders) MAY have shorter TTLs (60s) and direct-to-pager escalation; low-risk mutations (e.g. weekly review PDF generation) MAY have longer TTLs (12h) and email-only escalation.

The TTL is part of the request DTO so the operator's chat client can show "expires in 4m 32s" — important for operator UX during off-hours.

---

## 4. Channel ladder (project-portable)

A canonical 3-tier channel ladder, ordered by latency + reliability:

| Tier | Channel | Latency | Use case |
|---|---|---|---|
| **Primary** | Operator's preferred always-on chat (Telegram for hobby projects, WhatsApp via WABA-MCP for B2B, Slack for team-scale) | Seconds | Default for all approval requests. |
| **Secondary** | Hermes / on-call paging system (PagerDuty, Opsgenie) | Tens of seconds | Fallback when primary is down OR for high-priority mutations. |
| **Tertiary** | Email + ticket | Minutes-hours | Hard expiry escalation; audit trail. |

The ladder is project-discretionary but **at least two tiers** are mandatory (single-channel deployment is fragile — a phone battery dying becomes a missed approval).

---

## 5. Cross-project taxonomy of mutations requiring HITL

A non-exhaustive list, drawn from the three projects:

### 5.1 Trading / financial

- Live broker order submission (iguanatrader Wave 4 T4).
- Position close / stop-loss override.
- Capital allocation increase beyond a per-tenant cap.

### 5.2 Production deployment

- Image promotion to production (eligia-core ADR-028: WABA-MCP-routed approval before ArgoCD sync).
- Database migration on a live tenant (palafito-b2b: explicit operator click; no auto-apply).
- Feature flag flip that affects user-visible behaviour in production.

### 5.3 Secrets / access

- Secret rotation when the rotation requires manual coordination (e.g. IBKR paper → live credential swap).
- Service account key generation that grants new RBAC scopes.

### 5.4 Destructive / irreversible

- Tenant deletion / data purge (any project with multi-tenant schema).
- Backup restore on a non-test environment.
- DNS cutover.

### 5.5 Out of scope (no HITL needed)

- Idempotent reads (queries, dashboard renders).
- Internal transitions in a request lifecycle (e.g. `proposal → risk_evaluated` IS automated; `risk_evaluated → approved_for_execution` IS HITL).
- Ephemeral logging / observability writes.

The taxonomy is project-discretionary; each project's `AGENTS.md` MUST list the mutation classes it gates.

---

## 6. Failure modes this spec prevents

### 6.1 Auto-execution after a "looks fine" silent failure

Without HITL: a proposal that passes risk evaluation but conflicts with a hand-set position cap (operator changed the cap last night, AI hasn't re-read the env) executes → over-leveraged position. With HITL: the operator sees "BUY 1000 AAPL" + "current position: 800 AAPL"; the human notices the cap and rejects.

### 6.2 Replay attack on past approvals

Without HMAC: an attacker who scraped the Telegram channel could replay an old "Approve" callback → trades a stale proposal. With HMAC tied to `proposal_id`: the replay produces a different token; validation fails.

### 6.3 Operator phone offline → indefinite hold

Without TTL + ladder: the AI waits forever; the proposal becomes stale; market moves; intent is lost. With TTL + escalation: the proposal expires cleanly, the operator gets a paged alert, post-mortem follows.

### 6.4 Approval bypass via direct DB write

Without persisted `approval_decisions` table + foreign-key gate on the mutation: a bug in the AI could mutate state without an approved row. With the FK gate at the DB layer (e.g. `orders` rows REQUIRE a non-NULL `approval_decision_id`), the database itself blocks unauthorised writes.

---

## 7. Telemetry

Every project implementing this pattern emits these structured events (per [agent-telemetry.md](agent-telemetry.md)):

| Event | When | Required fields |
|---|---|---|
| `approval.request.created` | Request DTO persisted + sent to primary channel | request_id, mutation_class, ttl_seconds, primary_channel |
| `approval.decision.received` | HMAC-validated reply persisted | request_id, decision, decided_by, primary_channel_latency_ms |
| `approval.request.escalated` | Primary TTL elapsed; fallback channel invoked | request_id, fallback_channel |
| `approval.request.expired` | Hard TTL elapsed; no decision | request_id, mutation_class, escalation_path |
| `approval.hmac.invalid` | Reply received with invalid HMAC | request_id, source_handle, reason |

These events feed dashboards (mutations-pending, decision-latency p50/p95, expired-rate) and audit log (every mutation has a chain of events from request to decision to execution).

---

## 8. Anti-patterns

- **Auto-approve in tests bypassing HMAC**: forbidden. Tests use `InMemoryApprovalChannel` which short-circuits without invoking HMAC validation; production code path always validates HMAC.
- **Skipping the durable `approval_requests` row**: forbidden. The row is the source of truth; a request that lives only in the chat channel is invisible to dashboards and audit.
- **In-band approval via terminal command** (e.g. `iguanatrader trading approve <id>`): forbidden as the *primary* path because it bypasses the chat-channel audit trail. ALLOWED as a manual-override fallback (operator runbook only) with explicit telemetry tagging it as `decided_by='cli-override'`.
- **Channel-credentials in repo**: forbidden. Telegram bot tokens, WABA tokens, Slack OAuth secrets are SOPS-encrypted (or KMS-managed); never in plaintext in `.env.example` or commit history.
- **Mutating state on partial decision data**: forbidden. The decision row's `decision` field MUST be `'approved'` (not `'received'` / `'pending-confirmation'`) before the mutation proceeds. No "tentative approve, will firm up after second click".
- **Operator approving via email link**: forbidden as primary path; allowed as tertiary escalation only. Email is too high-latency for time-sensitive mutations and lacks the structured callback pattern.
- **Skipping HITL for "trivial" mutations because the operator complained about volume**: forbidden. The fix is to broaden the "no HITL needed" taxonomy (§5.5) or to reduce false-positive proposals upstream — never to let critical mutations flow without a check.

---

## 9. Cross-references

- [protocol-fake-deferred-install.md](protocol-fake-deferred-install.md) — the channel Protocol pattern this spec follows.
- [release-management.md](release-management.md) §4.5 — code-change review gates (sibling, not substitute).
- [agent-telemetry.md](agent-telemetry.md) — telemetry event schema referenced in §7.
- [notification-policy.md](notification-policy.md) — channel routing for non-approval notifications.
- [notification-queue.md](notification-queue.md) — durable queue for notifications, sister contract.
- [break-glass.md](break-glass.md) — the operator's runbook for genuine emergencies that bypass HITL (with mandatory post-event review).

---

## 10. Reference implementations

| Project | Mutation class | Primary channel | Fallback | TTL |
|---|---|---|---|---|
| iguanatrader (P1 + Wave 4 T4) | Live broker order submission | Telegram (operator-personal bot) | Hermes paging | 600s |
| iguanatrader (P1) | Risk eval override (per-symbol) | Telegram | Email + ticket | 7200s |
| eligia-core (ADR-028) | k8s production rollout | WABA-MCP (WhatsApp Business) | PagerDuty | 7200s (12h off-hours absorbed) |
| eligia-core (ADR-028) | secrets.env deploy | WABA-MCP | Email + ticket | 12h |
| palafito-b2b | Tenant production deploy | WABA-MCP | Email | 24h |

The pattern compounds: each new project that adopts ai-playbook v0.11+ should pre-define its mutation taxonomy + channel ladder during BMAD Phase 2 (Architecture / ADRs), so no Wave-3 slice ever ships an auto-mutating action without HITL gating.
