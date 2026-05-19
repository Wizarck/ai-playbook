---
schema: runbook/v1
slug: onboard-new-project
description: Attach a new repo to the ai-playbook (submodule pin, dispatcher routers, MCP config, SessionStart hook, propagation, Profile A/B enforcement).
audience: developer
estimated_time: 10-15 min (Profile A adds ~5 min for CodeRabbit install)
last_validated: "2026-05-19"
---

# Onboard a new project to the playbook

## Outcome

The new repo has:

- `.ai-playbook/` submodule pinned to the latest release.
- `AGENTS.md` (v1 dispatcher), `CLAUDE.md`, `GEMINI.md`, `.cursor/rules/00-dispatcher.mdc` routers.
- `mcp-servers.project.yaml` with a Hindsight bank assigned.
- `.claude/settings.json` with the SessionStart hook auto-fired.
- `.mcp.json` + `.gemini/settings.json` rendered from the 3-layer merge.
- `.gitignore` extended with playbook entries.
- Pre-commit hooks installed (schema, secrets, verdict, drift).
- `~/.ai-playbook/projects.yaml` updated for local path resolution.
- GitHub Project board with the canonical Status schema (and, for Profile A, branch protection + CodeRabbit + merge queue).

A Claude Code session at the repo root then auto-recalls from Hindsight bank `<project>` at startup and recognises the universal specs via inheritance. Submodule bumps are pulled by the consumer at its own pace (Dependabot / Renovate / manual `git submodule update`) per the v0.19.0 pull-model contract.

## When to use this

You are about to create (or have just created) a repo and want it to inherit from the playbook. Skip when:

- The repo already has `.ai-playbook/` and `AGENTS.md` — use the daily flow instead.
- The repo will not consume any playbook contract (rare; usually a third-party fork).

## Prerequisites

- `git --version` and `python --version` (3.11+) report success.
- `pipx list | grep pre-commit` shows pre-commit installed.
- `gh auth status` shows authenticated.
- Write access to the new repo and the ai-playbook repo.

## Steps

### 1. Decide the bank name and the profile (before bootstrap)

The bank defaults to `<project-name>` lowercased (per [Concept: memory-hierarchy](../concepts/memory-hierarchy.md)). Override only when sharing a bank deliberately.

Choose Profile A or B per [Concept: release-management](../concepts/release-management.md):

| Visibility | Profile | GH plan | Branch protection | CodeRabbit | Merge queue |
|---|---|---|---|---|---|
| `public` | A | Free OK | enabled | free unlimited | enabled |
| `private` | B | Free OK | needs Pro/Team | paid only | unavailable on Free |
| `private` | A | Pro/Team ($4+/mo) | enabled | paid only | Team+ |

Rule of thumb:
- OSS-friendly license + no IP secret → public + Profile A (cost 0, full enforcement).
- Privacy non-negotiable, solo developer → private + Profile B (convention-based).
- Privacy + multi-dev → private + Pro/Team + Profile A.

Document the decision in `docs/hitl-gates-log.md` of the consumer.

### 2. Create the repo on GitHub (if it does not exist)

```bash
gh repo create Wizarck/<project-name> --private --clone
cd <project-name>
git commit --allow-empty -m "chore: initial commit"
git push -u origin master
```

If the repo already exists with history, `cd` into its working tree and skip to step 3.

### 3. Run `bootstrap.py` from the playbook

```bash
cd /c/Projects/<project-name>

python /c/Projects/ai-playbook/scripts/bootstrap.py <project-name> \
    --owner <your-email> \
    --path . \
    --visibility private \
    --default-branch master
```

Flags:

| Flag | Purpose |
|---|---|
| `<project-name>` (positional) | Slug. `[a-zA-Z0-9][a-zA-Z0-9_-]*`. Bank is `<project-name>` lowercased. |
| `--owner` | Email for AGENTS.md frontmatter. Defaults to `$GIT_AUTHOR_EMAIL` or `git config user.email`. |
| `--path .` | Where to write. Defaults to `<cwd>/<project-name>`. Pass `.` when the repo already exists. |
| `--visibility private\|public` | Sets the visibility marker in AGENTS.md frontmatter. Public repos do not include the personal layer in `.mcp.json`. |
| `--default-branch master\|main` | Stored in AGENTS.md frontmatter; informational only. |
| `--personal` | For personal repos only. Marks `personal: true`; loads the personal add-on if configured. |
| `--dry-run` | Simulate without writing. Recommended on first pass. |

Expected output:

```
→ Bootstrapping project '<project-name>'
   target : /c/Projects/<project-name>
   owner  : <your-email>
   pin    : v0.19.0
   mode   : live
✓ added .ai-playbook submodule pinned at v0.19.0
✓ copied 8 templates with placeholder substitution
✓ pre-commit installed
✓ doctor.py: ✅ healthy
✓ rendered .mcp.json + .gemini/settings.json for <project-name>
```

