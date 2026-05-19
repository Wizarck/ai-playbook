---
schema: runbook/v1
slug: coderabbit-fallback
description: Execute the Profile B self-review fallback when CodeRabbit cannot review a PR, producing a populated §4.5 audit trail in the PR body.
audience: reviewer
estimated_time: 20-45 min
last_validated: "2026-05-19"
---

# Apply the Profile B self-review fallback

## Outcome

The PR body contains a populated `## AI-reviewer signoff` section (per release-management §4.5) covering every review category. If real findings surfaced, follow-up `fix(...)` commits are pushed on the same branch and CI is re-verified green. The L2 GitHub Action checklist stays silent because L1 ran first.

## When to use this

The worker AI (Claude / Gemini / Antigravity / future session — not a human) runs this immediately after pushing a PR when `scripts/check_coderabbit_status.py --pr <N> --repo <R> --wait 300` returns exit 1 with status `rate-limited` or `silent`. CodeRabbit could not review; the worker AI is the most cache-warm reviewer available.

Skip when:

- Exit code is 0 (CodeRabbit reviewed — read its comments instead).
- CI is currently red — fix CI first, then re-run the status check.
- The PR has already been merged.

## Prerequisites

- The worker AI just pushed or updated the PR.
- `scripts/check_coderabbit_status.py` returned exit 1 with a JSON payload on stdout. Capture the JSON.
- CI checks (Lint / Type / Test / Pre-commit / Secrets / boundary) are passing. Verify: `gh pr checks <N> --repo <R>`.

## Steps

1. **Capture the evidence from the status JSON.**
   Note three fields the §4.5 section will cite:
   - `status` — verbatim (`rate-limited` or `silent`).
   - `since_open_seconds` — how long the PR has been open without a review.
   - `last_comment_excerpt` — first 200 chars of CodeRabbit's most recent comment, or null when silent.

2. **Read the diff by category.**
   ```bash
   gh pr diff <N> --repo <R>
   ```
   For each of the 7 categories below, write a one-line note: "checked, no findings", "found X, fixed in commit Y", or "found X, filed as gotcha #N". Categories must NOT be skipped — mark `n/a` instead. The audit trail records that every category was considered.

   **2.1 Type safety + correctness**: new `mypy --strict` errors masked with `# type: ignore`; `Any` slipped in where concrete types were possible; generic types narrowed unsafely; new public symbols missing annotations; frozen dataclasses with wide-input/narrow-storage semantics.

   **2.2 Async + concurrency**: new async functions without exception handling or "must propagate" docs; `asyncio.create_task` without shutdown handling; shared mutable state across tasks without `asyncio.Lock` / `ContextVar` / immutability; worker tasks that silently kill on handler exceptions; long-lived `await` without timeout.

   **2.3 Error handling**: error paths missing remediation hints; new raises of plain `Exception` / `RuntimeError` / `ValueError` that should use domain classes; `except Exception` too broad; uncaught exceptions that would surface as 500 when 4xx is correct.

   **2.4 Security**: missing input validation on caller-supplied data; new regex without anchors / backtracking guards; file-system operations without path-traversal defence; SQL parameterisation; secret logging; new dependencies with known CVEs.

   **2.5 Edge cases**: empty collections; maximum-size inputs; concurrent access races; time / timezone (DST, leap seconds, microsecond precision); numeric edge cases (zero divisor, overflow, `Decimal` vs `float`).

   **2.6 Public API + docs**: new public symbols in module `__all__`; docstrings explaining intent + edge cases; semver-locked public API; test coverage ≥80% per NFR-M1.

   **2.7 Spec / runbook compliance**: boundary check passes; new scripts follow canonical layout (CLI docstring, UTF-8 stdio, telemetry); tests under the right path; conventional commit messages on every commit.

3. **Apply fixes for real bugs.**
   For findings that are real bugs (not style), add a `fix(<area>):` follow-up commit on the slice branch. Re-run the full check suite locally:
   ```bash
   mypy --strict <new-files>
   pytest tests/ -W error
   ruff check <new-files>
   black --check <new-files>
   pre-commit run --from-ref origin/main --to-ref HEAD
   ```
   All green → push. Do NOT amend prior commits silently — the audit trail wants the fix visible as its own commit.

   For findings that are real but out-of-scope: add to `docs/gotchas.md` citing PR + finding number, and mention under "deferred follow-ups" in §4.5. Do NOT block the merge.

