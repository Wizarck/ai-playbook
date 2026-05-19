# cleanup-zombies.md

> **Status**: v1.1.0 — shipped in ai-playbook v0.15.0 (initial); v0.17.0 expansion (slice `single-source-skills-reset`) added 8 v2 manifest entries deprecating RFC-0001 multi-source artefacts (`propagate-skills-bump-script`, `validate-skills-mirror-script`, `propagate-skills-bump-workflow`, `rfcs-folder-removed`, `skills-sources-submodule-v2`, `skills-sources-frontmatter`, `skills-pins-consumers-yaml`, `validate-skills-mirror-precommit-hook`) plus refined 3 existing entries (`skills-sources-submodule`, `skills-sources-frontmatter-simplify`, `pre-commit-deprecated-hooks`) with `removed_in: v0.17.0`. Manifest version bumped 2026-05-19.1 → 2026-05-19.2. Authored under OpenSpec change `add-cleanup-zombies-hook` on 2026-05-19.
>
> **Audience**: any agent or developer touching consumer-side hygiene. Authoritative contract for `scripts/cleanup_zombies.py` and `specs/zombies-manifest.yaml`.

This spec defines the consumer-side **zombie cleanup contract**: a declarative manifest of fossils left in consumer trees by past playbook versions, plus a single script that detects them, applies safe-deletes / textual renames, and reports the residue.

---

## 1 Purpose

Bumping `.ai-playbook` only advances the submodule pin. It does **not** remove files the prior pin's bootstrap or propagation deposited, nor rename literals when an internal identifier changes (e.g. `consumer-c-legacy → consumer-c`, v0.14.1). Without a cleanup channel, consumer trees accumulate zombie files / fields / blocks indefinitely.

Goals:

1. **Single source of truth** — one rolling manifest at `specs/zombies-manifest.yaml`, updated as part of any playbook release that removes or renames a consumer-surface artefact.
2. **Auto-fire** — script invoked from consumer `post-merge` / `post-checkout` hooks (same pattern as `sync_skills_local.py`); never requires manual remembering.
3. **Multi-channel visibility** — stdout + report file + Claude-injected context, because background hooks have no terminal in CI / Claude Code / subagent runs.
4. **Never break git** — the default invocation always exits 0, even on internal errors.

Non-goals:

- Cleaning the playbook source repo itself (handled by ordinary `git rm` in the originating commit).
- Cross-consumer org-wide dashboards.
- Tier-3 auto-deletion (kept advisory by design; highest false-positive surface).

---

## 2 Manifest schema

See `specs/zombies-manifest.yaml` for the canonical instance. Schema:

```yaml
version: <int>                     # manifest schema version; bump on breaking change
manifest_version: "<YYYY-MM-DD>.<N>"  # strictly monotonic; serial N starts at 1 each day
entries:
  - id: <kebab-case slug, unique>
    tier: 1 | 2 | 3
    action: delete | rename | prune_blocks | rotate | report
    safety: <safety-check name; see §4>
    path: <consumer-relative path or glob>
    introduced_in: <playbook version, e.g. v0.4.0>
    removed_in: <playbook version OR "deprecation_only">
    reason: <one-sentence why; ≤ 200 chars>
    evidence: <commit SHA, PR URL, or spec path>
    # action-specific extras:
    rename_from: <literal string>            # tier 2 rename only
    rename_to: <literal string>              # tier 2 rename only
    rename_in_files: [<path or glob>, ...]    # tier 2 rename only — restricts the scan
    rotation_days: <int>                      # action: rotate
    max_minor_drift: <int>                    # safety: inherits-from-too-old
```

### 2.1 Validation rules

- `version` must be `1`.
- `manifest_version` must match `^\d{4}-\d{2}-\d{2}\.\d+$` and be strictly greater than the prior committed version.
- Every entry MUST have `id`, `tier`, `action`, `safety`, `path`, `introduced_in`, `removed_in`, `reason`, `evidence`.
- `id` must be globally unique within the file.
- `tier` × `action` × `safety` triples are validated against the matrix in §3.
- `rename_from` / `rename_to` / `rename_in_files` REQUIRED iff `action == rename`.
- `rotation_days` REQUIRED iff `action == rotate`.

