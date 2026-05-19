---
schema: runbook/v1
slug: release
description: Cut a new ai-playbook semver tag, triggering propagation of bump PRs across every active consumer.
audience: developer
estimated_time: 15-30 min (rc), 30-90 min (stable cascade including per-consumer signoff)
last_validated: "2026-05-19"
---

# Cut a new ai-playbook version tag

## Outcome

A new semver tag exists on `Wizarck/ai-playbook` with a matching `VERSION` file and a CHANGELOG entry. The `propagate-playbook-bump.yml` workflow has auto-opened one `chore/bump-playbook-vX.Y.Z` PR per active consumer in `consumers.yaml`, and any prior open bump PRs are superseded. Each consumer PR has a populated §4.5 AI-reviewer signoff and is squash-merged after manual verification.

## When to use this

The playbook has accumulated changes worth shipping (new scripts, new specs, doc fixes) and a tag is ready to cut. Use the rc-first variant when the release touches multiple specs or scripts simultaneously.

Skip when:

- The changes are purely local (working-tree edits not committed to `main`).
- Only a single doc typo was fixed — wait for a bigger batch.
- A previous release is still in flight (its propagate workflow has not finished).

## Prerequisites

- Write access to `Wizarck/ai-playbook`.
- The `PLAYBOOK_PROPAGATION_TOKEN` secret on `Wizarck/ai-playbook` is non-expired and has `contents:write` + `pull-requests:write` on every active consumer in `consumers.yaml`. Verify: `gh secret list --repo Wizarck/ai-playbook | grep PLAYBOOK_PROPAGATION_TOKEN`.
- Working tree is clean and up-to-date with origin: `git status --short` empty and `git log @{upstream}..HEAD` empty.
- For rc-first mode: prior rc's propagate workflow has finished (`completed success`).

## Steps

### 1. Pick the semver bump

| Kind of change | Bump |
|---|---|
| Docs, typo fixes, stub closures | patch (`0.2.0 → 0.2.1`) |
| New scripts or specs (additive, no breaking schema) | minor (`0.2.0 → 0.3.0`) |
| Breaking schema (AGENTS.md frontmatter), removed script, renamed env var, changed verdict rubric | major (`0.x → 1.0.0`) — requires RFC first per [Concept: rollout-strategy](../concepts/rollout-strategy.md) |

For substantial releases (multiple specs / scripts / templates in one go), use the rc-first variant: tag `vX.Y.Z-rc1`, validate against one consumer, iterate `rc2` etc., then promote to `vX.Y.Z` stable. Each rc cleanly supersedes the previous via the v0.8.0+ supersede helper.

### 2. Pre-tag chronology check

Out-of-order tag pushes are the failure mode this guards against — pushing `v0.8.7` and `v0.9.0-rc2` close together once saw v0.8.7's propagate fire LAST and use supersede to close the newer rc2 PRs (recovery required re-pushing rc2).

```bash
gh run list --repo Wizarck/ai-playbook \
    --workflow propagate-playbook-bump --limit 5

# Confirm git log <prev-tag>..HEAD is non-empty:
git log --oneline $(cat VERSION | awk '{print "v"$1}')..HEAD
```

Proceed only when the previous run is `completed success` AND new commits exist.

### 3. Update VERSION + CHANGELOG

Edit `VERSION` (no leading `v`, one line + trailing newline):

```
0.2.2
```

Prepend a section to `CHANGELOG.md` above the latest entry. Pattern:

```markdown
## [X.Y.Z] — YYYY-MM-DD — <one-liner>

### Added
- ...

### Changed
- ...

### Notes
- ...
```

Body MUST be human-readable and ≤ ~40 lines — consumers read it on their bump PR to decide whether to merge.

### 4. Zombie manifest gate (v0.15.0+)

If this release REMOVED or RENAMED any consumer-surface artefact — a template under `templates/new-project/`, a literal identifier consumers hard-code (project name, MCP server alias), a frontmatter field, a script consumers invoke — append an entry to `specs/zombies-manifest.yaml` AND bump its `manifest_version` (`YYYY-MM-DD.N`, strictly monotonic).

Reference: [Rule: cleanup-zombies](../rules/cleanup-zombies.rule.md). Validation: `python scripts/rules/cleanup-zombies.rule.py validate` (pre-commit gate). Skip ONLY for internal-only releases that never touched consumer-facing surfaces.

