# Runbook — remove dead code without losing it

Turn a `sweep` ledger into deletions you can undo. Roughly thirty minutes for a
first batch, most of it spent reading, which is the point.

**Prerequisite:** an adopted `sweep.yaml` and a green probe gate. If probes are
failing, stop — the resolver is wrong and every finding below it is unreliable.
See `skills/sweep/SKILL.md`.

---

## The shape of it

```
  scan          adjudicate         authorize            apply
  ────          ──────────         ─────────            ─────
  ledger.json → /sweep decides  →  YOU raise to    →  git rm + tombstone
  (all Tier 3)  confirm/dismiss    Tier 1 per id      (staged, not committed)
                                   ▲
                                   └── the only step that can destroy anything,
                                       and the only one a machine may not do
```

Nothing before `authorize` can lose a file, and `authorize` only edits JSON.

---

## 1. Scan a clean tree

```bash
git status --porcelain          # must be empty of TRACKED changes
python .ai-playbook/scripts/sweep_scan.py scan --out ledger.json
```

The ledger records the HEAD it was computed against. Everything downstream
refuses once that HEAD moves, so do this on the commit you intend to clean —
not on a branch you are still writing.

## 2. Adjudicate

```
/sweep
```

The skill reads the ledger and rules on each row. It may `confirm` or `dismiss`;
it may not delete, may not remove a row, and may not raise anything to Tier 1.

**Read the dismissals.** They are where the interesting findings hide — a file
alive only through a webpack alias or a `COPY` in a Dockerfile is telling you
something about how the repo is wired that no import graph knows.

**Distrust clusters.** A whole directory reading as dead is nearly always a
broken resolver, not ten people abandoning ten files on one afternoon. Measured
twice on the same repo: 89 files from an unread path alias, then 10 more from a
framework preset missing an extension.

## 3. Look at each file yourself

This is the step that cannot be delegated, so give it the time.

```bash
git log --oneline -- <path>          # who wrote it, and did anything ever use it
grep -rn "<SymbolName>" --include=* .    # by NAME, not only by path
```

Ask, for each: is it reached by a string-built module name, a registry keyed by
string, a dynamic `import()`, a plugin entry point, a build config, a container
`COPY`, an operator runbook? Any yes → leave it, and say so in the row.

## 4. Authorize, one id at a time

```bash
python .ai-playbook/scripts/sweep_execute.py plan --ledger ledger.json

python .ai-playbook/scripts/sweep_execute.py authorize \
  --ledger ledger.json \
  --id orphan-app-lib-sanitizeurl-ts-4f2ac118 \
  --actor "arturo" \
  --rationale "No importer by path or by name. Not in any registry, no dynamic \
import, no build-config reference. 12 lines, unused since 2026-06-25."
```

The rationale lands on the tombstone verbatim. Write it for the person who reads
it in six months with none of today's context — name the mechanisms you checked,
not your confidence.

There is no `--all`. That is deliberate.

## 5. Apply

```bash
python .ai-playbook/scripts/sweep_execute.py apply \
  --ledger ledger.json --expect 3
```

`--expect` must equal what `plan` reported. It is your checksum, and it exists
because a previous rule in this playbook auto-deleted 623 lines of live code
from a `--quiet` hook and it went unnoticed for three weeks.

It refuses if: HEAD moved since the scan, tracked files are modified, a path is
missing, the count disagrees, or any row is not `confirm` + Tier 1 + `human`.

Then review and commit yourself:

```bash
git status
git diff --cached docs/operations/removed-code.md
git commit
```

## 6. Watch for a week

CI and the deploy that follows are the real test. If something breaks, the
tombstone row tells you exactly what to run.

---

## Restoring

```bash
grep -i sanitize docs/operations/removed-code.md
```

The row carries the command. Paste it:

```bash
git checkout a1b2c3d4e5 -- frontend/app/lib/sanitizeUrl.ts
```

The SHA is the commit **before** the removal, so the file is present there and
comes back byte-identical. Restore it, then delete its row — a tombstone for a
file that is alive again is worse than no row at all.

---

## Why there is no quarantine directory

The natural instinct is to move dead files somewhere for a while instead of
deleting them. It is worse in four ways:

- **The cost stays.** The tax is being in the tree, not being imported. A
  quarantined file is still grepped, still IDE-searched, still hit by rename
  refactors, still type-checked, still in the SBOM.
- **It can still run.** A Python module under the package tree stays importable
  wherever you park it. "Quarantined" is not "off", and believing otherwise is
  the dangerous part.
- **It kills the signal.** The value of removal is CI telling you at once that
  you were wrong. If the file still resolves, nothing breaks and the quarantine
  period proves nothing.
- **It never empties.** No trigger, so it grows — and `sweep` would report every
  file in it forever until someone excludes the directory, creating an unwatched
  region of the repo.

Git already stores the content perfectly. The only thing it lacks is
discoverability, and that is exactly and only what the tombstone file adds.

## See also

- `skills/sweep/SKILL.md` — adjudication, and why laundering is the failure mode.
- `docs/concepts/code-entropy.md` — the five axes.
- `schemas/schema-sweep-manifest-v1.json` — the ledger contract, including the
  Tier 1 rules this runbook enforces.
