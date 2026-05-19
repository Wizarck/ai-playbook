# design — `doc-drift-enforcement`

> Architecture detail behind [proposal.md](proposal.md). v0.16.0.

## 1 Manifest schema (`specs/co-edit-pairs.yaml`)

```yaml
# specs/co-edit-pairs.yaml
version: "1.0.0"             # schema version (semver); breaking changes bump major
manifest_version: "2026-05-19.1"   # data version (YYYY-MM-DD.N); monotonic per merge
pairs:
  - id: cleanup-zombies      # kebab-case slug; must match `^[a-z][a-z0-9-]{1,40}$`
    tier: 1                  # 1 = strict, 2 = soft (future), 3 = informational (future)
    code: "scripts/cleanup_zombies.py"     # glob OR exact path (fnmatch on /)
    doc: "specs/cleanup-zombies.md"        # glob OR exact path
    reason: "Cleanup script + its normative spec; both must move together."
    introduced_in: "v0.16.0"
```

### Field semantics

- `id`: kebab-case, slug-stable identifier. Used in violation messages.
- `tier`:
  - **1** — strict. v0.16.0 ships only this mode. Violation → exit 1.
  - **2** — soft (future). Violation → exit 0 + warn comment. Reserved.
  - **3** — informational (future). Violation → exit 0 + telemetry event only. Reserved.
- `code`: project-relative path; may contain `*` and `?` (fnmatch). Forward slash only.
- `doc`: same shape; typically points at `specs/`, `docs/`, or `runbooks/`.
- `reason`: human-readable; surfaced in sticky-comment violation message.
- `introduced_in`: semver tag at which the pair joined the manifest.

### Detection algorithm

1. Read `specs/co-edit-pairs.yaml`. Schema-validate; exit 2 on break.
2. Read `git diff --name-only origin/main...HEAD` (or `--diff-files` override).
3. For each pair:
   - `code_touched := any changed file matches `code` glob`
   - `doc_touched  := any changed file matches `doc` glob`
   - If `code_touched XOR doc_touched` → drift detected for this pair.
4. If any drift detected:
   - If PR title contains `[no-doc-impact]` (case-insensitive) → ALLOW; exit 0.
   - Else: emit canonical violation message; exit 1.
5. No drift → exit 0.

### Exit codes (per `specs/break-glass.md` convention)

| Code | Meaning |
|---|---|
| 0 | Pass (no drift, or escape hatch honoured) |
| 1 | Drift detected (Tier 1 violation) |
| 2 | Schema break (manifest malformed, YAML parse error, missing required field) |

### Violation message shape (per `specs/error-message-standard.md`)

```
❌ Doc-drift violation detected for N pair(s):

   • <pair-id> (tier 1)
     code: <changed code-side path(s)>
     doc:  <expected doc-side glob>
     reason: <reason from manifest>

   FIX: edit the doc side in the same PR, OR add `[no-doc-impact]`
        to the PR title if this change truly does not affect the doc contract.
   OVERRIDE: add `[no-doc-impact]` (case-insensitive) anywhere in PR title.

   See: specs/doc-drift-enforcement.md §3 (escape-hatch policy).
```

## 2 CI workflow design (`.github/workflows/doc-drift-check.yml`)

### Triggers

`pull_request: [opened, synchronize, reopened, edited]`. The `edited` trigger
is critical so changes to the PR title (to add the escape hatch) re-run the
check without requiring a synchronize event.

### Steps

1. `actions/checkout@v4` with `fetch-depth: 0` (need full history for
   `git diff origin/main...HEAD`).
2. Set up Python 3.12 (matches `pyproject.toml`).
3. `python scripts/check_doc_drift.py --pr-title "${{ github.event.pull_request.title }}"`.
4. On non-zero exit: post sticky comment via `marocchino/sticky-pull-request-comment@v2`.
   Sticky-comment pattern matches `branch-name-validator.yml` precedent: one
   comment per PR, updated on each re-run rather than appended.
5. Fail the check step (CI red).

### Why sticky comment

Per `specs/error-message-standard.md`: feedback must be human-actionable +
visible. PR-level checks alone do not show the message; the sticky comment
surfaces the violation pairs + the suggested fix without spamming the
conversation on each push.

## 3 Interaction with future telemetry (slice 6)

When slice 6 ships `scripts/telemetry/rule_event_logger.py`, the workflow
extension adds a `rule_event_logger` invocation on EVERY check run:

```yaml
- name: Log doc-drift event
  if: always()
  run: |
    python .ai-playbook/scripts/telemetry/rule_event_logger.py emit \
      --slug doc-drift-enforcement \
      --verdict ${{ steps.check.outcome == 'success' && 'allow' || 'block' }} \
      --escape-hatch ${{ contains(github.event.pull_request.title, '[no-doc-impact]') }}
```

This lets the monthly report flag patterns:
- `[no-doc-impact]` rate > 20% / month → escape-hatch abuse review.
- Specific pairs flapping (touched-without-pair > 10x / month) → tier review
  (may need to be downgraded to Tier 2 or split into finer pairs).

v0.16.0 does NOT ship the telemetry emit — slice 6 adds it. The schema +
workflow are designed to make the slice 6 addition a one-line change.

## 4 Edge cases

| Case | Behaviour |
|---|---|
| Empty diff (no files changed) | Exit 0 (no drift possible). |
| File matches multiple pairs | Each pair evaluated independently. |
| Single file is BOTH `code` and `doc` of different pairs | Each pair evaluated independently; both must be respected. |
| YAML parse error in manifest | Exit 2 with schema-break message. |
| Missing `code:` or `doc:` field on a pair | Exit 2 with schema-break message. |
| Glob matches no file in the repo (stale pair) | Pair is dormant; never fires. `T9` could warn-detect this but not in v0.16.0. |
| Git diff fails (no `origin/main` ref) | Exit 2 with environment-misconfiguration message. |

## 5 Why a separate script, not a pre-commit hook

Pre-commit hooks run on the developer's machine before commit. They cannot
know the PR title (which only exists at PR-open time). The escape hatch lives
on the PR title surface (D2.3), so the check necessarily runs at CI time.

A future enhancement: a pre-commit warning that pairs are out of sync, with
the same logic but no escape hatch. Deferred.

## 6 Why YAML for the manifest

- Consistent with `specs/zombies-manifest.yaml` precedent.
- Trivially extensible (new tier fields, future per-pair break-glass rules).
- Human-readable in PRs (diff review).
- Existing `scripts/schema_validate.py` patterns can be extended in slice 4 to
  cover this manifest if formal JSON Schema validation is needed.

## 7 Why not auto-derive pairs from a naming convention

A naming convention (e.g. `scripts/X.py` ↔ `specs/X.md` by stem) would
auto-derive most pairs but:
- Several pairs have non-matching stems (e.g. `_break_glass.py` ↔ `break-glass.md`).
- Some scripts have no doc pair (utility libraries).
- Some docs have no script pair (pure reference, like `taxonomy.md`).
- Future tier-2/3 pairs may include directory↔directory or pattern↔pattern
  relationships that no stem convention can express.

Hand-curated manifest is correct. Slice 4 (filesystem reorg per the v9 reset
plan) may revisit this once the slug-pairing convention lands for rules.
