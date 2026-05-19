# design — `enforce-apply-skill`

> Companion to [proposal.md](proposal.md). Architectural details, contracts, edge cases.

## 1 Marker contract

### 1.1 Location and lifecycle

```
<project-root>/openspec/changes/<change-id>/.apply_log.jsonl
```

- One file per change. Path is canonical; no override.
- Created on first `start` invocation. Never deleted (apply phase history is auditable).
- Appended to, not rewritten. Tail-readable for the "is_active" check.
- **Committed to git** per D1 of proposal. Tracked even on long-running slices.

### 1.2 JSONL record schema

Each line is one JSON object. Two record types:

```jsonc
// start record
{
  "ts": "2026-05-15T18:32:11.142Z",   // ISO 8601 UTC, ms precision
  "event": "start",
  "change_id": "enforce-apply-skill", // redundant with folder name; aids cross-file aggregation
  "session_id": "claude-9f4b...",     // claude session id (from $CLAUDE_SESSION_ID env or derived)
  "skill_version": "1.1",              // SKILL.md frontmatter version
  "user": "23051550+Wizarck@users.noreply.github.com",  // from git config or env
  "agent": "Claude Code/opus-4-7-1m"   // model id when available; "unknown" otherwise
}

// stop record (on successful skill completion OR on detected abort via session_end hook)
{
  "ts": "2026-05-15T19:14:33.802Z",
  "event": "stop",
  "change_id": "enforce-apply-skill",
  "session_id": "claude-9f4b...",
  "outcome": "completed" | "aborted" | "blocked-by-spec",
  "tasks_completed": 7,
  "tasks_total": 11
}

// override record (when AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE is honoured by the hook)
{
  "ts": "2026-05-15T19:22:08.119Z",
  "event": "override",
  "change_id": "enforce-apply-skill",
  "session_id": "claude-9f4b...",
  "reason": "<value of env var; ≤120 chars>",
  "file_path": "<the path the hook would have blocked>"
}
```

### 1.3 Helper API (`scripts/openspec_apply_marker.py`)

```
openspec_apply_marker.py start --change-id <id> [--session-id <id>] [--skill-version <ver>]
openspec_apply_marker.py stop  --change-id <id> --outcome {completed|aborted|blocked-by-spec} [--tasks-completed N --tasks-total M]
openspec_apply_marker.py override --change-id <id> --reason "<text>" --file-path <path>
openspec_apply_marker.py is_active --change-id <id> [--session-id <id>]   # exit 0 if active session matches; exit 1 otherwise
openspec_apply_marker.py session_started --change-id <id>                 # exit 0 if ANY start record for current session_id
openspec_apply_marker.py list --change-id <id> [--json]                   # diagnostic; reads tail of marker
```

- `session_id` defaults to `$CLAUDE_SESSION_ID` env. If unset, derived as `local-<gitconfig-user>-<host>-<pid>` (deterministic enough for local-only sessions).
- All subcommands exit `0` on success, non-zero on failure. Error messages comply with [error-message-standard.md](../../../docs/rules/error-message-standard.rule.md).
- `start` is idempotent within the same session_id: re-invocation appends a second `start` record (for observability) but does not error.

## 2 Hook contract

### 2.1 Trigger

PreToolUse hook on tool names `Edit` and `Write` (and `MultiEdit` if defined in this playbook version; check current registry). Hook receives JSON input on stdin per Claude Code hook protocol:

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

### 2.2 Decision flow

