# Tasks — slice-5b-concepts-rewrite

## Step 0 — branch + scaffold

- [x] Branch `feat/slice-5b-concepts-rewrite` cut from `main` (`d612350`).
- [x] `openspec/changes/slice-5b-concepts-rewrite/` created with `proposal.md`, `tasks.md`, `design.md`.

## Step 1 — STYLE.md exemplar

- [ ] `docs/concepts/STYLE.md` rewritten as the canonical style guide consumed by 5.A/C/D/E.
- [ ] ≤30 body lines (post-frontmatter).
- [ ] Sections: voice, RFC-2119 ban, link syntax, anchor convention, section structure, length cap.

## Step 2 — placeholder docs with real content

- [ ] `docs/concepts/enforcement-layers.md` — L1/L2/L3 architecture, D8 tie-break, paired-enforcement invariant.
- [ ] `docs/concepts/cross-llm-activation.md` — Cursor 4-mode mapping per LLM, D11 + D20 degradation matrix.
- [ ] `docs/concepts/enforcement-pairing-exceptions.md` — when `paired_hardrule: null` is allowed; entry template; audit trail.
- [ ] `docs/concepts/taxonomy.md` — alphabetical glossary, ≤80 entries, each ≤3 lines.

## Step 3 — inject v1 frontmatter (~53 docs)

- [ ] Every `docs/concepts/*.md` (excluding `INDEX.md`, `STYLE.md`) has the v1 frontmatter block at top.
- [ ] `slug:` matches filename stem exactly.
- [ ] `title:` derived from existing H1 or first descriptive sentence.
- [ ] `summary:` optional but populated when the doc has a clear one-paragraph thesis.
- [ ] Legacy `# filename.md` H1 + `> **Status**: v1.0.0` block removed (replaced by frontmatter + a clean H1).

## Step 4 — soften RFC 2119 vocabulary

- [ ] Body prose: `MUST` → `must` / `is required to`; `SHOULD` → `should` / `is recommended`; `MAY` → `may` / `can`.
- [ ] Code blocks and quoted spec excerpts preserved verbatim (RFC-2119 keywords inside ``` ``` ``` fences are allowed).
- [ ] Passages where the softening loses meaning ⇒ leave RFC 2119 intact AND flag in `flagged-for-rule-migration.md` for 5.A.

## Step 5 — flag rule-migration candidates

- [ ] `openspec/changes/slice-5b-concepts-rewrite/flagged-for-rule-migration.md` lists every passage where the normative intent genuinely belongs as a rule.
- [ ] Each entry: source path + section + 1-line rationale + suggested `docs/rules/<slug>.rule.md` filename.

## Step 6 — validation

- [ ] `python scripts/check_doc_language.py docs/concepts/` → exit 0.
- [ ] `python scripts/check_link_integrity.py docs/concepts/ --strict` → exit 0 within-concepts (cross-refs to rules/runbooks/tutorials may remain dead — those land in 5.A/C/D).
- [ ] `python scripts/check_agents_md_size.py` → exit 0.
- [ ] All `docs/concepts/*.md` frontmatter validates against `schemas/schema-concept-v1.json` (inline jsonschema check).
- [ ] `pytest tests/` green (baseline 918 + 2 e2e skipped).

## Step 7 — commit + push + PR

- [ ] Logical commits (3–6) with `Co-Authored-By: Claude Opus 4.7 (1M context)` trailer.
- [ ] Push branch + open PR with `[no-doc-impact]` tag (pure content reformat).
- [ ] PR body covers: summary, schema compliance, anchor lock, flagged-for-rule-migration count, deferred work, test plan, versioning note.
