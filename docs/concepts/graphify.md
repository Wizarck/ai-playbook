---
schema: concept/v1
slug: graphify
title: graphify — committed code knowledge graph
summary: |
  graphify parses a repo into a structured AST knowledge graph (nodes =
  symbols, edges = imports/calls/inheritance) committed under graphify-out/.
  Agents query it for structural orientation — callers, dependencies, blast
  radius — at a fraction of the tokens of raw grep/read. Distinct from a RAG:
  graph traversal over structure, not embedding similarity over text chunks.
last_validated: "2026-06-15"
---

# graphify — committed code knowledge graph

## Why

Agent orientation in an unfamiliar codebase is expensive: grep → read → grep →
read burns input tokens and context window, and raw search misses cross-file
relationships (who calls whom, what a change ripples into). graphify front-loads
that structure once into a committed graph so every later query is a cheap,
precise traversal instead of a broad file sweep.

## What it is

[graphify](https://github.com/safishamsi/graphify) (PyPI `graphifyy`, CLI
`graphify`) parses each file's AST into a knowledge graph:

- **Nodes** — files, functions, classes, symbols.
- **Edges** — imports, calls, inheritance, references.
- **Communities** — clustered related code, with a semantic label layer.
- **God nodes** — highly-connected central nodes (likely architectural hubs).

Output lives under `graphify-out/`: `graph.json` (the graph), `manifest.json`
(per-file hashes for incremental rebuild), `GRAPH_REPORT.md` (human/agent
report), plus label/semantic sidecars. Builds are AST-only — no LLM calls, no
token cost — and incremental: `graphify update .` re-parses only changed files.

## graphify vs a RAG

They solve different problems and are complementary, not competitors.

| | graphify | RAG |
|---|---|---|
| Stores | Structured graph (symbols + relationships) | Text chunks → embedding vectors |
| Retrieves by | Graph traversal (callers, paths, communities) | Vector similarity (nearest chunks) |
| Answers well | "What breaks if I change X?", "who calls X", "path A→B" | "which passage talks about X" |
| Blind to | Free prose outside code | Code structure (call/dependency graph) |
| Determinism | Deterministic (from the AST) | Probabilistic ranking |
| Infra | One committed JSON + a CLI; zero infra | Vector DB + embedding pipeline + hosting |

Rule of thumb: **a RAG answers "what text is similar to my question?"; graphify
answers "how is the code connected?"** Use graphify for structural navigation
and impact analysis; use a RAG for fuzzy natural-language search over prose. A
graphify graph also carries a semantic label layer, so it is a hybrid — but its
core value is the structure a RAG lacks, with no infra to run.

## Multi-dev portability

`graphify-out/` is meant to be committed so the whole team shares one map. Two
mechanisms make that safe across machines:

- **Relative paths (graphifyy ≥ 0.8.31)** — the graph stores relative paths and
  re-anchors on load, so it is portable across clones. Earlier versions baked
  absolute machine paths in; that is the version floor.
- **Union-merge driver** — `graphify hook install` registers a git merge driver
  that union-merges `graphify-out/graph.json`, so parallel graph updates from
  different developers do not collide on the multi-MB JSON.

Per-machine / per-run state (`.graphify_python`, `.graphify_uncached.txt`,
`cost.json`, `cache/`, dated snapshot dirs) MUST stay untracked — it leaks one
developer's absolute paths and rebuilds locally for free. The
[graphify-adoption rule](../rules/graphify-adoption.rule.md) enforces this.

## When to use it

- Orientation in an unfamiliar subsystem.
- Impact analysis / blast radius before a change.
- Tracing relationships (callers, dependency chains) that grep cannot follow.

Not for: editing a file you already know (go straight there), or prose Q&A (use
a RAG).

## See also

- [../rules/graphify-adoption.rule.md](../rules/graphify-adoption.rule.md) — portability invariants (gitignore + merge driver + version floor).
- [../runbooks/graphify-setup.md](../runbooks/graphify-setup.md) — per-clone install + hook install + troubleshooting.
- [../../skills/graphify/SKILL.md](../../skills/graphify/SKILL.md) — the agent-facing usage skill.
