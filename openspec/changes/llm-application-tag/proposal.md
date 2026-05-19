# proposal — `llm-application-tag`

> **Status**: in-flight (slice/`llm-application-tag`).
> **Wave**: ai-playbook v0.12.0 candidate (additive MINOR).
> **Authored**: 2026-05-12.
> **Parent project**: `Wizarck/consumer-d` `openspec/changes/add-litellm-enforcement/` — this playbook PR satisfies the playbook-side of T1.5+T3.4+T11+T12 of the cost-by-tag-dashboard Phase 1.

## Problem

The LLM helper `scripts/_llm.py` (shipped in v0.9.x) exposes a `consumer` parameter that maps to LiteLLM virtual-key budgets (ADVISOR, HERMES, JUDGE, WORKFLOWS, ...). This is the right dimension for **budget isolation** but the wrong granularity for **cost attribution by subsystem**.

A single consumer (e.g. `WORKFLOWS`) fans out to many functional subsystems:

```
consumer=WORKFLOWS
  ├─ aiops-workflow-vps-maintainer
  ├─ aiops-workflow-retro-generator
  └─ langgraph-doc-writer
```

Asking *"which subsystem is driving Opus cost?"* with only `consumer` collapses these into one bucket. Cost attribution downstream (per-app dashboards, per-workflow budgets, debugging *"Hermes ran up the bill, but which Hermes path?"*) becomes unanswerable.

Surfaced 2026-05-11 while scoping the cost-by-tag dashboard project in consumer-d (Phase 1 of 3). Will impact every consumer of this playbook that runs LLM calls: consumer-c, consumer-b, plus consumer-d.

## Proposed change

Add `application: str | None = None` as a kwarg parallel to `consumer`. M:M cardinality. Propagates end-to-end through OTel attrs into Langfuse trace metadata. Additive — no breaking changes to existing callers.

| Surface | Change |
|---|---|
| `scripts/_llm.py` | `call()` + `LLMResponse` gain `application`. `_resolve_application()` mirrors `_resolve_consumer()` with `AIPLAYBOOK_APPLICATION` env fallback. 4 OTel emission points propagate `ai_playbook.application`. CLI `--application` flag. |
| `docs/concepts/model-routing.md` → v2.1.0 | NEW §5 "Application tags" with canonical 7-app roster + how-to recipe + worked examples showing consumer × application M:M. §4 OTel table gains `ai_playbook.application` + `ai_playbook.consumer` rows. §5/§6 renumbered to §6/§7. |
| `docs/concepts/env-vars.md` | NEW "How to add a new consumer" recipe under §Per-consumer virtual keys. |
| `configs/litellm-router.yaml` | Top-of-file warning documenting the production-deploy mirror contract (LiteLLM accepts only ONE `--config` file → consumers must mirror task-class entries to project-local ConfigMaps). |

## Decisions

- **D1** `application` is a SEPARATE dimension from `consumer`. M:M cardinality. (Mirrors D3.8 in the parent consumer-d change.) Rationale: collapsing to single dim explodes virtual-key roster (one key per app) and breaks the LiteLLM budget abstraction.
- **D2** Backwards-compatible. `application=None` default; existing callers untouched. v0.11 → v0.12 is MINOR per semver.
- **D3** Sync test (`tests/test_litellm_config_sync.py`) lives in the CONSUMER repo, not here. It reads consumer-local paths (e.g. helm/consumer-d-stack/templates/configmaps.yaml) that don't exist in the playbook standalone.

## Acceptance

- [x] `_llm.call(..., application="dashboard-backend")` emits `ai_playbook.application` OTel attr.
- [x] `model-routing.md` v2.1.0 includes §5 Application tags with canonical roster.
- [x] `env-vars.md` includes "How to add a new consumer" recipe.
- [x] `litellm-router.yaml` top-of-file warning documents the deploy contract.
- [x] 16/16 existing `test_llm_helper.py` tests pass (backwards-compatible).
- [ ] CHANGELOG.md "Unreleased" section updated.
- [ ] v0.12.0 cut after merge (separate PR via `propagate_bump.py`).

## Cross-references

- Parent project: [Wizarck/consumer-d PR](https://github.com/Wizarck/consumer-d) — cost-by-tag-dashboard project, Phase 1.
- Spec extended: [`docs/concepts/model-routing.md`](../../../docs/concepts/model-routing.md) v2.0.0 → v2.1.0.
- Helper extended: [`scripts/_llm.py`](../../../scripts/_llm.py).
