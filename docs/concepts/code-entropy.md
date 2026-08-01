---
schema: concept/v1
slug: code-entropy
title: Code entropy
summary: |
  The curative half of code discipline. Ponytail gates what gets written;
  nothing gates what quietly stops being used. This defines the five axes of
  accumulated entropy, splits them by decidability (which decides whether a
  detector is a rule or a skill), and closes the preventive/curative loop with
  a ratchet so a cleanup campaign cannot silently undo itself.
last_validated: "2026-08-01"
---

# Code entropy

## Why

Repositories accumulate two different kinds of waste, and the playbook has only
ever addressed one of them.

The first is waste created at write time: the speculative abstraction, the
dependency that duplicates the standard library, the factory with one product.
[ponytail](../../skills/ponytail/SKILL.md) gates that at the diff, before it
lands. It is preventive, and it works.

The second is waste created by time itself. Nothing was written badly; a caller
was deleted, a feature was superseded, a registry entry was forgotten, a cache
directory grew. No diff introduced it, so no diff-scoped review can catch it.
A repository can pass every preventive gate on every commit and still drift into
a state where a meaningful fraction of its files are unreachable, several of its
capabilities are built but unregistered, and its working tree carries gigabytes
nobody can account for.

That second kind is entropy, and finding it is a different problem with
different tools. Reviewing a diff answers "should this exist?" Reviewing a
repository answers "does anything still use this?" — a question about the whole
graph, not the change.

## What

### The five axes

Entropy is not one phenomenon. Five distinct things rot, and conflating them
produces a detector that is wrong about all five:

| Axis | What accumulates |
|---|---|
| `orphan-file` | files reachable from no entry point |
| `dead-symbol` | exported or defined symbols with no consumer |
| `unused-dependency` | declared dependencies nobody imports |
| `unwired-capability` | code that was built but never registered in its registry |
| `disk-residue` | caches, build output, scratch files, stale reports |

`unwired-capability` is the axis no off-the-shelf tool covers, and the one that
produces genuine production incidents rather than untidiness. The other four
describe code that does nothing; this one describes code that was *supposed* to
do something and silently does not.

### Decidability decides the enforcement mode

The useful split is not by topic but by whether a machine can be right on its
own.

Three axes are decidable. Whether a declared dependency is imported, whether a
directory is a cache, whether a registry contains an entry for a given
symbol — each is a fact, checkable by crossing two artefacts. These belong in
`docs/rules/` with a paired hardrule: they run in hooks and CI, cost no tokens,
and are deterministic enough to gate a commit.

Two axes are undecidable without judgement. Whether an unreferenced file is dead
or is a plugin entry point, a public API surface, a fixture, or a target of a
dynamic import cannot be settled by static reachability alone. These belong in a
skill, which adjudicates candidates a scanner has already produced.

The consequence is economic as well as architectural: only two of the five axes
need a language model at all, so the majority of the system runs continuously at
zero marginal cost.

### Preventive and curative are one loop

Treating curative sweeps as a periodic campaign guarantees they recur. The
entropy that a sweep removes returns, because nothing changed about the
conditions that produced it.

The loop closes with a ratchet. Every axis publishes a number; CI freezes that
number; the number may fall but not rise. A sweep that produces only a report is
a campaign. A sweep that produces a ratchet is an architecture — the difference
being that the second one cannot be undone by inattention.

The stronger form of the same idea applies per finding: when a curative finding
is resolved, the question that follows is whether it can be expressed as a
preventive assertion. An orphaned blueprint discovered by a sweep becomes a
wiring assertion that blocks the next one at pre-commit. The curative half feeds
the preventive half, and the system learns from its own residue.

### Evidence-first adjudication

Language models improve recall on these axes and worsen precision; deterministic
scanners do the reverse. The composition that works is ordered, not blended:
scanners produce candidates with typed evidence, and the model adjudicates that
evidence rather than re-deriving the finding from raw source.

Two properties follow, and both are load-bearing. A finding with no evidence is
malformed and cannot enter the ledger. And adjudication can downgrade a
deterministic finding only with a recorded rationale — a model may add findings
or reclassify one, but it cannot quietly delete a fact a scanner established.

### Never auto-delete

The ledger is the deliverable. Execution is a separate, explicit step, and the
tiers are inherited from [cleanup-zombies](../rules/cleanup-zombies.rule.md):
tier 1 is safe to delete, tier 2 is a textual change, tier 3 is report-only.