```
1. Read tool_input.file_path; compute project-relative path (relative to cwd).
2. If path is outside the project (absolute path to /tmp, ~/, sibling repo): ALLOW.
3. If path matches openspec/changes/*/* (the change's OWN folder): ALLOW (refining proposal/design/tasks).
4. Enumerate openspec/changes/*/tasks.md. For each, parse "Owns (write_paths)" section.
   - Section is either a markdown bullet list under that heading OR a yaml frontmatter `write_paths:` array.
   - Each entry is a path (glob-allowed: *, **). Project-relative.
5. For each active change whose write_paths matches the target file:
   a. Check status via `openspec status --change <id> --json`. Skip changes NOT in ["applying", "applied"] state.
   b. Invoke `openspec_apply_marker.py session_started --change-id <id>`.
   c. If exit 0 (session has started record): ALLOW for this change.
   d. If exit non-zero: this is a candidate BLOCK.
6. If at least one candidate BLOCK and no ALLOW for the matching active change:
   a. If env AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE is set:
      - Record `override` event via `openspec_apply_marker.py override --change-id <id> --reason "$AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE" --file-path <path>`.
      - ALLOW.
   b. Otherwise: print canonical error to stderr, exit 2 (claude code reads exit code 2 as "block").
7. If no candidate BLOCK and no matching active change at all: ALLOW (changes outside any slice's write_paths are not gated by this hook).
```

### 2.3 Error message (canonical, per error-message-standard.md)

```
❌ apply phase bypass detected

The tool tried to edit `<file_path>` which is in the write_paths of an active
OpenSpec change in the `applying` state:

  • <change-id> (status: <status>; tasks: N/M complete)

But this Claude session has no `start` record in
`openspec/changes/<change-id>/.apply_log.jsonl`. The apply phase MUST be
initiated through the openspec-apply-change skill, which writes the marker
before performing edits.

FIX:
  Invoke the skill:        /openspec-apply-change <change-id>
  (or run the CLI helper:  python scripts/openspec_apply_marker.py start --change-id <change-id>)

OVERRIDE (use sparingly; logged for audit):
  export AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE="<one-line reason>"

See: docs/rules/apply-skill-enforcement.rule.md §3 (break-glass clause).
```

### 2.4 Performance budget

- Single Edit/Write triggers one hook invocation. Hook runs `openspec status` once per active change in the project's `openspec/changes/`. For projects with <50 in-flight changes (the realistic ceiling), total overhead < 250ms.
- For perf concerns at scale, future v0.x can cache the `openspec status` result for a TTL via filesystem lockfile. Out of scope here.

## 3 SKILL.md step 0 (new)

Inserted as the first step, before existing "Select the change":

```markdown
### 0. **Write apply-session start marker** (required, added v1.1)

   Before reading any context files or running implementation, signal that this
   apply session is skill-orchestrated:

   ```bash
   python scripts/openspec_apply_marker.py start --change-id "<name>"
   ```

   The marker is `openspec/changes/<name>/.apply_log.jsonl`. The PreToolUse
   hook (`templates/new-project/.claude/hooks/openspec-apply-enforce.py`)
   reads this marker to allow `Edit`/`Write` on the slice's `write_paths`.
   Without the marker, the hook blocks the first edit attempt.

   If the helper script is missing (consumer pre-v0.14.0), warn the user
   that they're running on an older playbook and proceed. The hook is
   per-project; old consumers without the hook see no enforcement.
```

## 4 Edge cases

| Case | Behaviour | Rationale |
|---|---|---|
| Two changes share a write_paths entry | Hook checks each independently; ALLOW requires the marker for *the change currently being applied*. If both are applying, ambiguous; hook BLOCKS with "ambiguous: multiple active changes claim this path". | Real conflict; humans resolve via slicing. |
| Apply runs out of band (e.g., post-review fix days later, no Claude session) | Helper script can be invoked directly from any shell. Hook respects the marker regardless of agent identity. | Skill is the canonical surface but not the only one. |
| Hook lookup fails (e.g., `openspec` CLI missing) | Hook fails OPEN (ALLOW with a warning to stderr). | Hook is enforcement-layer; CLI absence is project-misconfiguration, not a security failure. |
| Marker file is corrupt (malformed JSONL) | Helper script error-logs and reads what it can (best-effort line-by-line parse). `session_started` returns false if the matching session isn't found. Hook BLOCKS. | Fail-closed on corrupt audit trail. |
| `write_paths` heading is missing in tasks.md | Hook treats the change as having no gated paths (no block). Logs a warning. | tasks.md not yet written; not an apply phase yet. |
| Append-only `_shared/models.py` style shared file | The marker-aware change of the day owns it during its apply window. After commit, other slices reading it are not gated (their write_paths might also list it, but their apply phase will have its own marker). | Already-resolved via existing slice marker convention (§6.4 of consumer AGENTS.md). |
| Windows: shebang + venv path differences | Hook script uses `#!/usr/bin/env python3`; consumer `.claude/settings.json` invokes with `python` (resolves via PATH). On Windows, `py -3` fallback in the entrypoint. | Cross-platform per existing playbook scripts. |

