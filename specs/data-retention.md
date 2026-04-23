# data-retention.md

> **Status**: v1.0.0. Populated in T22d. Defines what the playbook and consumer projects retain, where, for how long, who reads it, and how it is deleted. The spec is normative; per-project deviations require an override under [../docs/contributing.md](../docs/contributing.md) §6 (backwards compatibility) + an entry in the project's AGENTS.md §7.

Retention is a safety surface. Too little retention makes audits impossible; too much creates a GDPR liability. This spec names the defaults and the deletion paths.

---

## 1. Retention table

Unless otherwise noted, "location" is relative to the consumer repo root when the data originates in a consumer project, or to the playbook repo root for playbook-native data.

| Data | Location | Retention | Who can read | Deletion path |
|---|---|---|---|---|
| `events.jsonl` (local) | `<repo>/.ai-playbook/events.jsonl` | 180 days rolling; rotated weekly to `events-<YYYY-WW>.jsonl.gz` under `<repo>/.ai-playbook/archive/` | the dev (local) | `python -m scripts.log_event --prune` (cron-friendly) OR manual `rm`; gitignored so deletion has no commit impact |
| `events.jsonl` (VPS) | `/srv/observability/events/<project>/events.jsonl` | 180 days rolling; rotated weekly to gz | maintainer + the project's owner (via SSH) | same rotation script on the VPS via `systemd-timer`; gz archives deleted at 180d via `find -mtime +180 -delete` |
| OTel traces (Langfuse) | Langfuse project store | 90 days default; 365 days for `severity=error` | maintainer + project owner | Langfuse retention policy per project (configured at bootstrap time via its API) |
| Hindsight retains | Hindsight MCP per-bank store | per-bank default 90-day soft decay; see [memory-hierarchy.md](memory-hierarchy.md) | the MCP user (scoped by `bank_id`) | `hindsight.decay(bank_id, cutoff=<iso>)` or explicit delete call per memory-hierarchy.md §retention |
| `.ai-playbook/overrides.log` | `<repo>/.ai-playbook/overrides.log` | **kept forever** (audit trail) | the dev (local) + maintainer (grep during retro) | do not delete; if compromised, rotate the file and keep the old copy |
| OpenSpec archives | `<repo>/openspec/archive/` | **kept forever** | anyone with repo read | never delete; superseded by a later archive, not removed |
| Retros | `<repo>/reports/retros/<YYYY-MM>/*.md` | **kept forever** | anyone with repo read | never delete; per [retrospective-cadence.md](retrospective-cadence.md) §3 |
| Post-mortems | `<repo>/reports/post-mortems/<date>-<slug>.md` | **kept forever** | anyone with repo read | never delete; per [post-mortem.md](post-mortem.md) |
| Pre-commit scan outputs | stdout/stderr of `pre-commit run` | **no retention (ephemeral)** | the dev (terminal) | scrollback; nothing persisted |
| CI logs (GitHub Actions) | GitHub Actions storage | 90 days (GitHub default) | GitHub members of the org | auto-purged by GitHub at 90 days |
| Secrets (SOPS-encrypted) | SOPS-encrypted `*.yaml` / `*.env` in repo | **kept forever**; `secrets.env` rotated on key compromise | holders of the SOPS key | never delete the encrypted file; rotate the plaintext (new SOPS re-encryption) on compromise |
| `.ai-playbook/migration-pending.log` | `~/.ai-playbook/migration-pending.log` | kept until the deprecation watcher flags the entry handled | the dev (local) | line-delete when the underlying project migrates to v1 |
| Personal dev logs | `~/.ai-playbook/*.log` | per-dev; no central retention | the dev (local) | per-dev `rm`; nothing central |
| Projects registry | `~/.ai-playbook/projects.yaml` | as long as needed | the dev (local) | regenerated via `scripts/discover_projects.py --refresh` |

---

## 2. Retention defaults rationale

