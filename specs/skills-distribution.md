# skills-distribution.md

> **Status**: v1.0.0 (introduced by [RFC-0001](../rfcs/RFC-0001-skills-distribution.md)).
> Defines how skill **content** (SKILL.md files plus assets) reaches consumer
> projects. Pairs with [`skills-registry.md`](skills-registry.md), which owns
> the **discovery** surface; this spec owns the **distribution** surface.

The distribution model is **semver-pinned source repos materialised as git
submodules with sparse-checkout**, plus a deterministic copy step that
generates per-LLM mirrors at bootstrap time.

This spec is the contract; the implementation lives in
`scripts/_skills_materialiser.py`,
`scripts/propagate_skills_bump.py`,
`scripts/validate_skills_mirror.py`,
and `.github/workflows/propagate-skills-bump.yml`.

---

## 1. Source repos and canonical layout

Skill content lives in **source repos** at the canonical, vendor-neutral path
`<repo>/skills/<skill-name>/`:

```
<source-repo>/
  skills/
    <skill-name>/
      SKILL.md              # required, vendor-neutral
      [steps-c/, templates/, data/, references/, ...]
```

### Required SKILL.md sections (v0.7.0+)

Every `SKILL.md` MUST contain the following sections in order. The `## Anti-patterns` section is new in v0.7.0 (pattern adopted from [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill)) and applies to skills authored or revised under v0.7.0+ — existing skills are migrated opportunistically (no flag day).

```markdown
---
name: <skill-name>
description: <one sentence: WHEN to use this skill, NEVER summarise the workflow>
license: <SPDX or "see LICENSE">
compatibility: <Claude Code | Cursor | universal>
---

# <Skill name> — <one-line tagline>

## Purpose

<one paragraph: what the skill does + when an agent should reach for it>

## Workflow

<numbered steps; concrete, no skeletons (per output-completeness.md)>

## Anti-patterns

<bulleted list of patterns this skill explicitly avoids, with one-line rationale per item.
The list is the skill's "what we will NOT do" inventory. Specific > generic. Cite verdict-contract.md or
agentic-failures.md where the failure mode is canonical.>

## Verification

<how the skill verifies its own output before emitting ✅ APPROVED, per verification-before-completion.md.
For non-code skills, the audit pattern from §8 of that spec applies>

## See also

<cross-refs to other specs / skills>
```

**Description rule (CSO — "command-style operations" pattern from `obra/superpowers`):** the `description` field tells an LLM **when** to invoke the skill, not what the skill does internally. Bad: "Generates a PRD with 12 sections via guided elicitation". Good: "Use when the user wants to start a new module's discovery phase and write its product requirements". This rule is checked by `scripts/check_skill_descriptions.py` (warning-level in v0.7.0; hardening planned for v0.8.0 after a per-skill audit).

Two source repos are recognised as of v0.4.0 (more may register later):

| Repo | Scope | Family |
|---|---|---|
| `Wizarck/ai-playbook` | public methodology | BMAD agents, BMAD workflows, OpenSpec commands, BMAD upstream-tracked |
| `Wizarck/consumer-d-skills` | public custom | mcp-builder, qa-* family, kickoff, nuevo-lote, etc. |

The path is **deliberately not** `.claude/skills/`. Skills are vendor-neutral
artefacts — a `SKILL.md` is just a Markdown contract — and consumer agents
beyond Claude (Gemini CLI, Antigravity, future) must be able to read the same
canonical files.

### 1.1 Adding a new source repo

To add a third source repo (e.g. a private enterprise skill set):

1. The source repo must adopt the canonical layout (`<repo>/skills/<name>/SKILL.md`).
2. Cut a semver tag (`v0.1.0` minimum).
3. Add an entry under `consumers.yaml` in any consumer that wants to pin it
   (the `skills_pins` map gains a new key for the new repo slug).
4. The consumer's `AGENTS.md` `skills_sources` block grows by one entry.
5. The propagation workflow auto-discovers the new repo on the next tag push
   if the workflow's repository_dispatch trigger is configured by the source
   repo's release process.

