---
schema: runbook/v1
slug: release
description: Cut a new ai-playbook semver tag. Consumers bump at their own pace (pull model, v0.19.0+).
audience: developer
estimated_time: 15-30 min
last_validated: "2026-06-17"
---

# Cut a new ai-playbook version tag

## Outcome

A new semver tag exists on `Wizarck/ai-playbook` with a matching `VERSION` file and CHANGELOG entry. The tag is the **public API** — every downstream consumer is free to pull it on their own schedule. No automation reaches into consumer repos.

## When to use this

The playbook has accumulated changes worth shipping (new scripts, new specs, doc fixes) and a tag is ready to cut. Use the rc-first variant when the release touches multiple specs or scripts simultaneously.

Skip when:

- The changes are purely local (working-tree edits not committed to `main`).
- Only a single doc typo was fixed — wait for a bigger batch.

## Prerequisites

- Write access to `Wizarck/ai-playbook`.
- Working tree is clean and up-to-date with origin: `git status --short` empty and `git log @{upstream}..HEAD` empty.

## Steps

### Overview — release flow at a glance

```mermaid
flowchart TD
    Start["Changes ready to ship"] --> Kind{"What kind<br/>of change?"}
    Kind -->|docs / typo / stub| Patch["patch bump<br/>0.18.0 → 0.18.1"]
    Kind -->|new scripts + specs<br/>(additive)| Minor["minor bump<br/>0.18.0 → 0.19.0"]
    Kind -->|breaking schema /<br/>removed script| Major["major bump<br/>0.x → 1.0.0<br/>RFC required first"]

    Patch --> Substantial{"Substantial?<br/>(multi-spec / multi-script)"}
    Minor --> Substantial
    Major --> Substantial

    Substantial -->|yes| Rc["rc-first variant<br/>tag vX.Y.Z-rc1"]
    Substantial -->|no| Bump["§2 — bump VERSION<br/>+ update CHANGELOG"]

    Rc --> RcValidate["validate against<br/>working checkout"]
    RcValidate --> RcOk{"all green?"}
    RcOk -->|no — iterate| RcBump["tag rc2, rc3 …<br/>fix-and-retest loop"]
    RcBump --> RcValidate
    RcOk -->|yes — promote| Bump

    Bump --> Zombie{"§3 — removed or<br/>renamed consumer surface?"}
    Zombie -->|yes| Manifest["append zombies-manifest.yaml<br/>+ bump manifest_version"]
    Zombie -->|no| Commit
    Manifest --> ZombieGate["cleanup-zombies.rule.py<br/>validate (pre-commit gate)"]
    ZombieGate --> Commit["§4 — git commit<br/>+ git tag -a vX.Y.Z"]

    Commit --> Push["§5 — git push origin<br/>main + vX.Y.Z"]
    Push --> Release["§5 — create Release manually<br/>gh release create vX.Y.Z<br/>(CHANGELOG = body)"]
    Release --> Smoke["§7 — first-run smoke test<br/>against a real consumer<br/>(OUTSIDE of CI)"]
    Smoke --> SmokeOk{"smoke passes?"}
    SmokeOk -->|no — rc only| RcBump
    SmokeOk -->|yes| Done["Tag published<br/>consumers pull at own pace"]

    classDef decision fill:#e3f2fd,stroke:#1565c0,color:#0d47a1
    classDef gate fill:#fff3e0,stroke:#ef6c00,color:#e65100
    classDef success fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20
    classDef rc fill:#f3e5f5,stroke:#6a1b9a,color:#4a148c
    class Kind,Substantial,Zombie,RcOk,SmokeOk decision
    class ZombieGate,Smoke gate
    class Done success
    class Rc,RcValidate,RcBump rc
```

### 1. Pick the semver bump

| Kind of change | Bump |
|---|---|
| Docs, typo fixes, stub closures | patch (`0.18.0 → 0.18.1`) |
| New scripts or specs (additive, no breaking schema) | minor (`0.18.0 → 0.19.0`) |
| Breaking schema (AGENTS.md frontmatter), removed script, renamed env var, changed verdict rubric | major (`0.x → 1.0.0`) — requires RFC first per [Concept: rollout-strategy](../concepts/rollout-strategy.md) |

For substantial releases (multiple specs / scripts / templates in one go), use the rc-first variant: tag `vX.Y.Z-rc1`, validate against your own working checkout, iterate `rc2` etc., then promote to `vX.Y.Z` stable.

### 2. Update VERSION + CHANGELOG

Edit `VERSION` (no leading `v`, one line + trailing newline):

