## Canonical procedural format (Diátaxis how-to)

Every runbook is rewritten to the following shape. Operator finds the right section by name, not by reading prose.

```yaml
---
schema: runbook/v1
slug: <kebab-case>
description: <one-line outcome, ≤300 chars>
audience: operator | developer | reviewer
prerequisite_runbooks: [<slug>, ...]   # optional
estimated_time: <e.g., "10-30 min">
last_validated: <YYYY-MM-DD>           # optional
---
```

```markdown
# <Outcome-stating title>

## Outcome
<one-paragraph: post-runbook system state>

## When to use this
<trigger conditions>

## Prerequisites
- <prerequisite>: <verification command>

## Steps
1. **<Step name>**
   ```bash
   <command>
   ```
   Expected output: `<text>`. If different, see Troubleshooting §<symptom>.

## Verification
<final-state check>

## Troubleshooting
### Symptom: <X>
**Cause**: <Y>
**Fix**: <Z>

## Related
- [Runbook: <X>](other-runbook.md)
- [Concept: <Y>](../concepts/<slug>.md)
- [Rule: <Z>](../rules/<slug>.rule.md)
```

## Schema disjointness

`schema-runbook-v1.json` follows the D9 disjointness principle:

- **rule schema** has `paired_hardrule`, `activation`, `status` (rule-class), `triggers`, `applies_to`, `globs`, `break_glass`, `rule_bundle`.
- **concept schema** has `title`, `summary`, `tags`.
- **runbook schema** has `description` (one-liner, similar to rule's `description` field), `audience` (rule-doc and concept-doc absent), `estimated_time`, `prerequisite_runbooks` (runbook-specific).

`additionalProperties: false` on all three enforces the disjointness — a frontmatter accidentally typed for the wrong category fails validation.

## Translation policy (D6)

- All prose: English.
- Code blocks, file contents, identifiers: preserved verbatim (Spanish project / variable names where they exist).
- Proper nouns: preserved (`Wizarck`, `consumer-d`, `Arturo`).
- The pre-existing `> **Status**: ...` quoted header is removed (frontmatter replaces it).

## Link-path fix policy

Slice 4 left two dead-link patterns inherited from the `git mv`:

1. **`../docs/concepts/<slug>.md`** — legacy path. From `docs/runbooks/`, the correct path is `../concepts/<slug>.md`. Rewritten in every runbook.
2. **`../rfcs/...`** — `rfcs/` was deleted in Slice 3. References dropped or, where the design rationale moved into a concept doc, redirected.

Link integrity check (`scripts/check_link_integrity.py`) is non-strict by default; this slice drives the warning count down on the runbooks corpus.

## Length policy (D7)

Runbooks cap at 500 body lines. The current corpus is well under (longest is `onboard-new-project.md` at ~315 lines). After rewriting, most shrink by 15-30% because bilingual duplication and ad-hoc narrative are removed; sections gain structure but lose prose.

## Out of scope

- VERSION bump (5.F).
- CHANGELOG entry (5.F).
- New runbooks (5.F may add `run-telemetry-report.md` for Slice 6).
- Rewriting `INDEX.md` content beyond what `gen_indexes.py` regenerates.
- Touching `docs/rules/`, `docs/concepts/`, `docs/tutorials/` (owned by parallel 5.A/5.B/5.D).
