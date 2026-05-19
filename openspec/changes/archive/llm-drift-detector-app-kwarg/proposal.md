# proposal — `llm-drift-detector-app-kwarg`

> **Status**: in-flight (slice/`llm-drift-detector-app-kwarg`).
> **Wave**: ai-playbook v0.13.0 candidate (additive MINOR).
> **Authored**: 2026-05-13.
> **Parent project**: `Wizarck/consumer-d` `openspec/changes/add-litellm-enforcement/` — this playbook PR satisfies the playbook-side of T7 (drift detector) of the cost-by-tag-dashboard Phase 1, specifically T7.5 (application= kwarg check) and T7.8 (CI warn-only step).

## Problem

`scripts/verify_llm_routing.py` (shipped in v0.9.x) flags direct-SDK callers (`import anthropic`, `import openai`, `ANTHROPIC_API_KEY` env reads). That covers half of the `llm-routing` capability spec — routing through `_llm.call(...)`.

The second half — every `_llm.call(...)` MUST carry an explicit `application=` kwarg or rely on `AIPLAYBOOK_APPLICATION` env — is currently unenforced. After v0.12.0 added the `application` parameter, nothing prevents new callers from silently shipping with `metadata.application = null`, which would render in the cost-by-application widget (Phase 3) as an "untagged" bucket.

## Proposed change

Extend the drift detector with an AST-based scan that flags `_llm.call(...)` invocations missing `application=`. AST is required because real call sites span multiple lines; line-by-line regex would miss them. The check tracks file-local import aliases (`from ._llm import call as _llm_call`), handles attribute-chained calls (`scripts._llm.call(...)`), and respects the existing `# llm-routing-allow: <reason>` inline whitelist.

| Surface | Change |
|---|---|
| `scripts/verify_llm_routing.py` | New `_scan_file_ast` + `_collect_llm_bindings` + `_is_llm_call`. New rule `missing-application-kwarg`. CLI hint differentiates direct-SDK findings from missing-application findings. Header docstring documents the new rule. |
| `tests/test_llm_helper.py` | 9 new `test_scan_*` tests (clean-tree updated, plus 8 new: missing/explicit/multiline/aliased/inline-allow/kwargs-splat/excludes-_llm.py/chained-attr). 26/26 passing. |
| `.github/workflows/test.yml` | New "Drift detector (warn-only)" CI step running `python -m scripts.verify_llm_routing` on every PR. Warn-only — exit 0 even on findings. |

## Decisions

- **D1** AST scan is line-cost-acceptable. ast.parse runs in O(n) per file; the project is <10k Python LOC. Adds <200ms to the existing scan loop in practice.
- **D2** Default `module_aliases = {"_llm"}` even when the file lacks an explicit import. Reason: in practice every caller uses one of `from scripts import _llm`, `from x import _llm`, or `_llm = ...`. Setting the default avoids false negatives when an unusual import shape escapes the AST walker.
- **D3** `**kwargs` splat skips the check. Static analysis cannot see whether the dict carries `application`. False positives here would push devs toward `# llm-routing-allow:` annotations everywhere, which dilutes the inline-allow signal. Better to under-flag than over-flag in v1.
- **D4** Warn-only at both pre-commit AND CI. The helper-side runtime enforcement (raise `LLMConfigError` on `application=None` + no env) lands in a separate v0.14.x change once 30 days of clean CI elapse. Mirrors the existing direct-SDK ratchet (D3.5 in parent).

## Acceptance

- [x] `verify_llm_routing.scan(...)` returns a `missing-application-kwarg` finding for `_llm.call(...)` without `application=`.
- [x] AST scan correctly handles aliased imports (`from ._llm import call as _llm_call`), attribute chains (`scripts._llm.call(...)`), and multiline call sites.
- [x] Inline allow `# llm-routing-allow: <reason>` whitelists missing-application findings on the call's start OR end line.
- [x] `# llm-routing-allow: env-fallback` documented in CLI hint as the canonical comment for callers relying on `AIPLAYBOOK_APPLICATION` env.
- [x] 26/26 tests in `tests/test_llm_helper.py` pass (17 existing + 9 new).
- [x] `verify_llm_routing` self-scan on playbook tree reports 0 findings (the playbook's only `_llm.call(...)` site — `prompt_injection_filter.py` — already passes `application="prompt-injection-filter"` per v0.12.1).
- [x] New CI step in `.github/workflows/test.yml` runs the detector in warn-only mode on every PR.
- [ ] CHANGELOG.md v0.13.0 entry.
- [ ] v0.13.0 cut after merge (separate PR via `propagate_bump.py`).

## Cross-references

- Parent project: [Wizarck/consumer-d PR](https://github.com/Wizarck/consumer-d) — cost-by-tag-dashboard project, Phase 1, T7 of `add-litellm-enforcement`.
- Capability spec (consumer-d): `openspec/changes/add-litellm-enforcement/specs/llm-application-tag/spec.md` §"Drift detector enforcement".
- Helper extended: [`scripts/verify_llm_routing.py`](../../../scripts/verify_llm_routing.py).
- Previous wave: [`openspec/changes/llm-application-tag/proposal.md`](../llm-application-tag/proposal.md) (v0.12.0 — added the `application` parameter being enforced here).
