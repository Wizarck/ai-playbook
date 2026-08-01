# code-entropy-taxonomy

> **Status**: SCRATCH. Satisfies branch-name-validator. openspec/changes/ gitignored — force-added.

## Why

Ponytail gates what gets written; nothing gates what quietly stops being used.
A repo can pass every preventive gate on every commit and still drift into
unreachable files, unregistered capabilities, and gigabytes nobody can account
for. Reviewing a diff answers "should this exist?"; reviewing a repository
answers "does anything still use this?" — a question about the whole graph,
not the change. No playbook artefact addresses the second question today.

Phase 0 of that work ships taxonomy and contracts only, deliberately: it is the
cheap artefact, where getting the model wrong costs an edit rather than a
rewrite of a detector.

## What

- New concept `docs/concepts/code-entropy.md` — five axes (`orphan-file`,
  `dead-symbol`, `unused-dependency`, `unwired-capability`, `disk-residue`) and
  three positions: decidability picks the enforcement mode (rule + hardrule vs
  skill; only two axes need a model at all); preventive and curative are one
  loop closed by a ratchet; never auto-delete (justified by the v0.19.29
  incident, not by principle). Axis 5 classifies by regeneration cost × value
  rather than size, so a cheap-to-rebuild artefact that provides value is
  reported *stale*, never *deletable*.
- New `specs/wiring-assertions.schema.yaml` — the assertion contract for
  `unwired-capability`: every case is *every artefact matching X is referenced
  in Z by pattern Y*, so the playbook ships the engine and the consumer ships
  its own `wiring.yaml`.
- New `specs/wiring-assertions.example.yaml` — six assertions measured against
  a real consumer tree. The precedent assertion is regression-proven against
  the historical bug it was derived from. One assertion ships `advisory`
  because it has two live findings; one requested assertion was not statically
  decidable and was substituted rather than faked.
- New `schemas/schema-sweep-manifest-v1.json` — the findings ledger. Executor
  compatibility is a field projection, not a translation. Evidence is
  structurally mandatory; adjudication cannot erase a finding.
- `enforcement-status` row at 📋 spec-only with the flip triggers.

## Release

`VERSION` → 0.20.0. Minor (1 concept + 3 contracts, no detector). Pull model.
