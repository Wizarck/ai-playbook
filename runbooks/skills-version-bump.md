# runbook: skills-version-bump.md — cut a new skills source-repo tag

> **Audience**: AI (Claude / future session) or human maintainer.
> **Status**: v1.0.0. Lands with `ai-playbook v0.4.0` (RFC-0001).
> **Prereqs**: write access to the source repo being bumped
> (`Wizarck/ai-playbook` and/or `Wizarck/eligia-skills`); the
> `PLAYBOOK_PROPAGATION_TOKEN` secret with `contents:write` +
> `pull-requests:write` on every consumer in
> [`consumers.yaml`](../consumers.yaml) — same secret used by the
> playbook bump runbook.

## What this runbook does

Cuts a new semver tag on a **skills source repo** (`ai-playbook` itself, or
`eligia-skills`, or any other registered source), which triggers
[`propagate-skills-bump.yml`](../.github/workflows/propagate-skills-bump.yml)
to auto-open "bump skills pin to `vX.Y.Z`" PRs across every active consumer
that has `skills_pins.<source-repo>` in [`consumers.yaml`](../consumers.yaml).

Sibling of [`release.md`](release.md), which bumps the playbook submodule;
this one bumps the skills submodules.

**Propose-only HITL**: automation opens PRs. A human reviews + merges per
consumer. Never auto-merge — the point of the bump is for each consumer to
verify the new skills don't regress its tests / workflows.

## When to bump

Bump skills when ANY of:

- A new skill is added to `<source-repo>/skills/`.
- An existing skill's `SKILL.md`, workflow, or assets change in a way that
  affects agent behaviour.
- A skill is renamed or removed (treat as breaking → major bump).
- A skill's `name` frontmatter changes (also breaking).

Do NOT bump when:

- README, docs, tests, or CI of the source repo change without touching
  `skills/`. Those land on `main`/`master` directly without a tag.

## Semver decision (per source repo)

| Kind of change in `skills/` | Bump |
|---|---|
| Typo fix, docs polish in a single SKILL.md | patch (`v0.4.0 → v0.4.1`) |
| New skill added; existing skill expanded with backwards-compatible content | minor (`v0.4.0 → v0.5.0`) |
| Skill renamed, deleted, or `name` frontmatter changed | major (`v0.x → v1.0.0`) — requires RFC first per [specs/rollout-strategy.md](../specs/rollout-strategy.md) |

Independent semver per source repo: `ai-playbook v0.4.5` and
`eligia-skills v0.2.7` are unrelated. The consumer's `skills_pins` block
tracks each independently.

## Steps

### 1. Stage the change

In the source repo (`ai-playbook` or `eligia-skills`):

```bash
cd C:/Projects/<source-repo>
git status --short              # must be clean
git log --oneline $(git describe --tags --abbrev=0)..HEAD -- skills/
```

The `-- skills/` filter shows only commits that touched the skills tree —
if the diff is empty, you don't need a tag bump.

### 2. Validate the skills are well-formed

```bash
# In any consumer or in the source repo itself:
cd C:/Projects/<source-repo>
python -c "
from pathlib import Path
import sys
broken = []
for sk in Path('skills').iterdir():
    if not sk.is_dir():
        continue
    md = sk / 'SKILL.md'
    if not md.exists():
        broken.append(f'{sk.name}: no SKILL.md')
        continue
    text = md.read_text(encoding='utf-8')
    if not text.startswith('---'):
        broken.append(f'{sk.name}: no frontmatter')
        continue
    if 'name:' not in text.split('---', 2)[1]:
        broken.append(f'{sk.name}: no name field')
sys.exit(1 if broken else 0)
print('\n'.join(broken) or '✅ all skills well-formed')
"
```

This catches the `eligia-skills` pre-existing issue (4 skills with malformed
frontmatter) before it ships in a tag. Do NOT cut the tag if any skill is
broken — fix or remove it first.

### 3. Update VERSION and CHANGELOG (ai-playbook only)

For `ai-playbook`, update the canonical version files:

```bash
# Bump VERSION
echo "0.5.0" > VERSION

# Add a CHANGELOG entry
$EDITOR CHANGELOG.md
```

