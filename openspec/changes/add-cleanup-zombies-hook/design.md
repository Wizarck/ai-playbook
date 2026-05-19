# design — `add-cleanup-zombies-hook`

> Companion to [proposal.md](proposal.md). Architectural details, contracts, edge cases.

## 1 Manifest contract

### 1.1 Location

```
<playbook-root>/specs/zombies-manifest.yaml
```

Shipped with the playbook submodule; consumers consume it via `.ai-playbook/specs/zombies-manifest.yaml`. Rolling — each playbook release that removes or renames a consumer-surface artefact appends an entry.

### 1.2 Schema (top-level)

```yaml
version: 1                       # manifest schema version; bump on breaking change
manifest_version: "2026-05-19.1" # date.serial — strictly monotonic; printed in report header
entries:
  - id: <kebab-case slug, unique>
    path: <consumer-relative path or glob>
    tier: 1 | 2 | 3
    action: delete | rename | report
    safety: <safety-check name; see §2>
    introduced_in: <playbook version, e.g. v0.2.0>
    removed_in: <playbook version, e.g. v0.8.x or "deprecation_only">
    reason: <one-sentence why; ≤ 120 chars>
    evidence: <commit SHA or PR URL>
    # tier 2 only:
    rename_from: <literal string>
    rename_to: <literal string>
    rename_in_files: [<glob>, ...]   # only YAML files by default
    # tier 1 file_exact_match_only:
    expected_sha256: <sha of historical canonical content; manifest update required if rotated>
```

### 1.3 Safety checks (per-entry policy)

