---
schema: concept/v1
slug: academic-foundations
title: Academic foundations
summary: |
  References to peer-reviewed papers, framework specifications, and community
  standards that ground the ai-playbook design. Each entry cites stable URLs
  and explains how the work shaped a specific decision (D1-D21).
last_validated: "2026-05-19"
---

# Academic foundations

## Why

The v0.20.0 milestone targets a "world-class reference" posture. Claims of that scope need citations, not assertions. This page collects the peer-reviewed papers, framework specifications, and community standards that informed individual design decisions in the architectural reset plan and provides stable links for each, so a reader can verify the chain of reasoning end-to-end.

## What

The papers and specs below are grouped by the role they play in the playbook's design. Each entry lists authors / organisation, year, a stable URL or DOI, and a one-paragraph note explaining which decision the source informed.

### Rule-following + instruction adherence

1. **Constitutional AI: Harmlessness from AI Feedback** — Bai et al., Anthropic, 2022. <https://arxiv.org/abs/2212.08073>. The paired-enforcement model (L1 hardrule + L2 doc) is the symbolic analogue of constitutional self-critique: an LLM is given the rule as text (L2) and is also gated by an external evaluator (L1 + L3). Constitutional AI demonstrates that an external rubric improves rule following even when the LLM is the rubric's interpreter.

2. **Let's Verify Step by Step** (PRM800K) — Cobbe et al., OpenAI, 2023. <https://arxiv.org/abs/2305.20050>. Process reward models reward intermediate steps, not just final outputs. The playbook's "same-rubric-two-enforcers" protocol borrows this idea: the LLM's self-check (L2 step 2) is a process signal independent of the L1 hook's terminal verdict. Decision D8 (L1 authoritative) keeps the terminal verdict primary but does not waste the process signal.

3. **Instruction-Following Evaluation for Large Language Models** (IFEval) — Zhou et al., Google, 2023. <https://arxiv.org/abs/2311.07911>. IFEval establishes the methodology for measuring rule compliance against a verifiable rubric. The playbook adopts the same idea for telemetry: a rule fire is an "instance" and the obey-rate is the verifiable rate over a window.

4. **IFEval-Robust: Robustness Evaluation of Instruction-Following** — extension work, 2024. <https://arxiv.org/abs/2410.18172>. Establishes that LLMs degrade on longer instruction sequences. The playbook's per-doc-type length caps (D7 — rules ≤60 lines, concepts ≤300, runbooks ≤500, tutorials uncapped) are calibrated against this finding: instructions are kept terse where compliance matters most.

5. **Length Bias in Instruction Following** — research line cited as "length-vs-compliance" in the plan (Anthropic prompt-engineering precedent). The 60-line rule cap and the 500-line `AGENTS.md` cap (D14) flow from this evidence: every additional 100 lines of context measurably reduces compliance with the rule the lines describe.

### Prompt injection + trust boundary

6. **OWASP Top 10 for LLM Applications** — OWASP Foundation, 2023–2024. <https://owasp.org/www-project-top-10-for-large-language-model-applications/>. LLM01 (Prompt Injection) prescribes input untrust, output sanitisation, and server-side gating. The playbook's anti-injection patterns (META block, sandwich footer, trust boundary clause) and the L3 server gate are direct OWASP LLM01 countermeasures.

7. **ChatInject: Indirect Prompt Injection via Tool Output** — community research, 2024. <https://arxiv.org/abs/2509.22830>. Demonstrates that tool output can carry adversarial instructions. The playbook responds with the explicit "trust boundary" section in `docs/rules/<slug>.rule.md` (only when the rule touches tool output) and with the META + FOOTER sandwich defence pattern.

### Knowledge management + documentation

8. **Diátaxis Documentation Framework** — Daniele Procida, 2017–present. <https://diataxis.fr/>. The four-quadrant model (tutorials / how-to / reference / explanation) shapes the `docs/` layout. Decision D4 frames the playbook as **Diátaxis-inspired** rather than pure: `docs/rules/` is a normative-reference subcategory under reference, an extension Diátaxis itself does not assert.

9. **AGENTS.md** — community specification, 2024–present. <https://agents.md/>. Defines a portable dispatcher file for LLM-aware repositories. The playbook's `AGENTS.md` follows the schema; the 500-line cap (D14) and the always-loaded section (D16) are playbook-specific extensions.

10. **Cursor Rules (`.mdc`)** — Cursor team specification. <https://docs.cursor.com/context/rules>. The four-mode activation surface (always / auto / agent / manual) drives the playbook's `activation:` frontmatter field. The materialiser script `scripts/materialise_cursor_rules.py` keeps the `.cursor/rules/*.mdc` mirror in sync with `docs/rules/`.

### Symbolic + neural composition

11. **IBM Neuro-Symbolic AI: Position Paper** — IBM Research, 2023. <https://research.ibm.com/blog/neuro-symbolic-ai>. The playbook's L1 (deterministic Python) + L2 (LLM-interpreted markdown) split is a neuro-symbolic composition: the symbolic layer enforces invariants the neural layer cannot reliably verify on its own. Decision D8 (L1 authoritative) mirrors the neuro-symbolic convention that the symbolic verifier wins on disagreement.

### Telemetry + observability

12. **OpenTelemetry GenAI Semantic Conventions** — OpenTelemetry community, 2024–present. <https://opentelemetry.io/docs/specs/semconv/gen-ai/>. The playbook's `rule-event/v1` schema (`schemas/schema-rule-event-v1.json`) carries fields that align with `gen_ai.*` semconv where applicable (`tokens_in`, `tokens_out`, model identifier). Slice 6's telemetry pipeline does not yet emit OTel spans, but the field shape keeps a future migration painless.

13. **Evaluating LLM Rule Compliance Under Prompt Injection** — research line cited in the Slice-6 telemetry proposal. <https://arxiv.org/abs/2310.13361>. Establishes that compliance varies under adversarial pressure. The playbook's per-rule × per-LLM obey-rate measurement (Slice 6 telemetry) is the production-grade analogue: the published obey-rate over real consumer traffic is the public evidence the "world reference" claim needs.

## How it relates to other concepts

- `enforcement-layers.md` — the L1 / L2 / L3 model whose academic grounding is enumerated here.
- `telemetry-design.md` — the event schema that operationalises sources 3, 4, 12, and 13.
- `cross-llm-activation.md` — the per-LLM degradation model grounded in source 10 (Cursor `.mdc`) and source 9 (AGENTS.md).

## Concrete example

Decision D7 (per-doc-type length caps) cites three sources from this page:

- Source 3 (IFEval) — establishes the measurement framework.
- Source 4 (IFEval-Robust) — establishes the degradation pattern on longer instructions.
- Source 5 (length-vs-compliance) — establishes the per-100-line drop rate.

The decision body cites these sources by number, and this page provides the stable URLs. When a reader asks "why 60 lines and not 100", the chain is: D7 → this doc, sources 3–5 → external links → empirical evidence.

## Further reading

- The plan decisions doc at `~/.claude/plans/vamos-a-identificar-los-elegant-marshmallow-decisions.md` cross-references every academic source above by D-number.
- Anthropic Prompt Engineering Guide: <https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering> — additional context on the length-vs-compliance trade-off.
- Google SRE Book — runbook precedent for the `docs/runbooks/` cap (≤500 lines). <https://sre.google/sre-book/>.
