# multi-layer-defense-single-operator.md

> **Status**: v1.0.0 (new in v0.11.0). Defines the canonical layered-defense pattern for **single-operator AI-driven systems where the operator IS the only safety net**. Cross-validated by eligia-core ADRs 017 (single PAT), 018 (sidecar HMAC), 019 (ServiceAccount RBAC), 020 (NetworkPolicy egress), 024 (no-undo-restart) + palafito-b2b `MERGE-ORDERS-SECURITY-AUDIT.md` (zero-permission plugin fork).

## 1. Why this spec

Multi-tenant SaaS with N customers absorbs operator mistakes via the law of large numbers — a botched mutation affects one tenant; the rest are insulated. **Single-operator AI systems do not have that luxury**: a botched mutation by the AI affects the operator's only environment.

The pattern that has emerged across eligia-core (5 ADRs about defense-in-depth) and palafito-b2b is **explicit layering**: every state mutation passes through ≥3 independent gates, each addressing a different failure mode. Defense-in-depth is not a buzzword — it's an enumeration of failures the operator has already paid for once.

This spec captures the canonical 5-layer pattern for **operator-gated AI infrastructure**: identity → ingress → network → state → ergonomic. Each layer is independently meaningful (dropping one doesn't degrade the others' value); together they form the practical security floor for single-operator AI systems.

This spec **complements** [hitl-approval-pattern.md](hitl-approval-pattern.md) (which gates the runtime mutation itself) by codifying the *infrastructure* gates that keep the AI in scope before any mutation request reaches the operator.

---

## 2. The five layers

| Layer | What it gates | Example mechanism (eligia / palafito) |
|---|---|---|
| **L1 — Identity** | Who is calling the AI / system at all | Cloudflare Access (OAuth → personal email); single PAT (ADR-017); zero-permission GH App for plugin |
| **L2 — Ingress** | Authenticated payloads only past the perimeter | HMAC-validated webhook (ADR-018); admin-token bearer auth on internal endpoints |
| **L3 — Network** | Outbound destinations the AI may reach | NetworkPolicy egress allowlist (ADR-020); CSP for browser-side; firewall rules |
| **L4 — State (RBAC)** | What the AI's process is permitted to mutate | ServiceAccount + namespace-scoped Role (ADR-019); zero-permission DB grants for plugin user (palafito audit) |
| **L5 — Ergonomic** | Per-action confirm-twice for irreversible mutations | Confirm-twice modal + visual lock (ADR-024); CI gate for `apt remove`; `--yes` flag explicit |

The layers are **layered**, not redundant. L1 alone (only identity) leaves the AI's process with full RBAC; an L1-bypassed attacker has superuser. L1+L4 (identity + RBAC) leaves egress open; an attacker who pwns the AI's runtime can exfiltrate data. L1+L4+L3 closes egress; an attacker can still flood the perimeter. L1+L2+L3+L4 covers the technical surface; L5 catches operator typos that the technical layers can't see (the operator typed `prod` when they meant `staging`).

---

## 3. When the pattern applies

Apply when the system is:

- **Single-operator** (no team rotation; operator is the only human in the loop).
- **AI-driven** (mutations are proposed by an LLM-based agent, not manually written).
- **Mutating production state** (deploys, secret rotations, broker orders, tenant data writes).
- **Reversibility-asymmetric** (some mutations are easy to revert — log writes, cache invalidations; some are hard — data deletes, deployed image rollbacks with state migrations).

Don't apply when:

- The system is read-only.
- The system has multi-tenant isolation that absorbs blast radius (a SaaS with N tenants has different threat-model economics).
- The mutation surface is fully idempotent + auto-rollback-capable (a stateless service behind a load balancer with green-blue deploys).

---

## 4. Per-layer guidance

### 4.1 L1 — Identity

- **One identity per actor**: the AI has one identity (its service account), the operator has one (their personal account); never share.
- **Time-bounded credentials**: PATs expire on a schedule; rotation is a runbook step, not "click renew when the alert fires".
- **Zero plugins / forks with elevated permission**: per palafito audit, the plugin's WordPress role is "subscriber" (zero edit permission); admin operations go through the operator's account, not the plugin's.

### 4.2 L2 — Ingress

- **HMAC over signed timestamps**: prevents replay attacks. Timestamp window: 5 minutes (long enough for clock drift; short enough to limit replay).
- **Allowlist over blocklist**: ingress accepts known senders; everything else 403s. New senders are an explicit operator action.
- **No "local-only" services exposed via reverse proxy**: if a service was designed for localhost, it stays localhost; the proxy adds attack surface without value.

### 4.3 L3 — Network