### 4. Fill the manual placeholders in AGENTS.md

Bootstrap leaves 4 placeholders unsubstituted (human-fill required):

```bash
grep -nE "\{\{[A-Z_]+\}\}" AGENTS.md
```

| Placeholder | What to write |
|---|---|
| `{{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}` | §1 identity — what the project IS in 1-3 lines. |
| `{{ACTIVE_OPENSPEC_CHANGE_OR_NONE}}` | §3 active work — `none (bootstrap)` is fine at start. |
| `{{PROJECT_SPECIFIC_RULES_NOT_DUPLICATING_PLAYBOOK}}` | §4 hard rules — yours, not the playbook's. |
| `{{NONE_OR_EXPLICIT_OVERRIDES_WITH_RATIONALE}}` | §7 overrides — `None.` by default. |
| `{{EMPTY_FILL_AS_YOU_LEARN}}` | §8 gotchas — empty by default. |

Validate:

```bash
python .ai-playbook/scripts/schema_validate.py AGENTS.md
# Expected: ✅ AGENTS.md valid against schema agents-md/v1
```

### 5. Commit + push the project

```bash
cd /c/Projects/<project-name>
git add .
git commit -m "chore: bootstrap <project-name> via ai-playbook v0.19.0"
git push
```

### 6. (Optional) Configure submodule-bump automation

If you want automated bump PRs each time the playbook tags, add a Dependabot or Renovate config in the new repo. Example Dependabot:

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "gitsubmodule"
    directory: "/"
    schedule: { interval: "weekly" }
```

Otherwise, bump manually with `cd .ai-playbook && git fetch && git checkout vX.Y.Z` whenever you decide to absorb a new release.

### 7. Bootstrap the GitHub Project board + Profile A/B enforcement

Create the GH Project (if it does not exist):

```bash
gh project create --owner Wizarck --title "<project-name>"
gh project list --owner Wizarck   # take the resulting number, e.g. 5
```

Even when Jira is the primary tracker, the GH Project still hosts the roadmap view + canonical Status schema.

Run the bootstrap (idempotent — safe re-run):

```bash
cd /c/Projects/<project-name>
python -m scripts.bootstrap_gh_project \
    --owner Wizarck --project-number <N> \
    --repo Wizarck/<project-name> \
    --profile auto \
    --visibility private   # only when not yet set
```

`--profile auto` detects visibility via `gh repo view` and applies:

- **Profile A (public)**: branch protection (1 review, 5 universal checks), repo settings (auto-merge=on, squash-only, delete-branch-on-merge), `.coderabbit.yaml` from template.
- **Profile B (private)**: only repo settings; emits a notice that branch protection is unavailable on GH Free private.

Both profiles add the canonical schema: Status (5 options) + Risk + P&L impact + Branch + Base SHA.

### 9. Install the CodeRabbit GitHub App (Profile A only)

CodeRabbit is free unlimited on OSS repos. It reviews every PR using the path-instructions in `.coderabbit.yaml`.

1. Visit <https://github.com/marketplace/coderabbitai>.
2. "Set up plan" → "CodeRabbit Free for Open Source".
3. Account: **`<your-org>`** · Repository access: **"Only select repositories"** → mark the new repo.
4. "Install & Authorize".

On the first PR, CodeRabbit comments automatically. The worker AI must read and respond to its comments before requesting Gate F (per [Concept: release-management](../concepts/release-management.md)).

Skip if the repo stays private or if CodeRabbit is not wanted. The §4.5 contract degrades to self-review (Profile B fallback, see [Runbook: coderabbit-fallback](coderabbit-fallback.md)).

### 10. Configure the `CONSUMER_D_GOD_MODE` secret (Profile A only)

If the consumer has CI workflows that need to clone `.ai-playbook/` (private submodule of `Wizarck/ai-playbook`):

```bash
gh secret set CONSUMER_D_GOD_MODE -R Wizarck/<project-name> --body "<your-pat>"
```

The PAT requires scope `Contents: read` on `Wizarck/ai-playbook` and `Wizarck/consumer-d-skills`. Without this, `actions/checkout@v4` with `submodules: true` fails with `404 Repository not found`.

### 11. Verify the SessionStart hook

Launch a Claude Code session in the repo:

```bash
cd /c/Projects/<project-name>
claude  # or whatever launches Claude Code
```

After ~30-60 seconds (cold recall) `.claude/injected-context.md` should appear with results from bank `<project-name>`. Empty on first run is normal — the bank is created lazily.

### 12. (Optional) Copy auto-transition + dep-check + coderabbit-fallback workflows

When the consumer uses the slicing graph actively (Wave 0 sequential + Wave N parallel):

```bash
cp .ai-playbook/templates/new-project/.github/workflows/project-status.yml.tmpl \
   .github/workflows/project-status.yml