No central registry of "approved source repos" is enforced — the gate is
review of the consumer's `consumers.yaml` PR.

## 2. Pinning model

Each consumer pins **independently** per source repo:

```yaml
# consumer's AGENTS.md frontmatter
skills_sources:
  - Wizarck/ai-playbook@v0.4.0
  - Wizarck/consumer-d-skills@v0.2.0
```

Mirror entry in the playbook's org-level `consumers.yaml`:

```yaml
consumers:
  consumer-e:
    repo: Wizarck/consumer-e
    default_branch: main
    visibility: private
    status: active
    skills_pins:
      ai-playbook: v0.4.0
      consumer-d-skills: v0.2.0
```

The two surfaces (`AGENTS.md.skills_sources` and `consumers.yaml.skills_pins`)
must agree. The propagation workflow updates both atomically; manual edits to
one without the other are caught by `drift_check.py --scope skills-pins`
(landing in v0.4.1).

### 2.1 Format of source refs

Canonical form: `<owner>/<repo>@<git-ref>` where `<git-ref>` is a semver tag
(`v0.4.0`), a commit SHA (40 hex chars), or — discouraged in production — a
branch name (`main`). The materialiser does not enforce semver; the human
review of the consumer's PR does.

Forbidden: floating refs like `latest`, `HEAD`, `master` without explicit
maintainer override (`--force-with-reason="<text>"` per `break-glass.md`).
The materialiser warns when a non-tag ref is detected.

## 3. Materialisation algorithm

Implemented in `scripts/_skills_materialiser.materialise_skills()`. Idempotent
end-to-end: re-running with no upstream changes produces zero filesystem
modifications.

```
INPUT: <consumer-dir>, dry_run=False
OUTPUT: SkillsMaterialisationResult { skills_total, sources_pinned, mirrors_generated, errors }

1. Parse <consumer-dir>/AGENTS.md frontmatter.
   If skills_sources is absent → no-op (consumer not yet migrated). Return early.

2. For each ref in skills_sources:
   a. Parse "<owner>/<repo>@<tag>" → (owner, repo, tag).
   b. submodule_path = .skills-sources/<repo-slug>/
   c. If submodule already added → git -C <submodule_path> fetch && checkout <tag>.
      Else → git submodule add https://github.com/<owner>/<repo>.git <submodule_path>
             with sparse-checkout pattern "skills/" + checkout <tag>.

3. Merge sources into <consumer-dir>/skills/:
   a. For each source's <submodule_path>/skills/<name>/, copy into <consumer-dir>/skills/<name>/.
   b. Detect name collisions across sources. On collision → emit
      "❓ CLARIFICATION NEEDED" per error-message-standard.md and abort with exit 3.

4. Regenerate per-LLM mirrors:
   a. rm -rf <consumer-dir>/.claude/skills/
   b. rm -rf <consumer-dir>/.gemini/skills/
   c. cp -r <consumer-dir>/skills/ <consumer-dir>/.claude/skills/
   d. cp -r <consumer-dir>/skills/ <consumer-dir>/.gemini/skills/

5. Verify content hashes match (defence-in-depth — detects FS races).

6. Return result with counts.
```

### 3.1 Submodule path: `.skills-sources/`

The submodule lands at `<consumer>/.skills-sources/<repo-slug>/` (hidden,
with leading dot). This is **derived state** — the canonical user-facing
surface is `<consumer>/skills/`, populated by the merge step. The hidden
location matches the existing convention `.ai-playbook/` for the playbook
submodule.

Sparse-checkout pattern: `skills/`. The materialiser limits the local clone
to that path only; the rest of the source repo (its own `tests/`, `docs/`,
etc.) is never written to disk on the consumer machine.

### 3.2 Collision rules

If two source repos both publish a skill with the same name (e.g. both
publish `mcp-builder`):

1. The materialiser raises `❓ CLARIFICATION NEEDED` at step 3b.
2. Resolution requires either renaming the skill in one source repo (e.g.
   `mcp-builder-bmad` vs `mcp-builder-consumer-d`) or excluding one source
   from the consumer's `skills_sources`.
