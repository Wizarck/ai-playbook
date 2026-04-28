---
deferred_work_file: '{implementation_artifacts}/deferred-work.md'
---

# Step 4: Present and Act

## RULES

- YOU MUST ALWAYS SPEAK OUTPUT in your Agent communication style with the config `{communication_language}`
- When `{spec_file}` is set, always write findings to the story file before offering action choices.
- `decision-needed` findings must be resolved before handling `patch` findings.

## INSTRUCTIONS

### 1. Clean review shortcut

If zero findings remain after triage (all dismissed or none raised): state that and proceed to section 6 (Sprint Status Update).

### 2. Write findings to the story file

If `{spec_file}` exists and contains a Tasks/Subtasks section, append a `### Review Findings` subsection. Write all findings in this order:

1. **`decision-needed`** findings (unchecked):
   `- [ ] [Review][Decision] <Title> — <Detail>`

2. **`patch`** findings (unchecked):
   `- [ ] [Review][Patch] <Title> [<file>:<line>]`

3. **`defer`** findings (checked off, marked deferred):
   `- [x] [Review][Defer] <Title> [<file>:<line>] — deferred, pre-existing`

Also append each `defer` finding to `{deferred_work_file}` under a heading `## Deferred from: code review ({date})`. If `{spec_file}` is set, include its basename in the heading (e.g., `code review of story-3.3 (2026-03-18)`). One bullet per finding with description.

### 3. Present summary

Announce what was written:

> **Code review complete.** <D> `decision-needed`, <P> `patch`, <W> `defer`, <R> dismissed as noise.

If `{spec_file}` is set, add: `Findings written to the review findings section in {spec_file}.`
Otherwise add: `Findings are listed above. No story file was provided, so nothing was persisted.`

### 4. Resolve decision-needed findings

If `decision_needed` findings exist, present each one with its detail and the options available. The user must decide — the correct fix is ambiguous without their input. Walk through each finding (or batch related ones) and get the user's call. Once resolved, each becomes a `patch`, `defer`, or is dismissed.

If the user chooses to defer, ask: Quick one-line reason for deferring this item? (helps future reviews): — then append that reason to both the story file bullet and the `{deferred_work_file}` entry.

**HALT** — I am waiting for your numbered choice. Reply with only the number (or "0" for batch). Do not proceed until you select an option.

### 5. Handle `patch` findings

If `patch` findings exist (including any resolved from step 4), HALT. Ask the user:

If `{spec_file}` is set, present all three options (if >3 `patch` findings exist, also show option 0):

> **How would you like to handle the <Z> `patch` findings?**
> 0. **Batch-apply all** — automatically fix every non-controversial patch (recommended when there are many)
> 1. **Fix them automatically** — I will apply fixes now
> 2. **Leave as action items** — they are already in the story file
> 3. **Walk through each** — let me show details before deciding

If `{spec_file}` is **not** set, present only options 1 and 3 (omit option 2 — findings were not written to a file). If >3 `patch` findings exist, also show option 0:

> **How would you like to handle the <Z> `patch` findings?**
> 0. **Batch-apply all** — automatically fix every non-controversial patch (recommended when there are many)
> 1. **Fix them automatically** — I will apply fixes now
> 2. **Walk through each** — let me show details before deciding

**HALT** — I am waiting for your numbered choice. Reply with only the number (or "0" for batch). Do not proceed until you select an option.

- **Option 0** (only when >3 findings): Apply all non-controversial patches without per-finding confirmation. Skip any finding that requires judgment. Present a summary of changes made and any skipped findings.
- **Option 1**: Apply each fix. After all patches are applied, present a summary of changes made. If `{spec_file}` is set, check off the items in the story file.
- **Option 2** (only when `{spec_file}` is set): Done — findings are already written to the story.
- **Walk through each**: Present each finding with full detail, diff context, and suggested fix. After walkthrough, re-offer the applicable options above.

  **HALT** — I am waiting for your numbered choice. Reply with only the number (or "0" for batch). Do not proceed until you select an option.

**Code review actions complete** (interim — canonical verdict is emitted in section 6a)

- Decision-needed resolved: <D>
- Patches handled: <P>
- Deferred: <W>
- Dismissed: <R>

### 6. Emit canonical review verdict, update story status, and sync sprint tracking