The CHANGELOG entry follows the existing pattern (see `## [0.3.1]` in
[`CHANGELOG.md`](../CHANGELOG.md)). For `eligia-skills` there is no
VERSION file or CHANGELOG; the git tag is the single authority. (Adding a
CHANGELOG to `eligia-skills` is a backlog item.)

### 4. Commit and tag

```bash
git add -A
git commit -m "chore(release): vX.Y.Z — <one-line summary of skills changes>"
git tag -a vX.Y.Z -m "ai-playbook vX.Y.Z (or eligia-skills vX.Y.Z)"
git push origin <branch>
git push origin vX.Y.Z
```

The `git push origin vX.Y.Z` is the **trigger** for the propagation
workflow.

### 5. Wait for propagation

For `ai-playbook` tags: the workflow fires automatically on tag push.

For `eligia-skills` tags: the source repo's own release process must call
the playbook's `repository_dispatch` endpoint. Manual fallback:

```bash
# From a machine with PLAYBOOK_PROPAGATION_TOKEN set:
gh api -X POST \
  /repos/Wizarck/ai-playbook/dispatches \
  -f event_type='skills-tag-pushed' \
  -F client_payload[source_repo]='eligia-skills' \
  -F client_payload[tag]='vX.Y.Z'
```

Verify the workflow run starts:

```bash
gh run list --repo Wizarck/ai-playbook --workflow propagate-skills-bump --limit 3
```

### 6. Review the consumer PRs

Within ~5 minutes of the workflow run, expect one PR per consumer that has
`skills_pins.<source-repo>` set:

```bash
gh search prs --repo Wizarck/iguanatrader \
              --repo Wizarck/nexandro \
              --repo Wizarck/eligia-core \
              --repo Wizarck/palafito-b2b \
              --label skills-bump --state open
```

Review each PR for:

- The diff is **only** the pin bump (one line in `AGENTS.md` frontmatter +
  one line in `consumers.yaml`'s mirror copy if the consumer has one).
- Consumer's CI passes (tests, drift_check, validate-skills-mirror).
- The new skills don't break any consumer-specific workflow.

### 7. Merge consumer-by-consumer

**Do not bulk-merge.** Each consumer is its own canary surface. Sequence:

1. Merge in **one** consumer (typically the most active one, e.g. `iguanatrader`
   while it's in MVP development).
2. Run a smoke test in that consumer: invoke a key skill from a Claude session
   (`/<key-skill>`), check it works.
3. If OK → merge the next consumer.
4. If broken → revert the merge in that consumer, leave the others as-is, open
   a follow-up tag (patch bump) on the source repo with the fix, and re-propagate.

The whole sequence (steps 5-7) typically takes < 24h elapsed; per RFC-0001
KPI 5 ("time to propagation"), this is the success target.

## Rollback

If a bumped tag turns out to ship a regression:

### Revert in a single consumer

```bash
cd C:/Projects/<consumer>
git revert <merge-commit-sha>
git push origin main
```

Other consumers stay on the new tag if they merged successfully — that's the
canary feature working as designed.

### Revert globally (all consumers)

If the regression is severe enough to revert across the board:

1. Manually revert the merge in each consumer's main branch.
2. **Cut a patch tag on the source repo** that backs out the offending change
   (do not delete the bad tag — leave it for audit). Example:
   `v0.4.0` (regressing) → `v0.4.1` (revert + fix).
3. Run this runbook again with the patch tag.

The bad tag remains in git history as a record of "this version shipped and
regressed"; the patch tag is the new pin everyone moves to.

## Cross-refs

- [`specs/skills-distribution.md`](../specs/skills-distribution.md) — the
  contract this runbook executes.
- [`specs/skills-registry.md`](../specs/skills-registry.md) — the discovery
  surface that benefits from a new tag (registry's `pin_recommended`
  hint updates next refresh).
- [`runbooks/release.md`](release.md) — the parallel runbook for bumping
  the playbook submodule itself.
- [`runbooks/propagate-bump-troubleshooting.md`](propagate-bump-troubleshooting.md) — failure
  modes of the propagation workflow (mostly applicable to skills propagation
  too — same scaffolding).
- [`rfcs/RFC-0001-skills-distribution.md`](../rfcs/RFC-0001-skills-distribution.md) — design
  rationale for this whole flow.