3. There is **no last-wins fallback** — silent shadowing across source repos
   would defeat the auditability goal of the whole architecture.

Initial source repos audit (Phase 1, 2026-04-26): zero collisions between
`ai-playbook/skills/` (69 methodology skills) and `consumer-d-skills/skills/`
(68 custom skills, post-restructure).

### 3.3 Copy vs symlink/junction

The merge step (3) and the per-LLM mirror generation (4) use **copy**, never
symlink or Windows junction. Rationale documented in
[RFC-0001 §2 "Why copy instead of symlink/junction"](../rfcs/RFC-0001-skills-distribution.md).
Summary: Windows symlinks need admin/Developer Mode; junctions are not
git-tracked cleanly; cross-shell resolution (Git Bash / PowerShell / WSL /
VS Code) is inconsistent. Copy is `O(seconds)` for typical skill volumes;
the pre-commit drift check enforces audit-tightness equivalent to a symlink.

## 4. Per-LLM adapter mirrors

Consumers maintain one **canonical** copy at `<consumer>/skills/` (committed
in git via the merged content) and **mirror** copies at:

- `<consumer>/.claude/skills/` — read by Claude Code.
- `<consumer>/.gemini/skills/` — read by Gemini CLI.

Both mirrors are **gitignored**; only `<consumer>/skills/` is tracked.
Regeneration is fast (copy of a few MB) so the gitignore is safe — re-bootstrap
on a fresh clone re-creates mirrors in seconds.

### 4.1 Drift detection

`scripts/validate_skills_mirror.py` compares `skills/` against each mirror.

```bash
python -m scripts.validate_skills_mirror --consumer <path>          # report-only
python -m scripts.validate_skills_mirror --consumer <path> --fix    # regenerate
```

Wired as a pre-commit hook via `.pre-commit-hooks.yaml`. Pre-migration
consumers (no `<consumer>/skills/` yet) are silent no-ops — the hook only
fires once the consumer has run the migration recipe.

Failure mode: `❌ skills mirror drift detected` printout + exit 1, listing
divergent files. Resolution is `--fix` or manual `cp -r skills/ .claude/skills/`.

## 5. Propagation

When a source repo cuts a new semver tag, every consumer whose
`consumers.yaml.skills_pins` references that source receives an automatic PR
bumping the pin.

### 5.1 Trigger surface

Two trigger paths land at `.github/workflows/propagate-skills-bump.yml`:

- **Tag push to ai-playbook itself** (`v*.*.*`) — the playbook's own tag
  push fires the workflow with `--source-repo ai-playbook --tag <tag>`.
- **`repository_dispatch` event `skills-tag-pushed`** — consumer-d-skills (or any
  future source repo) calls the playbook's `repository_dispatch` endpoint
  with `{"source_repo": "<slug>", "tag": "<tag>"}` from its own release
  workflow. Decoupling: source repos don't need to know about each consumer.

### 5.2 PR shape per consumer

Branch: `chore/bump-skills-<source-repo>-<tag>`.
Commit: `chore(skills): bump <source-repo> to <tag>`.
Diff: edits the relevant line in `consumers.yaml.skills_pins.<repo>` and the
matching `skills_sources` entry in the consumer's `AGENTS.md`. Both edits are
line-level regex (preserves YAML comments and ordering); whole-file rewrite
is forbidden.

Idempotency: if a PR for the same `chore/bump-skills-<repo>-<tag>` already
exists for that consumer, the workflow logs and skips. No clobbering.

### 5.3 Consumer review window

The propagation PR is **not auto-merged**. The consumer's CI runs (tests,
drift_check) and a maintainer reviews. This is the **canary surface** the
RFC promises: a regressing skill change opens 4 PRs (one per active consumer
in v0.4.0), and any one consumer can reject the bump while the others merge.
Rollback in a single consumer is a `git revert` of the merge commit.

## 6. Fallback / degraded mode

If a source repo is unreachable at materialisation time (DNS, rate limit,
auth failure, offline dev):

