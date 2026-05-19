# runbook: coderabbit-fallback.md — Profile B self-review when CodeRabbit is unavailable

> **Audience**: the worker AI (Claude / Gemini / Antigravity / future session). Not for humans (humans review at Gate F via the GH UI; this runbook is for the AI that authored the PR).
> **Status**: v1.0.0 (introduced in ai-playbook v0.9.0).
> **Trigger**: `scripts/check_coderabbit_status.py` returned exit 1 (status `rate-limited` or `silent`) after PR push.
> **Spec**: codified in [`specs/release-management.md`](../specs/release-management.md) §4.5.

## What this runbook does

Codifies the **Profile B (self-review) fallback** the worker AI MUST execute when CodeRabbit cannot review a PR. The runbook turns "do the review yourself" from a vague instruction into a structured walk-through that produces:

1. A populated **§4.5 AI-reviewer signoff** section in the PR body (the audit trail).
2. (Optional) Additional fix commits on the slice branch addressing real findings.
3. A re-verified set of CI checks after fixes land.

The runbook is invoked **in the same session** that pushed the PR — the worker AI has full context, the diff is in cache, the design intent is fresh. This is the L1 layer of the v0.9.0 3-layer defense; L2 (the GH Action checklist) is the safety net for when L1 doesn't run.

## Pre-conditions

- The worker AI has just pushed (or updated) a PR.
- `scripts/check_coderabbit_status.py --pr <N> --repo <R> --wait 300` returned exit 1 with status `rate-limited` or `silent` (and a JSON payload on stdout).
- The PR's CI checks (Lint / Type / Test / Pre-commit / Secrets / boundary checks) are passing — Profile B is a **supplement** to L0 mechanical checks, not a replacement. If CI is red, fix that first.

## The walk-through

### 1. Capture the evidence

Read the JSON returned by `check_coderabbit_status.py`. Note three fields you'll cite in §4.5:

- `status` — verbatim (`rate-limited` or `silent`).
- `since_open_seconds` — how long the PR has been open without a CodeRabbit review.
- `last_comment_excerpt` — the first 200 chars of CodeRabbit's most recent comment (the rate-limit notice, or null if `silent`).

These are the audit-trail breadcrumbs; the human reviewer uses them to confirm CodeRabbit really wasn't an option.

### 2. Inspect the diff by category

Run `gh pr diff <N> --repo <R>` and walk the diff with the following category lenses. **For each category**, write a one-line note in your scratch (mental or on a temporary file): "checked, no findings" or "found X — fixed in commit Y" or "found X — cannot fix in this PR, filed as gotcha #N".

Don't skip categories you think don't apply; mark them "n/a" instead of silently omitting. The §4.5 audit trail must show every category was considered.

#### 2.1 Type safety + correctness

