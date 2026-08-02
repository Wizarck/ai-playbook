# sweep — F3 of the code-entropy campaign

## Why

F1 and F2 shipped the three DECIDABLE axes as rules with paired hardrules. The
two remaining axes — `orphan-file` and `dead-symbol` — are the ones the taxonomy
says need judgement, because whether an unreferenced file is dead or is a plugin
entry point, a public surface, a fixture, or a dynamic-import target cannot be
settled by static reachability alone.

The measurement complicates that premise in a useful way. Against a real
consumer, a naive "not imported" scan produced **779 candidates, of which 17 were
real (2.2%)** — and the two failures that mattered were NOT judgement calls:

- ignoring `tsconfig.json` `compilerOptions.paths` (14 aliases in that project)
  reported 89 live files as dead, including the app's own layout and auth
  provider;
- counting references by NAME rather than by PATH produced a falsely reassuring
  negative, because two directories held same-named files.

So the axes are mostly decidable too, once the scanner reads the project's own
resolution config. The judgement residue is ~7 files. That reorders the work:
the value is in the scanner's fidelity, not in the adjudication layer, because a
model fed a broken scan writes fluent, confident, wrong rationales — laundering a
resolver bug into reasoned ledger rows.

## What changes

- `scripts/sweep_scan.py` — the deterministic scanner. Emits a ledger validating
  against `schemas/schema-sweep-manifest-v1.json` (published spec-only in
  v0.20.0). No delete path, asserted structurally against its own source.
- `skills/sweep/SKILL.md` — a THIN adjudication pass over that ledger. It reads
  evidence rather than re-deriving findings, may not remove a row, may not edit
  evidence, and may not escalate to Tier 1.
- `tests/test_sweep_scan.py` — 30 cases.
- `docs/concepts/enforcement-status.md` — code-entropy row `📋 spec-only` → `🟡`.

Two deliberate departures from how F1/F2 were built, both forced by the
measurement:

1. **A probe gate.** The consumer declares files it knows are live; the scanner
   refuses to emit a ledger if any reads as unreachable. It converts "I should
   have sanity-checked the resolver" into a structural failure.
2. **Entry-point conventions ship as framework PRESETS, not consumer data.**
   Which registry a project uses is irreducibly its own (F1/F2 were right to put
   that in consumer config); that pytest collects `test_*.py` is a framework
   fact. Six presets account for 762 of the 779 naive candidates.

## Acceptance

1. Dropping `resolve_from` on an aliased tree fails the probe gate, exits 1, and
   writes NO ledger.
2. The same tree with the resolver restored reports only the genuinely
   unreferenced file.
3. Same-named files in two directories do not cross-credit references.
4. The emitted ledger validates against the v1 JSON schema, empty or not.
5. Every finding is Tier 3 / `report` / `report_only`.
6. Against the real consumer tree: 20 candidates over 1567 files, probes green.

All six verified before merge.

## Non-goals

Deletion, under any flag. Also out of scope: the ratchet that freezes each axis's
number in CI — that is F4, and until it exists a cleanup campaign can silently
undo itself.