```
0.19.0
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

Body MUST be human-readable and ≤ ~40 lines — consumers read it on their own update flow to decide whether to pull.

### 3. Zombie manifest gate (v0.15.0+)

If this release REMOVED or RENAMED any consumer-surface artefact — a template under `templates/new-project/`, a literal identifier consumers hard-code (project name, MCP server alias), a frontmatter field, a script consumers invoke — append an entry to `specs/zombies-manifest.yaml` AND bump its `manifest_version` (`YYYY-MM-DD.N`, strictly monotonic).

Reference: [Rule: cleanup-zombies](../rules/cleanup-zombies.rule.md). Validation: `python scripts/rules/cleanup-zombies.rule.py validate` (pre-commit gate). Skip ONLY for internal-only releases that never touched consumer-facing surfaces.

### 4. Commit + tag

```bash
git add VERSION CHANGELOG.md
git commit -m "release: vX.Y.Z — <one-liner>"
git tag -a vX.Y.Z -m "vX.Y.Z — <one-liner>"
```

### 5. Push branch + tag, then create the Release

```bash
git push origin main vX.Y.Z
```

Pushing the tag triggers `release.yml`, which runs `scripts/release_cut` and **auto-creates** the GitHub Release from this version's CHANGELOG section. (`docs-deploy.yml` also fires on the tag push to deploy docs.) If that workflow ever fails, create the Release manually as a fallback — the tag itself is unaffected:

```bash
gh release create vX.Y.Z --verify-tag \
  --title "vX.Y.Z — <one-liner>" \
  --notes-file <file containing this version's CHANGELOG section>
# inline alternative: --notes "<paste the CHANGELOG section for this version>"
```

The CHANGELOG section for this version is the release-notes body — `release_cut` extracts it automatically on the tag push; the command above is the manual fallback.

### 6. (Optional) Notify maintainers manually

The playbook does not reach into consumer repos. If a release introduces a breaking change or a security fix that consumers need to absorb urgently, post a one-line heads-up in the team channel pointing at the GitHub Release URL. Otherwise, GitHub's "Watch → Releases" subscription is sufficient.

### 7. First-run smoke test (v0.11.0+)

Before merging the rc → stable promotion, run EVERY new or modified script / workflow / skill against ONE real consumer at least once, end-to-end, OUTSIDE of CI. CI mocks the boundary that hides environmental constraints (API rate limits, locale encoding, missing markers in auto-generated content); real invocation exposes them.

Procedure:

1. Pick the canonical first-run consumer (your own working checkout is fine).
2. For each new or modified surface, list a real invocation. Examples:
   - New rule script — execute its CLI against a real change folder.
   - New skill — invoke `/<skill-name>` interactively in a real Claude Code session.
   - Schema/frontmatter change — open a sample AGENTS.md and confirm the validator accepts/rejects as intended.
3. Smoke results land in the release PR body under `## First-run smoke (per release.md §7)`. Each result: `surface | command | exit code | observation`. Failures block stable promotion; rc bumps absorb the fix-and-retest loop.

Non-skippable for releases shipping new scripts / new workflows / new skills. Pure documentation releases MAY skip with a one-line rationale.

## Consumer-side bump (separate workflow)

Each consumer absorbs the tag on its own schedule:

```bash
cd <consumer-checkout>
cd .ai-playbook
git fetch origin
git checkout vX.Y.Z          # or `git pull origin main` for tip-of-main
cd ..
git add .ai-playbook
git commit -m "chore(playbook): bump .ai-playbook to vX.Y.Z"
git push
```

For consumers that want automated upgrade PRs, configure a Dependabot or Renovate rule that watches submodule tags — that's the recommended pull mechanism. The playbook ships no central propagation pipeline (retired in v0.19.0 — see [release-management.md](../concepts/release-management.md) for the rationale).

## Verification

- `git tag --list` shows the new tag locally and `git ls-remote --tags origin` shows it on `origin`.
- `gh release view vX.Y.Z` shows the Release with the CHANGELOG section as its body (created manually in §5 — the tag push does not auto-create it).
- `git push origin main vX.Y.Z` completed without error and the CI test workflow on the tagged commit is green.

## Troubleshooting

### Symptom: tag was cut by mistake (bad CHANGELOG, wrong version) and no consumer has pulled yet
**Cause**: human error in steps 2 or 4.
**Fix**: rollback the tag before any consumer adopts:

```bash
git tag -d vX.Y.Z
git push origin --delete vX.Y.Z

# Revert the VERSION + CHANGELOG commit if needed:
git revert HEAD
git push origin main
```

Coordinate with anyone you know has already pulled (they will need to reset their submodule pin).

### Symptom: a consumer already pulled and the release needs correction
**Cause**: same as above but discovered too late.
**Fix**: never rewrite a published tag. Cut the next version with the correction. Follow [Concept: rollout-strategy](../concepts/rollout-strategy.md) §rollback.

## Related

- [Concept: release-management](../concepts/release-management.md) — the pull-model contract + branch model + PR shape + CI gates.
- [Concept: rollout-strategy](../concepts/rollout-strategy.md) — breaking-change protocol.
- [Rule: cleanup-zombies](../rules/cleanup-zombies.rule.md) — zombie manifest gate.
