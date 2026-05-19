---
schema: runbook/v1
slug: propagate-bump-troubleshooting
description: Diagnose a failed propagate-playbook-bump or propagate-skills-bump workflow run and apply the matching remediation pattern.
audience: operator
estimated_time: 5-30 min depending on pattern
last_validated: "2026-05-19"
---

# Diagnose a failed propagate-bump workflow

## Outcome

The failing propagate workflow's root cause is identified and one of the canonical fix patterns is applied. The run is re-fired (by re-tagging or manual dispatch) and completes successfully, opening or refreshing bump PRs across every consumer in `consumers.yaml`.

## When to use this

The `propagate-playbook-bump.yml` or `propagate-skills-bump.yml` workflow failed on tag push. Detection:

- GitHub UI shows the run in red state.
- Email or dashboard notification from `scripts/notify.py` reports `propagate.failed`.
- A consumer is missing a bump PR after the tag was pushed.

Skip when the workflow succeeded but a downstream consumer is misbehaving — that is a per-consumer issue, not a propagate issue.

## Prerequisites

- `gh auth status` shows authenticated with read access to `Wizarck/ai-playbook` runs.
- Tag of the failing release is known: `gh run list --repo Wizarck/ai-playbook --workflow propagate-playbook-bump --limit 5`.
- Access to the run log: `gh run view <run-id> --log-failed`.

## Steps

### 1. Confirm the failure is not expected behaviour

Before debugging, rule out two intended behaviours:

- **Supersede auto-closes prior bump PRs (v0.8.0+)**. Each new `chore/bump-{playbook,skills}-vX.Y.Z` PR auto-closes ALL prior open PRs on the same change-stream. A `PR #N closed: Auto-closed: superseded by #M` message is correct, not a failure. Verify the supersede ran:
  ```bash
  gh pr list --repo Wizarck/<consumer> --state closed --limit 8 \
      --search "head:chore/bump-playbook" \
      --json number,headRefName,closedAt --jq '.[]'
  ```
  A tight cluster (timestamps within ~30s of the propagate run) means supersede worked.

- **AGENTS.md `updated:` date refresh (v0.8.3+)**. `propagate-skills-bump.yml` rewrites BOTH `skills_sources` AND `updated:` in lockstep. `updated: <today>` is correct. A stale date means the consumer is pre-v0.8.3 — bump its submodule pin to v0.8.3+ and the next cycle refreshes.

### 2. Identify the failing step

```bash
RUN=<run-id>
gh run view $RUN --log-failed --repo Wizarck/ai-playbook
```

Match the failing step against the diagnosis ladder:

```
Action failed on tag push
        │
        ▼
gh run view <run-id> --log-failed  →  which step?
        │
        ├── "Install playbook deps"  → Pattern A (setuptools)
        ├── "Propagate to every active consumer"
        │        │
        │        ├── "could not read Username"            → Pattern B (submodule auth)
        │        ├── "clone failed: Repository not found"  → Pattern C (token scope)
        │        ├── "gh pr create ... already exists"     → idempotent OK (pr-exists)
        │        ├── "supersede failed for <consumer>"     → Pattern F (post-v0.8.0)
        │        ├── "AGENTS.md updated: date is stale"    → Pattern G (pre-v0.8.3 — fixed)
        │        └── "fatal: Authentication failed"        → Pattern D (PAT expired)
        └── Any other → inspect env block + stderr tail
```

### 3. Apply the matching pattern from Troubleshooting below

Each pattern has a Symptom, Cause, Fix triplet plus an optional "If it fails again" subsection.

### 4. Re-fire the workflow

Once the fix lands on `main` (PAT rotated, code patched, etc.), re-fire the failed propagation:

```bash
cd C:/Projects/ai-playbook
git tag -d vX.Y.Z
git push origin --delete vX.Y.Z
git tag -a vX.Y.Z -m "vX.Y.Z — re-fire propagate after fix"
git push origin vX.Y.Z
gh run watch --repo Wizarck/ai-playbook
```

Re-tagging is the canonical way to dispatch the workflow; manual `workflow_dispatch` is not enabled on this workflow by design.

## Verification

- `gh run list --repo Wizarck/ai-playbook --workflow propagate-playbook-bump --limit 1` shows `completed success`.
- Every consumer in `consumers.yaml` (status `active`) has exactly one open `chore/bump-playbook-vX.Y.Z` PR (and matching `chore/bump-skills-...` if applicable).
- Prior stale bump PRs (different version) are closed with the supersede comment.

## Troubleshooting

### Pattern A — setuptools flat-layout discovery
**Symptom**:
```
error: Multiple top-level packages discovered in a flat-layout:
       ['rfcs', 'specs', 'routers', 'templates'].
ERROR: Failed to build ... when getting requirements to build editable
##[error]Process completed with exit code 1.
```
**Cause**: `pip install -e ".[dev]"` triggers setuptools auto-discovery. The playbook has sibling top-level dirs that are not Python packages.
**Fix**: `pyproject.toml` declares `[tool.setuptools.packages.find]` with `include = ["scripts*"]` and explicit excludes. If a contributor removes the block, the Action regresses. Verify:
```bash
python -m pip install -e ".[dev]" --dry-run 2>&1 | grep -iE "package|error" | head
```
Should list only `ai-playbook` + dependencies, no "multiple packages discovered" warning.

