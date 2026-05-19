# Design — slice-7-polish

## Scope discipline

Slice 7 is a polish-and-close slice. NEW concept docs ship under `docs/concepts/`; rewrites are tightly scoped. The 10 hardrule pickups are short (≤100 LOC each), pure-Python, dependency-light (regex / yaml / AST). The Pagefind integration is a post-build step — the `search` plugin already in mkdocs is the runtime fallback.

## Mermaid diagrams

Three diagrams ship in `docs/concepts/enforcement-layers.md`:

1. **L1/L2/L3 flow** — tool call enters; PreToolUse hook fires (L1); on allow, the LLM proceeds and self-checks (L2); at PR merge time, the workflow re-runs the same rubric (L3).
2. **Paired enforcement** — same rubric, three enforcers: the rule doc / the hardrule script / the workflow file. Arrows show L1 wins on disagreement (D8).
3. **Cross-LLM degradation** — Claude (native PreToolUse) gets all three layers; Cursor (`.mdc` activation) gets L2 + L3 + cursor-specific activation; Gemini (no native hook) gets L2 + L3 only.

## 10 hardrule pickup strategy

Each rule gets either a full hardrule script + ≥3 tests, OR an advisory downgrade with rationale and `paired_hardrule: null`. The decision per rule:

| Slug | Decision | Rationale |
|---|---|---|
| `alembic-migration-naming` | Full hardrule | AST + filename regex; validates `revision = "<NNNN>_<topic>"` matches the filename stem. |
| `cross-slice-additive-extension` | Full hardrule | Regex on Alembic migration source; rejects `ADD COLUMN ... NOT NULL` without `DEFAULT`. |
| `migration-slot-reservation` | Full hardrule | Walks a migrations directory; rejects duplicate integer prefixes (slot collisions). |
| `agentic-failure-catalog-schema` | Full hardrule | Validates `docs/concepts/agentic-failures.md` has a `## 1. Failure catalog` section with unique `\`id\`` rows. |
| `break-glass` | Full hardrule | Detects blocking scripts (`sys.exit(1)`) missing both the helper import + `add_break_glass_flag` and an `OVERRIDE: none` declaration. |
| `notification-channel-adapter` | Advisory downgrade | `scripts/notifications/` lives in each consumer, not in the playbook. Condition #3 (consumer-side surface). |
| `notification-level-declared` | Advisory downgrade | `notify.send()` runtime is consumer-side. Condition #3. |
| `notification-no-secrets` | Advisory downgrade | Scan chokepoint runs inside the consumer's `notify.send()`. Condition #3. |
| `apply-fix-contract` | Advisory downgrade | `langgraph-aiops/` workflows + `hitl.request_approval` runtime are consumer-side (eligia-core, palafito). Condition #3. |
| `hitl-approval-pattern` | Advisory downgrade | Mutation-class DTOs, channel adapters, `approval_decisions` schema all live in consumer single-operator AI systems. Condition #3. |

Five full implementations + five advisory downgrades. The downgrades all share condition #3 (consumer-side surface), a new pairing-exception category introduced by Slice 7 — the rule documents a contract whose runtime lives entirely downstream of the playbook. The decision is documented in each rule body and in `docs/concepts/enforcement-pairing-exceptions.md`.

## Pagefind integration

`mkdocs-material` ships a basic search. Pagefind adds:

- Static index built post-build (`npx pagefind --site site`).
- Fuzzy / multi-word matching that scales beyond the in-memory index.
- Zero runtime JS for the index — pure static files.

Activation: `scripts/build_docs.sh` runs `mkdocs build --strict && npx pagefind --site site`. Consumers viewing the published site see Material search + a Pagefind script tag injected via mkdocs' `extra_javascript` (or a wrapper template — TBD; for v0.18.3 the script is documented as a manual post-build step; full integration is left to v0.20.0 if needed).

## Rule use-cases matrix

Hand-built (the rule corpus is 38 rows — manageable). Columns:

- `slug` — links to `docs/rules/<slug>.rule.md`.
- `L1 trigger` — extracted from the rule doc's `## Trigger` section (one or two tools).
- `L2 binding clause` — the one-line RFC 2119 imperative from the rule body.
- `L3 workflow` — which `.github/workflows/<slug>.rule.yml` validates the pair (or "—" if shared workflow).
- `Live obey-rate` — placeholder "—" with footnote "first real data lands v0.18.3 + 1 week of consumer adoption".