cp .ai-playbook/templates/new-project/.github/workflows/dep-check.yml.tmpl \
   .github/workflows/dep-check.yml
cp .ai-playbook/templates/new-project/.github/workflows/coderabbit-fallback.yml.tmpl \
   .github/workflows/coderabbit-fallback.yml
```

Configure:

- Secret `PROJECT_AUTOMATION_TOKEN`: PAT with Project read+write.
- Variable `PROJECT_OWNER`: `<your-org>` (your GitHub user or org login).
- Variable `PROJECT_NUMBER`: `<N>` from step 8.

`project-status.yml` auto-transitions items from Blocked → Todo when their deps are Done. `dep-check.yml` (opt-in hard gate) blocks a slice's PR if its deps are not Done. `coderabbit-fallback.yml` (v0.9.0+) posts a self-review checklist when CodeRabbit is unavailable AND §4.5 is empty — only uses `secrets.GITHUB_TOKEN`.

`bootstrap_gh_project.py --profile auto` (v0.9.0+) copies `coderabbit-fallback.yml` automatically; the manual `cp` is for consumers skipping the bootstrap script.

## Verification

End-to-end checks:

```bash
python .ai-playbook/scripts/schema_validate.py AGENTS.md       # AGENTS.md valid
python .ai-playbook/scripts/mcp/validate.py --consumer-root .  # MCP config valid
python .ai-playbook/scripts/check_mcp_drift.py --consumer-root .  # No drift
python .ai-playbook/scripts/doctor.py                          # Full suite
```

All four must end in success. Each script prints a `FIX:` line on failure with the exact remediation.

## Troubleshooting

### Symptom: bootstrap exits with `bank not allowed`
**Cause**: the requested `--bank-id` is reserved or already claimed by another project.
**Fix**: pick a different bank name, or share an existing bank deliberately. Edit `mcp-servers.project.yaml` and `.claude/settings.json` after bootstrap to point at the chosen bank.

### Symptom: schema_validate fails with "unsubstituted placeholder"
**Cause**: AGENTS.md still has `{{PLACEHOLDER}}` literals.
**Fix**: `grep -nE "\{\{[A-Z_]+\}\}" AGENTS.md` and fill each one per step 4.

### Symptom: SOPS path mismatch on the SessionStart hook
**Cause**: the repo is not co-located with `consumer-d/` where the canonical CF Access creds live.
**Fix**: edit `.claude/settings.json` and replace
```
"command": "sops exec-env ../consumer-d/secrets/secrets.env -- python ..."
```
with an absolute path: `"command": "sops exec-env /absolute/path/to/your/secrets.env -- python ..."`. Or export the env vars in the shell profile and drop the `sops exec-env` wrapper.

### Symptom: CI submodule clone fails with `404 Repository not found`
**Cause**: `CONSUMER_D_GOD_MODE` secret missing or PAT lacks `Contents: read` on the playbook + skills repos.
**Fix**: rotate per [Runbook: rotate-secrets](rotate-secrets.md), confirming the PAT has both repos in scope.

### Symptom: rollback — something went wrong and the bootstrap must be undone
**Fix**:
```bash
cd /c/Projects/<project-name>
git rm -rf --cached .ai-playbook
rm -rf .ai-playbook AGENTS.md CLAUDE.md GEMINI.md .claude .cursor .mcp.json .gemini mcp-servers.project.yaml
# Edit .gitignore by hand if it carries playbook entries you want to keep.
```

## Related

- [Runbook: release](release.md) — when the playbook cuts a release, consumers pull at their own pace (v0.19.0+ pull model).
- [Runbook: hindsight-retain](hindsight-retain.md) — how to write lessons to the project's bank.
- [Runbook: coderabbit-fallback](coderabbit-fallback.md) — Profile B self-review when CodeRabbit is unavailable.
- [Runbook: rotate-secrets](rotate-secrets.md) — SMTP / Atlassian / dev `GITHUB_TOKEN` rotation.
- [Runbook: git-worktree-bare-setup](git-worktree-bare-setup.md) — alternative layout for projects that want per-branch worktrees.
- [Concept: memory-hierarchy](../concepts/memory-hierarchy.md) — bank naming convention.
- [Concept: release-management](../concepts/release-management.md) — Profile A/B and AI-reviewer §4.5.
- [Concept: session-start-hook](../concepts/session-start-hook.md) — hook wiring + degradation path.