### Pattern B — submodule auth (`could not read Username`)
**Symptom**:
```
fatal: could not read Username for 'https://github.com': No such device or address
fatal: clone of 'https://github.com/Wizarck/ai-playbook.git' into submodule path '...'
❌ consumer-c   error   clone failed: ...
```
**Cause**: the consumer's `.ai-playbook/` submodule URL in `.gitmodules` is plain `https://github.com/...`. On `--recurse-submodules`, git uses that URL without the PAT.
**Fix**: `scripts/propagate_bump.py::_configure_git_credentials` installs a `git config --global url.https://<PAT>@github.com/.insteadOf https://github.com/` rewrite at the start of the run. It also disables the credential helper (`credential.helper = ""`).
**If it fails again**:
1. Confirm the helper runs first:
   ```bash
   grep -n "_configure_git_credentials\|_clone_consumer" scripts/propagate_bump.py
   ```
   `_configure_git_credentials` must be called from `main()` before the per-consumer loop.
2. Confirm the PAT is reaching the runner:
   ```bash
   gh secret list --repo Wizarck/ai-playbook | grep PLAYBOOK_PROPAGATION_TOKEN
   ```
   Must show a recent `updated` timestamp.

### Pattern C — token scope (`Repository not found` on private)
**Symptom**:
```
❌ <consumer>   error   clone failed: Repository not found.
```
**Cause**: the PAT used as `PLAYBOOK_PROPAGATION_TOKEN` lacks read access to the consumer. Either a classic PAT not authorised for the org (SSO), or a fine-grained token scoped too narrowly.
**Fix**: see [Runbook: rotate-secrets](rotate-secrets.md) §PLAYBOOK_PROPAGATION_TOKEN. The token needs `contents:write` + `pull-requests:write` on every active repo in `consumers.yaml`. Classic PATs on SSO orgs must also be "Authorized for Wizarck".

### Pattern D — PAT expired
**Symptom**:
```
fatal: Authentication failed for 'https://github.com/...'
```
**Cause**: token expired or revoked.
**Fix**: rotate per [Runbook: rotate-secrets](rotate-secrets.md) §PLAYBOOK_PROPAGATION_TOKEN. Wait for the next legitimate release, or re-fire the workflow per step 4.

### Pattern E — `x-access-token` URL form
**Symptom** (historical — fixed 2026-04-24 at SHA `79ad91d4`): clone works only for GitHub App installation tokens, not classic PATs.
**Cause**: the `https://x-access-token:<token>@github.com/...` URL form is App-only.
**Fix**: `scripts/propagate_bump.py` uses `url.insteadOf` rewrite (see Pattern B). The legacy form was removed.

### Pattern F — supersede helper failure (post-v0.8.0)
**Symptom**:
```
[propagate_bump] supersede failed for <consumer>: <error>
```
**Cause**: after the new bump PR opens, `supersede_open_bump_prs()` (in `scripts/_bumper.py`) lists open PRs and closes prior `chore/bump-*` matches. It is best-effort, wrapped in try/except. Common failure modes:
- PAT lacks `pull-requests: write` scope on the consumer.
- Race with another auto-close mechanism (dependabot also closing).
- HTTP 429 rate limit.
**Fix**: the supersede failure is non-fatal — the new bump PR still opened. Close stale PRs manually:
```bash
for pr_num in <list of stale PR numbers>; do
  gh pr close $pr_num -R Wizarck/<consumer> \
    --comment "Superseded by #<new-pr> (manual cleanup after supersede helper failed)" \
    --delete-branch
done
```
If supersede fails consistently across multiple runs, file a bug — the helper may need broader try/except in `_bumper.py`.

### Pattern G — pre-v0.8.3 stale `updated:` date (fixed in v0.8.3)
**Symptom** (historical): a skills bump PR modifies `AGENTS.md` to update `skills_sources` but leaves `updated: YYYY-MM-DD` at the prior date.
**Cause**: `_edit_frontmatter_skills_source()` in `scripts/propagate_skills_bump.py` rewrote only `skills_sources`, not `updated:`. Surfaced 2026-05-01 on consumer-e PR #32.
**Fix**: bump the consumer's `.ai-playbook` submodule pin to v0.8.3 or later. The v0.8.3 fix tracks `updated:` in the same regex pass and refreshes via `datetime.now(timezone.utc).strftime("%Y-%m-%d")` when any `skills_sources` line gets rewritten. Pre-v0.8.3 staleness is cosmetic, not functional — merge the bump; the next cycle catches up.

### Pattern H — push from desktop to github.com hangs
**Symptom**: direct `git push origin` on the playbook hangs or returns `Connection timed out` to `github.com:443`.
**Cause**: intermittent — correlates with the local `10.0.0.1` proxy (Adguard / Pi-hole). Not the propagate workflow itself; this is the developer-side push to fire it.
**Fix (workaround)**: use the token-inline HTTPS URL form:
```bash
TOKEN=$(sops -d C:/Projects/consumer-d/secrets/secrets.env | grep ^GITHUB_TOKEN= | cut -d= -f2)
git push "https://x-access-token:${TOKEN}@github.com/Wizarck/ai-playbook.git" main vX.Y.Z
```
Once the push succeeds, normal `git push origin main` works again for the session. Investigate the proxy if the pattern persists.

## Related

- [Runbook: release](release.md) — the happy-path release flow that fires this workflow.
- [Runbook: rotate-secrets](rotate-secrets.md) — PAT and SMTP rotation; Patterns C and D depend on this.
- [Runbook: skills-version-bump](skills-version-bump.md) — sibling workflow for skills source-repo tags.
- [Concept: release-management](../concepts/release-management.md) §3.4 — supersede contract.
