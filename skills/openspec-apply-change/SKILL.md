---
name: openspec-apply-change
description: Implement tasks from an OpenSpec change. Use when the user wants to start implementing, continue implementation, or work through tasks.
license: MIT
compatibility: Requires openspec CLI.
metadata:
  author: openspec
  version: "1.0"
  generatedBy: "1.3.0"
---

Implement tasks from an OpenSpec change.

**Input**: Optionally specify a change name. If omitted, check if it can be inferred from conversation context. If vague or ambiguous you MUST prompt for available changes.

**Steps**

1. **Select the change**

   If a name is provided, use it. Otherwise:
   - Infer from conversation context if the user mentioned a change
   - Auto-select if only one active change exists
   - If ambiguous, run `openspec list --json` to get available changes and use the **AskUserQuestion tool** to let the user select

   Always announce: "Using change: <name>" and how to override (e.g., `/opsx:apply <other>`).

2. **Check status to understand the schema**
   ```bash
   openspec status --change "<name>" --json
   ```
   Parse the JSON to understand:
   - `schemaName`: The workflow being used (e.g., "spec-driven")
   - Which artifact contains the tasks (typically "tasks" for spec-driven, check status for others)

3. **Get apply instructions**

   ```bash
   openspec instructions apply --change "<name>" --json
   ```

   This returns:
   - Context file paths (varies by schema - could be proposal/specs/design/tasks or spec/tests/implementation/docs)
   - Progress (total, complete, remaining)
   - Task list with status
   - Dynamic instruction based on current state

   **Handle states:**
   - If `state: "blocked"` (missing artifacts): show message, suggest using openspec-continue-change
   - If `state: "all_done"`: congratulate, suggest archive
   - Otherwise: proceed to implementation

4. **Read context files**

   Read the files listed in `contextFiles` from the apply instructions output.
   The files depend on the schema being used:
   - **spec-driven**: proposal, specs, design, tasks
   - Other schemas: follow the contextFiles from CLI output

4b. **Preflight re-grep cited identifiers (added v0.11.0)**

   Per [release-management.md](../../specs/release-management.md) §6.5 (pre-flight rebase) the worktree base is fresh, but `proposal.md` may have been written days earlier. Identifiers cited in the proposal (class names, function names, file paths, migration slot numbers, fact-kind enum values, ADR numbers) may have **changed on `main` since the proposal landed**. Apply silently against stale citations produces silent divergence.

   Before starting implementation, re-grep every identifier the proposal/design/tasks cites:

   1. Walk `proposal.md` + `design.md` + `tasks.md` and extract:
      - Quoted file paths (`apps/api/src/.../foo.py`).
      - Backticked class / function names (`` `IBClient` ``, `` `place_order` ``).
      - Migration slot numbers (`0007_*`, `0010_*`).
      - ADR numbers (`ADR-021`).
      - Enum values mentioned in citations.
   2. For each, run `git grep -n "<identifier>"` (or `Grep` tool) on `main`.
   3. **If any cited identifier returns 0 hits**, surface as a divergence warning:

      ```
      ⚠ Citation drift detected
      proposal.md cites `FactKindEnum.MOMENTUM_SCORE` but no occurrence found on main.
      Likely renamed or removed in a parallel slice merged after this proposal landed.

      Options:
      1. Re-read the current main code to find the new name; update tasks.md citations.
      2. Re-open Gate D for design refresh (recommended for ≥3 drifted citations).
      3. Override with --skip-preflight-grep (logs deviation in retro carry-forward).
      ```

   4. **If 1-2 identifiers drifted**, show the diff and let the user decide (small drift is normal across week-old proposals).
   5. **If ≥3 identifiers drifted OR a critical surface (migration slot, FK, public API) drifted**, refuse to proceed without explicit `--skip-preflight-grep` flag.

   This catches the failure mode surfaced 2026-05-06 in iguanatrader (proposals written before parallel slices renamed cited classes) — without preflight grep, the worker AI would silently apply against drifted state and either fail at typecheck (best case) or ship broken code (worst case).

5. **Show current progress**

   Display:
   - Schema being used
   - Progress: "N/M tasks complete"
   - Remaining tasks overview
   - Dynamic instruction from CLI

6. **Implement tasks (loop until done or blocked)**

   For each pending task:
   - Show which task is being worked on
   - Make the code changes required
   - Keep changes minimal and focused
   - Mark task complete in the tasks file: `- [ ]` → `- [x]`
   - Continue to next task

   **Pause if:**
   - Task is unclear → ask for clarification
   - Implementation reveals a design issue → suggest updating artifacts
   - Error or blocker encountered → report and wait for guidance
   - User interrupts

7. **On completion or pause, show status**

   Display:
   - Tasks completed this session
   - Overall progress: "N/M tasks complete"
   - If all done: suggest archive
   - If paused: explain why and wait for guidance

**Output During Implementation**

```
## Implementing: <change-name> (schema: <schema-name>)

Working on task 3/7: <task description>
[...implementation happening...]
✓ Task complete

Working on task 4/7: <task description>
[...implementation happening...]
✓ Task complete
```

**Output On Completion**

```
## Implementation Complete

**Change:** <change-name>
**Schema:** <schema-name>
**Progress:** 7/7 tasks complete ✓

### Completed This Session
- [x] Task 1
- [x] Task 2
...

All tasks complete! Ready to archive this change.
```

**Output On Pause (Issue Encountered)**

```
## Implementation Paused

**Change:** <change-name>
**Schema:** <schema-name>
**Progress:** 4/7 tasks complete

### Issue Encountered
<description of the issue>

**Options:**
1. <option 1>
2. <option 2>
3. Other approach

What would you like to do?
```

**Guardrails**
- Keep going through tasks until done or blocked
- Always read context files before starting (from the apply instructions output)
- If task is ambiguous, pause and ask before implementing
- If implementation reveals issues, pause and suggest artifact updates
- Keep code changes minimal and scoped to each task
- Update task checkbox immediately after completing each task
- Pause on errors, blockers, or unclear requirements - don't guess
- Use contextFiles from CLI output, don't assume specific file names

**Fluid Workflow Integration**

This skill supports the "actions on a change" model:

- **Can be invoked anytime**: Before all artifacts are done (if tasks exist), after partial implementation, interleaved with other actions
- **Allows artifact updates**: If implementation reveals design issues, suggest updating artifacts - not phase-locked, work fluidly
