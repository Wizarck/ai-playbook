---
schema: runbook/v1
slug: runbook-key-rotation-emergency
description: Emergency rotation of 1-3 suspected or confirmed compromised credentials within 1 hour (revoke + reissue + restart + history rewrite if published).
audience: operator
estimated_time: ≤1 h to revoke + reissue; ≤48 h post-mortem draft
last_validated: "2026-05-19"
---

# Emergency rotation of leaked credentials

## Outcome

Every leaked credential is revoked at the vendor side, replaced with a narrower-scoped credential, and the secrets store and all consuming services have been updated and restarted. If the leak was in a published commit, the git history has been rewritten with `git filter-repo` and force-pushed. A security post-mortem is drafted within 48 hours and published within 7 days.

## When to use this

A credential is suspected or confirmed compromised AND the leak window is open. Escalates from [Runbook: rotate-secrets](rotate-secrets.md) when the breach is active rather than precautionary.

Common triggers:

- A vendor sends a "your token was used from an unexpected location" email.
- `secrets_scan.py` post-push CI fails AND the repo is public OR has >1 contributor.
- A team member reports having committed a secret to a repo they do not own.
- An external party reports a token or key valid in their possession.

This runbook handles **scoped** exposure (1-3 keys). For broad compromise (suspected machine compromise, suspected supplier compromise), use [Runbook: runbook-secrets-leak-containment](runbook-secrets-leak-containment.md) which assumes a wider blast radius.

Severity: **S1** if customer data is reachable via the leaked credential; **S2** otherwise. MTTR: ≤1 h to revoke + reissue.

## Prerequisites

- SOPS / age key for the encrypted secrets store: `age-keygen -y ~/.config/sops/age/keys.txt`.
- 1Password (or equivalent) for vendor-side rotation — most vendors require a manual UI dance.
- VPS SSH access for restarting any service that consumes the credential: `ssh project-d-vps echo ok`.
- `git-filter-repo` installed if history rewrite is anticipated: `pip install git-filter-repo`.

## Steps

1. **Identify the credential's blast radius.**
   For each leaked credential, determine:
   - What service consumes it: `grep -r '<env-var-name>' .` across consumer repos.
   - What does it grant: vendor docs (read access, write access, customer data, billing).
   - Was the credential used during the leak window: vendor audit log if available (Anthropic / OpenAI / GitHub all expose this).

2. **Revoke at the vendor side BEFORE issuing a replacement.**
   An active bad token is worse than 5 minutes of downtime.

   | Vendor | Revocation path |
   |---|---|
   | Anthropic | console.anthropic.com → Settings → API Keys → Revoke. |
   | OpenAI | platform.openai.com → API keys → Revoke. |
   | OpenRouter | openrouter.ai → Keys → Revoke. |
   | GitHub PAT | github.com/settings/tokens → Revoke / Delete. |
   | Atlassian API token | id.atlassian.com → Security → API tokens → Revoke. |
   | Google service account | console.cloud.google.com → IAM → Service Accounts → Keys → Delete. |
   | Cloudflare token | dash.cloudflare.com → My Profile → API Tokens → Delete. |
   | SOPS / age key | rotate the master key — run Step 6 NOW, before Steps 3–4. Anything written to the store while it is still encrypted to the leaked key is readable by whoever holds that key. |

3. **Issue a replacement credential.**
   Same vendor UI, "Create new key". Scope it as narrowly as possible (read-only when read-only suffices).

4. **Update the secrets store.**
   If the SOPS / age key itself leaked, Step 6 must already be done: the store has to be encrypted to the new key before it receives replacement credentials.
   ```bash
   sops <repo>/secrets/secrets.env   # decrypts in-place; replace the value
   # Save and close — sops re-encrypts.
   git add secrets/secrets.env
   git commit -m "chore(secrets): rotate <CREDENTIAL_NAME> after leak (INC-<n>)"
   ```

5. **Restart consuming services.**
   ```bash
   # k3s pods that read from secrets:
   kubectl rollout restart deploy/<service> -n project-d
   # Docker compose:
   cd /opt/<service> && docker compose up -d <service>
   # Local services (rare):
   systemctl --user restart <service>
   ```

