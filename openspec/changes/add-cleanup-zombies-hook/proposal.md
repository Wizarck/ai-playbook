# proposal — `add-cleanup-zombies-hook`

> **Status**: draft (slice/`feat/cleanup-zombies-hook`).
> **Wave**: ai-playbook v0.15.0 candidate (additive MINOR).
> **Authored**: 2026-05-19.

## Problem

Across 152 commits and 50 tags (v0.1.0 → v0.14.1), the playbook has **removed, renamed, and re-architected** files/folders that consumers received via earlier bootstrap or propagation passes. Bumping `.ai-playbook` only advances the submodule pin — it does **not** clean what the prior pin deposited into the consumer tree. Result: consumer repos accumulate **zombie files** with no ownership signal.

Concrete instances observed in active consumers (2026-05):

| Zombie | Source of decay | Confirmed in |
|---|---|---|
| `.github/workflows/release-cut.yml` | Removed from playbook v0.8.x (commit `205b818`); the template at `templates/new-project/.github/workflows/release-cut.yml.tmpl` was retired but earlier bootstrap may have placed it | older consumers |
| `routers/CLAUDE.md.example`, `routers/GEMINI.md.example`, `routers/cursor-rules.example` | Deleted in playbook v0.3.0 (commit `3b37629`) when the templates moved | unknown consumers; manifest required |
| `.skills-sources/<repo>/` submodule + `.git/modules/.skills-sources/` orphan | RFC-0001 multi-source pattern reversed for single-source consumers (consumer-a §7.6 simplification) | consumer-a (cleaned 2026-05-18); pattern likely repeats |
| References to `consumer-c-legacy` in `mcp-servers.project.yaml` / `consumers.yaml` / `AGENTS.md` | Renamed to `consumer-c` in playbook v0.14.1 (commit `0c3cd59`) | any consumer that hard-coded the old name |
| Skills present in consumer mirrors but NOT in current `.ai-playbook/skills/` | Skill renames during v0.7.0 alignment (commits `ade4ca2`, `4833403`); old materialisers may not rmtree | consumers running old materialiser script |
| `<!-- BEGIN auto-managed: <source> -->` blocks whose `<source>` no longer exists | `auto_managed.py` orphan-source detection exists but no cleanup path | per [auto-managed-sections.md](../../../docs/concepts/auto-managed-sections.md) gaps |
| `.cursor/rules/*.mdc` (opt-in concern) | Cursor adopted AGENTS.md universally; `.cursor/rules` is legacy | dev-personal preference |
| Stale `inherits_from:` pinned pre-v0.4.0 (no skills ecosystem) | Bump never happened; no advisory | observable in `AGENTS.md` of frozen consumers |

There is no single point that audits "given current playbook tag, what does THIS consumer have that should no longer exist?" Manual archaeology per consumer is unscalable as more consumers (`consumer-a`, `consumer-d`, `consumer-b`, `consumer-c`, `consumer-e`, future) onboard.

## Proposed change

A **declarative zombie manifest** shipped with the playbook + a **single cleanup script** that consumers invoke automatically from `post-merge` / `post-checkout` hooks (same pattern consumer-a already uses for `sync_skills_local.py`).

### Three-tier policy (per discussion 2026-05-19)

| Tier | Behaviour | Examples |
|---|---|---|
| **1 — safe-delete** | Auto-removed without prompt. High confidence, file-exact-match or orphan-only. | `release-cut.yml` (content match), `.skills-sources/` (not in `.gitmodules`), orphan auto-managed blocks, hindsight-queue rotation |
| **2 — textual changes** | Auto-applied (e.g. rename in YAML keys), but logged. Mid-confidence. | `consumer-c-legacy` → `consumer-c` literal string rename in YAML files, `skills_sources` simplification advice (report-only) |
| **3 — report-only** | Never auto-deleted; written to report file. | `inherits_from` pinned too old, extra skills present locally (may be custom), specs orphans |

### Multi-channel visibility (per discussion 2026-05-19)

Hooks run in background — stdout alone is invisible in CI / Claude Code / non-interactive use. The cleanup script writes to **3 channels** on each non-empty run:

1. **stdout** — compact summary visible during interactive `git pull` / `checkout`.
2. **`.ai-playbook/zombie-report.md`** (gitignored, overwritten each run) — full detail, persistent, readable any time.
3. **`.claude/injected-context.md`** (if file exists) — single-line notice appended so the SessionStart hook surfaces it to Claude on next session.

Hook exit code is **always 0** — cleanup never breaks git operations. Failure modes log to stderr and continue.

### Spec deliverables

