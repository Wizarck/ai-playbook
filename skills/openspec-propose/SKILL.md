---
name: openspec-propose
description: Propose a new change with all artifacts generated in one step. Use when the user wants to quickly describe what they want to build and get a complete proposal with design, specs, and tasks ready for implementation.
license: MIT
compatibility: Requires openspec CLI.
metadata:
  author: openspec
  version: "1.0"
  generatedBy: "1.3.0"
---

Propose a new change - create the change and generate all artifacts in one step.

I'll create a change with artifacts:
- proposal.md (what & why)
- design.md (how)
- tasks.md (implementation steps)

When ready to implement, run /opsx:apply

This skill is the Phase 2 → Phase 3 entry point of the BMAD+OpenSpec runbook. Default flow reads the canonical slicing artefact `docs/openspec-slice.md` (per [bmad-openspec-bridge.md](../../specs/bmad-openspec-bridge.md)) so each `<change-id>` is scaffolded with the FRs, dependencies, components, and scope note already approved at Gate C. Use `--no-slice` for ad-hoc changes that bypass the contract (legacy v0.6.x behaviour).

---

**Input**: A `<change-id>` that exists as a row in `docs/openspec-slice.md`. For ad-hoc changes outside the slice contract, pass `--no-slice` plus a kebab-case name OR a description.

**Flags**:
- `--slice-file <path>` — override the default slice file location.
- `--no-slice` — opt out of the slice contract; ask the user inline for name + description (legacy v0.6.x flow).
- `--batch` — iterate every row in the slice file in dependency order; idempotent (already-scaffolded folders are skipped).

**Steps**

1. **Read and validate the slice artefact** (default flow; skipped only when `--no-slice` is passed)

   a. Locate the slice file:
      - Default: `docs/openspec-slice.md`.
      - Fallback: if the default does not exist, pick the most recent `docs/openspec-slice-*.md` by mtime.
      - Override: `--slice-file <path>` wins over both.
      - If none of the above resolve to an existing file, refuse with: "no slice file found at `docs/openspec-slice.md` (or `docs/openspec-slice-*.md`); either run BMAD slicing per `runbook-bmad-openspec.md` §2.4 first, or pass `--no-slice` for ad-hoc changes".

   b. Parse the "Approved change list" table and the "Scope notes" section per the schema in [bmad-openspec-bridge.md](../../specs/bmad-openspec-bridge.md) §3.1.

   c. Locate the row whose `Change ID` equals the requested `<change-id>`.

   d. **If `<change-id>` is not in the slice list**, refuse with: "change-id `<change-id>` not in slice list at `<resolved slice file>`; either add it (re-slice + re-approve Gate C) or pass `--no-slice` for ad-hoc changes". Do NOT auto-add the row.

   e. Extract for downstream steps:
      - The row's **scope note** (the one-paragraph entry under `## Scope notes` for this change ID) — this is the proposal's initial framing.
      - The **Depends on** column — these become the proposal's "Prerequisites" section.
      - The **FRs** column — these become the proposal's "Capability coverage" section.
      - The **Components** column (if present, UI changes only) — these populate `design.md` design-token / state references against `docs/ux/components.md`.
      - The **Journeys** column (if present) — these enrich `design.md` with per-journey anchors from `docs/ux/jN.md`.

1b. **If `--no-slice` is passed (legacy / ad-hoc)**

   Ask what they want to build using **AskUserQuestion tool** (open-ended, no preset options):
   > "What change do you want to work on? Describe what you want to build or fix."

   From their description, derive a kebab-case name (e.g., "add user authentication" → `add-user-auth`).

   **IMPORTANT**: Do NOT proceed without understanding what the user wants to build. The downstream steps run without the FRs / dependencies / components enrichment — the user is responsible for filling those in by hand.

1c. **If `--batch` is passed**

   Iterate every row of the slice file in dependency order (foundations first; topologically sorted on `Depends on`). For each row, run steps 2-5 below as if `<change-id>` were that row. Skip rows whose folder `openspec/changes/<change-id>/` already exists (emit a notice). Emit one summary at the end (scaffolded / skipped / failed counts) instead of N separate confirmations.

2. **Create the change directory**
   ```bash
   openspec new change "<change-id>"
   ```
   This creates a scaffolded change at `openspec/changes/<change-id>/` with `.openspec.yaml`. Use the `<change-id>` from the slice row (not a re-derived name) to keep folder identity consistent with the contract.

3. **Get the artifact build order**
   ```bash
   openspec status --change "<name>" --json
   ```
   Parse the JSON to get:
   - `applyRequires`: array of artifact IDs needed before implementation (e.g., `["tasks"]`)
   - `artifacts`: list of all artifacts with their status and dependencies

4. **Create artifacts in sequence until apply-ready**

   Use the **TodoWrite tool** to track progress through the artifacts.

   Loop through artifacts in dependency order (artifacts with no pending dependencies first):

   a. **For each artifact that is `ready` (dependencies satisfied)**:
      - Get instructions:
        ```bash
        openspec instructions <artifact-id> --change "<name>" --json
        ```
      - The instructions JSON includes:
        - `context`: Project background (constraints for you - do NOT include in output)
        - `rules`: Artifact-specific rules (constraints for you - do NOT include in output)
        - `template`: The structure to use for your output file
        - `instruction`: Schema-specific guidance for this artifact type
        - `outputPath`: Where to write the artifact
        - `dependencies`: Completed artifacts to read for context
      - Read any completed dependency files for context
      - Create the artifact file using `template` as the structure
      - Apply `context` and `rules` as constraints - but do NOT copy them into the file
      - **When the slice contract is in effect** (i.e. `--no-slice` was NOT passed), enrich the artefact from the extracted slice row (per step 1e):
        - `proposal.md` — initial framing = the scope note paragraph; "Prerequisites" = `Depends on`; "Capability coverage" = `FRs`.
        - `design.md` — for UI changes, cite the `Components` column against `docs/ux/components.md` for design-token + state references; cite the `Journeys` column against `docs/ux/jN.md`.
      - Show brief progress: "Created <artifact-id>"

   b. **Continue until all `applyRequires` artifacts are complete**
      - After creating each artifact, re-run `openspec status --change "<name>" --json`
      - Check if every artifact ID in `applyRequires` has `status: "done"` in the artifacts array
      - Stop when all `applyRequires` artifacts are done

   c. **If an artifact requires user input** (unclear context):
      - Use **AskUserQuestion tool** to clarify
      - Then continue with creation

5. **Show final status**
   ```bash
   openspec status --change "<name>"
   ```

**Output**

After completing all artifacts, summarize:
- Change name and location
- List of artifacts created with brief descriptions
- What's ready: "All artifacts created! Ready for implementation."
- Prompt: "Run `/opsx:apply` or ask me to implement to start working on the tasks."

**Artifact Creation Guidelines**

- Follow the `instruction` field from `openspec instructions` for each artifact type
- The schema defines what each artifact should contain - follow it
- Read dependency artifacts for context before creating new ones
- Use `template` as the structure for your output file - fill in its sections
- **IMPORTANT**: `context` and `rules` are constraints for YOU, not content for the file
  - Do NOT copy `<context>`, `<rules>`, `<project_context>` blocks into the artifact
  - These guide what you write, but should never appear in the output

**Guardrails**
- Create ALL artifacts needed for implementation (as defined by schema's `apply.requires`)
- Always read dependency artifacts before creating a new one
- If context is critically unclear, ask the user - but prefer making reasonable decisions to keep momentum
- If a change with that name already exists, ask if user wants to continue it or create a new one
- Verify each artifact file exists after writing before proceeding to next
