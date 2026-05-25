# Runbook: upgrade a consumer to Bash-aware apply-skill enforcement (v0.20.0+)

> **When to use this runbook.** Your consumer project consumes the
> `ai-playbook` framework via the `.ai-playbook` submodule and you are
> bumping past v0.20.0, which adds heuristic Bash interception, a v2
> telemetry schema, and a new L3 GitHub Actions check. This runbook
> covers the bump, the matcher update, a local smoke test, the rollback
> flag, and the L3 required-check activation.

## TL;DR

```bash
# 1. Bump the submodule.
cd <consumer-root>/.ai-playbook
git fetch && git checkout v0.20.0

# 2. Re-render the hook template into the consumer's .claude/hooks/.
cp .ai-playbook/templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl \
   .claude/hooks/openspec-apply-enforce.py

# 3. Update the matcher in .claude/settings.json (one-line edit).
#    Old:  "matcher": "Edit|Write|MultiEdit"
#    New:  "matcher": "Edit|Write|MultiEdit|Bash"

# 4. Smoke-test locally (see "Smoke test" below).

# 5. Commit + push the bump.
cd <consumer-root>
git add .ai-playbook .claude/hooks/openspec-apply-enforce.py .claude/settings.json
git commit -m "chore(.ai-playbook): bump to v0.20.0 (Bash interception + telemetry v2)"

# 6. Add `apply-skill-enforcement.rule` as a required check in GitHub
#    branch protection on `main` (manual, owner-level step).
```

## What changes

| Change | Impact | Notes |
|---|---|---|
| `GATED_TOOLS` adds `Bash` | Hook intercepts Bash tool calls in addition to Edit/Write/MultiEdit | Heuristic detection only; ambiguous commands pass with stderr warning. |
| Matcher in `.claude/settings.json` | Required: `Edit\|Write\|MultiEdit\|Bash` | Forgetting this leaves Bash uncovered (silent regression). |
| Telemetry schema → `rule-event/v2` | Every event now carries optional `block_class`, `block_tool`, `target_rel`, `bash_pattern_kind`, etc. | v1 events still valid; v2 is additive. Strict validators must upgrade. |
| L3 workflow `apply-skill-enforcement.rule.yml` | Server-side PR gate | Catches anything the L1 heuristic misses; requires branch protection to be effective. |
| New env: `AIPLAYBOOK_BASH_INSPECTION` | `"0"` disables the Bash branch only | Emergency rollback without redeploy. Default `"1"`. |

## Smoke test (local, no PR needed)

In your consumer project with an active OpenSpec change whose `tasks.md` declares at least one `write_path`:

```bash
# 1. Pick a declared write_path (example).
WP="backend/foo.py"

# 2. With NO start marker present, try a Bash mutation.
echo "x" > "$WP"
```

**Expected:** Claude Code refuses to execute the command and prints a message starting with `❌ apply phase bypass detected (Bash command writes to declared write_path)`. The error references the matched `pattern_kind` (e.g. `redirect-write`) and the matched write_path.

**If the hook does NOT block:**
- Confirm the matcher in `.claude/settings.json` includes `Bash`. The most common upgrade mistake.
- Confirm the hook file is the new version (look for `GATED_TOOLS = {"Edit", "Write", "MultiEdit", "Bash"}` at line ~45).
- Confirm `AIPLAYBOOK_BASH_INSPECTION` is not set to `"0"`.
- Confirm `openspec/changes/<id>/tasks.md` has a `## Owns (write_paths)` section with the path you targeted (or a glob matching it).

To smoke-test a non-blocking case (mutation outside any declared `write_path`):

```bash
echo "scratch" > /tmp/scratch.txt   # should pass; not gated
git status                          # should pass; never inspected
```

## Rollback (if Bash false positives are blocking real work)

Set the env var globally for the affected user, terminal session, or CI step:

```bash
export AIPLAYBOOK_BASH_INSPECTION=0
```

This **disables only the Bash branch**; `Edit`/`Write`/`MultiEdit` remain gated. The change is immediate (next tool call); no restart required.

To roll back the entire upgrade (revert to v0.19.x behaviour), revert the submodule bump:

```bash
cd <consumer-root>/.ai-playbook
git checkout v0.19.5   # or the prior version
cd ..
git add .ai-playbook
git commit -m "revert(.ai-playbook): rollback to v0.19.5 (Bash gate regression)"
```

The hook in `.claude/hooks/` is local-only; re-render from the older template:

```bash
cp .ai-playbook/templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl \
   .claude/hooks/openspec-apply-enforce.py
```

Restore the matcher to `Edit|Write|MultiEdit` (drop `|Bash`).

## Verifying telemetry

After the bump, every hook decision (allow / block / warn / override) appends one JSONL row to `<consumer>/.ai-playbook-state/rule-events.jsonl`. Inspect:

```bash
tail -n 5 .ai-playbook-state/rule-events.jsonl | python -m json.tool --json-lines
```

A v2 block event includes the enriched fields (`block_class`, `block_tool`, `bash_pattern_kind`, `target_rel`, `change_id`, etc.). See [telemetry-design.md](../concepts/telemetry-design.md) "Event schema" for the full list.

Weekly report:

```bash
python -m scripts.telemetry.report weekly
# or
python -m scripts.telemetry.report weekly --json > report.json
```

The report shows obey-rate per rule × LLM. If you see `apply-skill-enforcement` blocks dominating a specific `bash_pattern_kind` (e.g. >5% of all fires hitting `redirect-write`), the heuristic is likely over-flagging legitimate flows — file an issue with the pattern_kind and command examples.

## Activating the L3 required check

L3 is the truth floor. To make it block merges:

1. Push the consumer's branch with the v0.20.0 bump.
2. Open a PR to `main`.
3. The new workflow `apply-skill-enforcement.rule` runs automatically.
4. In **GitHub → Settings → Branches → Branch protection rules → `main`**:
   - Add `apply-skill-enforcement.rule` to "Require status checks to pass before merging".
   - Save.

The check now blocks any PR that touches a declared `write_path` without a corresponding `start` record in `.apply_log.jsonl`.

## Common upgrade errors

| Symptom | Diagnosis | Fix |
|---|---|---|
| Bash mutation passes unblocked | Matcher in `settings.json` still says `Edit\|Write\|MultiEdit` (no `Bash`). | Add `\|Bash` to the matcher. |
| Hook errors with `from scripts.telemetry... import ...` failing | Helper not reachable; either submodule out of date or `.ai-playbook/scripts/` missing. | Ensure submodule is on v0.20.0+ and `.ai-playbook/scripts/telemetry/` is present. |
| L3 workflow always fails | PR base SHA cannot be resolved (shallow clone). | Ensure `actions/checkout@v4` has `fetch-depth: 0` (the template does this; check if you edited the workflow). |
| Weekly report shows zero events | `AI_PLAYBOOK_STATE_DIR` was set elsewhere; events written to a different path. | Run `python -c "import scripts.telemetry.rule_event_logger as r; print(r.resolve_state_dir())"` to inspect the resolved path. |

## See also

- [apply-skill-enforcement.rule](../rules/apply-skill-enforcement.rule.md) — rule definition + Bash heuristics + edge cases.
- [enforcement-layers](../concepts/enforcement-layers.md) — L1 / L2 / L3 model.
- [telemetry-design](../concepts/telemetry-design.md) — schema v2 fields + privacy guarantees.
- [break-glass.rule](../rules/break-glass.rule.md) — `AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE` contract.
- [run-telemetry-report](run-telemetry-report.md) — generate weekly / monthly reports.
