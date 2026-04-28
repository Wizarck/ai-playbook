---
name: openspec-archive-change
description: Archive a completed change in the experimental workflow. Use when the user wants to finalize and archive a change after implementation is complete.
license: MIT
compatibility: Requires openspec CLI.
metadata:
  author: openspec
  version: "1.0"
  generatedBy: "1.3.0"
---

Archive a completed change in the experimental workflow.

**Input**: Optionally specify a change name. If omitted, check if it can be inferred from conversation context. If vague or ambiguous you MUST prompt for available changes.

**Steps**

1. **If no change name provided, prompt for selection**

   Run `openspec list --json` to get available changes. Use the **AskUserQuestion tool** to let the user select.

   Show only active changes (not already archived).
   Include the schema used for each change if available.

   **IMPORTANT**: Do NOT guess or auto-select a change. Always let the user choose.

2. **Check artifact completion status**

   Run `openspec status --change "<name>" --json` to check artifact completion.

   Parse the JSON to understand:
   - `schemaName`: The workflow being used
   - `artifacts`: List of artifacts with their status (`done` or other)

   **If any artifacts are not `done`:**
   - Display warning listing incomplete artifacts
   - Use **AskUserQuestion tool** to confirm user wants to proceed
   - Proceed if user confirms

3. **Check task completion status**

   Read the tasks file (typically `tasks.md`) to check for incomplete tasks.

   Count tasks marked with `- [ ]` (incomplete) vs `- [x]` (complete).

   **If incomplete tasks found:**
   - Display warning showing count of incomplete tasks
   - Use **AskUserQuestion tool** to confirm user wants to proceed
   - Proceed if user confirms

   **If no tasks file exists:** Proceed without task-related warning.

4. **Assess delta spec sync state** (informational only — no automated sync in this version)

   Check for delta specs at `openspec/changes/<name>/specs/`. If none exist, proceed without notice.

   **If delta specs exist:**
   - Compare each delta spec with its corresponding main spec at `openspec/specs/<capability>/spec.md`
   - Determine what changes would be applied (adds, modifications, removals, renames)
   - Show a combined summary so the user knows what an eventual sync would do.

   Future enhancement: a dedicated spec-sync skill is planned for v0.8.0 (per `specs/v0.8.0-roadmap.md` item 10). For now, archive only does the move + retro — no automated sync is performed.

5. **Perform the archive**

   Create the archive directory if it doesn't exist:
   ```bash
   mkdir -p openspec/changes/archive
   ```

   Generate target name using current date: `YYYY-MM-DD-<change-name>`

   **Check if target already exists:**
   - If yes: Fail with error, suggest renaming existing archive or using different date
   - If no: Move the change directory to archive

   ```bash
   mv openspec/changes/<name> openspec/changes/archive/YYYY-MM-DD-<name>
   ```

6. **Chain a retrospective write to `retros/<change-id>.md`** (Gate F deliverable)

   Per [runbook-bmad-openspec.md](../../specs/runbook-bmad-openspec.md) §3.1 and §4 + Gate F in §5, every archive MUST chain a retro write. Path: `retros/<change-id>.md` (relative to the project root). Create the `retros/` directory if it does not exist.

   - **If a `bmad-retrospective` skill is available**, invoke it via the Skill tool, passing the change-id and the archive path. It produces the retro per the BMAD retrospective format.
   - **Otherwise, write a stub markdown directly** with the following sections (the human fills them in):

     ```markdown
     # Retrospective: <change-id>

     - **Archived**: YYYY-MM-DD
     - **Archive path**: openspec/changes/archive/YYYY-MM-DD-<change-id>/
     - **Schema**: <schema-name>

     ## What worked

     <one-paragraph: practices, patterns, decisions that paid off>

     ## What didn't

     <one-paragraph: friction, surprises, rework>

     ## Lessons

     <bulleted: durable lessons; candidates for retention to Hindsight if cross-project>

     ## Carry-forward to next change

     <bulleted: action items, follow-up tickets, spec edits>
     ```

   If `retros/<change-id>.md` already exists, do NOT overwrite — append a new dated section instead and warn the user.

7. **Display summary**

   Show archive completion summary including:
   - Change name
   - Schema that was used
   - Archive location
   - Whether specs were synced (if applicable)
   - Note about any warnings (incomplete artifacts/tasks)

**Output On Success**

```
## Archive Complete

**Change:** <change-name>
**Schema:** <schema-name>
**Archived to:** openspec/changes/archive/YYYY-MM-DD-<name>/
**Specs:** No automated sync (deferred to v0.8.0 spec-sync skill); delta-spec assessment shown above for human follow-up.
**Retro:** retros/<change-id>.md (stub written / appended)

All artifacts complete. All tasks complete.
```

**Guardrails**
- Always prompt for change selection if not provided
- Use artifact graph (openspec status --json) for completion checking
- Don't block archive on warnings - just inform and confirm
- Preserve .openspec.yaml when moving to archive (it moves with the directory)
- Show clear summary of what happened
- Always chain the retro write (step 6) — Gate F deliverable per the runbook; never skip silently
- If delta specs exist, always run the assessment and show the combined summary (informational only until v0.8.0)