- **Egress allowlist by FQDN, not IP**: cloud provider IP space changes; FQDNs are stable.
- **Per-pod NetworkPolicy** (k8s) or per-process firewall rules (bare metal): scope egress to the bare minimum the workload needs.
- **No "open internet" pods**: if a pod genuinely needs broad internet (LLM inference, package install at startup), document the rationale in an ADR; review periodically.

### 4.4 L4 — State (RBAC)

- **ServiceAccount per service**: never share across services.
- **Namespace-scoped Role over cluster-wide ClusterRole**: scope down by default.
- **Negative-list verification**: list what the SA CANNOT do (verify by attempted `kubectl auth can-i` calls); not just what it can do. The negative list is shorter and more meaningful for audits.

### 4.5 L5 — Ergonomic

- **Confirm-twice for irreversible mutations**: per ADR-024 — modal prompt with cooldown delay before the second click. Pattern is well-known UX; codified here as required for "no undo" actions.
- **Visual lock on resource state**: while a mutation is in flight, the UI shows "locked, in progress, do not retry" — eliminates the double-submit class of bugs.
- **CLI flags `--yes` / `--confirm` are explicit**: never auto-supplied even by automation; the automation script has the operator's eyeball at script-write time.

---

## 5. Decision heuristic: when each layer is warranted

Not every system needs all 5 layers. The decision matrix:

| If the system... | Need L1? | L2? | L3? | L4? | L5? |
|---|---|---|---|---|---|
| ...is internet-exposed | ✅ | ✅ | ✅ | ✅ | ✅ |
| ...is internal-only with privileged operations | ✅ | ✅ | ✅ | ✅ | ✅ |
| ...is internal-only with read-only operations | ✅ | (optional) | (optional) | ✅ | (skip) |
| ...is a one-shot CLI tool (no daemon) | ✅ (host auth) | (skip) | (skip) | (skip — implicit via shell user) | ✅ for irreversibles |
| ...is a fully-static dashboard | ✅ | (skip) | (skip) | (skip) | (skip) |

The systems that need all 5 layers are **the same systems that warrant a HITL gating spec** ([hitl-approval-pattern.md](hitl-approval-pattern.md)) — both kick in for "irreversible state mutation in a single-operator AI system".

---

## 6. Anti-patterns

- **Single-layer defense ("we have HMAC, we're fine")**: forbidden. HMAC alone is L2; an attacker who pwns the AI's runtime is past L2 with valid signatures.
- **Layers that depend on each other** (e.g. L4 RBAC checks the L1 identity but only via a header that L2 doesn't validate): forbidden. Each layer validates independently; an attacker who bypasses L1 doesn't automatically get past L4.
- **"Audit-only" layers**: forbidden if the system has irreversible mutations. Audit logs catch mistakes after they happen; defense layers prevent them. Audit complements, never replaces.
- **Skipping L5 because "the AI is careful"**: forbidden. AIs are sometimes careful; operators sometimes typo. L5 is for the human, not the AI.
- **L3 egress that allows `*` (any FQDN)**: forbidden — that's not L3, that's L0.

---

## 7. Cross-references

- [hitl-approval-pattern.md](hitl-approval-pattern.md) — runtime gating (sister spec).
- [break-glass.md](break-glass.md) — the operator's escape valve when defenses interfere with a genuine emergency.
- [post-mortem.md](post-mortem.md) — when a defense layer fails, postmortem.
- [security-policy.md](data-retention.md) (related) — data-retention rules; a layer above is "what data even exists for the AI to mutate".
- External: eligia-core ADRs 017/018/019/020/024 (one ADR per layer in the original analysis).

---

## 8. Reference implementations

| Project | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|
| eligia-core | Cloudflare Access (OAuth) + single PAT (ADR-017) | sidecar HMAC (ADR-018) | k8s NetworkPolicy (ADR-020) | ServiceAccount RBAC (ADR-019) | confirm-twice modal + visual lock (ADR-024) |
| palafito-b2b | WordPress admin OAuth + zero-permission plugin user | WP nonce + REST API auth | (cloud provider firewall) | DB grants per WP role | confirm-twice on order delete + automated MERGE-ORDERS audit |
| iguanatrader | GH OAuth + per-env PATs | (planned: webhook HMAC for Telegram callback) | NetworkPolicy (planned in deployment-foundation) | per-pod ServiceAccount (planned) | HITL approval per-mutation (P1 channels) |

The pattern compounds: each new project that adopts ai-playbook v0.11+ should pre-define its 5-layer matrix during BMAD Phase 2 (Architecture / ADRs) — one ADR per layer, even if the layer is "not needed for this system because <reason>".
