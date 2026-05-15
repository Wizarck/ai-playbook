# apply-skill-enforcement.md

> **Status**: v1.0.0. Ships with ai-playbook v0.14.0 (slice `enforce-apply-skill`).
> **Enforcement**: ✅ wired — see [enforcement-status.md](enforcement-status.md) row `apply-skill-enforcement.md`.

The OpenSpec apply phase MUST be initiated through the `openspec-apply-change`
skill (or an equivalent CLI invocation of the marker helper). Manual
`Edit`/`Write`/`MultiEdit` on a slice's declared `write_paths` is `goal_drift`
per [agentic-failures.md](agentic-failures.md) §2.13 and is blocked by the
PreToolUse hook installed per §2 below.

Motivation: a real instance observed in consumer-a's Revalid v1.0 epic
(2026-05-14, PRs #1-#4) where four slices were implemented with manual edits,
bypassing the skill's TDD walk, citation-drift preflight (§4b of the skill,
v0.11.0), and self-validation gates (§3.4 of
[runbook-bmad-openspec.md](runbook-bmad-openspec.md)). The work landed but the
retros could not distinguish skill-orchestrated work from manual work.

This spec defines:
1. The marker format that proves skill orchestration (§1).
2. The PreToolUse hook contract that enforces it (§2).
3. The break-glass clause (§3, per [break-glass.md](break-glass.md)).
4. Invariants (§4).
5. Adoption checklist for consumers (§5).
6. Retro and audit cadence (§6).

---

## 1 Marker contract

### 1.1 Location and lifecycle

```
<project-root>/openspec/changes/<change-id>/.apply_log.jsonl
```

- One file per change. Path is canonical; no override.
- Created on first `start` invocation. Never deleted (apply-phase history is auditable).
- Appended to, not rewritten. Tail-readable for the `is_active` and `session_started` checks.
- **Committed to git.** CI and retros need to read it; gitignored markers cannot serve audit.
  The git-history churn (~1-2 lines per apply session) is acceptable cost for the audit signal.

### 1.2 JSONL record schema

Each line is one JSON object. Three record types:

```jsonc
// start record — emitted at the top of the skill (step 0) or via the helper CLI
{
  "ts": "2026-05-15T18:32:11.142Z",
  "event": "start",
  "change_id": "enforce-apply-skill",
  "session_id": "claude-9f4b...",
  "skill_version": "1.1",
  "user": "23051550+Wizarck@users.noreply.github.com",
  "agent": "Claude Code/opus-4-7-1m"
}

// stop record — emitted at successful skill completion or session-end hook
{
  "ts": "2026-05-15T19:14:33.802Z",
  "event": "stop",
  "change_id": "enforce-apply-skill",
  "session_id": "claude-9f4b...",
  "outcome": "completed" | "aborted" | "blocked-by-spec",
  "tasks_completed": 7,
  "tasks_total": 11
}

// override record — emitted by the hook when AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE is honoured
{
  "ts": "2026-05-15T19:22:08.119Z",
  "event": "override",
  "change_id": "enforce-apply-skill",
  "session_id": "claude-9f4b...",
  "reason": "<value of env var; ≥10 chars, ≤120 chars>",
  "file_path": "<the project-relative path the hook would have blocked>"
}
```

### 1.3 Helper API

`scripts/openspec_apply_marker.py` (delivered via `.ai-playbook/scripts/` submodule):

```
openspec_apply_marker.py start --change-id <id> [--session-id <id>] [--skill-version <ver>]
openspec_apply_marker.py stop  --change-id <id> --outcome {completed|aborted|blocked-by-spec}
                              [--tasks-completed N --tasks-total M]
openspec_apply_marker.py override --change-id <id> --reason "<≥10-char text>" --file-path <path>
openspec_apply_marker.py is_active --change-id <id> [--session-id <id>]
openspec_apply_marker.py session_started --change-id <id> [--session-id <id>]
openspec_apply_marker.py list --change-id <id> [--json]
```

Session-id resolution: `--session-id` arg → `$CLAUDE_SESSION_ID` env → derived
`local-<git-user>-<host>-<pid>` (deterministic enough for local-only sessions).

Error shape on failure paths conforms to
[error-message-standard.md](error-message-standard.md): WHY/FIX/OVERRIDE.

---

## 2 Hook contract

### 2.1 Trigger

PreToolUse hook on tool names `Edit`, `Write`, `MultiEdit`. Hook receives JSON
input on stdin per Claude Code hook protocol:

```jsonc
{
  "tool_name": "Edit",
  "tool_input": {
    "file_path": "C:\\Projects\\consumer-a\\backend\\app\\blueprints\\revalid\\service_bulk.py",
    "old_string": "...",
    "new_string": "..."
  },
  "cwd": "C:\\Projects\\consumer-a",
  "session_id": "claude-9f4b..."
}
```

Exit codes: `0` = allow; `2` = block (Claude Code surfaces stderr to the agent).

### 2.2 Decision flow

```
1. Read tool_input.file_path; compute project-relative path.
2. If path is outside the project tree: ALLOW.
3. If path is under openspec/changes/<id>/ (any change's own metadata): ALLOW
   (refining proposal/design/specs/tasks is part of the propose/design phase).
4. Enumerate openspec/changes/*/tasks.md. For each:
   - If tasks.md missing → change is pre-apply; SKIP (not gated).
   - Parse "Owns (write_paths)" section: bullet lines `* `<path>`` or `- `<path>``.
   - Glob-match the target path against each write_paths entry (fnmatch on
     forward-slash-normalized paths; trailing "/" = prefix match).
5. For each matching active change, call:
       python .ai-playbook/scripts/openspec_apply_marker.py session_started --change-id <id>
   - Exit 0 (marker found): ALLOW.
   - Exit ≠0: candidate BLOCK.
6. If at least one candidate BLOCK and no matching ALLOW:
   - If env AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE has ≥10 chars:
     * Record `override` event via marker helper for each matched change.
     * ALLOW.
   - Else: print canonical block message to stderr, exit 2.
7. No matching active change and no candidate BLOCK: ALLOW.
```

