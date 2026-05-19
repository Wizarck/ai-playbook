---
schema: runbook/v1
slug: skills-version-bump
description: Cut a new semver tag on a skills source repo, triggering propagation of "bump skills pin" PRs to every consumer that pins it.
audience: developer
estimated_time: 15-30 min (rc), 60-120 min (full canary cascade across all consumers)
last_validated: "2026-05-19"
---

# Cut a new skills source-repo tag

## Outcome

A new semver tag exists on the chosen skills source repo (`ai-playbook` itself, `consumer-d-skills`, or any other registered source). The `propagate-skills-bump.yml` workflow has auto-opened one `chore/bump-skills-<source>-vX.Y.Z` PR per consumer that pins it. Each consumer's PR is verified against its CI + a smoke test, then merged consumer-by-consumer in a canary sequence.

## When to use this

Bump skills when any of:

- A new skill is added to `<source-repo>/skills/`.
- An existing skill's `SKILL.md`, workflow, or assets change in a way that affects agent behaviour.
- A skill is renamed or removed (breaking → major bump).
- A skill's `name` frontmatter changes (also breaking).

Skip when:

- README, docs, tests, or CI of the source repo changed without touching `skills/`. Those land on `main`/`master` directly without a tag.

Sibling of [Runbook: release](release.md), which bumps the playbook submodule. This one bumps the skills submodules.

## Prerequisites

- Write access to the source repo being bumped (`Wizarck/ai-playbook` and/or `Wizarck/consumer-d-skills`).
- The `PLAYBOOK_PROPAGATION_TOKEN` secret has `contents:write` + `pull-requests:write` on every consumer in `consumers.yaml` (same secret as [Runbook: release](release.md)).
- Working tree clean and up-to-date: `git status --short` empty, `git log @{upstream}..HEAD` empty.

## Steps

### 1. Stage the change in the source repo

```bash
cd C:/Projects/<source-repo>
git status --short                              # must be clean
git log --oneline $(git describe --tags --abbrev=0)..HEAD -- skills/
```

The `-- skills/` filter shows only commits that touched the skills tree. If empty, no tag bump is needed.

### 2. Validate the skills are well-formed

```bash
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

Catches `consumer-d-skills` pre-existing malformed frontmatter (4 skills, surfaced 2026-04). Do NOT cut the tag if any skill is broken — fix or remove it first.

### 3. Pick the semver bump

| Kind of change | Bump |
|---|---|
| Typo fix, docs polish in a single SKILL.md | patch (`v0.4.0 → v0.4.1`) |
| New skill added; existing skill expanded with backwards-compatible content | minor (`v0.4.0 → v0.5.0`) |
| Skill renamed, deleted, or `name` frontmatter changed | major (`v0.x → v1.0.0`) — requires RFC first per [Concept: rollout-strategy](../concepts/rollout-strategy.md) |

Independent semver per source repo: `ai-playbook v0.4.5` and `consumer-d-skills v0.2.7` are unrelated. The consumer's `skills_pins` block tracks each independently.

### 4. Update VERSION and CHANGELOG (`ai-playbook` source only)

For `ai-playbook`, update the canonical version files:

```bash
echo "0.5.0" > VERSION
$EDITOR CHANGELOG.md
```

The CHANGELOG entry follows the existing pattern. For `consumer-d-skills` there is no VERSION file or CHANGELOG; the git tag is the single authority.

### 5. Commit and tag

```bash
git add -A
git commit -m "chore(release): vX.Y.Z — <one-line summary of skills changes>"
git tag -a vX.Y.Z -m "<source-repo> vX.Y.Z"
git push origin <branch>
git push origin vX.Y.Z
```

The `git push origin vX.Y.Z` is the trigger for the propagation workflow.

### 6. Wait for propagation

For `ai-playbook` tags, the workflow fires automatically on tag push.

For `consumer-d-skills` tags, the source repo's own release process must call the playbook's `repository_dispatch` endpoint. Manual fallback:

```bash
gh api -X POST \
  /repos/Wizarck/ai-playbook/dispatches \
  -f event_type='skills-tag-pushed' \
  -F client_payload[source_repo]='consumer-d-skills' \
  -F client_payload[tag]='vX.Y.Z'
