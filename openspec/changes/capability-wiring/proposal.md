# capability-wiring — F1 of the code-entropy campaign

## Why

`docs/concepts/code-entropy.md` splits repo rot into five axes and shows that
decidability, not importance, decides the enforcement mode. Axis 4,
`unwired-capability`, is decidable: a capability is either named in its registry
or it is not. It therefore belongs in a rule with a paired hardrule at zero
token cost, not in a judgement-calling skill.

The precedent is geeplo `47717de3`. `emit_liveness_heartbeat` existed, was
imported, and had a `beat_schedule` entry — but no `task_routes` entry. Beat
published it to `default` instead of `scheduled`. Nothing was missing; nothing
failed to import; one line of registry was absent.

## What changes

- `scripts/rules/capability-wiring.rule.py` — the generic engine. Executes
  `specs/wiring-assertions.schema.yaml`, which was shipped spec-only in v0.20.0.
- `docs/rules/capability-wiring.rule.md` — the paired rule doc.
- `tests/test_capability_wiring.py` — 69 cases, including the hermetic
  reproduction of `47717de3` and the negative control proving the naive regex
  false-greens on it.
- `capability-wiring` pre-commit hook in the consumer template (no-op without a
  `wiring.yaml`).

## Acceptance

1. Run against geeplo `47717de3^` → exit 1 naming `emit_liveness_heartbeat`.
2. Run against geeplo `HEAD` → exit 0 for that assertion.
3. The six assertions in `specs/wiring-assertions.example.yaml` reproduce their
   documented population / referenced / finding counts against the real tree.

All three verified before merge.

## Non-goals

Deletion of anything. This rule reports a missing wire; it never proposes a
removal. Axes 1, 2, 3 and 5 are F2 and F3.
