# FEEDBACK.md

> **Status**: v1.0.0. Append-only, low-friction gripe channel. No issue, no RFC, no review required — just commit the line.

## Format

One bullet per gripe. Exact shape:

```
- YYYY-MM-DD @<handle> — <one-sentence gripe or wish>
```

Rules:

- **One issue per bullet.** If you have two gripes, write two bullets.
- **Append at the bottom.** Newest last. No editing earlier entries; annotate instead (`— triaged: promoted to RFC-N`).
- **Date is local ISO (`YYYY-MM-DD`).** Handle is your GitHub handle or email local-part.
- **One sentence.** If it takes a paragraph, file an RFC.
- **Keep it specific.** "error X at file Y said Z but the fix wasn't obvious" beats "docs are confusing".

## Triage cadence

- **Weekly** — Arturo reads this during the Monday weekly retro (per [specs/retrospective-cadence.md](specs/retrospective-cadence.md)). Recurring themes promote to issues or RFCs; one-offs stay here as evidence.
- **Monthly** — the lifecycle check (`scripts/lifecycle_check.py`, T14i) counts bullets per week and flags volume spikes (`>10/week`) as a systemic signal.
- **Triaged bullets are NOT deleted.** They are annotated in-line: `— triaged: promoted to #42` or `— triaged: dismissed (duplicate of 2026-02-18)`. The raw record is the audit trail.

## Examples of good gripes

- `2026-02-14 @arturo — schema_validate.py error message says "invalid" but doesn't tell me which frontmatter field`
- `2026-02-22 @jane — bootstrap.py fails silently on Windows when the project path contains a space`
- `2026-03-03 @arturo — mcp/render.py --dry-run prints the full YAML even when nothing changed; hard to scan diffs`

## Anti-patterns (rejected shapes)

- `- the docs are bad` — no date, no handle, no specificity. Unactionable.
- `- 2026-02-14 @arturo — the whole OpenSpec flow is broken and also MCP config is annoying and also…` — multi-issue bullet. Split.
- `- @arturo — fix bootstrap` — no date, no detail, imperative to nobody.

---

<!-- append below, newest last -->
