# runbook-secrets-leak-containment.md

> **Status**: Stub v0.1.0. Authored under OpenSpec change `complete-ir-and-model-migration-specs` (Phase 5 P5.6) on 2026-05-01. Sibling to [`specs/incident-response.md`](../specs/incident-response.md) §4 scenario #3 and [runbook-key-rotation-emergency.md](runbook-key-rotation-emergency.md).
>
> Use this runbook when the leak is **wide-scope** (suspected machine compromise, suspected supplier compromise, leak in a public-facing repo with downstream forks). For scoped leaks (1-3 individual credentials), use [runbook-key-rotation-emergency.md](runbook-key-rotation-emergency.md).

## When to use this runbook

Triggered by [incident-response.md](../specs/incident-response.md) §4 scenario #3 when the leak indicates a wider compromise:

- Multiple unrelated credentials leaked together (suggests compromised secrets store or compromised dev machine).
- Leak in a public repo that already has forks / clones (history rewrite is necessary but insufficient).
- Vendor audit log shows credential used from a clearly hostile location.
- A team member's machine is suspected compromised (laptop stolen, malware report, suspicious activity).

Severity: **S1**. MTTR: containment within 1h, full rotation within 4h, public disclosure (if customer data implicated) within 72h per relevant regulations.

## Prerequisites

- Out-of-band channel to coordinate (NOT the platform under suspicion — if Slack is suspected, use Signal; if email is suspected, use phone).
- Access to every secrets store (SOPS / 1Password / vendor consoles).
- Rights to revoke OAuth grants, GitHub Apps, deploy keys.
- VPS root access from a known-clean machine.

## Steps

### Phase 1 — Containment (≤ 1h)

1. **Isolate the suspected source.**

   - If a dev machine: power off, network-disconnect. Do not reboot, do not log out — preserve forensic state.
   - If the secrets store: revoke the master key (Step 6 of [runbook-key-rotation-emergency.md](runbook-key-rotation-emergency.md)).
   - If a CI runner: disable the runner; revoke its registration token.

2. **Block the blast radius at the network edge.**

   ```bash
   # Cloudflare WAF rule blocking suspected origin (use sparingly — false positives lock you out)
   # Rotate Cloudflare tokens (which themselves grant WAF edit rights — meta-rotation).
   ```

3. **Snapshot for forensics.**

   ```bash
   # On VPS:
   tar czf /opt/forensics/snapshot-$(date +%Y%m%d-%H%M%S).tar.gz \
       /var/log/auth.log /var/log/syslog \
       /opt/eligia/.ai-playbook/events.jsonl \
       /opt/eligia/.ai-playbook/overrides.log
   ```
   Snapshots feed the post-mortem and any law-enforcement involvement.

### Phase 2 — Rotation (≤ 4h)

4. **Inventory every credential.**

   ```bash
   sops -d secrets/secrets.env | grep -E '^[A-Z_]+_(KEY|TOKEN|SECRET|PASSWORD)='
   ```

   Also check:
   - Vendor consoles for OAuth grants (Anthropic, OpenAI, GitHub, Atlassian, Google).
   - GitHub repo deploy keys + Actions secrets (per repo).
   - Cloudflare API tokens (Zero Trust + DNS).
   - 1Password items tagged `production`.

5. **Rotate everything**, in priority order:

   ```
   Priority 1: anything that grants write access to customer data
               (DB credentials, S3 keys, customer API tokens you hold).
   Priority 2: anything that grants write access to infra
               (SSH keys, GitHub deploy tokens, Helm chart push tokens).
   Priority 3: read-only credentials (LLM API keys, observability tokens).
   ```

   For each: follow [runbook-key-rotation-emergency.md](runbook-key-rotation-emergency.md) Steps 2-5. Track in a checklist (paper or 1Password) — no tooling, this is hands-on.

6. **Re-key the secrets store itself (Step 6 of `runbook-key-rotation-emergency.md`)** — the SOPS / age master key.

7. **Force-push history rewrite for every affected repo** (Step 7 of `runbook-key-rotation-emergency.md`) — including downstream forks if you control them. For unowned forks, file an abuse report with GitHub (which can purge cached blobs).

### Phase 3 — Disclosure (per regulation; ≤ 72h if customer data was reachable)

8. **Determine notification obligations.**

   - GDPR (EU): 72h to supervising authority if a personal-data breach is "likely to result in a risk to the rights and freedoms of natural persons".
   - CCPA (California): without unreasonable delay; specific thresholds depend on the data category.
   - Sector-specific (HIPAA, PCI-DSS, SOC 2 audit clauses) per the applicable contract.

   For ELIGIA (solo-state, no paying customers as of 2026-05-01): no regulatory obligation today; obligation flips on with the same trigger as `incident-response.md` §2 (first paying SaaS customer).

9. **Customer + public communication.**

   Use [incident-response.md](../specs/incident-response.md) §7.1 templates, adjusted for security:

   ```
   [SECURITY ADVISORY — <UTC HH:MM>] Investigating a security incident affecting <service / scope>.
   No customer action required at this time. Status updates every <N> hours.
   ```

   Followed (when known):
   ```
   [SECURITY UPDATE — <UTC HH:MM>] We have completed credential rotation. Customer data at risk: <none | specific scope>.
   <If customer data was reachable: action requested of customers, e.g. "rotate your X token issued before <date>">.
   Full disclosure post-mortem within 7 days.
   ```

### Phase 4 — Forensics + post-mortem (≤ 7 days)

10. **Trace the leak vector.**

    - When did the bad credential first appear? (`git log -S '<leaked-token>' --all --pickaxe-regex`).
    - What pre-commit hook should have caught it? (`secrets_scan.py` rule gap?).
    - What process change closes the gap? (often: extend `secrets_scan.py` allowlist + add a CI-level gate that mirrors the pre-commit hook).

11. **Write the post-mortem.**

    Use [`templates/post-mortem.md.tmpl`](../templates/post-mortem.md.tmpl). Add a `security` section:
    - Vector.
    - Blast radius.
    - Affected customers (if any).
    - Regulatory notifications filed.
    - Process change shipped.

    Per [post-mortem.md](../specs/post-mortem.md), security post-mortems are mandatory ≤ 48h to draft, ≤ 7 days to publish.

## Verification

- Every credential from Step 4 is rotated AND the old credential is revoked at the vendor.
- Vendor audit logs show no requests with old credentials after their revocation timestamps.
- `secrets_scan.py` green across all repos.
- Forensic snapshots stored under `/opt/forensics/` with restricted ACL.
- Post-mortem published within deadline.

## Rollback

No rollback exists. Once a credential is suspected compromised, the answer is always "rotate" — never "un-rotate". If a rotated credential is found to have been a false alarm (the leak was not real), the cost is one batch of vendor-side revocation work; you do not re-instate the old credential.

## Post-incident artefact required

**Security post-mortem mandatory** ≤ 48h to draft, ≤ 7 days to publish. Template + contract: [post-mortem.md](../specs/post-mortem.md).

## Related

- [runbook-key-rotation-emergency.md](runbook-key-rotation-emergency.md) — scoped (1-3 credentials) variant of this runbook.
- [rotate-secrets.md](rotate-secrets.md) — non-emergency scheduled rotation.
- [incident-response.md](../specs/incident-response.md) §4 scenario #3.
- [data-retention.md](../specs/data-retention.md) — what data the leaked credentials could exfiltrate.
- [agentic-failures.md](../specs/agentic-failures.md) §2.11 — secrets-scan failure mode taxonomy.
- [post-mortem.md](../specs/post-mortem.md) — mandatory artefact.
