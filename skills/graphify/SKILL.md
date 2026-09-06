---
name: graphify
description: Use when navigating an unfamiliar codebase, tracing how code connects (callers, dependencies, the blast radius of a change), or whenever the repo ships a graphify-out/graph.json knowledge graph. Query the graph before grepping/reading raw source for orientation.
license: MIT
metadata:
  author: ai-playbook
  wraps: "Graphify — Apache-2.0, (c) 2026 Safi Shamsi and the Graphify contributors"
  notice: ../../NOTICE
  version: "1.0"
---

# graphify — knowledge-graph code navigation

graphify ([safishamsi/graphify](https://github.com/safishamsi/graphify), PyPI `graphifyy`) parses a repo into a structured knowledge graph — nodes are files/functions/classes, edges are imports/calls/inheritance — plus community clustering and a semantic label layer. Querying the graph returns a small, structurally-precise subgraph instead of a pile of raw file reads, so orientation costs far fewer tokens and round-trips.

## When to use

Act only when `graphify-out/graph.json` exists in the repo. Reach for graphify FIRST (before grep/read) when the task is orientation or structure:

- "How does <subsystem> work / where is <concern> handled?"
- "Who calls / what depends on <symbol>?" — blast radius before a change.
- "What is the path between <A> and <B>?"
- Onboarding to an unfamiliar area of the repo.

If `graphify-out/graph.json` is absent, graphify is not set up here — fall back to normal search.

## Commands

- `graphify query "<question>"` — scoped subgraph for a natural-language question. The default entry point.
- `graphify explain "<concept>"` — focused view of one concept/community.
- `graphify path "<A>" "<B>"` — the relationship chain between two symbols.
- `graphify update .` — re-parse changed files into the graph (AST-only, no API/token cost). Run after editing code so the graph stays fresh.
- `graphify-out/wiki/index.md`, if present, is good for broad navigation.
- `graphify-out/GRAPH_REPORT.md` — read only for a broad architecture pass when query/path/explain do not surface enough.

## Discipline

- **Query-first.** On a code-exploration task, run `graphify query` before raw grep/read. Grep AFTER the graph has oriented you, or to modify/debug specific lines.
- **Pass it down.** Include the query-first instruction in any subagent prompt that explores code.
- **Update-after-edit.** After changing code, run `graphify update .` so the next session's map is correct. A stale graph misleads.

## When NOT to use

- Editing a file you already know — go straight to it; graphify adds overhead.
- Prose/document Q&A with no code structure — graphify is structural, not a text-similarity RAG.
- The graph is stale or absent — regenerate (`graphify update .`) or fall back to grep; never trust a stale map.

## Boundaries

- graphify is a navigation aid, not a source of truth — verify a claim against the actual code before asserting it (the graph can lag the working tree).
- It complements, not replaces, grep/read for line-level work.

## Setup

Once per clone: `uv tool install "graphifyy>=0.8.31"` (or pipx) + `graphify hook install`. See [docs/runbooks/graphify-setup.md](../../docs/runbooks/graphify-setup.md). The `graphify-adoption` rule enforces the gitignore + merge-driver hygiene that keeps the committed graph portable across machines.

## See also

- [docs/concepts/graphify.md](../../docs/concepts/graphify.md) — what the graph is + graphify vs RAG.
- [docs/rules/graphify-adoption.rule.md](../../docs/rules/graphify-adoption.rule.md) — multi-dev portability invariants.
- [docs/runbooks/graphify-setup.md](../../docs/runbooks/graphify-setup.md) — install / hook install / troubleshoot.
