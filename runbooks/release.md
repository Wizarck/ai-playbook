# runbook: release.md — cut a new ai-playbook version

> **Audience**: the AI (Claude / future session) or a human maintainer.
> **Status**: v1.1.0 (updated 2026-05-01 for v0.8.x — adds rc-first mode for breaking releases, AI-reviewer signoff per consumer, post-merge bootstrap re-run).
> **Prereqs**: write access to `Wizarck/ai-playbook`; a PAT with
> `contents:write` + `pull-requests:write` on every consumer in
> [`consumers.yaml`](../consumers.yaml) (set as the
> `PLAYBOOK_PROPAGATION_TOKEN` repo secret).

## What this runbook does

Cuts a new semver tag on `ai-playbook`, which triggers
[`propagate-playbook-bump.yml`](../.github/workflows/propagate-playbook-bump.yml)
to auto-open "bump `.ai-playbook/` to `vX.Y.Z`" PRs across every active
consumer listed in [`consumers.yaml`](../consumers.yaml). The
`playbook_bump_propagator` LangGraph CronJob is a daily backup if the
primary Action misses a fire.

**Propose-only HITL**: automation opens PRs. A human reviews + merges per
consumer. Never auto-merge — the point of the bump is to let the consumer
verify nothing downstream broke.

## Semver decision

| Kind of change | Bump |
|---|---|
| Docs, typo fixes, stub closures | patch (`0.2.0 → 0.2.1`) |
| New scripts/specs additive; no breaking schema | minor (`0.2.0 → 0.3.0`) |
| Breaking schema (AGENTS.md frontmatter), removed script, renamed env var, changed verdict rubric | major (`0.x → 1.0.0`) — requires RFC first per [specs/rollout-strategy.md](../specs/rollout-strategy.md) |

### Rc-first mode (recommended for substantial releases)

When a release touches multiple specs / scripts / templates (e.g. v0.8.0
shipped Profile A/B + Branch+SHA + supersede + spec-edit fix in one go),
use the rc → stable sequence:

1. Tag `vX.Y.Z-rc1` first → propagate fires → consumer bump PRs land.
2. Validate against ONE consumer (typically consumer-e): merge bumps,
   run `bootstrap_gh_project.py --profile auto`, exercise the change.
3. If issues found: fix → tag `rc2`. Each rc cleanly supersedes the
   previous (per [release-management.md §3.4](../specs/release-management.md));
   stale rc PRs in consumers auto-close.
4. When stable: tag `vX.Y.Z` (no suffix). Same propagate cycle, last set
   of supersedes closes any remaining rc PRs.

Rationale: each rc validates 1 consumer; stable cascades to all 5 once
clean. Avoids the rc1→rc6 dogfooding pile-up that motivated supersede in
the first place — but ALSO catches surprises on a single consumer before
hitting them on 5.

## Steps

### 1. Stage the bump

```bash
cd C:/Projects/ai-playbook
git status --short              # must be clean
git log --oneline $(cat VERSION | awk '{print "v"$1}')..HEAD   # commits since last tag
```

Decide the new version `X.Y.Z` based on the decision table above.

### 2. Update VERSION + CHANGELOG

Edit `VERSION` to the new number (no leading `v`, one line + trailing newline):

```
0.2.2
```

Prepend a new section to [`CHANGELOG.md`](../CHANGELOG.md) above the last
section. Follow the existing pattern — "Added", "Changed", "Notes" subsections.
The section body MUST be human-readable and ≤ ~40 lines — consumers read it on
their bump PR to decide whether to merge.

Section header format:

```markdown
## [X.Y.Z] — YYYY-MM-DD — <one-liner>
```

### 3. Commit + tag

#### Pre-tag chronology check (per v0.9.0 followup #2)

Before tagging, verify the previous tag's propagation has FINISHED. Out-of-order
tag pushes are the failure mode this guards against — pushing `v0.8.7` and
`v0.9.0-rc2` close together saw v0.8.7's propagate workflow fire LAST, opening
PRs that the supersede helper then used to close the newer rc2 PRs (recovery
required deleting + re-pushing the rc2 tag).

```bash
# 1. Confirm the previous tag's propagate workflow is in `completed success`:
gh run list --repo Wizarck/ai-playbook \
    --workflow propagate-playbook-bump --limit 5

# 2. Confirm `git log <prev-tag>..HEAD` is non-empty (you actually have changes):
git log --oneline $(cat VERSION | awk '{print "v"$1}')..HEAD

# 3. Only THEN proceed with tagging.
```