1. The consumer's existing `<consumer>/skills/` (last good state from the
   previous successful materialisation) remains usable.
2. Mirrors regenerate from the local `skills/` content if it exists.
3. `bootstrap.py --refresh-skills --skills-offline` (lands in v0.4.1)
   skips the fetch and only regenerates mirrors. Errors clearly if
   `skills/` is empty.
4. The agent surfaces `DEGRADED_CONTEXT` per
   [`degradation-modes.md`](degradation-modes.md) when materialisation
   fails partially. The agent **must not** fabricate skill content to
   fill the gap; if a missing skill is required, escalate with
   `❓ CLARIFICATION NEEDED`.

## 7. Security

- **No content over the wire from a non-source-repo origin**. The materialiser
  refuses to fetch from URLs that do not match the documented source repo
  pattern. There is no "skills CDN" or arbitrary URL fetch.
- **Tag verification is opt-in**. The materialiser does not enforce signed
  tags by default. Maintainers who want signed-tag-only can set
  `SKILLS_REQUIRE_SIGNED_TAGS=1` (lands in v0.4.1) — enables `git verify-tag`
  before checkout.
- **Submodule auth via existing creds**. The materialiser uses the local
  git's credential helper / `GH_TOKEN` env. No new token storage. Private
  source repos work as long as the consumer's git user has read access.
- **No write access required** on source repos for materialisation. The
  whole flow is read-only on the source side; only the consumer's working
  tree is mutated.

## 8. KPIs

The migration's success criteria, per RFC-0001 and validated quarterly:

| KPI | Target | Measurement |
|---|---|---|
| Skill content duplication | 0 (each skill name has 1 canonical home in 1 source repo) | `find . -name SKILL.md -exec sha256sum {} \;` over all consumer working trees → unique hashes per name |
| Reproducibility | 100% | `git checkout <consumer-sha>` followed by `bootstrap.py --refresh-skills` produces a `skills/` tree byte-identical to the one at that SHA |
| Audit trail | 1 PR per propagated bump per consumer | `gh search prs --label skills-bump` returns one PR per consumer per source-repo tag |
| Windows portability | Bootstrap completes from clean clone with no admin / Dev Mode toggles | Smoke test on Win11 Pro (Git Bash + native PowerShell) |
| Time to propagation | ≤ 24h elapsed (≤ 5 min CI + maintainer wall-clock) | Tag push timestamp vs first PR open timestamp |
| Rollback | Per-consumer revert leaves other consumers unaffected | Manual smoke test |

## 9. Non-goals

This spec deliberately does **not** cover:

- A central skills marketplace beyond the 2-source-repo model.
- Skill versioning per-skill (we version the source repo, not the skill).
  Per-skill semver would need a v2 of this spec.
- Hot-reload of skills mid-session (consumers re-bootstrap to pick up bumps).
- LLM-side adaptation (e.g. converting a generic SKILL.md into a Claude-flavor
  prompt). The mirror is a byte-identical copy; agents read SKILL.md
  natively.

## 10. Cross-refs

- [`../rfcs/RFC-0001-skills-distribution.md`](../rfcs/RFC-0001-skills-distribution.md) — design rationale and alternatives considered.
- [`skills-registry.md`](skills-registry.md) — discovery surface (HTTP catalog).
- [`../runbooks/skills-version-bump.md`](../runbooks/skills-version-bump.md) — maintainer procedure for cutting a new tag and propagating.
- [`dispatcher-chain.md`](dispatcher-chain.md) — three-level dispatcher resolution that skills participate in.
- [`degradation-modes.md`](degradation-modes.md) — `DEGRADED_CONTEXT` enum used when materialisation fails.
- [`error-message-standard.md`](error-message-standard.md) — canonical shape of errors emitted by the materialiser.
- [`break-glass.md`](break-glass.md) — `--force-with-reason` flag semantics for the materialiser's offline mode.
- [`taxonomy.md`](taxonomy.md) — canonical definition of "skill", "source repo", "consumer".
