# runbook: propagate-bump-troubleshooting.md

> **Audience**: the AI or a human debugging a failed
> `propagate-playbook-bump.yml` (or `propagate-skills-bump.yml`) run.
> **Status**: v1.1.0 (2026-05-01 — adds Pattern E supersede + Pattern F skills-bump date refresh + post-v0.8.0 expected behaviors).

## Quick diagnosis flow

```
Action failed on tag push
        │
        ▼
gh run view <run-id> --log-failed  →  which step?
        │
        ├── "Install playbook deps"  → Pattern A (setuptools)
        ├── "Propagate to every active consumer"
        │        │
        │        ├── "could not read Username"  → Pattern B (submodule auth)
        │        ├── "clone failed: Repository not found" → Pattern C (token scope)
        │        ├── "gh pr create ... already exists"    → idempotent OK (treated as pr-exists)
        │        ├── "supersede failed for <consumer>"    → Pattern F (post-v0.8.0)
        │        ├── "AGENTS.md updated: date is stale"   → Pattern G (pre-v0.8.3, fixed)
        │        └── "fatal: Authentication failed"       → Pattern D (PAT expired)
        └── Any other → examine env block + stderr tail
```

## Expected behaviors (v0.8.0+)

Before debugging, confirm what you're seeing isn't expected behavior:

### Supersede auto-closes prior bump PRs (v0.8.0+)

Each new `chore/bump-{playbook,skills}-vX.Y.Z` PR auto-closes ALL prior open PRs on the same change-stream (per [release-management.md §3.4](../specs/release-management.md)). If you see "PR #N closed: Auto-closed: superseded by #M" on consumer side, that's **correct behavior** — the propagate workflow ran `supersede_open_bump_prs()` after opening the new PR.

To verify supersede ran: list closed PRs in a consumer with the bump prefix:

```bash
gh pr list --repo Wizarck/<consumer> --state closed --limit 8 \
    --search "head:chore/bump-playbook" \
    --json number,headRefName,closedAt --jq '.[]'
```

If you see a tight cluster (timestamps within ~30s of the propagate workflow run), supersede worked.

### AGENTS.md `updated:` date refreshed (v0.8.3+)

`propagate-skills-bump.yml` rewrites BOTH `skills_sources` AND `updated:` lines in lockstep. If you see `updated: <today>` in the bump PR's diff, that's correct. If you see `updated: <stale-date>`, you're on a pre-v0.8.3 playbook — bump the consumer's submodule pin to v0.8.3+ and the next bump cycle will refresh.

## Pattern A — setuptools flat-layout discovery

**Symptom**

```
error: Multiple top-level packages discovered in a flat-layout:
       ['rfcs', 'specs', 'routers', 'templates'].
ERROR: Failed to build ... when getting requirements to build editable
##[error]Process completed with exit code 1.
```

**Root cause**
`pip install -e ".[dev]"` triggers setuptools auto-discovery. The playbook
has sibling top-level directories that are not Python packages (markdown +
YAML), and setuptools refuses to guess.

**Fix (permanent — landed 2026-04-24)**
[`pyproject.toml`](../pyproject.toml) now declares
`[tool.setuptools.packages.find]` with `include = ["scripts*"]` and
explicit excludes. If a future contributor removes this block, the Action
will regress to this failure.

**Verify**

```bash
python -m pip install -e ".[dev]" --dry-run 2>&1 | grep -iE "package|error" | head
```

Should list only `ai-playbook` + dependencies, no "multiple packages
discovered" warning.

## Pattern B — submodule auth (`could not read Username`)

**Symptom**

```
fatal: could not read Username for 'https://github.com': No such device or address
fatal: clone of 'https://github.com/Wizarck/ai-playbook.git' into submodule path '...'
❌ consumer-c   error   clone failed: ...
```

