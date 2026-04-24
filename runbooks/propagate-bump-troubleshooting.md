# runbook: propagate-bump-troubleshooting.md

> **Audience**: the AI or a human debugging a failed
> `propagate-playbook-bump.yml` run.
> **Status**: v1.0.0. Populated from the first 4 runs on 2026-04-24 —
> 3 real failures, 1 success. Add a section here every time a new
> failure mode surfaces.

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
        │        └── "fatal: Authentication failed"       → Pattern D (PAT expired)
        └── Any other → examine env block + stderr tail
```

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
❌ openTrattOS   error   clone failed: ...
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
TOKEN=$(sops -d C:/Projects/eligia-core/secrets/secrets.env | grep ^GITHUB_TOKEN= | cut -d= -f2)
git push "https://x-access-token:${TOKEN}@github.com/Wizarck/ai-playbook.git" main vX.Y.Z
```

(For local `git push` `x-access-token` works fine — that's specifically
a GitHub feature for ambient auth on push. Distinct from Pattern E above
which was about clone URLs in automation.)

Once the push succeeds, normal `git push origin main` should work again
for that session. Investigate the proxy if this pattern persists — file
under Arturo's personal ops.

## Cross-references

- [release.md](release.md) — the happy-path flow.
- [rotate-secrets.md](rotate-secrets.md) — PAT + SMTP rotation.
- [scripts/propagate_bump.py](../scripts/propagate_bump.py) — the CI script itself.
- [.github/workflows/propagate-playbook-bump.yml](../.github/workflows/propagate-playbook-bump.yml) — the workflow.
