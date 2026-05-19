# proposal — `doc-drift-enforcement`

> **Status**: draft (slice/`feat/doc-drift-enforcement`).
> **Wave**: ai-playbook v0.16.0 candidate (additive MINOR).
> **Authored**: 2026-05-19.

## Problem

The playbook ships canonical scripts (e.g. `scripts/rules/cleanup-zombies.rule.py`) paired
with normative documentation (e.g. `docs/rules/cleanup-zombies.rule.md`). When a contributor
modifies one side of the pair without the other, the repo silently drifts:

- **Code-without-doc**: the script gains a new flag, a new exit code, or a new
  break-glass env var; the spec still describes v(N-1). Consumers reading the
  spec misinterpret what the script does.
- **Doc-without-code**: a spec is edited to assert a new invariant; the script
  still emits the old behaviour. Reading the spec produces false confidence.

Concrete drift instances observed in 2026-05:

| Pair | Symptom |
|---|---|
| `scripts/rules/cleanup-zombies.rule.py` ↔ `docs/rules/cleanup-zombies.rule.md` | Two PRs in slice 1 added new safety checks without updating the spec table |
| `templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl` ↔ `docs/rules/apply-skill-enforcement.rule.md` | Hook decision flow changed in a follow-up; spec §2.2 was a step behind |
| `scripts/wt_add.py` ↔ `docs/concepts/git-worktree-bare-layout.md` | Bare-repo + worktree convention; script behaviour drifted from documented flow |

There is no PR-time gate that warns "you touched the code side of a known pair
but not the doc side, was that intentional?". Reviewers catch drift only by
chance (and the reviewer is sometimes the same person as the author).

## Proposed change

Ship a **declarative co-edit-pairs manifest** + a **single CI check** that
fails a PR when one side of a paired (code, doc) tuple is modified without the
other, with a documented `[no-doc-impact]` escape hatch in the PR title for
truly tangential changes (typos, formatting-only commits, etc.).

### Three-tier policy

| Tier | Behaviour | Examples |
|---|---|---|
| **1 — strict pair** | Both files must move together; CI fails on drift. | `scripts/rules/cleanup-zombies.rule.py` ↔ `docs/rules/cleanup-zombies.rule.md` |
| **2 — soft pair** *(future)* | CI warns but does not block. (Not enabled in v0.16.0 — reserved for slice 5+.) | n/a |
| **3 — informational** *(future)* | Logged for telemetry only; no CI surface. (Reserved for slice 6 telemetry.) | n/a |

v0.16.0 ships only Tier 1. The schema reserves `tier: 2 | 3` for future use.

### Escape hatch

PR authors who legitimately touch one side without the other (typo fix, lint
churn, dead-code cleanup) put `[no-doc-impact]` (case-insensitive) anywhere in
the PR title. CI honours this and exits 0. Usage is logged for slice 6
telemetry (escape-hatch abuse > 20% / month flags a review).

### Deliverables

| Path | Action | Description |
|---|---|---|
| `scripts/check_doc_drift.py` | NEW | argparse-driven CLI. Loads `specs/co-edit-pairs.yaml`, reads `git diff --name-only origin/main...HEAD` (or `--base-ref`/`--head-ref` overrides), fails on Tier 1 violations. Honours `--pr-title` arg for the escape hatch. Exit 0 = pass, 1 = violation, 2 = schema break. |
| `specs/co-edit-pairs.yaml` | NEW | Declarative manifest. Schema: `version`, `manifest_version`, `pairs: [{id, tier, code, doc, reason, introduced_in}]`. v1 seeds ~10 grounded pairs. |
| `docs/rules/doc-drift-enforcement.rule.md` | NEW | Normative contract (v1.0.0). Documents the manifest schema, exit-code policy, escape-hatch, interaction with future telemetry. |
| `.github/workflows/doc-drift-enforcement.rule.yml` | NEW | Triggers on `pull_request: [opened, synchronize, reopened, edited]`. Invokes `check_doc_drift.py` with `--pr-title "${{ github.event.pull_request.title }}"`. Sticky comment on violation. Hard-fails the check. |
| `tests/test_check_doc_drift.py` | NEW | ≥15 tests covering pair detection, escape hatch, schema validation, unknown files, multi-file PRs, edge cases. |
| `docs/concepts/enforcement-status.md` | EDIT | Add row for `doc-drift-enforcement.md` (✅ wired). |
| `docs/concepts/development-flow.md` | EDIT | §5 enforcement table — add doc-drift row. |
| `README.md` | EDIT | Status section bumped to v0.16.0. |
| `tests/test_apply_enforce_hook_template.py` | EDIT | Tighten `_invoke_hook` to clear `AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE` from inherited env unless the test explicitly sets it (root cause of 3 pre-existing failing tests). |
| 4 dead cross-refs | FIX | Audit `runbooks/` and `docs/` for broken links left by past renames. |
| `CHANGELOG.md` | EDIT | `[0.16.0]` entry. |
| `VERSION` | EDIT | `0.15.0` → `0.16.0` (additive MINOR). |

### Decisions

- **D2.1 — Single source of truth**: pairs live in the playbook upstream
  (`specs/co-edit-pairs.yaml`), not per-consumer. Rationale: the playbook owns
  the canonical scripts + their docs; consumers do not extend the pair list.
- **D2.2 — Tier 1 only in v0.16.0**: ship the strictest mode first; soft pairs
  + informational pairs introduced when telemetry (slice 6) is live.
- **D2.3 — Escape hatch in PR title, not commit message**: PR title is the
  contract surface CI already reads (`branch-name-validator.yml` precedent).
  Commit message escape hatch is hard to surface in sticky-comment feedback.
- **D2.4 — `git diff origin/main...HEAD`**: triple-dot to capture the changes
  introduced *by this branch* relative to its merge-base, not all commits that
  happen to be in `HEAD` but not in `main` (which would over-report on stale
  branches).
- **D2.5 — Glob support on `code:` and `doc:`**: a single pair entry may have
  `code: "scripts/rules/*.rule.py"` matching many files. Doc-drift check then
  asserts EITHER any matching code-side file OR any matching doc-side file
  brings the other side into scope. Implementation uses `fnmatch` on
  forward-slash-normalised paths (mirrors the apply-enforce hook precedent).
- **D2.6 — Exit codes match break-glass conventions**: 0 = pass, 1 = drift
  detected, 2 = schema / config error (per `docs/rules/break-glass.rule.md` pattern).
- **D2.7 — Sticky comment + check failure**: same UX pattern as
  `branch-name-validator.yml` — sticky comment surfaces the offending pair(s)
  and the suggested fix; check status is the merge gate.

## Out of scope

- **Telemetry hooks** — slice 6 absorbs `[no-doc-impact]` usage tracking.
- **Tier 2/3 (soft + informational) behaviour** — schema reserves the values;
  enforcement deferred.
- **Cross-repo pair tracking** — pairs are intra-playbook only; consumer
  projects own their own drift gates.
- **Auto-generation of pair entries** — the manifest is hand-curated;
  contributors add an entry when introducing a new code-doc pair.

## Consumer adoption

Zero consumer action required. This slice runs entirely upstream in CI. The
check fires on every PR opened against `Wizarck/ai-playbook`.
