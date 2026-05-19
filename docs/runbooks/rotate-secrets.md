# runbook: rotate-secrets.md — ai-playbook secret rotation

> **Audience**: the AI or a human maintainer when a secret expires or is
> compromised.
> **Status**: v1.0.0. Canonical list of secrets the playbook uses, where
> they live, and the exact rotation steps. Rotation is audited per
> [docs/concepts/data-retention.md](../docs/concepts/data-retention.md).

## Secrets inventory

| Secret | Where stored | Used by | Rotation cadence | Owner |
|---|---|---|---|---|
| `PLAYBOOK_PROPAGATION_TOKEN` | GH repo secret on `Wizarck/ai-playbook` | `.github/workflows/propagate-playbook-bump.yml` → `scripts/propagate_bump.py` | 90 d or on compromise | Arturo |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | GH repo secrets on all 3 workflow repos + k8s Secret `consumer-d-secrets` on VPS | `scripts/notify.py` (SMTP fan-out) | On Gmail app-password rotation (~annual or on loss) | Arturo |
| `AIPLAYBOOK_NOTIFICATIONS_TO` | GH repo secrets + k8s Secret | `scripts/notify.py` | On email change | Arturo |
| `ATLASSIAN_URL`, `ATLASSIAN_USERNAME`, `ATLASSIAN_API_TOKEN` | GH repo secrets + k8s Secret | `scripts/issue_sync.py`, `scripts/release_cut.py` | On Atlassian API token expiry (~1 yr) | Arturo |
| `GITHUB_TOKEN` | SOPS `secrets/secrets.env` in `consumer-d` | Local dev + runbook escape hatch (propagate-bump-troubleshooting §Networking) | 30 d (god-mode) / 90 d (scoped) | Arturo |
| `AI_PLAYBOOK_AGE_KEY` | `~/.config/sops/age/keys.txt` per dev machine | SOPS decrypt of all encrypted secrets | Never (key is the root of trust) | Arturo personal |

## PLAYBOOK_PROPAGATION_TOKEN

### Scope required

A GitHub PAT with, at minimum, on every active consumer in
[`consumers.yaml`](../consumers.yaml):

- `contents:write` — to push `chore/bump-playbook-<tag>` branch.
- `pull-requests:write` — to open the PR.

For classic PATs on a Wizarck org with SSO, the token must also be
"Authorized for Wizarck" via the GitHub settings → SSO section.

Preferred: **fine-grained PAT** scoped to exactly the repos in
`consumers.yaml`. This is the least-privilege option.

### Fine-grained PAT scope (recommended)

GitHub PAT generation is **UI-only** (no API to create tokens) — perform on
https://github.com/settings/personal-access-tokens/new. Set:

| Field | Value |
|---|---|
| Token name | `playbook-propagation` |
| Description | `Used by Wizarck/ai-playbook propagate-playbook-bump.yml to open bump PRs across consumers in consumers.yaml` |
| Resource owner | `Wizarck` |
| Expiration | 90 days (calendar-rotated; or 1 year if Wizarck policy allows) |
| Repository access | "Only select repositories" → check **every active row in `consumers.yaml`** (today: `Wizarck/consumer-c`, `Wizarck/consumer-d`, `Wizarck/consumer-b`) |
| Repository permissions | `Contents: Read and write`, `Pull requests: Read and write`, `Metadata: Read-only` (auto). All other permissions stay at "No access". |
| Account permissions | None. |

After generating, copy the `github_pat_…` token value and continue with the rotation steps below.

### Rotation steps

1. **Generate new PAT** at https://github.com/settings/personal-access-tokens/new
   following the table above. (The legacy classic-PAT path at
   https://github.com/settings/tokens is still supported but discouraged —
   classic PATs grant org-wide access regardless of which repos you check.)
2. **Set the repo secret** on `Wizarck/ai-playbook`:
   ```bash
   gh secret set PLAYBOOK_PROPAGATION_TOKEN --repo Wizarck/ai-playbook --body "<new-pat>"
   ```
3. **Verify**:
   ```bash
   gh secret list --repo Wizarck/ai-playbook | grep PLAYBOOK_PROPAGATION_TOKEN
   # Must show an `updated` timestamp = just now.
   ```
4. **Trigger a dry-run verification** by creating a no-op tag OR waiting
   for the next legitimate release. A lazy alternative — re-tag the
   current VERSION:
   ```bash
   cd C:/Projects/ai-playbook
   CURRENT=v$(cat VERSION)
   git tag -d "$CURRENT"
   git push origin --delete "$CURRENT"
   git tag -a "$CURRENT" -m "re-tag after PAT rotation"
   git push origin "$CURRENT"
   gh run watch --repo Wizarck/ai-playbook
   ```