## 5 Spec invariants (lifted into apply-skill-enforcement.md)

- **INV-1** Every Edit/Write to a file matching an active change's write_paths MUST be preceded by a `start` record for that change in this session.
- **INV-2** The marker is append-only. Hand-edits are flagged in retros (compare git history of `.apply_log.jsonl` to surrounding code commits — out-of-order writes are a red flag).
- **INV-3** An `override` record is auditable; `>1 per slice per month` triggers a retro flag.
- **INV-4** Skill version bump (e.g., v1.1 → v1.2) MUST keep step 0 OR replace it with an equivalent marker mechanism. Removing step 0 without a replacement is a breaking change.

## 6 Adoption surface in this PR vs. follow-ups

| Surface | This PR | Follow-up |
|---|---|---|
| `scripts/openspec_apply_marker.py` | ✅ NEW | — |
| `tests/test_openspec_apply_marker.py` | ✅ NEW | — |
| `skills/openspec-apply-change/SKILL.md` | ✅ EDIT (step 0 + version bump) | — |
| `templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl` | ✅ NEW | — |
| `templates/new-project/.claude/settings.json.tmpl` | ✅ EDIT (register hook) | — |
| `docs/rules/apply-skill-enforcement.rule.md` | ✅ NEW | — |
| `docs/concepts/runbook-bmad-openspec.md` | ✅ EDIT (§3.1.1) | — |
| `docs/concepts/agentic-failures.md` | ✅ EDIT (new row) | — |
| `docs/concepts/enforcement-status.md` | ✅ EDIT (new row) | — |
| `tests/test_apply_enforce_hook_template.py` | ✅ NEW (rendering + dry-run) | — |
| `CHANGELOG.md` | ✅ EDIT (v0.14.0 entry) | — |
| `VERSION` | ✅ EDIT (0.13.3 → 0.14.0) | — |
| Adopting in `consumer-a` | — | Follow-up PR in consumer-a (this slice ships the template; consumer-a copies it) |
| Adopting in `consumer-d` / `consumer-b` / `consumer-c` | — | Follow-up PR per consumer |
| Future: telemetry on `apply_phase_bypass` count | — | After 30 days of marker data; out of scope |

## 7 Risks

| Risk | Mitigation |
|---|---|
| Hook adds visible latency (>500ms) on every Edit/Write | Perf budget §2.4; if exceeded in real use, cache via lockfile in a follow-up |
| Agents trip on the hook during legitimate refactor work that touches slice files outside apply phase | The hook only triggers when status is "applying"/"applied". Cleanup commits post-archive don't hit it. |
| False-negative: hook misses a path because `write_paths` heading uses a non-canonical format | Tests cover 3 heading variants; future linter in tasks.md schema validation ensures the heading exists |
| Adopters forget to copy the hook on bump | Adoption PR (per consumer) is a checklist; the hook absence is observable in retros (no `start` records exist for confirmed-applied slices) |

## 8 Out-of-scope

- Automatic propagation of the hook to existing consumers (humans run the adoption PR per consumer; rollout-strategy.md governs).
- Real-time dashboard of `apply_phase_bypass` events.
- Hook for non-Claude agents (Cursor, Codex, etc.) — those have their own hook protocols; out of scope.
- Retroactive marker reconstruction from git history of past slices.
