---
schema: concept/v1
slug: skills-distribution
title: Skills Distribution
summary: |
  This spec defines how skill content (SKILL.md files plus assets) reaches
  consumer projects. v0.17.0 collapses the previous multi-source design into a
  single-source model: the playbook submodule itself is the source of truth.
last_validated: "2026-05-19"
---

# Skills Distribution

This spec defines how skill **content** (SKILL.md files plus assets) reaches
consumer projects. v0.17.0 collapses the previous multi-source design into a
**single-source** model: the playbook submodule itself is the source of truth.

---

## 1 Architectural decisions

The single-source design follows from three locked decisions in the ai-playbook
reset plan (v0.15.0 -> v0.20.0):

- **D1 — Single-source skills.** `.ai-playbook/skills/` is THE source. No
  `skills_sources:` frontmatter. No `.skills-sources/` submodule. No multi-repo
  merging.
- **D2 — Scripts not mirrored.** Consumer hooks invoke the materialiser via the
  direct path `.ai-playbook/scripts/materialise_skills.py`. No script copies in
  the consumer's own `scripts/`.
- **D17 — Skills perpendicular Rules.** Skills may depend on rules; rules must not
  depend on skills. The materialiser sits squarely in the skills lane.

Full rationale, alternatives considered, and historical context for the
multi-source pattern that v0.17.0 removes:

- D1, D2, D17 — `~/.claude/plans/vamos-a-identificar-los-elegant-marshmallow-decisions.md`
- consumer-a PR #125 — the first downstream consumer to deviate (2026-05-18),
  whose `sync_skills_local.py` became the upstream template.
- ai-playbook v0.17.0 CHANGELOG entry — what shipped and what was removed.

---

## 2 Source repo and canonical layout

Skill content lives **in the playbook itself** at the canonical, vendor-neutral
path `<playbook>/skills/<skill-name>/`:

```
ai-playbook/
  skills/
    <skill-name>/
      SKILL.md              # required, vendor-neutral
      [steps-c/, templates/, data/, references/, ...]
```

Every consumer mounts the playbook as a git submodule at `.ai-playbook/`, so
on the consumer side the source resolves to:

```
<consumer>/.ai-playbook/skills/<skill-name>/SKILL.md
```

### 2.1 Required SKILL.md sections (v0.7.0+)

Unchanged from v1.0.0. Every `SKILL.md` must contain Purpose, Workflow,
Anti-patterns, Verification, See also (in order). Pattern adopted from
[Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill).

```markdown
---
name: <skill-name>
description: <one sentence: WHEN to use this skill, NEVER summarise the workflow>
license: <SPDX or "see LICENSE">
compatibility: <Claude Code | Cursor | universal>
---

# <Skill name> — <one-line tagline>

## Purpose
<one paragraph: what + when an agent should reach for it>

## Workflow
<numbered steps; concrete, no skeletons (per output-completeness.md)>

## Anti-patterns
<bulleted list; specific > generic; cite verdict-contract.md /
agentic-failures.md where the failure mode is canonical>

## Verification
<how the skill self-verifies before emitting ✅ APPROVED, per
verification-before-completion.md>

## See also
<cross-refs>
```

**Description rule (CSO — "command-style operations")**: the `description`
field tells an LLM **when** to invoke the skill, not what the skill does.
Bad: "Generates a PRD with 12 sections". Good: "Use when the user wants to
start a new module's discovery phase". Checked by
`scripts/check_skill_descriptions.py`.

### 2.2 No multi-source registry

v0.17.0 explicitly drops the multi-source registry that v1.0.0 maintained
(`Wizarck/ai-playbook` + `Wizarck/consumer-d-skills`). All skills now live in
`ai-playbook/skills/`. Skills previously published from `consumer-d-skills/skills/`
are absorbed upstream (or remain in `consumer-d-skills` as standalone artefacts
without a consumer-side distribution channel — see the
[v0.17.0 CHANGELOG entry](../../CHANGELOG.md) for the migration audit).