This is not caution for its own sake. The playbook has already run the
experiment: a tier 1 auto-delete entry whose safety check shared a bug with its
action handler destroyed 623 lines across 7 files of this repository, and did it
quietly, from a `--quiet` hook, for three weeks. A detector confident enough to
delete is a detector that will eventually delete the wrong thing. Emitting a
ledger costs one human decision and removes that entire failure mode.

### Regeneration cost, not size

Axis 5 is where naive detectors do the most damage, because size is the wrong
metric. The right one is a pair: what does regenerating this cost, and does it
provide value while it exists?

```
                REGENERATION CHEAP        REGENERATION EXPENSIVE
              ┌────────────────────────┬────────────────────────┐
  PROVIDES    │ knowledge-graph output │ node_modules/          │
  VALUE       │ framework build cache  │ virtualenvs            │
              │ → report STALENESS     │ → report STALENESS     │
              │ → never "deletable"    │ → never "deletable"    │
              ├────────────────────────┼────────────────────────┤
  PROVIDES    │ __pycache__/           │ old test artefacts     │
  NO VALUE    │ linter caches          │ soak snapshots, logs   │
              │ → tier 1               │ → archive, not delete  │
              └────────────────────────┴────────────────────────┘
```

An artefact in the top-left is the interesting case: cheap to rebuild and
valuable while current, so the finding it deserves is *stale*, never
*deletable*. A stale map is worse than no map, because it is consulted with
confidence. A detector that reports it by size recommends deleting the most
useful thing in the tree.

### A generic engine with consumer-supplied assertions

`unwired-capability` looks unshippable in a framework, because registries are
project-specific: one project registers routers in an application factory,
another registers tasks in a queue routing table, another labels channels in a
frontend constant.

They are the same sentence with different holes — *every artefact matching X is
referenced in Z by pattern Y*. The playbook ships the engine and the schema; the
consumer ships the assertions in its own `wiring.yaml`. Three fields express
every case, which is what makes the axis portable at all.

### Cadence

Entropy is a slow variable and does not deserve a fast loop. Decidable axes run
at pre-commit scoped to changed paths, and in full nightly. The undecidable axes
run on demand and on a monthly rhythm. A detector that interrupts more often
than the thing it measures changes is a detector that gets disabled.

## How it relates to other concepts

- [ponytail](../../skills/ponytail/SKILL.md) — the preventive half. Ponytail
  gates what enters the diff; this concept covers what rots after it lands. They
  compose through the ratchet rather than overlapping.
- [cleanup-zombies](../rules/cleanup-zombies.rule.md) — supplies the tier
  semantics and the execution machinery. Sweep findings are discovered by the
  consumer rather than curated upstream, but they land in the same shape so the
  same executor consumes them.
- [anti-drift-gates](anti-drift-gates.md) — the four-layer defense model this
  cadence instantiates; the ratchet-only-down guidance is the same guidance.
- [enforcement-status](enforcement-status.md) — where each axis records whether
  it is spec-only or wired.
- [agentic-failures](agentic-failures.md) — `over_confidence` is the failure this
  concept's never-auto-delete stance defends against.
- [graphify](graphify.md) — supplies the import graph that makes `orphan-file`
  detection cheap where a knowledge graph exists.

## Concrete example

A Celery task is added to a repository. It has a decorator, a queue name, tests,
and a code reviewer approved it. It is never added to the routing table, so the
queue it targets has no consumer. Nothing fails: no import error, no test
failure, no lint finding. The task simply never runs, and the feature it powers
is quietly absent in production until someone notices months later.

Each axis sees this differently, which is what makes the taxonomy worth having:

- `orphan-file` does not fire — the module is imported by the task registry.
- `dead-symbol` does not fire — the symbol is referenced by its own decorator.
- `unwired-capability` fires, because the assertion *every task decorated as a
  queue consumer is referenced in the routing table* is false for this symbol.

The assertion is three fields, the check is a regex over two files, it costs
nothing to run, and it converts a class of silent production absence into a
failed pre-commit. That is the whole argument for separating the axes: four of
them are hygiene, and one of them is a bug detector wearing hygiene's clothes.

## Further reading

- `specs/wiring-assertions.schema.yaml` — the assertion contract for
  `unwired-capability`.
- `schemas/schema-sweep-manifest-v1.json` — the ledger a sweep emits.
