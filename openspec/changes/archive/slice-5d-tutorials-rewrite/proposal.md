## Why

Slice 5.D rewrites every doc in `docs/tutorials/` into canonical Diátaxis tutorial format (learning-oriented; lead-by-the-hand, concrete actions, expected outputs), and replaces the `01-architecture-tour.md` placeholder with a complete ~15-minute cold-start tutorial for new contributors.

Slice 4 moved the legacy `docs/<tutorial>.md` files into `docs/tutorials/<NN>-<slug>.md` (history preserved via `git mv`), and Slice 5.B locked the cross-reference anchors and authored `docs/concepts/STYLE.md` as the exemplar of voice. Slice 5.D is the parallel-with-5.A/C/E pass that brings tutorials into the same shape: typed v1 frontmatter, "What you'll learn / Estimated time / Prerequisites" preamble, step-numbered sections, expected outputs, and a "What's next" footer with concrete forward pointers.

Per D4 (Diátaxis-inspired), tutorials are learning-oriented: confidence over completeness, narrative over taxonomy, hands-on over reference. Per D6 (ENGLISH mandate) every body is English. Per D7, tutorial length is uncapped — long is OK if the reader stays engaged.

The single biggest deliverable is `docs/tutorials/01-architecture-tour.md`: today a 22-line placeholder, after this slice a complete 15-minute walking tour that takes a new contributor from clone to "I understand what this repo is, what its 4 doc types are, and which command does what." It is the canonical entry point referenced from README + `02-start-here.md` + `INDEX.md`.

## What Changes

- **Add v1 frontmatter** to all 8 tutorial files (`schema: tutorial/v1`, `slug`, `title`, `description`, `estimated_time`, `prerequisite_concepts`, `audience`, `order`).
- **Renumber to avoid 01- collision**: `01-start-here.md` → `02-start-here.md`, `02-quickstart.md` → `03-quickstart.md`, ..., `07-fork-inventory.md` → `08-fork-inventory.md`. Architecture tour keeps `01-` (canonical entry per Slice 7.F + plan).
- **Rewrite `01-architecture-tour.md`** as a complete ~15-min cold-start tutorial:
  - What ai-playbook is (1 paragraph; link to `concepts/enforcement-layers.md` for L1/L2/L3)
  - The 4 doc types: rules, concepts, runbooks, tutorials (Diátaxis-inspired) with linked examples
  - Walking tour: clone, `pip install -e .`, `pytest`, `cleanup_zombies.py validate`, `check_doc_language.py docs/`, `validate_pairing.py` — what each does and what to expect
  - "What's next" pointer table to follow-up tutorials and concept docs for depth
- **Rewrite the other 7 tutorials** in Diátaxis tutorial style: lead-by-the-hand sections with expected outputs, prerequisite blocks, "What's next" footers, and corrected cross-references after the renumber.
- **No VERSION or CHANGELOG.md edits** — those are 5.F's job (the harmonization slice that bumps to v0.18.1 or higher).
- **Defer `schemas/schema-tutorial-v1.json`** to a follow-up (same decision as 5.C deferred for runbooks; flagged below). Frontmatter uses `schema: tutorial/v1` as the versioning hook so a later validator can be added without doc edits.

## Impact

- **Consumers** (5 own repos): no path breakage — file renumbering stays inside `docs/tutorials/`, but inbound links from `README.md`, `AGENTS.md`, and concept/runbook docs that reference the old `01-start-here.md` / `02-quickstart.md` paths need updating in 5.F's harmonization pass (this slice updates only intra-tutorials cross-refs; cross-category fixups land in 5.F).
- **CI**: `scripts/check_doc_language.py docs/tutorials/` must exit 0 (English mandate). `scripts/check_link_integrity.py docs/tutorials/` must exit 0 (no broken inbound or outbound refs). `pytest tests/` baseline preserved.
- **Schema follow-up**: `schemas/schema-tutorial-v1.json` not authored in this slice — file-ownership rule forbids touching `schemas/`. Tracked as a follow-up for the schema owner (Slice 5.F or a dedicated patch). The frontmatter shape used here is the de-facto contract until the JSON schema lands.
- **Reviewability**: 8 files; per-file commits grouped by tutorial; final commit re-renders `INDEX.md` and renumbered cross-references.

## Versioning

VERSION unchanged in 5.D. Harmonization slice 5.F owns the v0.18.x bump after merging 5.A/5.C/5.D/5.E.