### 5. Commit + tag

```bash
git add VERSION CHANGELOG.md
git commit -m "release: vX.Y.Z — <one-liner>"
git tag -a vX.Y.Z -m "vX.Y.Z — <one-liner>"
```

### 6. Push branch + tag

```bash
git push origin main vX.Y.Z
```

If the push hangs on network, use the token-inline form (see [Runbook: propagate-bump-troubleshooting](propagate-bump-troubleshooting.md) Pattern H):

```bash
TOKEN=$(sops -d C:/Projects/consumer-d/secrets/secrets.env | grep ^GITHUB_TOKEN= | cut -d= -f2)
git push "https://x-access-token:${TOKEN}@github.com/Wizarck/ai-playbook.git" main vX.Y.Z
```

### 7. Watch the propagation Action fire

```bash
gh run list --repo Wizarck/ai-playbook --workflow propagate-playbook-bump --limit 1
```

Expected outcome: `completed success` within ~90 s. On failure, see [Runbook: propagate-bump-troubleshooting](propagate-bump-troubleshooting.md).

### 8. Verify PRs on each consumer

```bash
for repo in Wizarck/consumer-c Wizarck/consumer-d Wizarck/consumer-e Wizarck/consumer-b Wizarck/livekit; do
  echo "=== $repo ==="
  gh pr list --repo "$repo" --state open --head "chore/bump-playbook-vX.Y.Z" \
    --json url,title --jq '.[] | "\(.title) → \(.url)"'
done
```

Each consumer should have exactly one `chore(playbook): bump .ai-playbook to vX.Y.Z` PR (plus a matching `chore/bump-skills-ai-playbook-vX.Y.Z` if its `skills_sources` references the playbook).

Missing PRs:
- Check `consumers.yaml` for `status: active`.
- Confirm the consumer has a `.ai-playbook/` submodule (the script skips consumers without one).
- Re-dispatch by deleting and re-pushing the tag.

The v0.8.0+ supersede behaviour auto-closes any consumer's prior `chore/bump-playbook-v*` PRs with `Auto-closed: superseded by #N`.

### 9. AI-reviewer signoff + per-consumer merge

For each consumer's bump PR, BEFORE merging:

1. Run the L1 detection script (added in v0.9.0):
   ```bash
   python -m scripts.check_coderabbit_status \
       --pr <N> --repo Wizarck/<repo> --wait 300
   ```
   Exit 0 → CodeRabbit reviewed; address its comments. Exit 1 → rate-limited or silent; apply Profile B per [Runbook: coderabbit-fallback](coderabbit-fallback.md). Bump PRs are mechanical so the §4.5 audit trail is short ("Self-review findings: none, mechanical bump diff only.") but MUST be populated.

2. If CodeRabbit was rate-limited (typical during multi-bump series), the L2 `coderabbit-fallback.yml` workflow auto-fires after 5 minutes. L1's whole point is to have §4.5 populated BEFORE L2 fires so L2 stays silent.

3. Squash-merge.

### 10. Post-merge: re-run consumer bootstrap (idempotent)

```bash
cd <consumer-checkout> && git pull && git submodule update --init --recursive .ai-playbook
python -m scripts.bootstrap_gh_project \
    --owner Wizarck --project-number <N> --repo Wizarck/<repo> \
    --profile auto
```

Idempotent: only applies what is missing. Adds new Status options, custom fields, trace fields. Re-applies repo settings. For Profile A, applies branch protection (UNION semantics — preserves project-specific required checks per [Concept: release-management](../concepts/release-management.md)). For Profile B, emits a notice that branch protection is unavailable. Copies `coderabbit-fallback.yml` if absent.

### 11. Notify maintainers

The Action auto-emits `warn` notifications per PR via `scripts/notify.py` (JSONL + SMTP). The dashboard bell surfaces them. No manual step needed.

### 12. First-run smoke test (v0.11.0+)

Before merging the rc → stable promotion, run EVERY new or modified script / workflow / skill against ONE real consumer at least once, end-to-end, OUTSIDE of CI. CI mocks the boundary that hides environmental constraints (API rate limits, locale encoding, missing markers in auto-generated content); real invocation exposes them.

Procedure:

