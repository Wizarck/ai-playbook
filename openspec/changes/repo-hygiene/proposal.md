# repo-hygiene — F2 of the code-entropy campaign

## Why

`docs/concepts/code-entropy.md` splits repo rot into five axes and shows that
decidability, not importance, decides the enforcement mode. F1 shipped the one
decidable axis that is about *reachability* (4, `unwired-capability`). The two
remaining decidable axes are about *waste*: 3 `unused-dependency` and 5
`disk-residue`. Both are facts, so both belong in a rule with a paired hardrule
at zero token cost. Axes 1 and 2 need judgement and stay with the `sweep` skill
(F3).

The reason this needs an engine rather than a one-line check is that **both
obvious detectors were measured against geeplo and both were wrong**:

- `declared − imported` produced 16 candidates and all 16 were false positives,
  in five categories (console script, plugin entry point, driver chosen by DSN,
  feature extra, implicit at deserialisation). The dangerous one is
  `scikit-learn`: nothing imports it, it loads when `joblib.load()` deserialises
  a vendored pipeline. Acting on the naive signal deletes it and breaks piracy
  detection only when that path runs.
- The artefact's own mtime produced a permanent false STALE, because a
  well-behaved generator leaves unchanged output untouched to preserve caches.
  `graphify update .` rewrites only `manifest.json`.

So the contract models *used* as a **disjunction of declared channels** and
*fresh* as a **declared signal**. Both are consumer data; the engine ships once.

## What changes

- `scripts/rules/repo-hygiene.rule.py` — the generic engine, executing
  `specs/repo-hygiene.schema.yaml`.
- `specs/repo-hygiene.schema.yaml` — the field-by-field contract.
- `docs/rules/repo-hygiene.rule.md` — the paired rule doc.
- `tests/test_repo_hygiene.py` — 56 cases, including the two negative controls.
- `scripts/rules/_rule_kit.py` — the primitives shared with `capability-wiring`,
  extracted rather than copied into a second engine.
- `repo-hygiene` pre-commit hook in the consumer template (no-op without a
  `repo-hygiene.yaml`).

## Acceptance

1. An import-only check flags `uvicorn`; declaring the console-script channel
   clears it, and a genuinely unused package is still caught.
2. Freshness anchored on the payload reports STALE; anchored on the signal the
   generator always rewrites, it reports fresh — on the same tree.
3. The engine contains no delete path, asserted structurally against its source.
4. Against geeplo's real tree: 44 of 46 dependencies proved, the 2 remaining
   findings genuine, run time under 2 s.

All four verified before merge.

## Non-goals

Deletion of anything, under any flag. This rule reports; a human decides — the
`cleanup-zombies` v0.19.29 Tier-1 auto-delete destroyed 623 lines of live code.
Also out of scope: orphan files and dead symbols (axes 1 and 2, F3), and
transitive dependency health (CVEs, licences, lockfile skew), which needs a
resolver and a network while this engine is static and offline.
