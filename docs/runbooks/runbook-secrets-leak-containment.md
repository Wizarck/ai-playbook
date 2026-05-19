---
schema: runbook/v1
slug: runbook-secrets-leak-containment
description: Contain a wide-scope secrets leak (machine compromise, supplier compromise, public-repo leak with forks) through isolation, full credential rotation, history rewrite, and disclosure.
audience: operator
estimated_time: ≤1 h containment; ≤4 h full rotation; ≤72 h disclosure (if customer data implicated); ≤7 days post-mortem
last_validated: "2026-05-19"
---

# Contain a wide-scope secrets leak

## Outcome

The compromise vector is isolated; every credential potentially reachable from that vector is rotated and the old credentials are revoked; the secrets store master key is rotated; git histories are rewritten for any affected repos (including downstream forks); customer + public communications are issued if required; a security post-mortem is drafted within 48 hours and published within 7 days.

## When to use this

Triggered by [Concept: incident-response](../concepts/incident-response.md) §4 scenario #3 when the leak indicates a wider compromise:

- Multiple unrelated credentials leaked together (suggests compromised secrets store or compromised dev machine).
- Leak in a public repo that already has forks or clones (history rewrite is necessary but insufficient).
- Vendor audit log shows credential used from a clearly hostile location.
- A team member's machine is suspected compromised (laptop stolen, malware report, suspicious activity).

For scoped exposure (1-3 credentials), use [Runbook: runbook-key-rotation-emergency](runbook-key-rotation-emergency.md) instead.

Severity: **S1**. MTTR: containment within 1 h, full rotation within 4 h, public disclosure (if customer data implicated) within 72 h.

## Prerequisites

- Out-of-band communication channel (NOT the platform under suspicion — if Slack is suspected, use Signal; if email is suspected, use phone).
- Access to every secrets store (SOPS / 1Password / vendor consoles).
- Rights to revoke OAuth grants, GitHub Apps, deploy keys.
- VPS root access from a known-clean machine.

## Steps

### Phase 1 — Containment (≤1 h)

1. **Isolate the suspected source.**
   - If a dev machine: power off, disconnect from network. Do not reboot, do not log out — preserve forensic state.
   - If the secrets store: revoke the master key (Phase 2 step 6 of [Runbook: runbook-key-rotation-emergency](runbook-key-rotation-emergency.md)).
   - If a CI runner: disable the runner; revoke its registration token.

2. **Block the blast radius at the network edge.**
   ```bash
   # Cloudflare WAF rule blocking suspected origin (use sparingly — false positives lock you out).
   # Rotate Cloudflare tokens (which themselves grant WAF edit rights — meta-rotation).
   ```

3. **Snapshot for forensics.**
   ```bash
   # On VPS:
   tar czf /opt/forensics/snapshot-$(date +%Y%m%d-%H%M%S).tar.gz \
       /var/log/auth.log /var/log/syslog \
       /opt/consumer-d/.ai-playbook/events.jsonl \
       /opt/consumer-d/.ai-playbook/overrides.log
   ```
   Snapshots feed the post-mortem and any law-enforcement involvement.

### Phase 2 — Rotation (≤4 h)

4. **Inventory every credential.**
   ```bash
   sops -d secrets/secrets.env | grep -E '^[A-Z_]+_(KEY|TOKEN|SECRET|PASSWORD)='
   ```
   Also check:
   - Vendor consoles for OAuth grants (Anthropic, OpenAI, GitHub, Atlassian, Google).
   - GitHub repo deploy keys + Actions secrets (per repo).
   - Cloudflare API tokens (Zero Trust + DNS).
   - 1Password items tagged `production`.

5. **Rotate everything in priority order:**
   ```
   Priority 1: anything that grants write access to customer data
               (DB credentials, S3 keys, customer API tokens you hold).
   Priority 2: anything that grants write access to infra
               (SSH keys, GitHub deploy tokens, Helm chart push tokens).
   Priority 3: read-only credentials (LLM API keys, observability tokens).
   ```
   For each: follow [Runbook: runbook-key-rotation-emergency](runbook-key-rotation-emergency.md) steps 2-5. Track progress in a paper checklist or 1Password — no tooling, this is hands-on.

6. **Re-key the secrets store itself** per Step 6 of [Runbook: runbook-key-rotation-emergency](runbook-key-rotation-emergency.md) — the SOPS / age master key.

7. **Force-push history rewrite for every affected repo** per Step 7 of [Runbook: runbook-key-rotation-emergency](runbook-key-rotation-emergency.md). Include downstream forks you control. For unowned forks, file an abuse report with GitHub (which can purge cached blobs).

### Phase 3 — Disclosure (per regulation; ≤72 h if customer data was reachable)

