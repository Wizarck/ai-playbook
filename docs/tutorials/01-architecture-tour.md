# 01 — Architecture tour (placeholder)

> **Slice 4 placeholder**: this is the canonical cold-start entry point.
> Slice 7 (v0.18.x) writes the full 15-minute tutorial content (Diátaxis
> tutorial style with Mermaid diagrams + step-by-step walkthrough).

For now, see:

- [`README.md`](../../README.md) — top-level project overview
- [`docs/concepts/enforcement-layers.md`](../concepts/enforcement-layers.md) — L1/L2/L3 model
- [`docs/concepts/taxonomy.md`](../concepts/taxonomy.md) — vocabulary glossary
- [`docs/tutorials/02-quickstart.md`](02-quickstart.md) — quick-start

## What this tour will cover (Slice 7)

1. Repo layout at a glance (`docs/` / `scripts/` / `schemas/` / etc.)
2. The L1/L2/L3 paired-enforcement model
3. The slug pairing convention (D3)
4. How rules are loaded per LLM (Cursor / Claude / Gemini)
5. The dispatcher daemon design (≤50ms SLA per D10)
6. The validator chain (`validate_pairing` + `check_link_integrity` + `check_doc_language` + `check_agents_md_size`)
7. The Slice 6 telemetry pipeline (post-v0.18.x)