**Root cause**
The consumer's `.ai-playbook/` submodule is declared in `.gitmodules` with
a plain `https://github.com/...` URL. When `git clone --recurse-submodules`
recurses, it uses that URL **without** the PAT, and private-repo auth
fails (no TTY on the runner to prompt).

**Fix (permanent — landed 2026-04-24)**
[`scripts/propagate_bump.py`](../scripts/propagate_bump.py) `_configure_git_credentials`
installs a `git config --global url.https://<PAT>@github.com/.insteadOf https://github.com/`
rewrite at the start of the run. That rewrite applies transparently to
every github.com URL — parent clone AND nested submodule clones. Verified
working on 2026-04-24 run at SHA `6c5aa25a`.

**Also disabled**: the credential helper (`credential.helper = ""`) so git
doesn't try to prompt on a miss.

**If it fails again**
1. Confirm `_configure_git_credentials` runs before `_clone_consumer`:
   ```bash
   grep -n "_configure_git_credentials\|_clone_consumer" scripts/propagate_bump.py
   ```
   `_configure_git_credentials` must be called from `main()` before the
   per-consumer loop.
2. Confirm the PAT value is reaching the runner:
   ```bash
   gh secret list --repo Wizarck/ai-playbook | grep PLAYBOOK_PROPAGATION_TOKEN
   ```
   Must exist with a recent `updated` timestamp.

## Pattern C — token scope

**Symptom**

```
❌ <consumer>   error   clone failed: Repository not found.
```

On a PRIVATE consumer, `Repository not found` means the PAT lacks read
access to that specific repo.

**Root cause**
The PAT used as `PLAYBOOK_PROPAGATION_TOKEN` is a classic PAT with `repo`
scope but missing the org's SSO authorization for that specific private
repo, OR a fine-grained token scoped too narrowly.

**Fix**
See [`rotate-secrets.md`](rotate-secrets.md) §PLAYBOOK_PROPAGATION_TOKEN.
The token needs `contents:write` + `pull-requests:write` on every active
repo in [`consumers.yaml`](../consumers.yaml). For classic PATs on an org
with SSO, the token must also be "Authorized for Wizarck" in GitHub
settings.

## Pattern D — PAT expired

**Symptom**

```
fatal: Authentication failed for 'https://github.com/...'
```

Token expired or was revoked.

**Fix**
Rotate per [`rotate-secrets.md`](rotate-secrets.md) §PLAYBOOK_PROPAGATION_TOKEN.
After rotating, either wait for the next tag release OR manually re-trigger:

```bash
# Delete + recreate the tag to re-fire the Action on the same commit:
cd C:/Projects/ai-playbook
git tag -d vX.Y.Z
git push origin --delete vX.Y.Z
git tag -a vX.Y.Z -m "vX.Y.Z — re-tag after PAT rotation"
git push origin vX.Y.Z
```

## Pattern E — `x-access-token` URL form

**Symptom** (historical — fixed 2026-04-24 at SHA `79ad91d4`)
Clone works via `https://x-access-token:<token>@github.com/...` only for
GitHub App installation tokens, not classic PATs.

**Fix (permanent)**
[`scripts/propagate_bump.py`](../scripts/propagate_bump.py) uses
`url.insteadOf` rewrite (see Pattern B above). The legacy `x-access-token`
form was removed.

## Networking — pushing from desktop to github.com hangs

**Symptom**
Direct `git push origin` on the playbook from Arturo's desktop hangs or
gives "Connection timed out" to `github.com:443`.

**Root cause**
Intermittent — appears to correlate with the `10.0.0.1` local proxy
(Adguard? Pi-hole?). Not a recurring issue but has bitten multiple times.

**Workaround**
Use the token-inline HTTPS URL form for the specific push:

```bash
TOKEN=$(sops -d C:/Projects/consumer-d/secrets/secrets.env | grep ^GITHUB_TOKEN= | cut -d= -f2)
git push "https://x-access-token:${TOKEN}@github.com/Wizarck/ai-playbook.git" main vX.Y.Z
```

