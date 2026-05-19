---
schema: runbook/v1
slug: rotate-secrets
description: Rotate any of the playbook-managed secrets (GitHub PATs, SMTP credentials, Atlassian token, dev GITHUB_TOKEN, SOPS age key) on schedule or on compromise.
audience: operator
estimated_time: 15-30 min per secret
last_validated: "2026-05-19"
---

# Rotate a playbook-managed secret

## Outcome

The old credential is revoked at the vendor side; the new credential is set on every consuming surface (GitHub repo secrets, SOPS-encrypted store, k8s Secret); consuming services have been restarted; an end-to-end smoke test confirmed the new credential works; the rotation is logged in `.ai-playbook/overrides.log` per [Rule: break-glass](../rules/break-glass.rule.md).

## When to use this

Pick the secret matching the trigger:

- **Scheduled rotation** (cadence per inventory below) — calendar-driven.
- **Compromise** — anything that suggests the secret leaked. For active leaks, escalate to [Runbook: runbook-key-rotation-emergency](runbook-key-rotation-emergency.md) which has tighter MTTR.

This runbook covers calendar-driven rotations. For incident-driven rotations (wide-scope leak), see [Runbook: runbook-secrets-leak-containment](runbook-secrets-leak-containment.md).

## Prerequisites

- `gh auth status` shows authenticated.
- `sops` installed and the `AI_PLAYBOOK_AGE_KEY` is in `~/.config/sops/age/keys.txt`: `age-keygen -y ~/.config/sops/age/keys.txt`.
- 1Password (or equivalent vault) for vendor-side rotation.
- SSH access to the VPS for k8s Secret updates: `ssh consumer-d-vps echo ok`.

## Secrets inventory

| Secret | Where stored | Used by | Rotation cadence | Owner |
|---|---|---|---|---|
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | GH repo secrets on all 3 workflow repos + k8s Secret `consumer-d-secrets` | `scripts/notify.py` SMTP fan-out | On Gmail app-password rotation (~annual or loss) | maintainer |
| `AIPLAYBOOK_NOTIFICATIONS_TO` | GH repo secrets + k8s Secret | `scripts/notify.py` | On email change | maintainer |
| `ATLASSIAN_URL`, `ATLASSIAN_USERNAME`, `ATLASSIAN_API_TOKEN` | GH repo secrets + k8s Secret | `scripts/issue_sync.py`, `scripts/release_cut.py` | On Atlassian API token expiry (~1 yr) | maintainer |
| `GITHUB_TOKEN` | SOPS `secrets/secrets.env` in `consumer-d` | Local dev + ad-hoc direct push fallback | 30 d (god-mode) / 90 d (scoped) | maintainer |
| `AI_PLAYBOOK_AGE_KEY` | `~/.config/sops/age/keys.txt` per dev machine | SOPS decrypt of all encrypted secrets | Never (root of trust) | maintainer personal |

> **v0.19.0 update**: `PLAYBOOK_PROPAGATION_TOKEN` was retired alongside the push pipeline. The playbook no longer holds any PAT with write access to consumer repos. Consumers manage their own bump credentials (Dependabot, Renovate, or local cron). If your fork still has the secret set, revoke it at <https://github.com/settings/tokens>.

## Steps

### A. Rotate SMTP credentials (Gmail app-password)

1. **Generate a new app password** at <https://myaccount.google.com/apppasswords> (account: the maintainer's notification email; 2-Step Verification must be enabled). Name it `ai-playbook-notifications-<YYYY-MM-DD>`. Copy the 16-char value (no spaces) and revoke the old entry.

2. **Update SOPS**:
   ```bash
   cd C:/Projects/consumer-d
   sops --set '["SMTP_PASSWORD"] "<new-16-char-no-spaces>"' secrets/secrets.env
   git commit -am "chore(secrets): rotate SMTP_PASSWORD"
   git push
   ```

3. **Update GH repo secrets** on each workflow repo via retry wrapper (direct `gh secret set` has been flaky):
   ```bash
   NEW_PW="<new-16-char-no-spaces>"
   for repo in Wizarck/ai-playbook Wizarck/consumer-c Wizarck/consumer-d; do
     for i in 1 2 3 4 5; do
       gh secret set SMTP_PASSWORD --repo "$repo" --body "$NEW_PW" && break
       sleep 2
     done
   done
   ```