The `_bumper.supersede_open_bump_prs` helper is also semver-aware (per
followup #2's code-side fix), so an out-of-order push won't silently corrupt
the cascade. But the runbook check stays as the operational guard so devs
don't rely on script correctness when tagging close together.

#### Tag

```bash
git add VERSION CHANGELOG.md
git commit -m "release: vX.Y.Z — <one-liner>"
git tag -a vX.Y.Z -m "vX.Y.Z — <one-liner>"
```

### 4. Push branch + tag

Direct push to `main` plus tag. If your shell's origin push is flaky,
use the token-inline URL form (see [propagate-bump-troubleshooting.md](propagate-bump-troubleshooting.md) §Networking):

```bash
git push origin main vX.Y.Z
# or if that hangs on network:
TOKEN=$(sops -d C:/Projects/consumer-d/secrets/secrets.env | grep ^GITHUB_TOKEN= | cut -d= -f2)
git push "https://x-access-token:${TOKEN}@github.com/Wizarck/ai-playbook.git" main vX.Y.Z
```

### 5. Watch the propagation Action fire

```bash
gh run list --repo Wizarck/ai-playbook --workflow propagate-playbook-bump --limit 1
```

The run fires automatically on `push: tags: v*.*.*`. Expected outcome:
`completed success` within ~90 s. If it fails → see
[propagate-bump-troubleshooting.md](propagate-bump-troubleshooting.md).

### 6. Verify PRs on each consumer

```bash
for repo in Wizarck/consumer-c Wizarck/consumer-d Wizarck/consumer-e Wizarck/consumer-b Wizarck/livekit; do
  echo "=== $repo ==="
  gh pr list --repo "$repo" --state open --head "chore/bump-playbook-vX.Y.Z" \
    --json url,title --jq '.[] | "\(.title) → \(.url)"'
done
```

Each consumer should have exactly one `chore(playbook): bump .ai-playbook to vX.Y.Z` PR (and one `chore/bump-skills-ai-playbook-vX.Y.Z` for consumers with `skills_sources` referencing the playbook). If a consumer is missing:
- Check its status in [`consumers.yaml`](../consumers.yaml) (paused?).
- Check whether it has a `.ai-playbook/` submodule at all (script skips consumers without one).
- Re-dispatch: delete + re-push the tag (see [propagate-bump-troubleshooting.md](propagate-bump-troubleshooting.md)).

**v0.8.0+ supersede behavior**: if any consumer had open `chore/bump-playbook-v*` PRs from prior releases, they auto-close with comment "Auto-closed: superseded by #N". Verify by listing `--state closed --limit 8 --search "head:chore/bump-playbook"` per consumer.

### 7. AI-reviewer signoff + per-consumer merge (per release-management.md §4.5)

For each consumer's bump PR, BEFORE merging:

1. **Run the L1 detection script** (added in v0.9.0):
   ```bash
   python -m scripts.check_coderabbit_status \
       --pr <N> --repo Wizarck/<repo> --wait 300
   ```
   Exit 0 → CodeRabbit reviewed; address comments per §4.5. Exit 1 → rate-limited or silent; apply Profile B fallback per [`runbooks/coderabbit-fallback.md`](coderabbit-fallback.md). Bump PRs are mechanical so the self-review section is short ("Self-review findings: none, mechanical bump diff only.") but MUST be populated for the audit trail.
2. If CodeRabbit was rate-limited (typical during multi-bump series), the L2 workflow (`coderabbit-fallback.yml`) on the consumer auto-fires after 5 minutes and posts a checklist if §4.5 is empty. L1's whole point is to have §4.5 populated BEFORE L2 fires, so L2 stays silent. This is the v0.9.0 contract.
3. Squash-merge.

### 8. Post-merge: re-run consumer bootstrap (idempotent)

Once the bump PR merges, optionally re-run [`bootstrap_gh_project.py`](../scripts/bootstrap_gh_project.py) on the consumer to pick up new release-management features:

```bash
cd <consumer-checkout> && git pull && git submodule update --init --recursive .ai-playbook
python -m scripts.bootstrap_gh_project \
    --owner Wizarck --project-number <N> --repo Wizarck/<repo> \
    --profile auto
```

Idempotent: only applies what's missing. The script:
- Adds new Status options / custom fields / trace fields if absent.
- Re-applies repo settings (auto-merge on, squash-only, delete-branch-on-merge).
- For Profile A: applies branch protection (UNION semantics — preserves existing project-specific required checks per [release-management.md §gotcha #12 fix in v0.8.1](../specs/release-management.md#41-mandatory-ci-for-slice-branch-prs)).
- For Profile B: emits notice that branch protection unavailable on GH Free private; skips.
- (v0.9.0+) **Copies `coderabbit-fallback.yml` workflow** to `<consumer>/.github/workflows/` if absent. The L2 safety net workflow (per release-management.md §4.5.2) is now propagated automatically. Skips if the file exists (consumer may have local edits — delete + re-run to refresh).

### 9. Notify maintainers

The Action auto-emits `warn` notifications per PR via
[`scripts/notify.py`](../scripts/notify.py) (JSONL + SMTP fan-out).
Dashboard bell at `https://consumer-d-dashboard.consumer-bfood.com/api/notifications`
surfaces them. No manual step needed.

### 10. First-run smoke test (added v0.11.0)

> Closes the v0.10.3 gap from CHANGELOG.md noting "v0.10.x had 3
> real-world-surfaced gaps after release: tests stub at the boundary,
> real invocation reveals environmental constraints".

Before merging the rc → stable promotion (step 5 in §"Quick reference"
below), run **every new or modified script / workflow / skill** against
ONE real consumer at least once, end-to-end, OUTSIDE of CI. CI mocks the
boundary that hides environmental constraints (API rate limits, locale
encoding, missing markers in auto-generated content); real invocation
exposes them.

Procedure:

1. Pick the canonical first-run consumer (default: `consumer-e`).
2. For each new / modified surface in the release, list a real
   invocation that exercises the boundary CI mocks. Examples from
   v0.10.x retros:
   - `verify_board_state.py` (v0.10.0) — invoke against the real
     project board with `--expected-status='In Progress'` (caught the
     `first: 200` GraphQL pagination limit and the cp1252 stdio crash;
     CI mocks couldn't surface either).
   - `propagate_bump.py` body rendering (v0.10.0) — open a real bump PR
     and assert `gh pr view --json body | jq` contains the §4.5 markers
     (caught the missing-block bug across 5 PRs; CI tested the function
     in isolation, not the rendered body).
   - New skills — invoke `/<skill-name>` interactively in a real Claude
     Code session against a real change folder; compare output to the
     skill's documented schema.
3. Smoke-test results land in the release PR's body under `## First-run
   smoke (per release.md §10)`. Each result: `surface | command | exit
   code | observation`. Failures block stable promotion; rc bumps
   absorb the fix-and-retest loop.

This step is non-skippable for releases that ship new scripts / new
workflows / new skills. Pure documentation releases MAY skip with a
one-line rationale in the release PR ("v0.X.Y is docs-only; no runtime
surface to smoke").

The smoke-test discipline is the cheapest insurance against the
"v0.10.x cascade" pattern (3 hotfixes within 5 days because real
invocations surfaced environmental gaps that mocked tests didn't).

## Quick reference: post-v0.8.x release flow

For a release that touches multiple specs/scripts:

```
┌──────────────────────────────────────────────────────────────┐
│ 1. Bump VERSION + CHANGELOG + commit + push to main         │
│ 2. Tag vX.Y.Z-rc1 → push tag                                 │
│    → propagate-{playbook,skills}-bump.yml fires              │
│    → bump PRs land in 5 consumers                            │
│    → supersede closes any prior open bump PRs                │
│ 3. Validate against ONE consumer (consumer-e by default)  │
│    → §4.5 AI-reviewer signoff → merge bumps                  │
│    → re-run bootstrap_gh_project.py --profile auto           │
│    → exercise the new feature                                │
│ 4. If issues: fix → tag rc2 → loop step 2                    │
│ 5. When clean: tag vX.Y.Z (stable) → cascade to all 5        │
│    → §4.5 + post-merge bootstrap per consumer                │
└──────────────────────────────────────────────────────────────┘
```

## Rollback

If a tag was cut by mistake (bad CHANGELOG, wrong version, etc.) AND no
consumer has merged the bump PR yet:

```bash
# Close open PRs on consumers first (prevents accidental merge):
for repo in Wizarck/consumer-c Wizarck/consumer-d; do
  gh pr close --repo "$repo" "chore/bump-playbook-vX.Y.Z" --delete-branch
done

# Delete the local + remote tag:
git tag -d vX.Y.Z
git push origin --delete vX.Y.Z

# Revert the VERSION+CHANGELOG commit if needed:
git revert HEAD
git push origin main
```

If a consumer already merged the bump and you need to recover: cut the
next version with the correction; never rewrite a merged tag. Follow
[specs/rollout-strategy.md](../specs/rollout-strategy.md) §rollback.

## Cross-references

- [consumers.yaml](../consumers.yaml) — active downstream inventory.
- [scripts/propagate_bump.py](../scripts/propagate_bump.py) — CI script.
- [scripts/bump_consumers.py](../scripts/bump_consumers.py) — manual fallback for local bumps via `~/.ai-playbook/projects.yaml`.
- [.github/workflows/propagate-playbook-bump.yml](../.github/workflows/propagate-playbook-bump.yml) — event-driven primary path.
- [consumer-d/langgraph-aiops/workflows/playbook_bump_propagator.py](https://github.com/Wizarck/consumer-d/blob/master/langgraph-aiops/workflows/playbook_bump_propagator.py) — daily circuit-breaker backup.
- [specs/rollout-strategy.md](../specs/rollout-strategy.md) — breaking-change protocol.
- [propagate-bump-troubleshooting.md](propagate-bump-troubleshooting.md) — when things break.