- New `mypy --strict` errors masked with `# type: ignore`? Each one needs justification.
- `Any` slipped in where a concrete type was possible?
- Generic types narrowed unsafely (e.g. literal narrowing across method calls — consumer-side `docs/gotchas.md` #15 is the canonical case, e.g. in `consumer-e`)?
- New public symbols missing type annotations?
- Frozen dataclasses with wide-input/narrow-storage semantics — handled correctly via `init=False` + custom `__init__`? (See gotcha #18.)

#### 2.2 Async + concurrency

- New async functions: are exceptions handled or documented as "must propagate"?
- New `asyncio.create_task` without explicit cancellation handling on shutdown?
- New shared mutable state across tasks without `asyncio.Lock` / `ContextVar` / immutability?
- New worker tasks: do handler exceptions kill the worker silently? (See `MessageBus._worker` in slice 2 — documented behavior, not a bug, but worth flagging at every new worker.)
- Long-lived `await` without timeout on external IO?

#### 2.3 Error handling

- New error paths: do they include a remediation hint in the message?
- New raise sites of plain `Exception` / `RuntimeError` / `ValueError` — could they use a domain-specific class from `shared.errors`?
- `except Exception` clauses too broad? (Each one needs a justification — usually only acceptable in shutdown / cleanup paths.)
- Uncaught exceptions that would surface as 500 in the API layer — should they be 4xx (`ValidationError` / `NotFoundError` / etc.) instead?

#### 2.4 Security

- New input validation on caller-supplied data (HTTP request bodies, CLI flags, file paths, env vars)?
- New regex patterns: anchored? backtracking-safe?
- New file-system operations: paths traversed safely (no `../` injection)?
- New SQL: parameterised? (slice 3+ context — for slice 2 there's no DB yet.)
- New secret-handling paths: no logging of tokens / passwords / cookies?
- New deps in `pyproject.toml` / `package.json`: known CVEs? supply-chain risk?

#### 2.5 Edge cases

- Empty collections (zero-length lists, empty strings, `None` defaults) — handled?
- Maximum-size inputs (long strings, huge dicts) — performance acceptable?
- Concurrent access patterns — race conditions visible?
- Time / timezone edge cases (DST, leap seconds, microsecond precision) — handled by `shared.time`? (If new datetime code exists outside `shared.time`, it should funnel through `now()` / `parse_iso8601` / `format_iso8601`.)
- Numeric edge cases: zero divisors, overflow, precision loss (`Decimal` vs `float`).

#### 2.6 Public API + docs

- New public symbols (functions, classes, constants) listed in module `__all__`?
- New public symbols have docstrings explaining intent + edge cases?
- Public API additions semver-locked? (Anything in `shared/` is locked from slice 2 onwards — extending requires a new openspec change, not a refactor.)
- Test coverage ≥80% per NFR-M1? Coverage tool output should be in the PR body.

#### 2.7 Spec / runbook compliance

- Boundary check (e.g. `apps/api/scripts/check_shared_boundary.py`) passes? It's wired into pre-commit but worth a manual scan if the PR touches `shared/`.
- New scripts follow the canonical layout (module docstring with CLI / Behavior / Exit codes; UTF-8 stdio; `_emit()` telemetry)?
- New tests under the right path (`tests/property/` for Hypothesis, `tests/unit/<area>/` for module-level unit tests, `tests/integration/` for E2E)?
- Conventional commit messages on every commit in the branch?

### 3. Apply fixes (if any findings are real bugs)

If a category surfaced a **real bug** (not a style gripe, not a "could be cleaner"): fix it now. Add a follow-up commit on the slice branch with a `fix(<area>):` conventional-commit subject. Run the full check suite again locally:

```
mypy --strict <new-files>
pytest tests/ -W error
ruff check <new-files>
black --check <new-files>
pre-commit run --from-ref origin/main --to-ref HEAD
```

All green → push the fix commit. Do NOT silently amend prior commits — the audit trail wants the fix to be visible as its own commit.

If a finding is real but **out of scope for this PR** (e.g. requires changes in another bounded context): file a `docs/gotchas.md` entry citing the PR + finding number, and mention it in §4.5 under "deferred follow-ups". Do NOT block the merge for it.

### 4. Populate §4.5 in the PR body

Edit the PR body (via `gh pr edit <N> --body-file <path>`) so the **AI-reviewer signoff** section reads as follows. **Every field is mandatory** — L2's regex check looks for the structure.

```markdown
## AI-reviewer signoff (per release-management.md §4.5)

**Profile**: A (active on this repo) | B (private + GH Free, no CodeRabbit)

**Reviewer**: CodeRabbit — **rate-limited** at PR open. <one-sentence reason: "Wizarck account exceeded the per-hour commit-review quota during the multi-bump series at HH:MM Z" or "PR sat for N minutes with no CodeRabbit response">. Per §4.5 the rate-limit is **NOT exoneration**; the worker AI applied the **Profile B (self-review) fallback** with the audit trail recorded here.

**Self-review findings** (this branch):

1. **<category>** — <finding>. Fixed in commit `<sha>`. <or>: Documented as `docs/gotchas.md` #<N> for follow-up; not blocking.
2. ...

**Other items reviewed, no change needed**:
- <category>: <one-line "checked, n/a / passed">
- ...

**Re-verification after the fix commits**: <list checks: mypy / pytest / ruff / black / pre-commit / coverage>. All green. <N> tests pass.

**CodeRabbit re-review**: when the rate-limit lifts, CodeRabbit may add findings beyond this self-review. Any further commits in this PR will be treated as a new review cycle.
```

L2's regex looks for these markers (case-sensitive):
- `Profile: A` or `Profile: B`
- `Reviewer:` (anything follows)
- `Self-review findings:`

If all three are present and non-stub, L2 marks `ai-self-review-required` ✅ and skips posting its checklist. If any marker is missing or stubbed (`<finding>` literal), L2 posts the checklist as a comment.

### 5. Re-run `check_coderabbit_status.py` (optional, recommended)

After 30+ minutes, the rate-limit window may have lifted. Re-run the script — if the status is now `available`, CodeRabbit may have posted a real review. Treat that as a **new review cycle**: read the comments, address findings (in additional commits), update §4.5 with a new "CodeRabbit follow-up" subsection.

This is rare in practice (rate-limits last 1-3 hours; humans usually want to merge before that) but documented for completeness.

### 6. Declare PR ready for Gate F

Only after §4.5 is fully populated and re-verification is green:

- Comment on the PR (or in the chat session): "PR ready for Gate F. CodeRabbit was <rate-limited|silent>; Profile B self-review applied per §4.5."
- The human reviewer (Arturo) takes over from here.

## Examples

### Reference run — `consumer-e` PR #41 (slice 2 `shared-primitives`)

The 2026-05-01 manual self-review on PR #41 is the **canonical reference run** for this runbook. v0.9.0 codified the structure, but the content of #41's §4.5 is what L1 should produce. Two findings:

1. Real bug — `HeartbeatMixin` used `@abstractmethod` without inheriting `abc.ABC`; runtime did not enforce overrides. Fixed in a follow-up commit; new test added; verified with mypy + pytest.
2. Documentation gap — `MessageBus._worker` swallows handler exceptions silently (kills the worker task). Acceptable behavior given slice 2 has no logging wired (slice O1 lands `structlog`); documented in the class docstring with a `.. caution::` admonition.

Six other categories reviewed without findings, each noted as "n/a / passed". Re-verification: 129 tests pass, mypy --strict clean, all pre-commit hooks green.

The PR was merged at Gate F after Arturo reviewed the §4.5 audit trail.

### Reference run — bump PR (mechanical change)

Bump PRs (submodule SHA + AGENTS.md version) are mechanical: no logic changes, no test surface, no security exposure. The §4.5 self-review is correspondingly short:

```markdown
**Profile**: A.
**Reviewer**: CodeRabbit — rate-limited at PR open (<reason>).
**Self-review findings**: none. The diff is a single submodule SHA bump from `<old>` to `<new>` (and an AGENTS.md version+date refresh). No logic changes, no new public symbols, no security exposure. CI green. Approved for Gate F.
```

The audit trail still matters — it confirms the worker AI looked at the diff, even though the diff was trivial.

## Anti-patterns (do not do these)

- **"CodeRabbit will eventually review it" → merge anyway**. The whole point of §4.5 is that the audit trail must be present at Gate F regardless of CodeRabbit's later behavior. If you merge before §4.5 is populated, the human reviewer can't tell whether the AI reviewed at all.
- **Stub §4.5 with `Self-review findings: TODO`**. L2's regex catches this and re-posts the checklist; the §4.5 contract is unmet. Either fill it in or admit you didn't review (then don't claim Gate F readiness).
- **Use § 4.5 as a place to brag** ("everything is perfect, no findings"). The runbook explicitly asks for "Other items reviewed, no change needed" notes per category — empty PR bodies suggest the AI didn't actually look.
- **Skip re-verification after fix commits**. If you fixed a real bug, run the full check suite again. mypy / pytest may surface new issues in the fix.
- **Treat L1 (this runbook) as optional when L2 fires later**. L2 is the safety net for AI sessions that ended; if your session is active, L1 is mandatory and L2's checklist is redundant.

## Cross-references

- [`scripts/check_coderabbit_status.py`](../scripts/check_coderabbit_status.py) — the detection script that triggers this runbook.
- [`scripts/post_self_review_checklist.py`](../scripts/post_self_review_checklist.py) — the L2 fallback that posts a checklist when L1 didn't run.
- [`templates/new-project/.github/workflows/coderabbit-fallback.yml.tmpl`](../templates/new-project/.github/workflows/coderabbit-fallback.yml.tmpl) — the L2 workflow template.
- [`specs/release-management.md`](../specs/release-management.md) §4.5 — the contract this runbook satisfies.
- [`specs/v0.9.0-roadmap.md`](../specs/v0.9.0-roadmap.md) — the design rationale for the 3-layer defense.
- `consumer-e` PR #41 — the canonical reference run.
