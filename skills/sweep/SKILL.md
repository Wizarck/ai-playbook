---
name: sweep
description: Use when the user wants to find code that has quietly stopped being used — types /sweep, asks for a "dead code sweep", "repo entropy", "what can we delete", "orphan files", "unused code", or asks to review a sweep ledger. Adjudicates candidates a deterministic scanner already produced; it never deletes anything and never re-derives findings from raw source. Pairs with ponytail, which gates what gets written rather than what rots.
license: MIT
metadata:
  author: ai-playbook
  version: "1.0"
---

# sweep — adjudicate repo entropy, never delete it

You are reviewing a ledger, not searching a repository.

`scripts/sweep_scan.py` has already done the deterministic half: it resolved
imports through the project's own module-resolution config, applied the
entry-point conventions of the declared frameworks, and produced one row per
unreachable file with typed evidence. Your job is the half a scanner cannot do —
decide whether each candidate is genuinely dead, or is reached by something
static analysis cannot see.

## Read this before you adjudicate anything

**Your failure mode is laundering.** Measured on a real repository: a naive
resolver that ignored `tsconfig.json` path aliases reported 89 live files as
dead, including the application's own layout and auth provider. A model
adjudicating that output would have produced 89 fluent, confident, wrong
rationales — converting a resolver bug into reasoned ledger rows that look like
analysis.

So the first question is never "is this file dead?" It is **"do I believe this
scan at all?"**

- The scanner refuses to emit a ledger unless the consumer's declared `probes` —
  files known to be live — all read as reachable. If you are holding a ledger,
  that gate passed.
- **A passed gate is not a clean bill of health.** It proves the resolver works
  for the paths the probes exercise, and nothing more. On the same repository, a
  second run reported ten live modals in one directory as orphans: the framework
  preset listed `page.tsx` but not `page.js`, so the routes above them were not
  entry points. All six probes were `.tsx` files reached through `.tsx`
  importers, so every one of them passed. If the repo is half-migrated, or spans
  languages, ask whether the probes actually cover the mechanism a cluster
  depends on.