1. Pick the canonical first-run consumer (default: `consumer-e`).
2. For each new or modified surface, list a real invocation. Examples from v0.10.x retros:
   - `verify_board_state.py` against the real project board with `--expected-status='In Progress'` (caught the `first: 200` GraphQL pagination limit and the cp1252 stdio crash).
   - `propagate_bump.py` body rendering — open a real bump PR and assert `gh pr view --json body | jq` contains the §4.5 markers.
   - New skills — invoke `/<skill-name>` interactively in a real Claude Code session against a real change folder.
3. Smoke results land in the release PR body under `## First-run smoke (per release.md §12)`. Each result: `surface | command | exit code | observation`. Failures block stable promotion; rc bumps absorb the fix-and-retest loop.

Non-skippable for releases shipping new scripts / new workflows / new skills. Pure documentation releases MAY skip with a one-line rationale.

## Verification

- `gh run list --repo Wizarck/ai-playbook --workflow propagate-playbook-bump --limit 1` shows `completed success`.
- Every active consumer has the expected bump PR(s).
- Each consumer's PR has §4.5 populated.
- The first-run smoke test results are in the release PR body.
- `git tag --list` shows the new tag.

## Troubleshooting

### Symptom: tag was cut by mistake (bad CHANGELOG, wrong version) and no consumer has merged
**Cause**: human error in steps 3 or 5.
**Fix**: rollback before any merge lands:
```bash
# Close open PRs on consumers first (prevents accidental merge):
for repo in Wizarck/consumer-c Wizarck/consumer-d; do
  gh pr close --repo "$repo" "chore/bump-playbook-vX.Y.Z" --delete-branch
done

# Delete the local + remote tag:
git tag -d vX.Y.Z
git push origin --delete vX.Y.Z

# Revert the VERSION + CHANGELOG commit if needed:
git revert HEAD
git push origin main
```

### Symptom: a consumer already merged the bump and the release needs correction
**Cause**: same as above but discovered too late.
**Fix**: never rewrite a merged tag. Cut the next version with the correction. Follow [Concept: rollout-strategy](../concepts/rollout-strategy.md) §rollback.

### Symptom: propagate workflow failed
**Cause**: token, setuptools, supersede, or networking issue.
**Fix**: see [Runbook: propagate-bump-troubleshooting](propagate-bump-troubleshooting.md) for the diagnosis ladder + per-pattern fix.

### Symptom: a consumer is missing its bump PR
**Cause**: consumer not in `consumers.yaml` as `status: active`, OR missing `.ai-playbook/` submodule, OR PAT scope gap.
**Fix**: confirm the row in `consumers.yaml`; if active, verify the submodule exists and the PAT covers the repo (Pattern C in propagate-bump-troubleshooting). Re-fire by re-tagging.

### Symptom: §4.5 missing on a bump PR after L2 fired
**Cause**: L1 (worker AI) ran but §4.5 markers were misspelled or stubbed.
**Fix**: see [Runbook: coderabbit-fallback](coderabbit-fallback.md) — re-edit the PR body with the three required markers exactly.

## Quick reference: post-v0.8.x release flow

```
1. Bump VERSION + CHANGELOG + commit + push to main.
2. Tag vX.Y.Z-rc1 → push tag.
   → propagate-{playbook,skills}-bump.yml fires.
   → bump PRs land in 5 consumers.
   → supersede closes any prior open bump PRs.
3. Validate against ONE consumer (consumer-e by default).
   → §4.5 AI-reviewer signoff → merge bumps.
   → re-run bootstrap_gh_project.py --profile auto.
   → exercise the new feature.
4. If issues: fix → tag rc2 → loop step 2.
5. When clean: tag vX.Y.Z (stable) → cascade to all 5.
   → §4.5 + post-merge bootstrap per consumer.
```

## Related

- [Runbook: propagate-bump-troubleshooting](propagate-bump-troubleshooting.md) — when the workflow fails.
- [Runbook: skills-version-bump](skills-version-bump.md) — sibling runbook for the skills source-repo tag.
- [Runbook: rotate-secrets](rotate-secrets.md) — PAT and SMTP rotation.
- [Runbook: coderabbit-fallback](coderabbit-fallback.md) — Profile B self-review fallback.
- [Concept: release-management](../concepts/release-management.md) — Profile A/B, AI-reviewer §4.5, pre-flight rebase.
- [Concept: rollout-strategy](../concepts/rollout-strategy.md) — breaking-change protocol.
- [Rule: cleanup-zombies](../rules/cleanup-zombies.rule.md) — zombie manifest gate.