5. **Revoke the old PAT** at https://github.com/settings/tokens once the
   new run succeeds. Do NOT leave overlapping PATs alive beyond 24 h.
6. **Log the rotation** by appending to `.ai-playbook/overrides.log`:
   ```
   <ISO-ts> 23051550+Wizarck@users.noreply.github.com rotate-secrets.md PLAYBOOK_PROPAGATION_TOKEN "scheduled 90d rotation"
   ```

## SMTP credentials

### Where set

Three surfaces — keep them consistent:

1. **SOPS-encrypted** in `consumer-d/secrets/secrets.env`:
   `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`.
2. **GitHub repo secrets** on all 3 workflow repos (`ai-playbook`,
   `consumer-c`, `consumer-d`) — same 4 keys.
3. **k8s Secret** `consumer-d-secrets` in `consumer-d` namespace on the VPS —
   stringData fields for the 4 keys.

### Rotation (Gmail app-password case)

1. Log into https://myaccount.google.com/apppasswords (Google account
   `23051550+Wizarck@users.noreply.github.com`). Must have 2-Step Verification enabled.
2. Generate a new app password named `ai-playbook-notifications-<YYYY-MM-DD>`.
   Copy the 16-char value (no spaces); revoke the old entry.
3. **Update SOPS**:
   ```bash
   cd C:/Projects/consumer-d
   sops --set '["SMTP_PASSWORD"] "<new-16-char-no-spaces>"' secrets/secrets.env
   git commit -am "chore(secrets): rotate SMTP_PASSWORD"
   git push
   ```
4. **Update GH repo secrets** on each workflow repo via retry wrapper
   (the direct `gh secret set` has been flaky — wrap in retry):
   ```bash
   NEW_PW="<new-16-char-no-spaces>"
   for repo in Wizarck/ai-playbook Wizarck/consumer-c Wizarck/consumer-d; do
     for i in 1 2 3 4 5; do
       gh secret set SMTP_PASSWORD --repo "$repo" --body "$NEW_PW" && break
       sleep 2
     done
   done
   ```
5. **Update k8s Secret** on VPS:
   ```bash
   ssh consumer-d-vps "kubectl patch secret consumer-d-secrets -n consumer-d --patch '{\"stringData\":{\"SMTP_PASSWORD\":\"$NEW_PW\"}}'"
   ```
   Then restart pods consuming the secret so they pick up the change:
   ```bash
   ssh consumer-d-vps "kubectl rollout restart deployment/consumer-d-dashboard -n consumer-d"
   ```
6. **Verify end-to-end**:
   ```bash
   cd C:/Projects/ai-playbook
   PYTHONPATH=. python -m scripts.notify --event smtp.rotation.verify --severity warn \
       --summary "SMTP credential rotation" --detail "Post-rotation smoke test."
   # Check 23051550+Wizarck@users.noreply.github.com inbox within 30s.
   ```
7. **Log rotation** to `.ai-playbook/overrides.log`.

## ATLASSIAN_API_TOKEN

Same 3-surface pattern (SOPS + GH secrets + k8s Secret). Generate a new
token at https://id.atlassian.com/manage-profile/security/api-tokens,
update the 3 surfaces, revoke the old.

## GITHUB_TOKEN (dev-side, SOPS)

This is the PAT Arturo uses for local ops (direct `git push` fallback,
`gh` CLI when `gh auth` is not set up, etc.). Rotation:

1. Generate new PAT at https://github.com/settings/tokens.
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
4. Revoke old PAT.

## God-mode PAT caveat

If a temporary god-mode PAT is issued (e.g. the one user provided on
2026-04-24 with 1-week expiry), track it separately — do NOT set it as
`PLAYBOOK_PROPAGATION_TOKEN` long-term. Use it only for the bootstrap
session, then rotate to a scoped fine-grained PAT ASAP.

## Cross-references

- [docs/concepts/data-retention.md](../docs/concepts/data-retention.md) — retention + deletion contract.
- [docs/concepts/env-vars.md](../docs/concepts/env-vars.md) — env var catalog (name + purpose for every secret).
- [docs/rules/break-glass.rule.md](../docs/rules/break-glass.rule.md) — log every ad-hoc override to `overrides.log`.
- [propagate-bump-troubleshooting.md](propagate-bump-troubleshooting.md) §Pattern D — when the Action fails with `Authentication failed`.