- If findings cluster suspiciously (an entire directory, every file of one
  extension, a whole framework's worth of components), suspect the RESOLVER
  before you suspect the repo. Say so, and stop. A missing preset or an unread
  path alias explains a cluster; twenty independent developers abandoning one
  directory does not.

The mechanisms that have actually produced false orphans, in order of how often
they bite: an unread path alias, a missing entry-point extension, an importer
the config never parsed, a resolution rule outside the language (a webpack
`resolve.alias`, a `COPY` in a Dockerfile, a dynamic `import()`).

## What you may and may not do

The ledger schema (`schemas/schema-sweep-manifest-v1.json`) enforces most of
this; the point of restating it is that you should not want to do it either.

- **You may not delete, move, or edit any file.** Producing an adjudicated
  ledger is the whole of the job. Execution is a separate, explicit human step.
  A previous auto-delete in this playbook destroyed 623 lines of live code, from
  a `--quiet` hook, and went unnoticed for three weeks.
- **You may not remove a row.** There is no `delete` decision. The weakest thing
  you can do to a finding is `dismiss`, which KEEPS the row at Tier 3 with a
  written rationale, so the next sweep can see it was already considered.
- **You may not edit `evidence`.** It was written once, by the detector. You
  consume it; you do not revise it.
- **You may not escalate to Tier 1.** Delete authority requires a human. Your
  escalations cap at Tier 2/3.
- **Every decision other than `confirm` requires a rationale**, and the rationale
  must name the MECHANISM, not the feeling. "Looks unused" is not a rationale.
  "Loaded by `next/dynamic` in `app/(ops)/page.tsx:26`" is.

## When a finding carries `unfinished_commitments`

Stop. This row does not mean what the others mean.

`evidence.unfinished_commitments` is a count of undischarged obligations the
scanner found in the file — unticked task boxes, `TODO`, "still required", "MUST
TEAR DOWN". A stranded document that owes work is not entropy. It is **an
obligation with no watcher**, and it is more dangerous than a dead file, because
deleting it destroys the only record that the work exists.

Measured on a real repository, two of these were live: a `PROGRESS.md`
unreferenced at the repo root for four weeks, owing a teardown of seed data in a
customer's production Google Workspace; and a security remediation checklist with
eight unticked P0 items including credential rotation.

So:

- **Never `confirm` such a row for removal.** The executor refuses it anyway, but
  you should not want to: your recommendation would be to delete a promise.
- **Read the commitments and report them as the finding.** The interesting output
  is not "this file is unreferenced", it is "these N obligations are unowned, and
  here is what they are". Quote them.
- **The fix is to MOVE the obligation**, not the file — into a ticket, a runbook,
  or the deferred-items ledger, wherever this project actually watches work. Once
  it has an owner, the marker leaves with it and the next scan clears the row
  honestly.
- An unticked box that is genuinely done and was never ticked is still a finding:
  the record is wrong, and a record nobody maintains is one nobody can trust.

## How to adjudicate one finding

Work from the evidence, then look for the thing the scanner structurally cannot
see. In order:

1. **Read `evidence.locations` and `evidence.search_scope`.** "Nothing
   references it" is only as strong as where the scanner looked. If the subject
   lives outside the searched scope, that is a `dismiss` with the scope named.
2. **Search for the subject by NAME as well as by path**, and read the hits.
   A dynamic import, a lazy `next/dynamic`, a string-built module name, a
   registry keyed by string, or a plugin entry point all reference a file
   without an import statement. Any of these → `dismiss` (or `downgrade` if
   partial), naming the file and line.
3. **Check whether it is a deliberate surface**: a public API re-export, a
   fixture, a template rendered by path, a script an operator invokes, a
   documented escape hatch. These are alive by contract, not by import.
4. **Check for a twin.** A file with a same-named sibling elsewhere is often
   half of a duplication where only one copy is wired. That is a REAL finding
   and usually a more interesting one than a lone orphan: the two copies drift,
   and fixes applied to the live one never reach the dead one. Link them with
   `related_ids`.
5. **Only then confirm.** A `confirm` means: the evidence stands, and you looked
   for the four things above and found none.

Cluster related rows with `related_ids` so one root cause reads as one problem
rather than as ten.

## What you write

Add the `adjudication` block to each row, in place, leaving `evidence`
untouched:

```json
{
  "decided_by": "llm",
  "decision": "dismiss",
  "tier": 3,
  "decided_at": "2026-08-02T11:04:00Z",
  "model": "<your model id>",
  "rationale": "Reached by `next/dynamic(() => import('./BulkDeleteModal'))` in app/(app)/(modules)/group-management/page.tsx:31, which the static resolver cannot follow. Not an orphan; the scan is correct that no import statement names it."
}
```

Then report to the user, in this order: how many findings, how many you
confirmed, how many you dismissed and why in one line each, and any cluster you
suspect is a resolver artefact rather than real entropy.

Close with the one question the ledger cannot answer: which of the confirmed
findings the user actually wants to act on. Do not act on it yourself.

## When to fire

- User types `/sweep`, or asks for a "dead code sweep", "repo entropy check",
  "what can we delete", "orphan files", "unused code".
- User asks you to review or adjudicate an existing sweep ledger.
- A monthly cadence reminder fires. Entropy is a slow variable; scanning it more
  often than it changes is how a detector gets disabled.

## When NOT to fire

- **Mid-feature.** A file added in the current branch and not yet wired is
  work-in-progress, not entropy. Sweep against a merged tree.
- **On a dirty worktree.** `scan.dirty_worktree` in the ledger tells you; a
  half-written import can make a live file look orphan. Discount accordingly and
  say so.
- **For the decidable axes.** Unused dependencies, unwired capabilities and disk
  residue have deterministic rules that run at zero token cost
  (`repo-hygiene`, `capability-wiring`). Do not re-derive their findings by
  hand — read their output.

## See also

- `docs/concepts/code-entropy.md` — the five axes and why only two need you.
- `schemas/schema-sweep-manifest-v1.json` — the ledger contract, including every
  constraint above expressed as schema.
- `docs/rules/cleanup-zombies.rule.md` — the tier semantics, and the executor
  that acts on a ledger once a human authorises it.
- `skills/ponytail/SKILL.md` — the preventive twin: it gates what enters a diff,
  this adjudicates what rotted after it landed.