8. **Determine notification obligations.**
   - GDPR (EU): 72 h to supervising authority if a personal-data breach is "likely to result in a risk to the rights and freedoms of natural persons".
   - CCPA (California): without unreasonable delay; thresholds depend on the data category.
   - Sector-specific (HIPAA, PCI-DSS, SOC 2 audit clauses) per the applicable contract.

   For consumer-d (solo-state, no paying customers as of 2026-05-01): no regulatory obligation today. Obligation flips on with the same trigger as [Concept: incident-response](../concepts/incident-response.md) §2 (first paying SaaS customer).

9. **Customer + public communication.**
   Use [Concept: incident-response](../concepts/incident-response.md) §7.1 templates, adjusted for security:
   ```
   [SECURITY ADVISORY — <UTC HH:MM>] Investigating a security incident affecting <service / scope>.
   No customer action required at this time. Status updates every <N> hours.
   ```
   Followed (when known):
   ```
   [SECURITY UPDATE — <UTC HH:MM>] We have completed credential rotation.
   Customer data at risk: <none | specific scope>.
   <If customer data was reachable: action requested of customers, e.g. "rotate your X token issued before <date>">.
   Full disclosure post-mortem within 7 days.
   ```

### Phase 4 — Forensics + post-mortem (≤7 days)

10. **Trace the leak vector.**
    - When did the bad credential first appear: `git log -S '<leaked-token>' --all --pickaxe-regex`.
    - What pre-commit hook should have caught it: `secrets_scan.py` rule gap?
    - What process change closes the gap: often extend `secrets_scan.py` allowlist + add a CI-level gate mirroring the pre-commit hook.

11. **Write the post-mortem.**
    Use `templates/post-mortem.md.tmpl`. Add a `security` section:
    - Vector.
    - Blast radius.
    - Affected customers (if any).
    - Regulatory notifications filed.
    - Process change shipped.

    Per [Concept: post-mortem](../concepts/post-mortem.md), security post-mortems are mandatory ≤48 h to draft, ≤7 days to publish.

## Verification

- Every credential from Step 4 is rotated AND the old credential is revoked at the vendor.
- Vendor audit logs show no requests with old credentials after their revocation timestamps.
- `secrets_scan.py` green across all repos.
- Forensic snapshots stored under `/opt/forensics/` with restricted ACL.
- Post-mortem published within deadline.

## Troubleshooting

### Symptom: rollback request — the leak turns out to have been a false alarm
**Cause**: report was based on a misinterpretation (e.g., a token shown in a screenshot was already rotated).
**Fix**: no rollback exists. Once a credential is suspected compromised, the answer is always "rotate" — never "un-rotate". The cost of a false alarm is the rotation work; you do not re-instate the old credential.

### Symptom: forks of a public repo still contain the leaked credential after force-push
**Cause**: GitHub caches blobs from old refs; downstream forks have their own histories that the force-push does not touch.
**Fix**: file an abuse report with GitHub at <https://github.com/contact?form%5Bsubject%5D=Sensitive%20data%20exposure>; provide the blob SHAs and the upstream repo. GitHub can purge cached blobs but cannot reach into third-party forks — assume the credential is permanently public and rely on revocation, not history rewrite.

### Symptom: out-of-band channel unavailable (Signal not installed, no phone access)
**Cause**: every channel was assumed compromised, or normal channels are down.
**Fix**: defer non-urgent coordination until a clean channel is available. Containment (Phase 1) must NOT wait for coordination; isolate first, communicate when possible.

### Symptom: notification deadline missed because the credential rotation took >72 h
**Cause**: rotation scope was wider than the 4 h MTTR target.
**Fix**: file the regulatory notification with the available information at the 72-h mark; supplement with follow-up updates as rotation completes. Late notification is a regulatory finding; missing notification is much worse.

## Post-incident artefact required

**Security post-mortem mandatory** ≤48 h to draft, ≤7 days to publish. Template + contract: [Concept: post-mortem](../concepts/post-mortem.md).

## Related

- [Runbook: runbook-key-rotation-emergency](runbook-key-rotation-emergency.md) — scoped (1-3 credentials) variant.
- [Runbook: rotate-secrets](rotate-secrets.md) — non-emergency scheduled rotation.
- [Runbook: git-worktree-bare-setup](git-worktree-bare-setup.md) — collaborator re-clone after force-push.
- [Concept: incident-response](../concepts/incident-response.md) — incident-class ladder; this is §4 scenario #3.
- [Concept: data-retention](../concepts/data-retention.md) — what data the leaked credentials could exfiltrate.
- [Concept: agentic-failures](../concepts/agentic-failures.md) — secrets-scan failure mode taxonomy.
- [Concept: post-mortem](../concepts/post-mortem.md) — mandatory artefact.
