# Tasks — slice-7-polish

## 1. README rewrite (7.A)

- [x] 1.1 Rewrite `README.md` with hero + Mermaid + 60-sec quickstart + scope statement + doc map + badges.

## 2. Enforcement-layers diagrams (7.B)

- [x] 2.1 Add Mermaid `flowchart` diagram for L1/L2/L3 flow.
- [x] 2.2 Add Mermaid `flowchart` diagram for paired-enforcement same-rubric protocol.
- [x] 2.3 Add Mermaid `flowchart` diagram for cross-LLM degradation (Claude / Cursor / Gemini).

## 3. Academic foundations (7.C)

- [x] 3.1 Author `docs/concepts/academic-foundations.md` with 13 paper citations, each with stable URL/DOI and one-paragraph relevance.

## 4. Mkdocs + Pagefind (7.D)

- [x] 4.1 Update `mkdocs.yml` with refreshed theme/palette/features + navigation hierarchy.
- [x] 4.2 Add `scripts/build_docs.sh` (mkdocs build + npx pagefind).
- [x] 4.3 Document Pagefind requirement in README + `docs/runbooks/docs-build-deploy.md`.
- [x] 4.4 Verify `mkdocs build --strict` exits 0.

## 5. Rule use-cases matrix (7.E)

- [x] 5.1 Author `docs/concepts/rule-use-cases-matrix.md` covering every rule under `docs/rules/`.

## 6. Architecture tour polish (7.F)

- [x] 6.1 Refresh `docs/tutorials/01-architecture-tour.md` post-Slice-6 commands; add "What you can build next" section.

## 7. 10 deferred hardrules

- [x] 7.1 `alembic-migration-naming` — **full hardrule** (AST + filename regex).
- [x] 7.2 `cross-slice-additive-extension` — **full hardrule** (Alembic source regex; NOT NULL without DEFAULT).
- [x] 7.3 `migration-slot-reservation` — **full hardrule** (directory walk; duplicate-slot detection).
- [x] 7.4 `agentic-failure-catalog-schema` — **full hardrule** (validates `docs/concepts/agentic-failures.md` shape).
- [x] 7.5 `notification-channel-adapter` — **advisory downgrade** (consumer-side surface).
- [x] 7.6 `notification-level-declared` — **advisory downgrade** (consumer-side surface).
- [x] 7.7 `notification-no-secrets` — **advisory downgrade** (consumer-side surface).
- [x] 7.8 `apply-fix-contract` — **advisory downgrade** (langgraph-aiops + hitl runtime are consumer-side).
- [x] 7.9 `break-glass` — **full hardrule** (detects blocking scripts missing helper + override-none).
- [x] 7.10 `hitl-approval-pattern` — **advisory downgrade** (mutation-class DTOs are consumer-side).
- [x] 7.11 Delete `scripts/rules/deferred-hardrules.txt` (no remaining deferrals).

## 8. Release + validation

- [ ] 8.1 Bump VERSION 0.18.2 → 0.18.3.
- [ ] 8.2 CHANGELOG v0.18.3 entry.
- [ ] 8.3 `pytest tests/` green; `mkdocs build --strict` green; all validators green.
- [ ] 8.4 PR opened; STOP-FOR-REVIEW callout in PR body.
