# Design — slice-5f-harmonization

## Goal

Close the seams introduced by Slice 5's 5 parallel sub-slices. Sub-slice 5.F is a read-only-first review pass over the merged content, plus a small set of deterministic edits and validator-tightening changes that bring the corpus into the strict-mode contract declared in the v0.18.0 plan.

## What counts as a redundancy worth deduping?

Three classes, in order of priority:

1. **Same MUST clause in two rules.** Example: `cleanup-zombies.rule.md` restating the full break-glass contract that already lives in `break-glass.rule.md`. Resolution: keep the authoritative clause once; the other rule cites it via a one-line `Per [break-glass](break-glass.rule.md)` pointer.
2. **Same example used in two concept docs.** Example: an architecture example appearing verbatim in `enforcement-layers.md` and `agent-contract.md`. Resolution: consolidate to one host concept; the other cites it.
3. **Same definition phrased twice.** Example: the term `paired_hardrule` defined in both `taxonomy.md` and `enforcement-layers.md`. Resolution: keep the definition in `taxonomy.md` (glossary); other docs link to the glossary entry.

**Not a redundancy** (do not consolidate):
- Per-rule break-glass paragraphs that name the rule's own `AIPLAYBOOK_*_SKIP` env var — each rule needs to surface its own bypass.
- Canonical block messages emitted by rules (the literal text is load-bearing for L3 grep).
- Cross-references — duplication of `[label](path)` links is intentional and helps reading paths converge.

## What counts as a tone seam worth normalising?

Three classes:

1. **RFC 2119 keywords in concept-doc bodies.** 5.B's softening script caught 102 substitutions; manual passes may have re-introduced a few. Sweep again for `MUST`/`SHOULD`/`MAY` outside code fences.
2. **Imperative voice in concept-doc bodies.** Concepts explain; they do not command. Imperative survives only when quoting a rule or a spec excerpt.
3. **Declarative voice in runbook bodies.** Runbooks are how-to (Diátaxis); the body should be a sequence of imperative steps. Declarative voice slows the reader.

## Strict-mode validator flip — change shape

`scripts/validate_pairing.py`:

- Today: `--strict` flag opts into the strict gates; default is lenient.
- Tomorrow: strict is the default. `--lenient` opts back to the Slice-4 lifeline mode.
- Migration path: any caller that needs the lenient lifeline (none expected — Slice 5 declared content rewrite complete) must add `--lenient` explicitly.

`scripts/check_link_integrity.py`:

- Today: dead links print WARN; exit 0 unless `--strict` is set.
- Tomorrow: dead links print FAIL; exit 2. `--warn-only` opts back to the legacy WARN-only behaviour.

Both validators retain their argv flags for symmetry — flipping the default does not delete the prior mode, it inverts the choice. Tests assert both shapes.

## Hardrule deferral pattern

Strict mode declares "every rule with a non-null `paired_hardrule:` MUST have the named `.py` on disk." Slice 5 left ~25 rules pointing to unimplemented hardrules — those `.py` files ship in a future slice (target Slice 6 telemetry + Slice 7 polish).

For each unimplemented hardrule, Sub-slice 5.F either:

- **Authors the stub** (≤50 LOC scaffold with `validate()`, `apply()`, CLI entrypoint) — chosen when the rubric is trivial and ships in this slice.
- **Marks the rule advisory** — `paired_hardrule: null` + `status: advisory`, plus an entry in `docs/concepts/enforcement-pairing-exceptions.md` table naming the deferral condition.

The deferral register in `deferred-strict-failures.md` tracks every advisory marking with the target slice that ships the hardrule. The register itself is owned by Sub-slice 5.F and shipped as part of this PR.

## AGENTS.md Rule Map regeneration

D3 signal #4 requires AGENTS.md to mention every rule slug. The §2 "Dispatcher index" lists a curated subset; a new §3 "Rule Map" appendix lists every `docs/rules/<slug>.rule.md` slug grouped by `status:`. Auto-generation via `gen_indexes.py` is out of scope here — 5.F hand-curates the appendix; a future slice can wire the generator.

Cap remains ≤500 lines per D14.

## Out of scope (for 5.F)

- Telemetry integration (Slice 6, v0.18.2).
- Mermaid diagrams in concept docs (Slice 7, v0.18.3).
- Full content rewrite of `01-architecture-tour.md` (Slice 7).
- Authoring the remaining 25 hardrule scripts (deferred per above).
- Auto-generation of AGENTS.md §3 (future slice).