| Safety check | Semantics | Used by |
|---|---|---|
| `file_exact_match_only` | Read file, compute SHA-256, compare to `expected_sha256`. Delete only on exact match. Mismatch → downgrade to Tier 3 report. | release-cut.yml, routers/*.example |
| `check_gitmodules_first` | Read `.gitmodules` of consumer; delete directory ONLY if the submodule path is NOT registered (i.e. already deregistered, leaving orphan). | `.skills-sources/`, `.git/modules/.skills-sources/` |
| `file_mtime_gt` | Delete only if file mtime exceeds N days configured per-entry (default 30). Used for log rotation. | hindsight-queue.jsonl rotation |
| `yaml_literal_rename` | Read each file in `rename_in_files`; rename instances of `rename_from` → `rename_to` ONLY when the match is a YAML scalar value (not a key, not in comment). Skip if file is not valid YAML. | openTrattOS → nexandro |
| `directory_orphan` | Delete directory ONLY if neither it nor any descendant is tracked by git (`git ls-files <dir>` empty). | `.git/modules/<name>/` |
| `report_only` | Never delete; always to Tier 3 report regardless of conditions. | inherits_from advisory, extra-skills advisory |

### 1.4 Manifest validation

`scripts/cleanup_zombies.py validate` runs `manifest validate`: checks every entry has required fields per `tier`, every `safety` value is a known check name, `manifest_version` parses, etc. Pre-commit gate added in this slice.

## 2 Script contract

### 2.1 CLI

```
cleanup_zombies.py [--quiet] [--no-stdout] [--report-only] [--apply] [--manifest <path>] [--consumer-root <path>]
cleanup_zombies.py validate [--manifest <path>]
cleanup_zombies.py version
```

| Flag | Default | Effect |
|---|---|---|
| `--quiet` | false | Suppress stdout summary; only write to file channels. Used by hooks. |
| `--no-stdout` | false | Suppress stdout entirely (errors still go to stderr). |
| `--report-only` | true (default behavior) | Dry-run. Don't modify FS. Identical to default `report` mode. |
| `--apply` | false | Execute Tier 1 + Tier 2 changes. Mutually exclusive with `--report-only`. |
| `--manifest <path>` | `<playbook-root>/specs/zombies-manifest.yaml` | Override for tests. |
| `--consumer-root <path>` | `<cwd's nearest ancestor with .ai-playbook/>` | Override for tests. |

### 2.2 Discovery — finding the consumer root

```python
def find_consumer_root(start: Path) -> Path | None:
    for candidate in [start.resolve(), *start.resolve().parents]:
        if (candidate / ".ai-playbook").is_dir():
            return candidate
    return None  # not in a consumer; exit 0 silently
```

If invoked from inside the playbook source repo itself (no `.ai-playbook/` subdir because it IS the playbook), exit 0 with no-op message. The hook is consumer-only.

### 2.3 Decision flow per entry

```
For each entry in manifest.entries:
    target = consumer_root / entry.path
    if not target_present(target, entry):
        continue   # no zombie to clean
    if not safety_check_passes(target, entry):
        record_tier3_advisory(entry, reason="safety check failed: <name>")
        continue
    if entry.tier == 1:
        if apply_mode: do_delete(target)
        record_action_log(entry, "deleted" if apply_mode else "would-delete")
    elif entry.tier == 2:
        diff = compute_textual_diff(target, entry)
        if apply_mode: apply_diff(target, diff)
        record_action_log(entry, "renamed" if apply_mode else "would-rename")
    elif entry.tier == 3:
        record_tier3_advisory(entry, reason=entry.reason)
```

### 2.4 Channel writers

```
class ChannelSet:
    stdout_summary(counts: dict) -> None       # one-line "🧹 cleanup: X deleted, Y renamed, Z reports"
    report_file(detail: ReportDetail) -> None  # writes .ai-playbook/zombie-report.md (overwrite)
    injected_context_notice() -> None          # appends 1 line to .claude/injected-context.md if exists
```

`stdout_summary` is suppressed when `--quiet`. The report file is ALWAYS rewritten if any non-empty action — overwriting prior reports prevents stale advisories from lingering. When zero zombies, the report file is **removed** if present (clean state signal).

`injected_context_notice` is best-effort. Failure to write (e.g. file locked, permission) logs to stderr and continues.

### 2.5 Break-glass

```
if os.environ.get("AIPLAYBOOK_CLEANUP_SKIP", "").strip():
    print("⚠ cleanup_zombies: skipped via AIPLAYBOOK_CLEANUP_SKIP", file=sys.stderr)
    sys.exit(0)
```

Per [break-glass.md](../../../specs/break-glass.md): env var name in `AIPLAYBOOK_*` namespace. No audit log for this skip (the script doesn't have a writable audit channel beyond report file). Reasoning: cleanup is opportunistic; skipping has no compliance impact.

### 2.6 Exit codes

| Exit | Meaning |
|---|---|
| 0 | Success (including no-op, including non-fatal failures recorded to stderr) |
| 0 | Break-glass skip |
| 0 | Manifest missing or unreadable (logs warning, treats as no-op) |
| **2** | `validate` subcommand only: manifest schema invalid (caller is a pre-commit gate; non-zero is the correct signal) |

Default path (the hook-invoked case) NEVER exits non-zero, by D1.6.

## 3 Hook integration

### 3.1 Consumer-side hook lines

`templates/new-project/scripts/git-hooks/post-merge.tmpl`:

```bash
#!/usr/bin/env bash
# Post-merge hook — re-materialise skills + cleanup playbook zombies.
set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"

# Skills sync (if consumer uses single-source pattern; safe no-op otherwise)
if [ -f "$REPO_ROOT/scripts/sync_skills_local.py" ]; then
    python "$REPO_ROOT/scripts/sync_skills_local.py" --quiet || {
        echo "warn: skills sync failed (post-merge); run manually" >&2
    }
fi

# Playbook zombie cleanup (Tier 1+2 auto-apply, exit 0 always per spec)
if [ -f "$REPO_ROOT/.ai-playbook/scripts/cleanup_zombies.py" ]; then
    python "$REPO_ROOT/.ai-playbook/scripts/cleanup_zombies.py" --apply --quiet || true
fi
```

`post-checkout.tmpl` is analogous, gated on `$3 == "1"` (branch checkout flag) per existing convention.

### 3.2 Why post-merge / post-checkout (not pre-commit / pre-push)

- **Cleanup must precede development**: a developer pulling latest playbook should land on a clean tree before they start typing. Pre-commit fires only at commit time — too late.
- **post-merge fires on every successful `git pull` merge** (including fast-forward), which covers the submodule-bump scenario.
- **post-checkout fires on branch switches**, covering "I switched branches and the new branch has a newer .ai-playbook pin".
- Pre-push would be too late (already developed).
- CI would not help (CI is server-side; the zombie is local).

### 3.3 Bootstrap

First-time consumer: `bash scripts/install-skills-hooks.sh` already runs sync + cleanup. After this slice, the install script gains one additional line (downstream consumer-side PR).

## 4 v1 manifest entries — full inventory

Based on archaeology of 152 commits + 50 tags (2026-05-19 audit). See `specs/zombies-manifest.yaml` for the canonical YAML; this table is doc-only.

| id | tier | action | safety | reason |
|---|---|---|---|---|
| `release-cut-workflow` | 1 | delete | `file_exact_match_only` | Removed from playbook v0.8.x (commit `205b818`). |
| `routers-claude-md-example` | 1 | delete | `file_exact_match_only` | Removed in v0.3.0 (commit `3b37629`). |
| `routers-gemini-md-example` | 1 | delete | `file_exact_match_only` | Same commit. |
| `routers-cursor-rules-example` | 1 | delete | `file_exact_match_only` | Same commit. |
| `skills-sources-submodule` | 1 | delete | `check_gitmodules_first` | RFC-0001 reversal (geeplo §7.6 simplification, 2026-05-18). |
| `skills-sources-git-modules` | 1 | delete | `directory_orphan` | Orphan submodule git metadata. |
| `hindsight-queue-rotation` | 1 | delete | `file_mtime_gt` (default 30 days) | DEGRADED_CONTEXT queue file when stale. |
| `auto-managed-orphan-blocks` | 1 | rewrite | (uses `auto_managed.py`) | Stale `<source>` references in markdown. |
| `opentrattos-rename` | 2 | rename | `yaml_literal_rename` (rename_in_files: ["**/*.yaml", "**/*.yml"]) | v0.14.1 (commit `0c3cd59`) renamed `openTrattOS` → `nexandro`. |
| `skills-sources-frontmatter-simplify` | 3 | report | `report_only` | Single-source `skills_sources` field could be dropped (see geeplo `AGENTS.md` §7.6). |
| `cursor-rules-legacy` | 3 | report | `report_only` | `.cursor/rules/` adopted into AGENTS.md universal. |
| `inherits-from-too-old` | 3 | report | `report_only` | `inherits_from:` pinned > 3 minor versions behind current. |
| `extra-skills-in-mirror` | 3 | report | `report_only` | Skills present in `skills/` / `.claude/skills/` / `.gemini/skills/` not present in `.ai-playbook/skills/`. |
| `orphan-specs` | 3 | report | `report_only` | Specs in `openspec/specs/` not referenced by any active `openspec/changes/`. |
| `pre-commit-deprecated-hooks` | 3 | report | `report_only` | Pre-commit entries invoking `propagate_skills_bump.py` when consumer has no `skills_sources` field. |
| `template-drift` | 3 | report | `report_only` | Files in consumer matching a `templates/new-project/*.tmpl` name but with content drift > threshold. |

## 5 Edge cases

| Edge case | Resolution |
|---|---|
| Manifest YAML malformed | `cleanup_zombies.py` logs `ERROR: manifest unparseable: <line>`; exits 0. Default-mode (hook) is unaffected. `validate` subcommand exits 2. |
| Consumer-root not found (running from outside any consumer) | Exit 0 silently with debug log. |
| Tier 1 entry's `safety` check raises (e.g. PermissionError) | Log to stderr; record as Tier 3 advisory; continue. |
| Tier 2 YAML rename in a file the consumer has actively edited (conflicting changes) | The `yaml_literal_rename` check only operates on EXACT literal matches. If the consumer renamed surrounding context, the literal is still found and replaced. If the consumer deleted the line entirely, no match → no action. Conflict surfaced via git diff. |
| `.ai-playbook/zombie-report.md` is staged in git index (consumer forgot to gitignore) | Write proceeds; `.gitignore` advisory added to Tier 3 report. |
| Concurrent runs (two `git pull`s back-to-back) | Both write to `zombie-report.md`; last writer wins. Idempotent on outcome — file content is deterministic from manifest + tree state. Not protected by lockfile (overkill for ms-scale runs). |
| Running on Windows where `git rev-parse` line endings differ | Hook templates already use `set -e` + bash; `cleanup_zombies.py` reads `git ls-files` output text-mode with universal newlines. Tested in CI matrix per `specs/cross-os-validation.md`. |
| Network FS / WSL2 9p shares (slow stat) | Manifest entries with `file_mtime_gt` use `Path.stat().st_mtime`; on slow FS, this remains O(n) over manifest entries (~ 20). Acceptable. |

## 6 Doc-drift enforcement (cross-cutting note)

This slice is the FIRST consumer of the doc-drift enforcement work landing in slice `add-doc-drift-gate` (separate proposal, follow-up). When that gate lands:

- Editing `scripts/cleanup_zombies.py` will require touching `specs/cleanup-zombies.md` in the same PR (or marking `no-doc-impact`).
- Editing `specs/zombies-manifest.yaml` will require bumping `manifest_version` and adding a `CHANGELOG.md` entry.

Until that gate lands, doc updates are convention-only per [docs/development-flow.md](../../../docs/development-flow.md) §7.

## 7 Rollout

- v0.15.0 cuts with script + manifest + spec + tests (all in playbook).
- Consumer PRs follow per `proposal.md` § "Consumer adoption". First: `geeplo` (single-line hook addition).
- Manifest entries flagged Tier 3 (`extra-skills-in-mirror`, `template-drift`) are advisory-only on day 1; promotion to Tier 2/1 happens only after observing real consumer reports for ≥ 30 days without false positives (per `enforcement-status.md` standard promotion cadence).