---

## 3 Consumer-side layout

Every consumer carries the playbook submodule and three **gitignored** mirror
directories:

```
<consumer>/
  .ai-playbook/             # playbook submodule (source of truth for skills/)
    skills/<skill>/SKILL.md
  skills/                   # gitignored mirror #1 (generic tools)
  .claude/skills/           # gitignored mirror #2 (Claude Code)
  .gemini/skills/           # gitignored mirror #3 (Gemini CLI / Antigravity)
```

All three mirrors are regenerated from the same source via the materialiser.
Per D2, the materialiser lives upstream and is invoked via its direct
submodule path; no copy in `<consumer>/scripts/`.

### 3.1 Why three mirrors

| Mirror | Read by | Why a separate copy? |
|---|---|---|
| `<consumer>/skills/` | Generic tools, IDE pickers, ad-hoc shell scripts | Vendor-neutral; the visible `ls`-able location |
| `<consumer>/.claude/skills/` | Claude Code skill harness | Required by Claude Code's hard-coded path |
| `<consumer>/.gemini/skills/` | Gemini CLI / Antigravity | Required by Gemini's hard-coded path |

Per RFC-0001 (now deleted) §2 "Why copy instead of symlink/junction": copy is
the only portable approach across Git Bash, native Windows, WSL, and VS Code's
file watchers. The drift-detection guarantee that symlinks would provide is
instead delivered by the fingerprint-equality short-circuit inside the
materialiser (§4).

### 3.2 .gitignore entries

All three mirrors are gitignored, from the playbook-managed block in
`templates/new-project/.gitignore.tmpl`:

```
/skills/
/.claude/skills/
/.gemini/skills/
```

Until v0.24.0 this section stated the rule and the template implemented none of
it, so what a consumer ignored was whatever it had hand-written. Repos onboarded
under RFC-0001 carry a block that ignores `.claude/skills/` and `.gemini/skills/`
but keeps `/skills/` — correct then, because `skills/` was the source and the
other two were its copies. v0.17.0 collapsed to single-source and made all three
mirrors; those repos still commit one.

The cost of committing a mirror is that every playbook bump arrives as a diff of
files nobody in that repo wrote, and any hand-edit there is overwritten without
warning on the next run (§4.1). Untrack it once, after the pin reaches v0.24.0:

```
git rm -r --cached skills/
```

---

## 4 Materialisation algorithm

Implemented in `scripts/materialise_skills.py::materialise_skills()`. Idempotent
end-to-end: re-running with no upstream changes is a fingerprint-equal no-op
on each of the three mirrors.

```
INPUT: <consumer-dir>, source_override=None, dry_run=False, quiet=False
OUTPUT: SkillsMaterialisationResult { skills_total, mirrors_rewritten,
                                       mirrors_in_sync, errors, summary }

1. source = source_override or <consumer-dir>/.ai-playbook/skills/
   If source missing -> emit canonical error, return with errors[]; exit 2.
   desired = immediate children of source holding a SKILL.md, minus disabled.

2. manifest   = read(<consumer-dir>/.ai-playbook-state/skills-manifest.json)
   ever_owned = slugs from <source>/../specs/skills-owned-history.yaml

3. For each mirror in (skills/, .claude/skills/, .gemini/skills/):
   a. If the mirror is a symlink -> skip; do not manage provenance.
   b. present    = immediate child directories of the mirror.
      owned_prev = manifest[mirror], or `present ∩ (desired ∪ ever_owned)`
                   when absent (§4.1).
      stale      = (owned_prev - desired) ∩ present
      user_kept  = present - owned_prev - desired
   c. Delete every directory in `stale`.
   d. For each name in `desired`, compare the per-skill fingerprint and
      rmtree + copytree only that directory when it differs.
      On OSError -> append to result.errors, continue.
   e. manifest[mirror] = desired

4. Persist the manifest (best-effort; skipped in dry-run). Return result.
```

