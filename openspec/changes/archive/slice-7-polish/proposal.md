# slice-7-polish — Polish for showcase + 10 remaining hardrules

## Why

v0.18.2 (Slice 6) shipped the telemetry pipeline and 14 of the 24 deferred paired hardrules. The remaining 10 — migrations (4), notifications (3), apply / break-glass (3) — still gate the strict `validate_pairing.py` exit when the deferred allowlist is removed. Slice 7 closes that surface AND finishes the showcase work the v0.20.0 plan deferred to the polish slice: a Mermaid-rich README, an enforcement-layers concept with diagrams, an academic-foundations references doc, a Pagefind-integrated mkdocs site, a per-rule use-case matrix, and a final polish pass on the 15-min architecture tour.

Slice 7 is the LAST slice of the v0.18.x architectural reset arc. The next gate is a user review pause; subsequent fixes ship as v0.19.x; v0.20.0 is the final cut on explicit user approval.

## What Changes

- **7.A README.md rewrite** — hero paragraph, Mermaid L1/L2/L3 paired-enforcement diagram, 60-second quickstart, explicit scope (Claude / Gemini / Cursor; others out of scope), doc map, status badges. 100–300 lines.
- **7.B docs/concepts/enforcement-layers.md** — final rewrite with ≥2 Mermaid diagrams (L1/L2/L3 flow + paired enforcement + cross-LLM degradation).
- **7.C docs/concepts/academic-foundations.md (new)** — ≥10 citations (Constitutional AI, PRM800K, Neuro-Symbolic AI, Diátaxis, AGENTS.md, Cursor .mdc, OWASP LLM01, IFEval, IFEval-Robust, ChatInject, length-vs-compliance) with stable URLs.
- **7.D mkdocs polish** — full `mkdocs-material` theme config (light/dark palette toggle, tabs/expand/suggest/highlight), Pagefind post-build integration via `scripts/build_docs.sh`, navigation hierarchy (Tutorials → Concepts → Rules → Runbooks → Telemetry → Reset Decisions → Reference), Telemetry page kept.
- **7.E docs/concepts/rule-use-cases-matrix.md (new)** — one row per rule under `docs/rules/`, columns slug / L1 trigger / L2 binding clause / L3 workflow / live obey-rate placeholder.
- **7.F docs/tutorials/01-architecture-tour.md polish** — verify post-Slice-6 commands, add a "What you can build next" section, cap at 350 lines.
- **10 deferred hardrules**: implementations OR explicit advisory downgrade with rationale; `scripts/rules/deferred-hardrules.txt` deleted.
- **VERSION 0.18.2 → 0.18.3** + comprehensive CHANGELOG v0.18.3 entry.

## Impact

- **Consumers**: zero schema break. No new mandatory frontmatter. The 10 new hardrules emit events through the existing telemetry pipeline; their L1 gating is opt-in via the consumer's hook config.
- **CI behaviour**: `validate_pairing.py` strict mode exits 0 with `deferred-hardrules.txt` deleted (no remaining deferrals). All new hardrules carry paired tests (≥3 cases each).
- **GitHub Pages**: the published site shifts from search-only to search + Pagefind static indexer; consumers reading the site see no API change.

## Versioning

VERSION bumps 0.18.2 → **0.18.3**. Per user-refined versioning 2026-05-19, Slice 7 closes the v0.18.x arc; user review opens after merge; v0.19.x is reserved for post-review fix iterations; v0.20.0 is the final cut on explicit user approval.

## STOP-FOR-REVIEW

Post-merge, do **not** auto-tag v0.19.0 or v0.20.0. Hand the session back to the user for review.