`scripts/cleanup_zombies.py validate` enforces these rules. Pre-commit gate registers it on edits to the manifest file. Exit 2 on validation failure (the only non-zero exit code in the tool).

---

## 3 Tier semantics

| Tier | Behaviour | Failure mode |
|---|---|---|
| **1 — safe-delete** | Auto-removed by `--apply`. Default invocation is dry-run (`--report-only`). Safety check MUST PASS for any deletion. | Safety check fails → entry downgrades to Tier 3 advisory in the report. |
| **2 — textual changes** | Auto-applied by `--apply` (rename, rewrite). Idempotent. Reports prior + new state in the report file. | Safety check fails → entry downgrades to Tier 3 advisory. |
| **3 — report only** | Never modifies the FS, regardless of flags. Always reported. | N/A — Tier 3 reports its presence, full stop. |

### 3.1 Tier × action × safety matrix

| Tier | Allowed actions | Allowed safeties |
|---|---|---|
| 1 | `delete`, `prune_blocks`, `rotate` | `check_gitmodules_first`, `directory_orphan`, `auto_managed_orphan`, `file_mtime_and_drained` |
| 2 | `rename` | `yaml_literal_rename` |
| 3 | `report` | `report_only` |

---

## 4 Safety checks

Each entry's `safety` field names ONE check from this catalogue. The check runs BEFORE the action is allowed to execute. A check returns `(passed: bool, reason: str)`.

| Safety name | Semantics | Used by |
|---|---|---|
| `check_gitmodules_first` | Open consumer `.gitmodules`. PASS only if `entry.path` is NOT listed as a `path = ...` of any `[submodule "..."]` block. PASS implies the consumer has already deregistered the submodule, leaving the directory as orphan. | `skills-sources-submodule` |
| `directory_orphan` | Run `git ls-files -- <entry.path>` from consumer root. PASS only if output is empty (no tracked content). | `skills-sources-git-modules-orphan` |
| `auto_managed_orphan` | Delegate to `scripts/auto_managed.py --check --prune-orphans-dry`. PASS if the script identifies at least one orphan block in the target. | `auto-managed-orphan-blocks` |
| `file_mtime_and_drained` | Open the JSONL file. PASS only if (a) `Path.stat().st_mtime` < `now - rotation_days` AND (b) every non-empty line has `"state": "drained"`. | `hindsight-queue-rotation` |
| `yaml_literal_rename` | For each file in `rename_in_files`, parse with `yaml.safe_load`. PASS if at least one **scalar value** equals `rename_from`. Skip silently on invalid YAML. NEVER renames YAML keys (only values). | `consumer-c-legacy-rename` |
| `report_only` | Always returns `(False, "report-only entry")`. Used to force Tier 3 routing even when entries appear to "match" something. | All Tier 3 entries |

### 4.1 Adding a new safety check

1. Append entry to this table.
2. Implement `_safety_<name>(target, entry, consumer_root) -> SafetyResult` in `scripts/cleanup_zombies.py`.
3. Register in `SAFETY_CHECKS` dict.
4. Add unit tests in `tests/test_cleanup_zombies.py`.
5. Update §3.1 matrix if the check is permitted in a new tier.

---

## 5 Channels contract

When any non-empty run occurs (≥ 1 deletion, rename, or report), the script writes to **3 channels**:

| Channel | Always-on? | Format | Purpose |
|---|---|---|---|
| **stdout** | Yes, unless `--quiet` | One line: `🧹 cleanup_zombies: N deleted, M renamed, K reports — see .ai-playbook/zombie-report.md` | Visible during interactive `git pull` / `checkout`. |
| **`.ai-playbook/zombie-report.md`** | Yes, always | Markdown — header (`manifest_version`, run time), section per tier, table per entry with `id`, `path`, `action_taken`, `reason` | Persistent, readable any time. Overwritten each run; **removed** on empty runs (clean-state signal). |
| **`.claude/injected-context.md`** | Only if file exists | One line appended: `⚠ playbook-cleanup found pending items on <ISO timestamp> — see .ai-playbook/zombie-report.md` | SessionStart hooks surface this to Claude on next session. |

