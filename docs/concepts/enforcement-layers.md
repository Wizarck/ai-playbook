---
schema: concept/v1
slug: enforcement-layers
title: Enforcement layers (L1 / L2 / L3) — placeholder
summary: |
  Architecture explainer for the 3-layer paired enforcement model: L1
  Python hooks, L2 markdown rules, L3 GitHub Actions. Content rewrite
  scheduled in Slice 5.
---

# Enforcement layers (L1 / L2 / L3) — placeholder

> **Slice 4 placeholder**: this doc is a stub. Slice 5 (target v0.18.1)
> rewrites the content to canonical form with Mermaid diagrams and a
> per-LLM degradation matrix.

## Overview

Three coordinated layers enforce the same rule from three angles:

| Layer | Mechanism | Location | LLM target | Failure cost |
|---|---|---|---|---|
| **L1 — Hard terminal** | Python PreToolUse / PostToolUse hooks | `scripts/rules/<slug>.rule.py` | Claude Code (native) | LOW — edit-time |
| **L2 — Soft declarative** | Markdown rules read by LLM as context | `docs/rules/<slug>.rule.md` | All LLMs (Claude, Gemini, Cursor) | MEDIUM — LLM compliance |
| **L3 — Hard server** | GitHub Actions required checks | `.github/workflows/<slug>.rule.yml` | N/A (server-side) | HIGH — PR merge gate |

## Resolution protocol

When L1 and L2 disagree, **L1 is authoritative** (D8). The `.rule.md` doc
DOCUMENTS the hook; both should agree, but if drift exists, code wins.
Validator enforces byte-identical CLI invocation in the doc's
`## Process supervision` section.

## Invariant

Every L1 hook MUST have a paired L2 doc (and vice versa). Enforced via
`scripts/validate_pairing.py`. Exceptions (`paired_hardrule: null`) require
justification in [`enforcement-pairing-exceptions.md`](enforcement-pairing-exceptions.md).

## See also

- [`cross-llm-activation.md`](cross-llm-activation.md) — per-LLM activation degradation
- [`enforcement-pairing-exceptions.md`](enforcement-pairing-exceptions.md)
- [`enforcement-status.md`](enforcement-status.md)
