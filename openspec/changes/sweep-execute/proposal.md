# sweep-execute — remove an adjudicated orphan, leave a tombstone

## Why

`sweep_scan.py` (v0.22.2) finds orphan files and deliberately cannot delete
them. That was correct, and it left the campaign with a ledger nobody can act on
without hand-deleting files and hand-writing the reasoning somewhere — which is
how the reasoning stops being written.

The obvious next step is a quarantine directory: move dead files somewhere safe
for a while instead of deleting them. It was considered and rejected, and the
rejection is the substance of this change.

### Why not a quarantine directory

1. **It does not remove the cost.** The tax on dead code is being IN THE TREE,
   not being imported. A quarantined file is still grepped, still searched by the
   IDE, still caught by a rename refactor, still type-checked, still in the SBOM.
   Measured on the consumer: a repo-wide rename edited a file nothing has called
   since the initial commit — moving it would not have stopped that.
2. **It can still run.** A Python module under the package tree stays importable
   from wherever it is parked; a TypeScript file stays bundleable. "In
   quarantine" is not "off", which is the most dangerous state available, because
   the name says otherwise.
3. **It destroys the signal.** The value of removal is that CI or production
   tells you immediately when you were wrong. If the file still resolves, nothing
   breaks, nothing is learned, and the quarantine period proves nothing. Make it
   unresolvable and it is equivalent to deletion — so why keep the bytes?
4. **Nothing ever empties it.** There is no trigger. It grows, and `sweep` would
   report every file in it every month until someone excludes the directory,
   creating an unwatched region of the repo: the exact opposite of the campaign.

Git is already an exact quarantine — content, path, date, author. What it lacks
is **discoverability**: nobody runs `git log --diff-filter=D` six months later
wondering whether a URL sanitiser ever existed. So this supplies only the missing
half.

## What changes

- **`scripts/sweep_execute.py`** — `plan` / `authorize` / `apply`.
- **The tombstone ledger**, default `docs/operations/removed-code.md`: one
  append-only row per removed file carrying the path, the date, the pre-removal
  SHA, who authorised it, the rationale, the originating finding id, and a
  restore command that can be pasted without thinking.
- `AGENTS.md` template row; `docs/concepts/code-entropy.md` gains the removal
  half of axes 1/2; CHANGELOG + VERSION 0.22.3.

## The safety model is the existing contract, not new invention

`schemas/schema-sweep-manifest-v1.json` (v0.20.0) already states that a Tier 1
action must not be applied once HEAD has moved, and that `human` is the only
authority permitted to authorise Tier 1. This enforces exactly that:

    deletable  <=>  decision == confirm
                    AND tier == 1
                    AND decided_by == human
                    AND scan.commit == HEAD
                    AND no tracked worktree changes

The last two together are stronger than they look: an unmoved HEAD plus a clean
index means the tree IS the tree that was scanned, so no per-file content hash is
needed to prove the authorisation still holds.

Two additions beyond the contract, both from the same precedent:

- **`--expect N`.** The operator types how many deletions they reviewed, and a
  mismatch refuses. v0.19.29 of `cleanup-zombies` shipped a Tier 1 auto-delete,
  ran it from a `--quiet` hook, destroyed 623 lines of live code, and nobody
  noticed for three weeks.
- **`authorize` is per-id, with no `--all`.** The whole point of the step is that
  a person looked at each file; a bulk flag would restore the blast radius the
  tiers exist to bound.

`apply` stages but never commits. The commit is the last checkpoint where a
mistake is still free, so it stays with the human.

## Acceptance

1. **The restore command in a generated row is executed verbatim and the file
   returns byte-identical.** This is the whole argument for deleting rather than
   quarantining; if it fails, the tombstone is a promise the repo cannot keep.
2. A Tier 3 row — what the scanner actually emits — is never deleted.
3. `decided_by: llm` at Tier 1 is refused: a model cannot authorise its own
   deletion.
4. A `dismiss`ed row cannot be authorised.
5. A moved HEAD expires the authorisation and refuses.
6. A wrong `--expect` refuses; `--expect 1` with nothing authorised is an error,
   not a quiet success.
7. Tracked worktree changes refuse; an untracked ledger does not.
8. One missing path refuses the whole batch.
9. Rows are append-only across runs, and a `|` or newline in a rationale cannot
   break the table.
10. `plan` changes nothing and names why each held row is held.
11. The CLI rejects `--all`.

All eleven verified before merge. 16 tests.

## Non-goals

Any automatic invocation. This is never a hook, never a CI job, never part of
`apply` in another tool. Also out of scope: removing the ten orphans the consumer
scan already found — the mechanism ships first and they become its first real
use, which is the same order F1/F2/F3 followed.
