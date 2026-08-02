# markdown-reachability — the obligation nobody is watching

## Why

Sweep covered code and stopped there. The first consumer's repo root held
nineteen markdown files that no scan had ever looked at, and reading them by hand
turned up something the code axes cannot express:

`PROGRESS.md`, unreferenced at the repo root for four weeks, carrying
**"Prod source teardown still required"** for seed data written into a customer's
PRODUCTION Google Workspace. And a security remediation checklist with **eight
unticked P0 items**, credential rotation among them.

Neither is entropy. A dead file costs a reader; these cost a promise. And the
naive fix — delete the stranded files — would have destroyed the only record
that the work exists.

## What changes

**A `markdown` language.** A document is reached by a LINK, so it gets its own
resolver rather than being bolted onto a code one: inline `[x](y)`, reference
definitions, raw `href=`, anchors stripped, directory links resolving to the
section index. The `docs-index` preset makes `README.md` and `**/INDEX.md` entry
points, because a documentation tree is entered at its index.

**`evidence.unfinished_commitments`.** A count of undischarged obligations —
unticked task boxes, `TODO`/`FIXME`, "still required", "MUST TEAR DOWN".
Deliberately NOT RFC-2119 `MUST`, which is normative prose in every spec and
would fire on all of them.

**`sweep_execute.py` refuses to delete a file that owes work**, even when a human
authorised it. That is the one refusal a signature cannot override, because the
signature is on the wrong question: not "may this be deleted" but "has this debt
found an owner". Once it has, the marker leaves with it and a re-scan clears the
row honestly.

## Two limits, stated rather than discovered later

- **Prose is legitimately unlinked far more often than a module is legitimately
  unimported.** Notes and reports are written to be read once. Measured: 41 of
  111 documents unreferenced, versus 10 of 1674 source files. So a markdown root
  starts report-only, behind its own baseline, and `allow` earns its keep here
  more than anywhere else.
- **A document can be reached from CODE** — a template resolved by id — and no
  link graph sees that. Those belong in `entrypoints`, exactly like an Alembic
  migration. Measured: 57 of the consumer's 58 backend markdown files are
  notification templates.

## Acceptance

1. A document is reached through its index; an unlinked one is reported.
2. A link to a directory resolves to that directory's index.
3. Inline, anchored, reference-style and raw-HTML links all count.
4. An external URL is not an edge.
5. A template declared in `entrypoints` is not a finding.
6. A stranded file carrying any commitment marker reports the count.
7. RFC-2119 `MUST` prose does NOT count; a ticked box does NOT count.
8. `sweep_execute apply` refuses a commitment-bearing row even when authorised.

All eight verified. 80 sweep tests.

## Non-goals

Gating on the markdown count anywhere yet. The false-positive profile is
genuinely worse than for code and has to be measured on a real tree before it
freezes a number — the same order every other axis in this campaign followed.