```

Verify the workflow run starts:

```bash
gh run list --repo Wizarck/ai-playbook --workflow propagate-skills-bump --limit 3
```

### 7. Review consumer PRs

Within ~5 minutes of the workflow run, expect one PR per consumer with `skills_pins.<source-repo>` set:

```bash
gh search prs --repo Wizarck/consumer-e \
              --repo Wizarck/consumer-c \
              --repo Wizarck/consumer-d \
              --repo Wizarck/consumer-b \
              --label skills-bump --state open
```

Review each PR for:

- The diff is ONLY the pin bump (one line in `AGENTS.md` frontmatter + one mirror line in `consumers.yaml` if the consumer has one).
- Consumer CI passes (tests, drift_check, validate-skills-mirror).
- The new skills do not break any consumer-specific workflow.

### 8. Merge consumer-by-consumer (canary sequence)

Do NOT bulk-merge. Each consumer is its own canary surface.

1. Merge in ONE consumer first (typically the most active, e.g. `consumer-e`).
2. Smoke-test in that consumer: invoke a key skill from a Claude session (`/<key-skill>`), confirm it works.
3. If OK → merge the next consumer.
4. If broken → revert the merge in that consumer, leave the others as-is, cut a patch tag on the source repo with the fix, re-propagate.

The whole sequence (steps 5-8) typically takes <24 h elapsed.

## Verification

- `gh run list --repo Wizarck/ai-playbook --workflow propagate-skills-bump --limit 1` shows `completed success`.
- Each consumer pinned to this source has one open `chore/bump-skills-<source>-vX.Y.Z` PR.
- After merges, `git -C <consumer> log -1 --format=%B` on `main` shows the bump commit.
- Smoke-test invocation of the new or changed skill succeeds in at least one consumer.

## Troubleshooting

### Symptom: regression detected after merging in one consumer
**Cause**: a skill change broke a consumer-specific workflow not covered by CI.
**Fix (single consumer)**:
```bash
cd C:/Projects/<consumer>
git revert <merge-commit-sha>
git push origin main
```
Other consumers stay on the new tag (canary feature working as designed). File a follow-up patch tag on the source repo with the fix.

### Symptom: regression severe enough to revert across all consumers
**Cause**: a skill change broke a universal contract (rare).
**Fix (global)**:
1. Manually revert the merge in each consumer's main branch.
2. Cut a patch tag on the source repo backing out the offending change. Example: `v0.4.0` (regressing) → `v0.4.1` (revert + fix). Do NOT delete the bad tag — leave it for audit.
3. Run this runbook again with the patch tag.

The bad tag remains in git history as a record of "this version shipped and regressed"; the patch tag is the new pin everyone moves to.

### Symptom: propagate workflow failed
**Cause**: same patterns as the playbook bump workflow — token, supersede, networking.
**Fix**: see [Runbook: propagate-bump-troubleshooting](propagate-bump-troubleshooting.md) for the diagnosis ladder.

### Symptom: skill validation in Step 2 reports `no frontmatter`
**Cause**: a skill author committed a `SKILL.md` without the YAML frontmatter block.
**Fix**: open the file, add the frontmatter, re-run Step 2 until it returns `✅ all skills well-formed`. Do not tag with a broken skill in the tree.

### Symptom: bump PR diff includes more than the pin line
**Cause**: the propagate script also rewrote the `updated:` date (v0.8.3+ behaviour). That is intended — both lines refresh in lockstep.
**Fix**: confirm the only changes are the pin line + `updated:` date. Anything else (e.g., a `mcp-servers.project.yaml` change) is unexpected — flag for investigation.

## Related

- [Runbook: release](release.md) — sibling runbook for the playbook submodule bump.
- [Runbook: propagate-bump-troubleshooting](propagate-bump-troubleshooting.md) — failure modes of the propagation workflow.
- [Runbook: coderabbit-fallback](coderabbit-fallback.md) — Profile B self-review when CodeRabbit is unavailable on a consumer bump PR.
- [Concept: skills-distribution](../concepts/skills-distribution.md) — the contract this runbook executes.
- [Concept: skills-registry](../concepts/skills-registry.md) — discovery surface that benefits from a new tag.
- [Concept: rollout-strategy](../concepts/rollout-strategy.md) — breaking-change protocol.
