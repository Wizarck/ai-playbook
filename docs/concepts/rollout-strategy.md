---
schema: concept/v1
slug: rollout-strategy
title: Rollout Strategy
summary: |
  How breaking changes to the playbook are proposed, announced, deprecated,
  and removed. The spec is written for the consumer's protection: a dev whose
  project pins .ai-playbook@v0.1.0 must never wake up to a merge conflict
  because the maintainer silently renamed a flag on master.
last_validated: "2026-05-19"
---

# Rollout Strategy

How breaking changes to the playbook are proposed, announced, deprecated, and removed. The spec is written for the consumer's protection: a dev whose project pins `.ai-playbook@v0.1.0` must never wake up to a merge conflict because the maintainer silently renamed a flag on `master`.

---

## 1. What counts as breaking

A change is **breaking** if it can reject, misinterpret, or silently alter an artefact that was valid under the previous semver. Canonical list:

- **Schema version bump** (`agents-md/v1` → `agents-md/v2`, same for `mcp-servers/v*`).
- **Required field added** to any spec's `## Contract` section (new required frontmatter field, new required section header, new required CLI argument).
- **CLI flag removed or renamed** on any script under `scripts/`.
- **Well-known MCP server removed or renamed** in the base templates (`mcp-servers-base.yaml`).
- **Exit-code semantics changed** per [error-message-standard.md](../rules/error-message-standard.rule.md) — e.g. repurposing exit 3.
- **Dispatcher resolution order changed** per [dispatcher-chain.md](dispatcher-chain.md).
- **Verdict literal changed** — the literal strings in [verdict-contract.md](../rules/verdict-contract.rule.md) §1 are frozen; any change is breaking.
- **Semver major bump** by definition; this spec exists to make major bumps rare.

## 2. Non-breaking but notable

These land as **minor** or **patch** versions and do not trigger the deprecation window:

- New CLI flags (with safe defaults).
- New optional env vars (prefix `AIPLAYBOOK_`).
- New specs (additive).
- New tests, new hooks, new templates.
- New optional frontmatter fields (`additionalProperties: true` across v1 schemas).
- Doc-only changes (typo fixes, examples, cross-refs).
- New MCP servers in `mcp-servers-base.yaml` (additive).

Patch versions fix bugs without changing any contract. Minor versions add capability. Majors are for breaks.

---

## 3. Deprecation window

**1 full minor cycle OR 90 days, whichever is longer.**

Example: a flag deprecated in `v0.3.0` → cannot be removed earlier than `v0.4.0` AND cannot be removed before 90 days have elapsed since the `v0.3.0` tag. If `v0.4.0` ships 30 days after `v0.3.0`, the flag survives into `v0.5.0` until day 90 is reached.

Rationale: consumers operate on different upgrade cadences. A lone 90-day window ignores consumers who pin rarely; a lone minor-cycle window punishes consumers who just pinned to the deprecation release.

---

## 4. Announcement path

Each breaking change walks every row of this table. Skipping a row is a governance violation and surfaces in the monthly retro per [retrospective-cadence.md](retrospective-cadence.md).

| Phase | Artefact | Audience | SLA |
|---|---|---|---|
| **Proposal** | RFC under `rfcs/NNNN-<slug>.md` per ../rfcs/README.md. | Maintainer + named reviewers per [contributing.md](contributing.md) §2. | Triage ≤7 days, decision ≤30 days per contributing.md §3.2. |
| **Acceptance** | RFC merged with `Decided: accept`. CHANGELOG entry under the next minor. | Contributors + consumers (via GH Release notes). | Same day as merge. |
| **Deprecation** | Entry added to `specs/deprecations.yaml` (schema: `{change-id, deprecated-in, remove-earliest, migration-link}`). Emitter wired into `scripts/telemetry/report.py (absorbed in Slice 6)` (owned by Subagent A, T22 track). | Consumers — surfaces on every CLI invocation that touches the deprecated path. | Ships in the minor that contains the RFC acceptance. |
| **Grace** | Warning emitted on every invocation during the window. Weekly `info`-level `deprecation.usage.observed` notification per [notification-policy.md](notification-policy.md). | Consumers. | Window = §3 rules. |
| **Removal** | Hard fail (exit non-zero, `OVERRIDE: none` per [error-message-standard.md](../rules/error-message-standard.rule.md)) + migration recipe. CHANGELOG entry under the semver-major that removes it. | Consumers. | Ships in the minor or major after the window closes. |