### 2.3 Canonical block message (per [error-message-standard.md](error-message-standard.md))

```
❌ apply phase bypass detected at <path>
   The tool tried to edit a path in the write_paths of `<change-id>`
   but this session has no `start` record in
   `openspec/changes/<change-id>/.apply_log.jsonl`.
   FIX: invoke the skill `/openspec-apply-change <change-id>` first,
        or run `python .ai-playbook/scripts/openspec_apply_marker.py start --change-id <change-id>`.
   OVERRIDE: export AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE="<≥10-char reason>"
   See: specs/apply-skill-enforcement.md §3 (break-glass clause).
```

### 2.4 Fail-open scenarios (intentional)

- Marker helper script absent (consumer pre-v0.14.0): hook warns to stderr, exits 0.
  Rationale: hook is enforcement-layer, not a security gate. CLI absence is
  project-misconfiguration, surfaced via the warning rather than blocking work.
- `openspec/changes/` directory absent: hook exits 0. No slice to gate.

### 2.5 Performance budget

A single Edit/Write triggers one hook invocation. Hook walks
`openspec/changes/*/tasks.md` once per call (typically <50 active changes in a
healthy project) and invokes `session_started` subprocess once per matching
change. Total p95 budget: 250 ms on a warm filesystem. If exceeded in
practice, follow-up adds a per-session memoization via lockfile.

---

## 3 Break-glass clause

The hook honours the `AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE` environment variable
per the contract in [break-glass.md](break-glass.md):

- Minimum reason length: 10 chars (matches `MIN_REASON_LEN` in `_break_glass.py`).
- Override is **audited**: every override emits an `override` JSONL record.
- Override is **counted**: `>1 override per slice per month` triggers a retro
  flag per [retrospective-cadence.md](retrospective-cadence.md).
- Override does NOT silence the block message on subsequent edits — each
  triggering edit emits its own `override` record (the env stays set, so
  Allow returns 0; users notice if their reason is wrong via the audit).

Legitimate override use cases:
- Post-review fixes that touch the same files days after the skill session
  concluded (skill marker shows a `stop` outcome and the new session has no
  `start` for this change).
- Emergency hotfixes touching slice files outside the planned apply phase.

Use sparingly. The retro counts override events and surfaces patterns.

---

## 4 Invariants

| ID | Invariant |
|---|---|
| **INV-1** | Every `Edit`/`Write`/`MultiEdit` to a file matching an active change's `write_paths` MUST be preceded by a `start` record for that change in the current session. |
| **INV-2** | The marker file is append-only. Hand-edits or reorderings are a retro red flag (compare git history of `.apply_log.jsonl` to surrounding code commits). |
| **INV-3** | An `override` record is auditable. `>1 per slice per month` triggers a retro discussion. |
| **INV-4** | Skill version bumps that touch the apply skill MUST preserve step 0 (the marker write) or replace it with an equivalent mechanism. Removing it without a replacement is a breaking change. |

---

## 5 Adoption checklist (per consumer)

Cookie-cutter steps for a project bumping to ai-playbook v0.14.0+:

1. **Bump submodule.**
   ```bash
   cd .ai-playbook && git fetch origin && git checkout v0.14.0 && cd .. && git add .ai-playbook
   ```
2. **Copy the hook script.**
   ```bash
   cp .ai-playbook/templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl \
      .claude/hooks/openspec-apply-enforce.py
   chmod +x .claude/hooks/openspec-apply-enforce.py
   ```
3. **Register the hook** in `.claude/settings.json`:
   ```jsonc
   "hooks": {
     "PreToolUse": [
       {
         "matcher": "Edit|Write|MultiEdit",
         "hooks": [
           { "type": "command", "command": "python .claude/hooks/openspec-apply-enforce.py", "timeout": 10 }
         ]
       }
     ]
   }
   ```
4. **Update `AGENTS.md`** to point at this spec (one line in the inherited specs
   list or in the project-specific "OpenSpec workflow" section).
5. **For projects with custom schemas** (e.g. `consumer-a-team`): declare
   `apply.handler: openspec-apply-change` in
   `openspec/schemas/<name>/schema.yaml` so consumers of the schema know
   programmatically which skill handles the apply phase.
6. **Dogfooding pass**: for the first slice after adoption, intentionally
   attempt one `Write` on a write_paths file without invoking the skill.
   Confirm the hook blocks. Then invoke the skill, confirm the marker is
   written, and the same `Write` is allowed.

---

## 6 Retros and audit cadence

The monthly retro (per [retrospective-cadence.md](retrospective-cadence.md))
surfaces:

- **Override count** per slice. >1 per slice flags the slice for discussion:
  was the manual edit warranted? Should the slice's `write_paths` have included
  the touched file?
- **Aborted apply sessions**: slices with `start` but no matching `stop` in 14
  days indicate the session crashed or was forgotten. Either resume via the
  skill or close the slice with `stop --outcome aborted`.
- **Bypass attempts** (hook block events). The hook does not emit telemetry in
  v1.0; in a future version it could write a separate audit log
  (`.apply_log.blocked.jsonl`).

A consumer that observes a recurring override pattern (e.g. same file always
overridden) is encouraged to either move the file out of `write_paths` or to
RFC a new ALLOW rule for that specific class of edit.
