# doc-drift-enforcement.md

> **Status**: v1.0.0 — shipped in ai-playbook v0.16.0. Authored under OpenSpec change `doc-drift-enforcement` on 2026-05-19. v0.17.0 (slice `single-source-skills-reset`) registered the `materialise-skills` pair (`scripts/materialise_skills.py` ↔ `docs/concepts/skills-distribution.md`), bringing the manifest to 13 pairs (`manifest_version: 2026-05-19.2`).
>
> **Audience**: anyone authoring a PR against the playbook upstream. Authoritative contract for `scripts/check_doc_drift.py` and `specs/co-edit-pairs.yaml`.

This spec defines the **doc-drift gate**: a declarative manifest of (code, doc) pairs that MUST move together, plus a CI check that fails PRs touching one side without the other, with a documented PR-title escape hatch for legitimately tangential changes.

---

## 1 Purpose

The playbook accumulates pairs where a canonical script is governed by a normative doc. Touching one side without the other silently degrades the repo:

- **Code-without-doc**: behaviour drifts from the documented contract; consumers reading the spec mislead themselves.
- **Doc-without-code**: a spec asserts an invariant the script does not yet enforce; reading the spec gives false confidence.

Reviewers catch drift only by chance. The doc-drift gate makes the pair contract explicit and CI-enforced.

Goals:

1. **Declarative pair registry** — `specs/co-edit-pairs.yaml` enumerates every paired (code, doc) tuple; hand-curated; one entry per pair.
2. **PR-time gate** — `.github/workflows/doc-drift-enforcement.rule.yml` runs `scripts/check_doc_drift.py` on every PR; fails on drift; sticky-comments the violation.
3. **Documented escape hatch** — `[no-doc-impact]` (case-insensitive) anywhere in the PR title bypasses the gate; usage is auditable (slice 6 telemetry).
4. **Forward-compatible tiering** — schema reserves Tier 2 (soft / warn) and Tier 3 (informational / telemetry-only) for future use without manifest migration.

Non-goals:

- Catching content drift INSIDE a paired file (linting prose against code); only co-modification is checked.
- Pre-commit hook (escape hatch is on PR title, which only exists at PR-open time).
- Cross-repo pair tracking; consumers maintain their own gates if needed.

---

## 2 Manifest schema

See `specs/co-edit-pairs.yaml` for the canonical instance. Schema:

```yaml
version: "<semver>"                # schema version; breaking changes bump major
manifest_version: "<YYYY-MM-DD>.<N>"  # data version; serial N starts at 1 each day
pairs:
  - id: <kebab-case slug, unique>
    tier: 1 | 2 | 3
    code: <project-relative path or fnmatch glob>
    doc:  <project-relative path or fnmatch glob>
    reason: <one-sentence why; ≤ 200 chars>
    introduced_in: <playbook version, e.g. v0.16.0>
```

### 2.1 Validation rules

- `version` must be `"1.0.0"` (v1 schema).
- `manifest_version` must match `^\d{4}-\d{2}-\d{2}\.\d+$`.
- Every pair MUST have `id`, `tier`, `code`, `doc`, `reason`, `introduced_in`.
- `id` must be unique within the file and match `^[a-z][a-z0-9-]{1,40}$`.
- `tier` must be `1`, `2`, or `3` (integer).
- `code` and `doc` are forward-slash-normalised paths or fnmatch globs (`*`, `?`).
- `code` and `doc` MUST be different strings (a file cannot pair with itself).

Violation of any rule causes `check_doc_drift.py validate` to exit 2 with a canonical WHY/FIX/OVERRIDE error (per `docs/rules/error-message-standard.rule.md`).

### 2.2 Tier semantics

| Tier | Behaviour | v0.16.0 status |
|---|---|---|
| 1 — strict | Drift → exit 1 → CI red → PR blocked from merge | ✅ enforced |
| 2 — soft | Drift → exit 0 + sticky-comment warning | 📋 reserved (slice 5+) |
| 3 — informational | Drift → exit 0 + telemetry event only (no PR surface) | 📋 reserved (slice 6) |

---

## 3 CI gate behaviour

### 3.1 Trigger

PR events: `opened`, `synchronize`, `reopened`, `edited`. The `edited` trigger is essential — it lets authors add `[no-doc-impact]` to the title after CI red without forcing a no-op code push.

### 3.2 Detection algorithm

1. Load `specs/co-edit-pairs.yaml`; schema-validate per §2. Exit 2 on break.
2. Compute `changed_files := git diff --name-only origin/main...HEAD` (triple-dot — changes introduced by this branch, not all of `HEAD ^ main`).
3. For each pair in the manifest:
   - `code_touched := any path in changed_files matches the `code` glob`
   - `doc_touched  := any path in changed_files matches the `doc` glob`
   - If `code_touched != doc_touched` (XOR) → record drift for this pair.