4. **Update the k8s Secret** on VPS:
   ```bash
   ssh consumer-d-vps "kubectl patch secret consumer-d-secrets -n consumer-d --patch '{\"stringData\":{\"SMTP_PASSWORD\":\"$NEW_PW\"}}'"
   ssh consumer-d-vps "kubectl rollout restart deployment/consumer-d-dashboard -n consumer-d"
   ```

5. **Verify end-to-end**:
   ```bash
   cd C:/Projects/ai-playbook
   PYTHONPATH=. python -m scripts.notify --event smtp.rotation.verify --severity warn \
       --summary "SMTP credential rotation" --detail "Post-rotation smoke test."
   ```
   Check the configured inbox within 30 s.

6. **Log rotation** in `.ai-playbook/overrides.log`.

### B. Rotate `ATLASSIAN_API_TOKEN`

Same 3-surface pattern (SOPS + GH secrets + k8s Secret). Generate a new token at <https://id.atlassian.com/manage-profile/security/api-tokens>, update the 3 surfaces using the §A template, revoke the old.

### C. Rotate `GITHUB_TOKEN` (dev-side, SOPS)

This is the PAT for local ops (direct push fallback, `gh` when `gh auth` is not configured).

1. Generate new PAT at <https://github.com/settings/tokens>.
2. Update SOPS:
   ```bash
   sops --set '["GITHUB_TOKEN"] "<new-pat>"' C:/Projects/consumer-d/secrets/secrets.env
   git -C C:/Projects/consumer-d commit -am "chore(secrets): rotate GITHUB_TOKEN"
   git -C C:/Projects/consumer-d push
   ```
3. Re-authenticate `gh`:
   ```bash
   echo "<new-pat>" | gh auth login --with-token
   ```
4. Revoke the old PAT.

### D. God-mode PAT caveat

A temporary god-mode PAT (e.g. one issued with 1-week expiry) MUST be tracked separately. Use it only for the bootstrap session, then rotate to a scoped fine-grained PAT within 24 h.

## Verification

For every rotation:

- Vendor audit log shows no requests using the old credential after its revocation timestamp.
- The replacement credential works end-to-end (smoke test in step §A.3 / §B.5 / similar).
- `gh secret list --repo Wizarck/<repo>` shows the new `updated` timestamp on every surface.
- `.ai-playbook/overrides.log` has a fresh entry.

## Troubleshooting

### Symptom: `gh secret set` returns success but the workflow still fails auth
**Cause**: GitHub takes 30-90 s to propagate secret updates to runners.
**Fix**: wait 2 minutes and re-fire the workflow. If still failing, confirm the secret value contains no whitespace or quotes (`gh secret list` does not show value, but reset with `--body` to be safe).

### Symptom: SOPS `--set` errors with `value must be a string`
**Cause**: SOPS escaping subtleties — double-quote the value within the inner argument.
**Fix**: use the exact form `sops --set '["KEY"] "value"'` (note the single-quote wrapping the whole argument and double-quotes around value). When in doubt, run `sops` interactively and let it open the editor.

### Symptom: k8s Secret patched but service still uses old credential
**Cause**: pods read the secret at startup, not on each request.
**Fix**: `kubectl rollout restart deployment/<service> -n <namespace>` to force pod replacement.

### Symptom: smoke test in §B.5 succeeds but no email arrives
**Cause**: Gmail app-password lacks "Mail" scope, OR the from-address is mismatched, OR a Gmail-side rate limit (rare).
**Fix**: confirm the app password was generated for "Mail"; confirm `SMTP_USER` matches the Google account; wait 5 minutes and retry. Check Gmail "Sent" folder of the source account.

### Symptom: overlapping PATs alive for >24 h
**Cause**: forgot to revoke the old token after the new one was verified.
**Fix**: revoke at <https://github.com/settings/tokens> immediately. The audit trail must show only one active PAT per role.

## Related

- [Runbook: runbook-key-rotation-emergency](runbook-key-rotation-emergency.md) — emergency variant when leak is suspected or confirmed.
- [Runbook: runbook-secrets-leak-containment](runbook-secrets-leak-containment.md) — wide-scope leak containment.
- [Concept: data-retention](../concepts/data-retention.md) — retention and deletion contract.
- [Concept: env-vars](../concepts/env-vars.md) — env var catalog (name + purpose for every secret).
- [Rule: break-glass](../rules/break-glass.rule.md) — log every ad-hoc override to `overrides.log`.