The **deprecation watcher** (`scripts/telemetry/report.py (absorbed in Slice 6)`, Subagent A-owned — **flag for race: ensure its emitter schema aligns with `specs/deprecations.yaml` shape above**) reads `deprecations.yaml`, inspects consumer `AGENTS.md` + CLI invocations, and emits the warnings. Without the watcher, the grace period is invisible and the removal phase surprises consumers.

---

## 5. Migration artefacts

Every breaking change must ship with one of:

- **An updated section in [migration-guide.md](migration-guide.md)** — preferred when the change fits the v0→v1 narrative there.
- **A dedicated `migrations/<change-id>.md` doc** — preferred for standalone recipes (e.g. renaming a single CLI flag, where the v0→v1 guide isn't the right venue).

The migration artefact names, for every affected shape: the BEFORE snippet, the AFTER snippet, the autofix invocation (if any), and the failure mode when the consumer does nothing. No migration doc ⇒ no removal phase; the PR that removes a deprecated path is blocked by the verdict linter.

---

## 6. Opt-out for consumers

Consumers are not forced onto any release. Three escape hatches:

1. **Pin the submodule.** `inherits_from: github.com/Wizarck/ai-playbook@v0.3.0` stays on v0.3.0 forever. The deprecation watcher prints a weekly `warn` on every CLI invocation: "Playbook v0.5.0 is current; you are on v0.3.0, N deprecations pending migration." The warning rate-limits per [notification-policy.md](notification-policy.md) §2.
2. **`--force-with-reason="..."` per [break-glass.md](../rules/break-glass.rule.md).** For a single invocation past a hard-fail gate during emergency migration work. Logged to `.ai-playbook/overrides.log`, surfaces in the next retro.
3. **Open an RFC** to push the removal-earliest window back. Must cite concrete consumer blockers; the maintainer evaluates per contributing.md §3 SLAs.

---

## 7. Emergency path

Security vulnerabilities and data-corruption bugs bypass the deprecation window.

- **Trigger**: a finding that would rate `S1` per [verdict-contract.md](../rules/verdict-contract.rule.md) §2 AND affects correctness/safety AND cannot be fixed inside the existing contract.
- **Action**: immediate hard-fail release (patch version — semver allows breaking fixes in patches for security, signalled by a `SECURITY:` prefix in the CHANGELOG).
- **Mandatory post-mortem** per `docs/concepts/post-mortem.md` (owned by Subagent A, T22 track — **flag for race: ensure the post-mortem template cross-refs this file as the trigger**). Post-mortem lands within 7 days, commits to `reports/post-mortems/<YYYY-MM-DD>-<slug>.md`.
- **No retroactive deprecation.** The fact that the window was skipped is the story the post-mortem tells.

---

## 8. Anti-patterns

- **Silent rename.** Renaming a script, a flag, or a frontmatter field without a deprecation alias. Any consumer pinned to the previous tag gets a confusing `AttributeError` with no migration signpost.
- **Flag-flag.** Adding a new flag to un-break a previous break. E.g. shipping `--legacy-schema` because `v2` was too aggressive. Fix is to revert the breaking change and RFC a slower path; don't compound.
- **CHANGELOG-only breaking.** A CHANGELOG entry that says "behaviour X changed" without a corresponding spec update. The spec is the contract; CHANGELOG is the announcement. Both must move.
- **Removing during a patch bump.** Patch versions are for fixes inside the contract. The only exception is §7 emergency path, and it is signalled explicitly.
- **Consumer-specific grace extensions via private channel.** If one consumer needs more time, so do others. Extensions flow through RFC, not DM.

---

## 9. Cross-references

- [migration-guide.md](migration-guide.md) — v0→v1 migration and the template for future major migrations.
- ../rfcs/README.md — RFC template and SLA.
- [../docs/concepts/contributing.md](contributing.md) §3 — RFC process, reviewer matrix.
- [slos.md](slos.md) — the break-glass-ratio SLO tracks consumers who get stuck during a deprecation window.
- [break-glass.md](../rules/break-glass.rule.md) — single-invocation escape hatch during migration.
- [notification-policy.md](notification-policy.md) §4 — `deprecation.usage.observed` event mapping.
- [verdict-contract.md](../rules/verdict-contract.rule.md) — severity taxonomy that classifies emergency-path triggers.
- `scripts/telemetry/report.py (absorbed in Slice 6)` — emitter of deprecation warnings (Subagent A, T22).
- `docs/concepts/post-mortem.md` — template for the §7 mandatory post-mortem (Subagent A, T22).