4. If any drift recorded AND PR title does NOT contain `[no-doc-impact]` (case-insensitive substring match):
   - Emit canonical block message to stderr (§4).
   - Exit 1.
5. Else: exit 0.

### 3.3 Exit codes (per `docs/rules/break-glass.rule.md` convention)

| Code | Meaning |
|---|---|
| 0 | Pass — no drift, OR drift bypassed via escape hatch |
| 1 | Drift detected (Tier 1 violation, no escape hatch) |
| 2 | Schema break — manifest malformed, missing required field, YAML parse error, git diff failure |

### 3.4 Sticky comment

On drift, CI posts/updates a single sticky comment per PR (pattern from `.github/workflows/branch-name-validator.yml`). Content mirrors the stderr block message. Updated on each re-run; never appended.

---

## 4 Canonical block message (per `docs/rules/error-message-standard.rule.md`)

```
❌ Doc-drift violation detected for N pair(s):

   • <pair-id> (tier 1)
     code: <changed code-side path(s) OR expected glob>
     doc:  <expected doc-side glob OR changed doc-side path(s)>
     reason: <reason from manifest>

   FIX: edit the doc side in the same PR, OR add `[no-doc-impact]`
        to the PR title if this change truly does not affect the doc contract.
   OVERRIDE: add `[no-doc-impact]` (case-insensitive) anywhere in PR title.

   See: docs/rules/doc-drift-enforcement.rule.md §3 (CI gate behaviour).
```

---

## 5 Escape hatch — `[no-doc-impact]`

### 5.1 Contract

- Case-insensitive substring match anywhere in the PR title.
- Honoured by the CI check; bypasses Tier 1 drift only.
- NOT honoured by Tier 2 / Tier 3 (informational tiers do not block, so no escape needed).

### 5.2 Legitimate uses

- Pure formatting / whitespace / lint cleanup on the code side.
- Comment-only edits that do not change observable behaviour.
- Removing dead code paths the spec was not documenting anyway.
- Doc-side edits that fix typos, grammar, or cross-reference paths.

### 5.3 Audit

Every CI run logs whether the escape hatch was honoured. Slice 6 (`scripts/telemetry/rule_event_logger.py`, v0.19.1) emits a `rule_event` per check fire with `escape_hatch: true|false`. The monthly report flags:

- `[no-doc-impact]` rate > 20% / month → escape-hatch abuse review.
- Specific pairs always escape-hatched → tier review (may need to be downgraded to Tier 2).

v0.16.0 does NOT ship the telemetry emit (slice 6 adds it). The schema is designed so slice 6 adds a single workflow step.

---

## 6 Adoption checklist (for the playbook itself)

1. Bump `VERSION` to v0.16.0.
2. Ship the script, manifest, spec, workflow, and tests in one PR.
3. Confirm CI green on the PR opening this slice (the slice's PR title should contain the spec itself paired with the script — both move together).
4. Document the rule in `docs/concepts/development-flow.md` §5 enforcement table.
5. Flip `docs/concepts/enforcement-status.md` row for `doc-drift-enforcement.md` to ✅.

This spec self-applies: `specs/co-edit-pairs.yaml` has a `doc-drift-enforcement` pair entry. Any future change to `scripts/check_doc_drift.py` will require an update to this file.

---

## 7 Invariants

| ID | Invariant |
|---|---|
| **INV-1** | Every Tier 1 pair MUST be co-modified or the PR MUST carry `[no-doc-impact]`. |
| **INV-2** | The manifest is append-mostly. Adding a new pair is additive (MINOR); changing the tier of an existing pair is BREAKING (MAJOR — per `docs/concepts/migration-guide.md`). |
| **INV-3** | `scripts/check_doc_drift.py` exits 0/1/2 only. Other exit codes indicate a bug. |
| **INV-4** | Escape-hatch usage is auditable from the PR title; the title is the single source. CI does not inspect commit messages, body text, or labels. |

---

## 8 Open questions (deferred)

- **Q1** Should pairs allow N-to-M (one code file mandates multiple doc files, or vice versa)? Today the schema is 1↔1. If a real need surfaces, extend to `code: [<path>...]` / `doc: [<path>...]` in v2. Deferred until a real instance.
- **Q2** Should Tier 2 (soft) ship in v0.17.x or v0.19.x (slice 5)? Today reserved; activation tied to slice 5 (doc content rewrites) which may introduce many transient pair violations.
- **Q3** Should the manifest support a `not_co_edited_with: [<path>...]` exclusion list to suppress false positives on shared infrastructure files? Deferred until a real false positive surfaces.
