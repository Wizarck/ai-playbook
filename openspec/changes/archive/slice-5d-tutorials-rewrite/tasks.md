# Tasks — slice-5d-tutorials-rewrite

## 1. Scaffold + numbering

- [x] 1.1 Create openspec change folder + proposal/tasks/design
- [x] 1.2 Renumber existing tutorials to free `01-` for the architecture tour:
  - `01-start-here.md` → `02-start-here.md`
  - `02-quickstart.md` → `03-quickstart.md`
  - `03-bootstrap-new-project.md` → `04-bootstrap-new-project.md`
  - `04-quickstart-lessons.md` → `05-quickstart-lessons.md`
  - `05-curriculum.md` → `06-curriculum.md`
  - `06-why-these-choices.md` → `07-why-these-choices.md`
  - `07-fork-inventory.md` → `08-fork-inventory.md`

## 2. Write 01-architecture-tour.md (canonical entry point)

- [x] 2.1 Replace placeholder with full 15-min cold-start tutorial body
- [x] 2.2 Sections: what ai-playbook is → 4 doc types → walking tour (clone → pip install -e . → pytest → cleanup_zombies validate → check_doc_language → validate_pairing) → What's next pointer table
- [x] 2.3 Concrete shell commands the reader can paste, with expected outputs
- [x] 2.4 Length 100–300 lines (target ~250)

## 3. Rewrite the other 7 tutorials

- [x] 3.1 `02-start-here.md` — 60-second orientation
- [x] 3.2 `03-quickstart.md` — full 25–40 min walkthrough
- [x] 3.3 `04-bootstrap-new-project.md` — using `scripts/bootstrap.py`
- [x] 3.4 `05-quickstart-lessons.md` — per-OS friction
- [x] 3.5 `06-curriculum.md` — 4-week structured path
- [x] 3.6 `07-why-these-choices.md` — design-decision rationale
- [x] 3.7 `08-fork-inventory.md` — upstream-tracked forks catalog

For each:

- [x] Add v1 frontmatter (schema/slug/title/description/estimated_time/prerequisite_concepts/audience/order)
- [x] Add "What you'll learn / Estimated time / Prerequisites" preamble
- [x] Number sections; add expected-output blocks under shell commands
- [x] Add "What's next" footer with concrete forward pointers
- [x] Fix any intra-tutorials cross-references for the renumber

## 4. INDEX

- [x] 4.1 Regenerate `docs/tutorials/INDEX.md` (auto-generated; run after rewrites)

## 5. Validate

- [x] 5.1 `python scripts/check_doc_language.py docs/tutorials/` → exit 0
- [x] 5.2 `python scripts/check_link_integrity.py docs/tutorials/` → exit 0
- [x] 5.3 `pytest tests/` → green (918+ baseline)

## 6. Ship

- [x] 6.1 Commit per logical group (scaffold; renumber; arch tour; other rewrites; INDEX)
- [x] 6.2 Push branch
- [x] 6.3 Open PR `feat/slice-5d-tutorials-rewrite` → `main`