### 4.1 Orphan removal is provenance-gated

The materialiser deletes only what it recorded as having installed. A directory
that is neither playbook-owned nor desired is a user skill and survives
untouched — that is the additive contract.

When a skill is removed upstream, a mirror with no manifest entry has no record
of who installed it. Seeded as `present ∩ desired` alone, the removed slug is
excluded from the owned set by construction, so it can never be classified as
stale — not on that run nor on any later one — and the only remedy was to seed
the manifest in the consumer **before** its pin moved past the removal.

That remedy was illegitimate. This playbook is pull-model: consumers bump on
their own schedule and [nothing reaches into their
repos](../runbooks/release.md). A correctness requirement that must be executed
inside every consumer, in advance, cannot be relied on and presumes the playbook
knows who its consumers are. It does not, and ships nothing that walks them.

So the playbook supplies the missing half from its own side. `specs/skills-owned-history.yaml`
lists every slug it has ever shipped, and the seed becomes:

```
owned_prev = present ∩ (desired ∪ ever_owned)
```

A slug the playbook removed is in `ever_owned` and not in `desired`, so it is
owned, stale, and cleared on the consumer's first ordinary `bootstrap.py
--update`. A slug the consumer authored is in neither set and is preserved. No
advance step, no coordination, no consumer list.

The list is append-only: removing a slug from it re-creates the orphan it exists
to clear. `tests/test_materialise_skills.py` fails if a shipped skill is missing
from it. A consumer whose playbook copy predates the file degrades to the old
behaviour — nothing is deleted — rather than failing.

Hand-edits inside a playbook-owned mirror directory are NOT preserved. Mirrors
are derived state; edits go upstream to `ai-playbook/skills/<name>/`.

### 4.2 Idempotency cost

Cold run: ~1s per mirror to fingerprint + copy 75 skills on Win11 SSD.
Hot run (all three already in sync): ~150ms total (fingerprint-only, no I/O
writes). Acceptable for post-checkout / post-merge git hook usage.

### 4.3 Exit codes

| Path | CLI exit |
|---|---|
| Success (no-op or rewrite) | 0 |
| Source missing | 2 |
| Filesystem write failure | 1 |

CLI errors emit the canonical error shape from
[`error-message-standard.md`](../rules/error-message-standard.rule.md).

---

## 5 Hook wiring

The materialiser is wired into two git hooks at the consumer side:

| Hook | When it fires | Why this matters |
|---|---|---|
| `post-merge` | After every `git pull` / `git merge` | Catches the playbook submodule pin advancing |
| `post-checkout` (flag=1 only) | After a branch checkout | Catches branch switches that change the submodule pin |

Hook templates ship under `templates/new-project/scripts/git-hooks/`. The
installer template `templates/new-project/scripts/install-playbook-hooks.sh.tmpl`
points `git config core.hooksPath scripts/git-hooks` and runs the first sync.

Both hooks call:

```bash
python "$REPO_ROOT/.ai-playbook/scripts/materialise_skills.py" --quiet || {
    echo "warn: skills sync failed; run manually" >&2
    exit 0  # never abort git operation on sync failure
}
```

The `|| exit 0` pattern matches `cleanup_zombies.py` (§6 exit-code policy in
[`cleanup-zombies.md`](../rules/cleanup-zombies.rule.md)): hooks NEVER block `git pull` /
`git checkout`. Failures surface via stderr only.

### 5.1 Gemini-specific start wrapper

Gemini CLI does not have a built-in session-start hook (unlike Claude Code).
The playbook ships `scripts/gemini_start.py` as a wrapper that:

1. Runs the materialiser (idempotent — fast no-op when already synced).
2. Runs `inject_context.py` to seed the Gemini session with playbook memory.
3. Exec's the `gemini` binary with the user's args.

Consumers install via `templates/new-project/scripts/gemini_start.py.tmpl`.
Users invoke `gemini_start` instead of `gemini` directly.

---

## 6 Fallback / degraded mode

If `.ai-playbook/skills/` is missing (submodule not initialised, or playbook
checked out at a tag predating the skill set):

1. The materialiser exits with code 2 and the canonical error message.
2. Existing mirrors are left untouched (no rmtree on missing source).
3. Hook context: stderr warning, hook returns 0, git operation continues.
4. Fix path: `git submodule update --init .ai-playbook` then re-run.

The materialiser never fabricates skill content. Per
[`degradation-modes.md`](degradation-modes.md), if a missing skill is
required for a task, the agent emits `❓ CLARIFICATION NEEDED`.

---

## 7 Security

- **No content over the wire from arbitrary origins.** The materialiser reads
  ONLY from the consumer's local filesystem (`.ai-playbook/skills/` or
  `--source <path>` override).
- **No new credentials required.** Submodule auth is whatever the consumer
  already configured for the `.ai-playbook` submodule pull.
- **No write access required on the playbook.** The materialiser is read-only
  against the source.

Compared to RFC-0001 (now deleted): the multi-source attack surface is gone.
No `repository_dispatch` propagation channel, no `GH_TOKEN` requirement, no
cross-consumer fan-out workflow.

---

## 8 KPIs

The single-source migration's success criteria (validated at slice 8 / v0.20.0
cut):

| KPI | Target | Measurement |
|---|---|---|
| Skill content duplication across consumers | 0 (one canonical source: `ai-playbook/skills/`) | `find . -name SKILL.md` against the playbook submodule + each consumer mirror — every consumer mirror byte-identical to source |
| Reproducibility | 100% | `git checkout <consumer-sha>` + `python .ai-playbook/scripts/materialise_skills.py` produces byte-identical mirrors |
| Idempotency | 100% — second run is a fingerprint-equal no-op | Test fixture `test_materialise_skills.py::test_idempotent_run` |
| Windows portability | Materialisation runs from clean clone with no admin / Dev Mode | Smoke test on Win11 Pro (Git Bash + native PowerShell) |
| Orphan removal | Skill removed upstream disappears in the next materialise run **that has a manifest entry for the mirror** | Test fixture `test_materialise_skills.py::test_orphan_skill_removed` |
| Hook overhead | ≤500ms p50 for hot (in-sync) runs | Bench in `tests/test_materialise_skills.py` |

---

## 9 Non-goals

This spec deliberately does **not** cover:

- Multi-source skills (dropped in v0.17.0; see CHANGELOG migration table).
- A central skills marketplace.
- Per-skill semver (v0.17.0 skills version with the playbook tag).
- Hot-reload mid-session (consumers re-run the materialiser).
- LLM-side adaptation of SKILL.md content (mirror is byte-identical).

---

## 10 Cross-references

- [`skills-registry.md`](skills-registry.md) — discovery surface (HTTP catalog;
  registry contract unchanged in v0.17.0, only the upstream source field
  semantics simplify).
- [`../runbooks/release.md`](../runbooks/release.md) —
  maintainer procedure for cutting a new playbook tag (incorporates skill
  changes by definition — tagging the playbook = tagging the skill set).
- [`dispatcher-chain.md`](dispatcher-chain.md) — three-level dispatcher
  resolution; skills participate per D17.
- [`cleanup-zombies.md`](../rules/cleanup-zombies.rule.md) — consumer-side cleanup contract;
  v0.17.0 extends the manifest with 8 v2 entries covering the multi-source
  artefacts.
- [`degradation-modes.md`](degradation-modes.md) — `DEGRADED_CONTEXT` enum
  used when materialisation fails partially.
- [`error-message-standard.md`](../rules/error-message-standard.rule.md) — canonical shape
  of errors emitted by `materialise_skills.py`.
- [`taxonomy.md`](taxonomy.md) — canonical definitions of "skill" and "consumer".