- **180 days for `events.jsonl`**: covers two full monthly retros plus a quarter-over-quarter lookback without ballooning disk usage. One year rotates out of the archive.
- **90 days for OTel traces (default)**: balances investigation utility (most incidents look back ≤14 days) with Langfuse storage cost. `severity=error` gets 365 days because error traces drive the monthly systemic-flags section of the retro.
- **90 days for Hindsight retains (default)**: matches the memory-hierarchy spec's soft-decay contract so memories age out at the same rate traces do, keeping cross-references coherent.
- **Forever for overrides.log, archives, retros, post-mortems, secrets**: these are evidence. Deleting evidence defeats the audit surface. Storage cost is negligible (text files).
- **90 days for CI logs**: we accept the GitHub default; we do not ship our own CI storage.

---

## 3. Deletion paths summary

When you need to delete data, the path depends on the row:

- **Ephemeral** → scrollback / terminal buffer. Nothing to do.
- **Rolling** (`events.jsonl`) → wait for the rotation window, or force with the pruning CLI.
- **Never-delete** → do nothing. The data is load-bearing for audit.
- **Key rotation** (secrets) → re-encrypt; the old encrypted blob stays in git history forever (that's git's nature). Rotate the plaintext key material out-of-band.
- **Right to deletion** (see §4) → anonymisation, not deletion.

---

## 4. Right to deletion (GDPR-adjacent)

Contributors who leave the project may request removal of their identifying data. The policy is **anonymisation, not deletion**:

- **Contributions stay.** Commits, PR threads, review markdown, FEEDBACK.md bullets, archived OpenSpec proposals, retro narratives — all remain. These are part of the repo's history and removing them would corrupt the audit trail.
- **Identity detaches.** The contributor's handle is replaced with an opaque token (`anon-<short-hash>`) where feasible:
  - Git commits: history is immutable; a `CONTRIBUTORS.md` footnote records the anonymisation request with its date.
  - FEEDBACK.md: the handle column is blanked; the bullet text stays.
  - Retros and post-mortems: handles in the "Responder" or "Action items" columns are replaced with `anon-<hash>`; narrative bodies are NOT edited (retros target systems, not people, so identity rarely appears in narrative per [retrospective-cadence.md](retrospective-cadence.md) §5).
  - `.ai-playbook/overrides.log` lines: actor email is replaced with `anon-<hash>`.

The request is filed as a GH issue titled `retention: anonymise <handle>`; maintainer processes within 30 days. Completed anonymisations are noted in the next monthly retro's retention subsection.

Anonymisation is irreversible. Contributors are told this before they file the request.

---

## 5. Special cases

- **Secret exposure.** If a secret hits the log unredacted, the row is redacted in place (text file sed) and the incident triggers a post-mortem per [post-mortem.md](post-mortem.md). The original exposure remains in git history and in any off-box copy (backups, operator shells); rotation of the leaked key is mandatory.
- **Pre-commit scan outputs** containing matched secrets: `secrets_scan.py` prints the file and the line, NOT the secret content. If a dev copy-pastes the output into a chat log, that's a human error and is handled per the secrets-exposure path.
- **Breaking-change RFCs that cite contributor handles** (as part of "who proposed the old design"): treat per §4 on anonymisation request.
- **Cross-repo data** (a consumer repo carrying playbook-authored data): the consumer's retention policy takes precedence within its own repo; the playbook's policy only governs playbook-authored files. When they disagree, the tighter policy wins unless the consumer's AGENTS.md §7 explicitly overrides with a `Why:` line.

---

## 6. Cross-references

- [memory-hierarchy.md](memory-hierarchy.md) §retention — authoritative for Hindsight bank decay rules.
- [break-glass.md](break-glass.md) §4 — `overrides.log` is kept forever; retention rationale.
- [retrospective-cadence.md](retrospective-cadence.md) — retros are retained forever; monthly retention subsection surfaces anonymisations.
- [post-mortem.md](post-mortem.md) — post-mortems retained forever.
- [incident-response.md](incident-response.md) — a retention-related incident (leak in logs) triggers the IR path.
- [role-matrix.md](role-matrix.md) §contributor — anonymisation request originates from a contributor leaving.
