# runbook-key-rotation-emergency.md

> **Status**: Stub v0.1.0. Authored under OpenSpec change `complete-ir-and-model-migration-specs` (Phase 5 P5.6) on 2026-05-01. Sibling to [`docs/concepts/incident-response.md`](../docs/concepts/incident-response.md) §4 scenario #3 and [rotate-secrets.md](rotate-secrets.md).
>
> Emergency variant of [rotate-secrets.md](rotate-secrets.md): same target (rotate every credential), tighter clock (1h to revoke + reissue, not the leisurely calendar-driven path).

## When to use this runbook

A credential is suspected or confirmed compromised AND the leak window is open. Escalates from [rotate-secrets.md](rotate-secrets.md) when the breach is active rather than precautionary.

Common triggers:
- A vendor sends a "your token was used from an unexpected location" email.
- `secrets_scan.py` post-push CI fails AND the repo is public OR has > 1 contributor.
- A team member reports having committed a secret to a repo they don't own.
- An external party reports a token or key valid in their possession.

This runbook is for **scoped** credential exposure (1-3 keys). For broad compromise (suspected machine compromise, suspected supplier compromise), escalate to [runbook-secrets-leak-containment.md](runbook-secrets-leak-containment.md) which assumes a wider blast radius.

Severity: **S1** if customer data is reachable via the leaked credential; **S2** otherwise. MTTR: ≤ 1h to revoke + reissue.

## Prerequisites

- SOPS / age key for the encrypted secrets store.
- 1Password (or equivalent) for vendor-side rotation — most vendors require a manual UI dance.
- VPS SSH for restarting any service that consumes the credential.

## Steps

1. **Identify the credential's blast radius.**

   For each leaked credential, determine:
   - What service consumes it? (`grep -r '<env-var-name>' .` across consumer repos.)
   - What does it grant? (vendor docs — read access, write access, customer data, billing).
   - Was the credential used during the leak window? (vendor audit log if available — Anthropic / OpenAI / GitHub all expose this).

2. **Revoke the credential at the vendor side.**

   This is a manual UI action per vendor. Do this BEFORE issuing a replacement — an active bad token is worse than 5 min of downtime.

   | Vendor | Revocation path |
   |---|---|
   | Anthropic | console.anthropic.com → Settings → API Keys → Revoke. |
   | OpenAI | platform.openai.com → API keys → Revoke. |
   | OpenRouter | openrouter.ai → Keys → Revoke. |
   | GitHub PAT | github.com/settings/tokens → Revoke / Delete. |
   | Atlassian API token | id.atlassian.com → Security → API tokens → Revoke. |
   | Google service account | console.cloud.google.com → IAM → Service Accounts → Keys → Delete. |
   | Cloudflare token | dash.cloudflare.com → My Profile → API Tokens → Delete. |
   | SOPS / age key | rotate the master key — see Step 6. |

3. **Issue a replacement credential.**

   Same UI, "Create new key". Scope it as narrowly as possible (read-only when read-only suffices).

4. **Update the secrets store.**

   ```bash
   sops <repo>/secrets/secrets.env  # decrypts in-place; replace the value
   # Save and close — sops re-encrypts.
   git add secrets/secrets.env
   git commit -m "chore(secrets): rotate <CREDENTIAL_NAME> after leak (INC-<n>)"
   ```

5. **Restart consuming services.**

   ```bash
   # k3s pods that read from secrets:
   kubectl rollout restart deploy/<service> -n consumer-d
   # Docker compose:
   cd /opt/<service> && docker compose up -d <service>
   # Local services (rare):
   systemctl --user restart <service>
   ```

6. **If the leaked credential was the SOPS / age master key itself**, the rotation is recursive:
   ```bash
   # Generate new age key
   age-keygen -o ~/.config/sops/age/keys-new.txt
   # Re-encrypt every sops file with the new public key
   for f in $(find . -name 'secrets*.env'); do
       sops -d "$f" | sops -e --age <new-pub-key> /dev/stdin > "$f.new"
       mv "$f.new" "$f"
   done
   # Replace the old key, commit
   ```
   This is the "rotation of the rotation key" — slow, error-prone, do it carefully.

7. **Force-push history rewrite IF the leak was in a published commit.**

   ```bash
   # Use git filter-repo (not filter-branch — too slow, deprecated)
   pip install git-filter-repo
   git filter-repo --replace-text <(echo "<leaked-token>==>REDACTED")
   git push --force origin <branch>
   ```

   **Coordinate with collaborators before force-push.** Anyone with the old history needs to re-clone. Per [git-worktree-bare-setup.md](git-worktree-bare-setup.md), bare-repo collaborators need to re-fetch and reset their worktrees.

8. **File a CISA-style note.**
   ```bash
   echo '{"ts":"<iso>","incident_id":"INC-<n>","severity":"S1","scenario":"secrets-leak","credentials_rotated":["<list>"],"force_push":<true|false>,"customer_data_at_risk":<true|false>,"state":"resolved"}' >> incidents.jsonl
   ```

## Verification

- Vendor audit log shows no requests with the old token after revocation timestamp.
- Replacement token works end-to-end (smoke test the consumer service).
- `secrets_scan.py` is green on `HEAD`.
- If history was rewritten: `git log --all --pickaxe-regex --pickaxe-all -S '<leaked-token>'` returns empty.

## Rollback

There is no rollback for "I revoked a leaked credential". The only forward path is "issue a new one and keep going". If the replacement does not work, debug the consumer (Step 5 likely failed); do not un-revoke the leaked credential.

## Post-incident artefact required

**Security post-mortem ≤ 48h** per [incident-response.md](../docs/concepts/incident-response.md) §4 scenario #3. The post-mortem must answer:
- How did the credential leak?
- Was it used by a third party? (vendor audit log evidence).
- What customer data was reachable? (blast radius).
- What process change prevents the next leak? (often a `secrets_scan.py` rule update or a pre-commit hook gap).

## Related

- [rotate-secrets.md](rotate-secrets.md) — non-emergency scheduled rotation.
- [runbook-secrets-leak-containment.md](runbook-secrets-leak-containment.md) — broader containment when leak scope is wide.
- [incident-response.md](../docs/concepts/incident-response.md) §4 scenario #3.
- [data-retention.md](../docs/concepts/data-retention.md) — what data the leaked credential could exfiltrate determines severity.
- [post-mortem.md](../docs/concepts/post-mortem.md) — required artefact.