4. **Populate §4.5 in the PR body.**
   ```bash
   gh pr edit <N> --body-file pr-body.md   # edit the body file with §4.5 below
   ```
   Required structure (regex-checked by L2):
   ```markdown
   ## AI-reviewer signoff (per release-management.md §4.5)

   **Profile**: A (CodeRabbit-enabled) | B (private + GH Free, no CodeRabbit)

   **Reviewer**: CodeRabbit — **rate-limited|silent** at PR open. <one-sentence reason>. Per §4.5 the rate-limit is NOT exoneration; the worker AI applied the Profile B (self-review) fallback with the audit trail recorded here.

   **Self-review findings** (this branch):
   1. **<category>** — <finding>. Fixed in commit `<sha>`. <or>: Documented as `docs/gotchas.md` #<N> for follow-up; not blocking.
   2. ...

   **Other items reviewed, no change needed**:
   - <category>: <one-line "checked, n/a / passed">

   **Re-verification after fix commits**: <list checks: mypy / pytest / ruff / black / pre-commit / coverage>. All green. <N> tests pass.

   **CodeRabbit re-review**: when the rate-limit lifts, CodeRabbit may add findings beyond this self-review. Further commits in this PR will be treated as a new review cycle.
   ```
   L2 regex looks for `Profile: A` or `Profile: B`, `Reviewer:`, and `Self-review findings:` (case-sensitive). All three must be present and non-stub. If any is missing or contains literal `<finding>` placeholders, L2 posts the checklist as a comment.

5. **Re-run the CodeRabbit status check (optional).**
   ```bash
   python -m scripts.check_coderabbit_status --pr <N> --repo <R> --wait 0
   ```
   After 30+ minutes the rate-limit window may have lifted. If status is now `available` and CodeRabbit posted a review, treat it as a new review cycle: read the comments, add commits if needed, update §4.5 with a new "CodeRabbit follow-up" subsection.

6. **Declare PR ready for Gate F.**
   Comment on the PR: `PR ready for Gate F. CodeRabbit was <rate-limited|silent>; Profile B self-review applied per §4.5.` The human reviewer takes over from here.

## Verification

- `gh pr view <N> --repo <R> --json body --jq .body | grep -E "^(Profile|Reviewer|Self-review findings):"` returns the three required markers.
- The L2 workflow (`coderabbit-fallback.yml`) on the consumer fires after 5 minutes and observes a populated §4.5 — it stays silent (no checklist comment posted).
- If fix commits were pushed, `gh pr checks <N> --repo <R>` returns all green again.

## Troubleshooting

### Symptom: L2 posts its checklist anyway after §4.5 was populated
**Cause**: regex mismatch — `<finding>` placeholders remain, or one of the three required markers (`Profile`, `Reviewer`, `Self-review findings`) is misspelled.
**Fix**: re-read `gh pr view <N> --repo <R> --json body --jq .body`, audit the three markers character-by-character, re-edit the body. The L2 regex is case-sensitive.

### Symptom: bump PR audit trail feels disproportionate to a 1-line diff
**Cause**: bump PRs (submodule SHA + AGENTS.md version refresh) are mechanical; the self-review is correspondingly short.
**Fix**: use the abbreviated form: `Self-review findings: none. The diff is a single submodule SHA bump from <old> to <new>. No logic changes, no new public symbols, no security exposure. CI green. Approved for Gate F.`

### Symptom: a finding was real but the worker AI cannot fix it in this PR
**Cause**: cross-boundary-context change required; this PR has the wrong scope.
**Fix**: file the finding as a `docs/gotchas.md` entry referencing the PR + finding number. Add it to §4.5 under "deferred follow-ups". Do NOT block the merge — the gotcha is the follow-up handle.

### Symptom: §4.5 is silent on a category (no row at all)
**Cause**: the worker AI thought the category did not apply and omitted it.
**Fix**: every category gets a row. If the category is genuinely irrelevant (no async code in a docs-only PR), the row says "Async + concurrency: n/a — docs-only PR." Empty PR bodies suggest the AI did not look.

## Related

- [Runbook: release](release.md) — release flow that triggers per-consumer bump PRs needing this fallback.
- [Runbook: propagate-bump-troubleshooting](propagate-bump-troubleshooting.md) — when the propagate workflow fails.
- [Concept: release-management](../concepts/release-management.md) — §4.5 contract this runbook satisfies.
- [Rule: verdict-contract](../rules/verdict-contract.rule.md) — Gate F verdict format expected after §4.5 is populated.