6. **If the leaked credential was the SOPS / age master key**, re-key the store. Do this before Steps 3–4 (see Step 2). Needs sops ≥ 3.7 (the first release with age). Paste the whole block, parentheses included, from the repo root, after replacing `<leaked-pub-key>` (and `STORE`, if the store's files are named otherwise):
   ```bash
   (
     set -euo pipefail   # inside ( ): a failure ends this block, not your shell or SSH session
     STORE=('*secrets*.env')   # git pathspecs of every sops dotenv file to re-key, e.g. ('.secrets/*.env.enc')
     K=~/.config/sops/age   # the directory holding keys.txt (sops on Windows defaults to %AppData%/sops/age)
     FILES=$(git ls-files -- "${STORE[@]}")
     [ -n "$FILES" ] || { echo "no store files matched ${STORE[*]}; nothing changed" >&2; exit 1; }
     [ -f "$K/keys-new.txt" ] || age-keygen -o "$K/keys-new.txt"   # a retry reuses the key it made
     NEW_PUB=$(age-keygen -y "$K/keys-new.txt")
     OLD_PUB=<leaked-pub-key>   # age1...; `age-keygen -y ~/.config/sops/age/keys.txt` prints it
     dec() { SOPS_AGE_KEY_FILE="$1" sops -d --input-type dotenv --output-type dotenv "$2" > /dev/null 2>&1; }
     for f in $FILES; do
       # Removal is read from the file's recipients: keys.txt may also hold a kept recipient's identity.
       if dec "$K/keys-new.txt" "$f" && ! grep -qF "$OLD_PUB" "$f"; then continue; fi   # done by an earlier run
       grep -qF "$OLD_PUB" "$f" || { echo "$OLD_PUB is not a recipient of $f; nothing changed" >&2; exit 1; }
       # sops 3.7 `--rotate` exits 0 and EMPTIES the file when it cannot decrypt it:
       # prove keys.txt can, keep a copy, and put it back unless the result verifies.
       dec "$K/keys.txt" "$f" || { echo "keys.txt cannot decrypt $f; nothing changed" >&2; exit 1; }
       cp "$f" "$f.pre-rekey"
       if SOPS_AGE_KEY_FILE="$K/keys.txt" sops --rotate --in-place \
            --add-age "$NEW_PUB" --rm-age "$OLD_PUB" --input-type dotenv --output-type dotenv "$f" \
          && dec "$K/keys-new.txt" "$f" && ! grep -qF "$OLD_PUB" "$f"; then
         rm "$f.pre-rekey"
       else
         mv "$f.pre-rekey" "$f"
         echo "re-key of $f did not verify (the new key alone must decrypt it, and the leaked key must be gone from its recipients); restored it" >&2
         exit 1
       fi
     done
   )
   ```
   In place, so there is no `/dev/stdin` (which native sops cannot open from Git Bash) and no new file name for a path-scoped `.sops.yaml` creation rule to reject. `--rotate` re-encrypts each file under a fresh data key for its current recipients, minus the leaked key, plus the new one; other recipients (a server or CI key) keep access. Whether the leaked key is gone is read from each file's recipient list, not by decrypting with `keys.txt`, which may also hold such a kept recipient's identity. The first failure stops the block with that file restored and the rest untouched, and re-running it skips the files already done. Then point the `.sops.yaml` recipients at the new public key, swap the leaked identity in `keys.txt` for the one in `keys-new.txt` (keep any other identity it holds), and commit.
   The old ciphertext stays in git history and the leaked key still decrypts it: every secret that was in the store counts as leaked and goes through Steps 2–4.

7. **Force-push history rewrite IF the leak was in a published commit.**
   ```bash
   pip install git-filter-repo
   git filter-repo --replace-text <(echo "<leaked-token>==>REDACTED")
   git push --force origin <branch>
   ```
   Coordinate with collaborators before force-pushing. Anyone with the old history must re-clone. Per [Runbook: git-worktree-bare-setup](git-worktree-bare-setup.md), bare-repo collaborators need to re-fetch and reset their worktrees.

8. **File a CISA-style note in `incidents.jsonl`.**
   ```bash
   echo '{"ts":"<iso>","incident_id":"INC-<n>","severity":"S1","scenario":"secrets-leak","credentials_rotated":["<list>"],"force_push":<true|false>,"customer_data_at_risk":<true|false>,"state":"resolved"}' >> incidents.jsonl
   ```

## Verification

- Vendor audit log shows no requests with the old token after revocation timestamp.
- Replacement token works end-to-end (smoke test the consumer service per its runbook).
- `secrets_scan.py` is green on `HEAD`.
- If history was rewritten: `git log --all --pickaxe-regex --pickaxe-all -S '<leaked-token>'` returns empty.

## Troubleshooting

### Symptom: rollback after the rotation completed (false-alarm leak)
**Cause**: the leak was reported but turned out to be a false positive.
**Fix**: there is no rollback for "I revoked a leaked credential". The only forward path is "issue a new one and keep going". The cost of a false alarm is one batch of vendor-side revocation work; you do not re-instate the old credential.

### Symptom: replacement token does not work after Step 5
**Cause**: pod did not pick up the new secret (cached env at startup), OR the new token's scope is narrower than required.
**Fix**: confirm `kubectl rollout restart` completed (`kubectl rollout status`). If still failing, audit the new token's scopes at the vendor side and re-issue with the original scopes.

### Symptom: `git filter-repo` rewrites locally but force-push is rejected
**Cause**: branch protection prevents force-push on the default branch, OR the remote has new commits since the rewrite.
**Fix**: temporarily relax branch protection (admin override), force-push, then re-enable protection. If the remote has new commits, rebase the new commits on top of the rewritten history before force-pushing — coordinate with collaborators first.

### Symptom: SOPS master key rotation stopped part-way
**Cause**: the block in Step 6 stopped and printed why. When it names a file, the files before it are re-keyed; that file (restored from `<file>.pre-rekey` when its re-key did not verify) and the rest are not.
**Fix**: act on the message, then re-run the whole block: it reuses `keys-new.txt` and skips the files already done.

- `no store files matched <pathspecs>`: nothing was changed; set `STORE` to the pathspecs of the store's files (`git ls-files -- <pathspec>` shows what one matches).
- `<key> is not a recipient of <file>`: `<leaked-pub-key>` is mistyped (compare it with the `recipient` entries in the file's sops metadata), or that file was never encrypted to the leaked key and needs no re-key: leave it out of `STORE` (an extra `':!<file>'` pathspec excludes it).
- `keys.txt cannot decrypt <file>`: `SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops -d <file>` shows the sops error; often `K` is not the directory that holds the identity.
- `re-key of <file> did not verify`: the file is back as it was; the sops error printed above the message says why `--rotate` failed.

Do NOT take the leaked identity out of `keys.txt` until every file decrypts with `keys-new.txt` alone.

## Post-incident artefact required

**Security post-mortem ≤48 h to draft, ≤7 days to publish** per [Concept: incident-response](../concepts/incident-response.md) §4 scenario #3. The post-mortem must answer:

- How did the credential leak?
- Was it used by a third party? (vendor audit log evidence).
- What customer data was reachable? (blast radius).
- What process change prevents the next leak? (often a `secrets_scan.py` rule update or a pre-commit hook gap).

## Related

- [Runbook: rotate-secrets](rotate-secrets.md) — non-emergency scheduled rotation.
- [Runbook: runbook-secrets-leak-containment](runbook-secrets-leak-containment.md) — wider containment when leak scope is broad.
- [Runbook: git-worktree-bare-setup](git-worktree-bare-setup.md) — collaborator re-clone after history rewrite.
- [Concept: incident-response](../concepts/incident-response.md) — incident-class ladder; this is §4 scenario #3.
- [Concept: data-retention](../concepts/data-retention.md) — what data the leaked credential could exfiltrate determines severity.
- [Concept: post-mortem](../concepts/post-mortem.md) — mandatory artefact.