(For local `git push` `x-access-token` works fine — that's specifically
a GitHub feature for ambient auth on push. Distinct from Pattern E above
which was about clone URLs in automation.)

Once the push succeeds, normal `git push origin main` should work again
for that session. Investigate the proxy if this pattern persists — file
under Arturo's personal ops.

## Pattern F — supersede helper failure (post-v0.8.0)

**Symptom**

```
[propagate_bump] supersede failed for <consumer>: <error>
```

(Or, in `propagate_skills_bump.py`: `[propagate_skills_bump] supersede failed for <consumer>: ...`)

**Root cause**

After the new bump PR opens, `supersede_open_bump_prs()` (in `scripts/_bumper.py`) lists the consumer's open PRs and tries to close any with the matching `chore/bump-*` prefix (excluding the new one). It is **best-effort** — wrapped in a try/except so any individual close failure doesn't abort the propagate run. The most common failure modes:

- **The PAT lacks `pull-requests: write` scope on the consumer.** Verify `PLAYBOOK_PROPAGATION_TOKEN` per [rotate-secrets.md](rotate-secrets.md).
- **Race condition with another auto-close mechanism** (e.g. dependabot also closing the same PR). Check the consumer's PR for closure events near the timestamp.
- **API rate limit**. Look for HTTP 429 in the stderr.

**Fix**

The supersede failure is non-fatal: the new bump PR still opens, and the stale PRs can be closed manually:

```bash
for pr_num in <list of stale PR numbers>; do
  gh pr close $pr_num -R Wizarck/<consumer> \
    --comment "Superseded by #<new-pr> (manual cleanup after supersede helper failed)" \
    --delete-branch
done
```

If supersede fails consistently across multiple runs, file a bug — the helper might need broader try/except coverage in `_bumper.py`.

## Pattern G — pre-v0.8.3 stale `updated:` date (fixed in v0.8.3)

**Symptom (historical)**

A consumer's bump PR for skills (`chore/bump-skills-ai-playbook-vX.Y.Z`) modifies `AGENTS.md` to update `skills_sources` line, but leaves `updated: YYYY-MM-DD` at the prior (stale) date.

**Root cause**

`_edit_frontmatter_skills_source()` in `scripts/propagate_skills_bump.py` only rewrote `skills_sources` lines — not `updated:`. Each automated bump left the date drift behind. Surfaced 2026-05-01 in consumer-e PR #32 (rc7 bump) where AGENTS.md kept `updated: 2026-04-30` after a 2026-05-01 bump.

**Fix**

Bump consumer's `.ai-playbook` submodule pin to **v0.8.3 or later**. The fix tracks `updated:` index in the same regex pass and refreshes via `datetime.now(timezone.utc).strftime("%Y-%m-%d")` when any `skills_sources` line gets rewritten. Test in v0.8.3 release: confirmed end-to-end on consumer-e PR #33 (`updated: 2026-04-30 → 2026-05-01`).

If you see this on a consumer pinned to v0.8.0–v0.8.2: just merge the bump (the date staleness is cosmetic, not functional). The next bump cycle on v0.8.3+ will catch up.

## Cross-references

- [release.md](release.md) — the happy-path flow.
- [rotate-secrets.md](rotate-secrets.md) — PAT + SMTP rotation.
- [scripts/propagate_bump.py](../scripts/propagate_bump.py) — playbook bump CI script.
- [scripts/propagate_skills_bump.py](../scripts/propagate_skills_bump.py) — skills bump CI script.
- [scripts/_bumper.py](../scripts/_bumper.py) — `supersede_open_bump_prs()` shared helper.
- [.github/workflows/propagate-playbook-bump.yml](../.github/workflows/propagate-playbook-bump.yml) — playbook bump workflow.
- [.github/workflows/propagate-skills-bump.yml](../.github/workflows/propagate-skills-bump.yml) — skills bump workflow.
- [specs/release-management.md §3.4](../specs/release-management.md) — supersede contract.