#### 6a. Emit the canonical QA verdict (always — even if `{spec_file}` is not set)

Code review is a QA-style artefact and MUST end with one of the canonical verdict literals from [verdict-contract.md](../../../specs/verdict-contract.md) §1. The literals (exact emoji, capitalisation, and spacing — checked by `scripts/verdict_lint.py`):

| Verdict | When to emit |
|---|---|
| `✅ APPROVED` | Zero blocking findings remain after triage (all `decision-needed` resolved; all `patch` either fixed or accepted as deferred; no unresolved HIGH/MEDIUM issues). |
| `⚠️ ISSUES FOUND (iter N)` | Findings present that are not yet resolved (left as action items, or `patch` items the user chose not to fix this pass). For per-finding severity (S1–S4), see [verdict-contract.md](../../../specs/verdict-contract.md) §2. |
| `❓ CLARIFICATION NEEDED` | A `decision-needed` finding cannot be resolved because the spec or the rule is ambiguous and the user could not disambiguate. Halts the track until a human edits the spec. |
| `⛔ ARCHITECTURE QUESTIONED` | Use ONLY when iter ≥ 2 and the same class of failure has recurred across iterations because the structural design (not the spec) is wrong. See [verdict-contract.md](../../../specs/verdict-contract.md) §4.1. Do not emit on iter 1. |

**Iteration counter `N`**: tracked per `{spec_file}`. On the first review pass for a story, `N = 1`. On a re-review (option 2 from section 7 — "Re-run code review"), increment `N`. If `{spec_file}` is not set, treat each invocation as iter 1. Per the max-2-rework rule ([verdict-contract.md](../../../specs/verdict-contract.md) §3), iter 3 is not attempted; on a third recurrence of the same finding, escalate to `❓` or `⛔` instead.

Print the verdict line as the LAST line of the review summary message (a single literal on its own line).

#### 6b. Update story status and sync sprint tracking

Skip this section if `{spec_file}` is not set.

##### Determine new story status based on the verdict

The story-file `Status` field tracks sprint lifecycle (NOT a QA verdict):

- Verdict `✅ APPROVED` → `{new_status}` = `done`. Update the story file Status section to `done`.
- Verdict `⚠️ ISSUES FOUND (iter N)` → `{new_status}` = `in-progress`. Update the story file Status section to `in-progress`.
- Verdict `❓ CLARIFICATION NEEDED` → `{new_status}` = `blocked-by-spec` (per [verdict-contract.md](../../../specs/verdict-contract.md) §4 and the runbook lifecycle).
- Verdict `⛔ ARCHITECTURE QUESTIONED` → `{new_status}` = `blocked-by-architecture`.

Save the story file.

#### Sync sprint-status.yaml

If `{story_key}` is not set, skip this subsection and note that sprint status was not synced because no story key was available.

If `{sprint_status}` file exists:

1. Load the FULL `{sprint_status}` file.
2. Find the `development_status` entry matching `{story_key}`.
3. If found: update `development_status[{story_key}]` to `{new_status}`. Update `last_updated` to current date. Save the file, preserving ALL comments and structure including STATUS DEFINITIONS.
4. If `{story_key}` not found in sprint status: warn the user that the story file was updated but sprint-status sync failed.

If `{sprint_status}` file does not exist, note that story status was updated in the story file only.

#### Completion summary

> **Review Complete!**
>
> **Story Status:** `{new_status}`
> **Issues Fixed:** <fixed_count>
> **Action Items Created:** <action_count>
> **Deferred:** <W>
> **Dismissed:** <R>
>
> <verdict literal — exactly one of `✅ APPROVED`, `⚠️ ISSUES FOUND (iter N)`, `❓ CLARIFICATION NEEDED`, `⛔ ARCHITECTURE QUESTIONED` per [verdict-contract.md](../../../specs/verdict-contract.md) §1; this MUST be the last line of the artefact>

### 7. Next steps

Present the user with follow-up options:

> **What would you like to do next?**
> 1. **Start the next story** — run `dev-story` to pick up the next `ready-for-dev` story
> 2. **Re-run code review** — address findings and review again
> 3. **Done** — end the workflow

**HALT** — I am waiting for your choice. Do not proceed until the user selects an option.