Notes:
- The report file path is fixed by spec. `.ai-playbook/` is the consumer's submodule mount; the file is gitignored per consumer adoption checklist (§8).
- Channel writers are best-effort. Failure to write any channel logs to stderr and continues; the run still exits 0.

---

## 6 Exit code policy

Default invocation (hook context) NEVER exits non-zero. Mapping:

| Path | Exit code |
|---|---|
| Success (no zombies) | 0 |
| Success (zombies handled per tier) | 0 |
| Break-glass skip via `AIPLAYBOOK_CLEANUP_SKIP=1` | 0 |
| Manifest missing or unreadable | 0 (logs warning) |
| Consumer root not found (invoked outside any consumer) | 0 (silent) |
| Safety check raised exception | 0 (entry recorded as Tier 3 advisory) |
| `validate` subcommand only — manifest schema invalid | **2** |

Rationale: cleanup is opportunistic. A manifest bug, transient FS error, or YAML parse failure must not block `git pull`. Failures surface via the report file (with detail) and stderr (with summary).

---

## 7 Break-glass

```
AIPLAYBOOK_CLEANUP_SKIP=1   # any non-empty value
```

When set, the script logs `⚠ cleanup_zombies: skipped via AIPLAYBOOK_CLEANUP_SKIP` to stderr and exits 0 immediately. No file mutations, no channel writes.

Per `specs/break-glass.md`: env var sits in the `AIPLAYBOOK_*` namespace. No audit log for this skip (the script lacks a writable audit channel beyond the report file, which would be the very thing being skipped).

Use when:
- A consumer needs to defer cleanup (e.g. mid-rebase, dirty tree).
- Diagnosing a suspected false positive — run with skip, inspect manually, file a manifest bug.

---

## 8 Consumer adoption checklist

After bumping the consumer's `.ai-playbook` to v0.15.0:

1. **Hook wire-up** — add one line to `scripts/git-hooks/post-merge` AND `scripts/git-hooks/post-checkout` (both already exist if the consumer adopted `sync_skills_local.py`):

   ```bash
   python "$REPO_ROOT/.ai-playbook/scripts/cleanup_zombies.py" --apply --quiet || true
   ```

2. **Gitignore** — append to `.gitignore`:

   ```
   # Playbook cleanup report (regenerated per hook run)
   .ai-playbook/zombie-report.md
   ```

3. **First run** — `bash scripts/install-skills-hooks.sh` (or equivalent) runs the cleanup immediately as part of post-install. Inspect the generated `zombie-report.md`. Review any Tier 3 advisories manually.

4. **Verify clean state** — `python .ai-playbook/scripts/cleanup_zombies.py` (no `--apply`). Should print no summary line if zero zombies. Report file should be absent.

For consumers that have **never** wired the skills sync (and therefore have no `scripts/git-hooks/` setup), point at `templates/new-project/scripts/git-hooks/` shipped in this release and the bootstrap runbook `runbooks/onboard-new-project.md`.

---

## 9 Cross-references

- [`zombies-manifest.yaml`](zombies-manifest.yaml) — the canonical manifest instance.
- [`auto-managed-sections.md`](auto-managed-sections.md) — the auto-managed orphan detection delegated to by safety `auto_managed_orphan`.
- [`break-glass.md`](break-glass.md) — `AIPLAYBOOK_*` env namespace.
- [`error-message-standard.md`](error-message-standard.md) — error message shape used by `validate` subcommand on schema failure.
- [`enforcement-status.md`](enforcement-status.md) — wiring status row for this spec.
- [`memory-hierarchy.md`](memory-hierarchy.md) — hindsight queue lifecycle (rationale for `hindsight-queue-rotation`).
- [`dispatcher-chain.md`](dispatcher-chain.md) — `inherits_from` semantics (rationale for `inherits-from-too-old` Tier 3 entry).
- [`runbook-bmad-openspec.md`](runbook-bmad-openspec.md) — change workflow.
- [`../runbooks/release.md`](../runbooks/release.md) §X — release-cut checklist gates a manifest update when consumer-surface artefacts change.
- [`../docs/development-flow.md`](../docs/development-flow.md) §5 — enforcement row for this spec.
