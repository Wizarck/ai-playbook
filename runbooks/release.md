# runbook: release.md — cut a new ai-playbook version

> **Audience**: the AI (Claude / future session) or a human maintainer.
> **Status**: v1.0.0. Executed every time the playbook tags a new semver.
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
TOKEN=$(sops -d C:/Projects/eligia-core/secrets/secrets.env | grep ^GITHUB_TOKEN= | cut -d= -f2)
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
for repo in Wizarck/openTrattOS Wizarck/eligia-core; do
  echo "=== $repo ==="
  gh pr list --repo "$repo" --state open --head "chore/bump-playbook-vX.Y.Z" \
    --json url,title --jq '.[] | "\(.title) → \(.url)"'
done
```

Each consumer should have exactly one `chore(playbook): bump .ai-playbook to vX.Y.Z` PR. If a consumer is missing:
- Check its status in [`consumers.yaml`](../consumers.yaml) (paused?).
- Check whether it has a `.ai-playbook/` submodule at all (script skips consumers without one).
- Re-dispatch: `gh workflow run propagate-playbook-bump --repo Wizarck/ai-playbook --ref main` (does not re-trigger because Action key is `push: tags`; instead delete+re-push the tag, see troubleshooting).

### 7. Notify maintainers

The Action auto-emits `warn` notifications per PR via
[`scripts/notify.py`](../scripts/notify.py) (JSONL + SMTP fan-out).
Dashboard bell at `https://eligia-dashboard.palafitofood.com/api/notifications`
surfaces them. No manual step needed.

## Rollback

If a tag was cut by mistake (bad CHANGELOG, wrong version, etc.) AND no
consumer has merged the bump PR yet:

```bash
# Close open PRs on consumers first (prevents accidental merge):
for repo in Wizarck/openTrattOS Wizarck/eligia-core; do
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
- [eligia-core/langgraph-aiops/workflows/playbook_bump_propagator.py](https://github.com/Wizarck/eligia-core/blob/master/langgraph-aiops/workflows/playbook_bump_propagator.py) — daily circuit-breaker backup.
- [specs/rollout-strategy.md](../specs/rollout-strategy.md) — breaking-change protocol.
- [propagate-bump-troubleshooting.md](propagate-bump-troubleshooting.md) — when things break.
