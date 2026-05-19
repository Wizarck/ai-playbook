---
schema: concept/v1
slug: enforcement-layers
title: Enforcement layers (L1 / L2 / L3)
summary: |
  Three coordinated layers enforce each ai-playbook rule from three
  angles: L1 Python hooks at edit time, L2 markdown rules in LLM context,
  L3 GitHub Actions at PR merge. L1 is authoritative on disagreement (D8).
last_validated: "2026-05-19"
---

# Enforcement layers (L1 / L2 / L3)

## Why

A single enforcement mechanism leaves gaps. A Python pre-commit hook (L1) catches edits at the developer's machine but not in a CI run from a fork. A markdown rule loaded into an LLM's context (L2) influences the next response but does not block a non-LLM commit. A GitHub Action (L3) gates merge but adds minutes of latency and runs after the work is already done. Pairing all three closes the holes and produces an auditable defence-in-depth posture.

The paired-layer model also addresses cross-LLM portability. Claude Code has native PreToolUse hooks; Gemini CLI does not. An L2 markdown rule is the only enforcement an LLM without hook support sees in real time. L3 is the floor for everyone.

## What

| Layer | Mechanism | Location | Targets | Failure cost |
|---|---|---|---|---|
| **L1 — Hard terminal** | Python PreToolUse / PostToolUse hooks | `scripts/rules/<slug>.rule.py` | Claude Code (native hook support) | Low — caught at edit time |
| **L2 — Soft declarative** | Markdown rules loaded as LLM context | `docs/rules/<slug>.rule.md` | All LLMs (Claude, Gemini, Cursor) | Medium — caught at LLM compliance |
| **L3 — Hard server** | GitHub Actions + branch-protection required check | `.github/workflows/<slug>.rule.yml` | Server-side (no LLM) | High — caught at PR merge |

Every L1 hook is required to have a paired L2 doc (and vice versa); the invariant is enforced by `scripts/validate_pairing.py`. Exceptions — advisory-only rules with `paired_hardrule: null` — are documented in `enforcement-pairing-exceptions.md`.

### Same-rubric-two-enforcers protocol

1. The L2 doc declares the rubric in its `## Process supervision` section: "run `scripts/rules/<slug>.rule.py validate`, expect exit 0".
2. The LLM reads the doc, performs the action, self-checks via the validator, reports the verdict.
3. The L1 hook independently implements the same rubric as a PostToolUse hook.
4. The L3 workflow runs the same validator on the PR diff.

Outcomes:

- LLM self-checks ⇒ L1 confirms ⇒ consistent.
- LLM skips self-check ⇒ L1 PostToolUse catches it.
- LLM attempts to bypass ⇒ L3 catches it at PR merge.

### Tie-break protocol (D8)

When L1 and L2 disagree, L1 is authoritative. The `.rule.md` doc documents the hook; the hook owns the truth. The validator enforces byte-identical CLI invocation between the doc's `## Process supervision` block and the actual hook entrypoint — drift is treated as a doc bug, not a hook bug.

## How it relates to other concepts

- The discriminator that decides whether a doc is a rule (L2) or a concept (this doc) is the presence of `paired_hardrule:` in the frontmatter — see `enforcement-pairing-exceptions.md` for the advisory-only escape hatch.
- Per-LLM behaviour of the L2 layer (Cursor 4-mode activation, Gemini degradation) is documented in `cross-llm-activation.md`.
- The slug regex that binds the four artefacts (`.rule.py` / `.rule.md` / test / `.rule.yml`) at a single name is documented in `taxonomy.md` under "slug".
- Current enforcement status across the rule corpus is tracked in `enforcement-status.md`.

## Concrete example

Rule `cleanup-zombies` ships four paired artefacts bound by the slug:

```
scripts/rules/cleanup-zombies.rule.py     # L1 hook + CLI validator
docs/rules/cleanup-zombies.rule.md         # L2 doc, frontmatter slug: cleanup-zombies
tests/test_cleanup_zombies.py              # fixture coverage for L1
.github/workflows/cleanup-zombies.rule.yml # L3 required check
```

A consumer commit that violates the rule triggers three independent gates:

1. The developer's pre-commit fires `scripts/rules/cleanup-zombies.rule.py validate` (L1) and refuses the commit.
2. If the developer bypasses pre-commit (`git commit --no-verify`), the next LLM session loads `docs/rules/cleanup-zombies.rule.md` (L2) and refuses to ship the change without remediation.
3. If the commit still reaches a PR, the `.github/workflows/cleanup-zombies.rule.yml` (L3) required check blocks merge.

The byte-identical invocation in the doc's `## Process supervision` block is `python .ai-playbook/scripts/rules/cleanup-zombies.rule.py validate`. The L3 workflow runs the same command. The LLM self-check (L2 step 2) runs the same command. Three enforcers, one rubric.

## Further reading

- D8 (L1 authoritative on disagreement) — see the Slice-5 plan decisions doc.
- IBM Neuro-Symbolic AI patterns for paired symbolic + neural enforcement (arXiv 2305.20050).
- OWASP LLM Top 10 — LLM01 prompt-injection countermeasures rely on L2 sandwich-defence + L3 server gates.