- **New spec**: [`docs/rules/cleanup-zombies.rule.md`](../../../docs/rules/cleanup-zombies.rule.md) — defines manifest schema, three-tier policy, channel contract, exit-code policy, break-glass override.
- **New data**: [`specs/zombies-manifest.yaml`](../../../specs/zombies-manifest.yaml) — declarative inventory; one entry per zombie. Rolling — new entries added in each release where the playbook removes/renames a consumer-surface artefact.
- **Updated**: [`docs/concepts/enforcement-status.md`](../../../docs/concepts/enforcement-status.md) — new row for `cleanup-zombies.md`.
- **Updated**: [`docs/concepts/development-flow.md`](../../../docs/concepts/development-flow.md) — §5 enforcement table gets a row for consumer-side zombie cleanup.
- **Updated**: [`docs/runbooks/release.md`](../../../docs/runbooks/release.md) — release-cut checklist gains "update `zombies-manifest.yaml` if this release removed/renamed any consumer-surface file".

### Code deliverables

| Path | Action | Description |
|---|---|---|
| `scripts/rules/cleanup-zombies.rule.py` | NEW | argparse-driven CLI. Loads `specs/zombies-manifest.yaml`. Three subcommands: `report` (default; dry-run), `apply` (executes Tier 1+2), `version` (prints manifest version). Walks consumer-relative paths from the cwd's nearest ancestor containing `.ai-playbook/`. Idempotent. Always exits 0. |
| `specs/zombies-manifest.yaml` | NEW | Declarative manifest. Schema: `version`, `entries: [{id, path, tier, action, safety, introduced_in, removed_in, reason, evidence}]`. |
| `docs/rules/cleanup-zombies.rule.md` | NEW | Contract spec. |
| `tests/test_cleanup_zombies.py` | NEW | ≥ 15 tests covering manifest schema validation, each safety check, three-channel output, exit-code-0 policy, break-glass env honoured, idempotency, missing manifest graceful failure, missing consumer-root graceful failure. |
| `templates/new-project/scripts/git-hooks/post-merge.tmpl` | NEW | Hook template invoking `python .ai-playbook/scripts/rules/cleanup-zombies.rule.py --quiet || true`. |
| `templates/new-project/scripts/git-hooks/post-checkout.tmpl` | NEW | Same. |
| `CHANGELOG.md` | EDIT | `[0.15.0]` entry. |
| `VERSION` | EDIT | `0.14.1` → `0.15.0` (additive MINOR). |

### Decisions (carried from 2026-05-19 conversation)

- **D1.1 — Single source of truth**: manifest + script live in the playbook upstream, not per-consumer. Rationale: rolling list updated per playbook release; consumers get fresh zombies automatically via submodule bump.
- **D1.2 — Auto-fire on hook trigger**: `post-merge` + `post-checkout` invocation, NOT manual cron. Rationale: matches `sync_skills_local.py` pattern already accepted in consumer-a; runs when the source-of-zombies actually changes (submodule bump).
- **D1.3 — Full manifest in v1**: ship all identified zombie patterns at once, not incremental. Rationale: user explicit choice (2026-05-19): "todo de golpe". Iterate via Tier escalation if false positives surface.
- **D1.4 — Tier 2 includes `consumer-c-legacy` rename auto**: literal-string rename in YAML files is low-risk and high-value. Rationale: user explicit choice (2026-05-19): "incluyelo, a muy malas lo depuramos luego".
- **D1.5 — Multi-channel report**: stdout + file + injected-context. Rationale: single-channel (stdout) is invisible in non-interactive runs (CI / Claude Code subagents). User explicit: "ese output donde se imprime ?? porque si es un hook yo no lo veria aquí en pantalla".
- **D1.6 — Exit 0 always**: hook never breaks git. Rationale: cleanup is opportunistic; a manifest bug or transient FS error must not block `git pull`. Failures surface via the report file.
- **D1.7 — Break-glass env**: `AIPLAYBOOK_CLEANUP_SKIP=1` skips the entire cleanup. Per [break-glass.md](../../../docs/rules/break-glass.rule.md) pattern (analogous to `AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE`).

## Consumer adoption (downstream, in a follow-up)

After this slice merges and v0.15.0 is cut, each consumer adopts in its own PR:

1. Bump `.ai-playbook` submodule to v0.15.0.
2. Add one line to existing `scripts/git-hooks/post-merge` and `scripts/git-hooks/post-checkout`:
   ```bash
   python .ai-playbook/scripts/rules/cleanup-zombies.rule.py --quiet || true
   ```
3. Add `.ai-playbook/zombie-report.md` to `.gitignore`.

First adoption: `consumer-a` (already uses the `sync_skills_local.py` hook pattern; one-line addition).

## Out of scope

- **Tier 3 auto-deletion** — out by design (highest false-positive risk).
- **Cross-consumer aggregation** — this slice is per-consumer; an org-wide dashboard is a separate concern.
- **Cleaning the playbook source repo itself** — only consumers carry zombies; the playbook is self-managed via `git rm` in the originating commit.
- **Retroactive manifest entries for v0.1.0–v0.14.1 zombies discovered LATER** — the v1 manifest is best-effort from current archaeology. Future zombies added in their respective releases per [release.md](../../../docs/runbooks/release.md) checklist update.
