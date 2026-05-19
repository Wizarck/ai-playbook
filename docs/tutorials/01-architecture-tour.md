---
schema: tutorial/v1
slug: architecture-tour
title: Architecture tour — your first 15 minutes
description: A guided cold-start tour for new contributors. Clone, install, run the validators, and finish knowing what ai-playbook is, how its four doc types relate, and which command does what.
estimated_time: "15 min"
prerequisite_concepts: []
audience: new-contributor
order: 1
---

# Architecture tour — your first 15 minutes

> **What you'll learn**: What ai-playbook is, how its four doc types (rules, concepts, runbooks, tutorials) fit together, and how to run the validators that keep the repo honest. By the end you will have cloned the repo, installed it locally, and watched four real validators report green on your machine.
> **Estimated time**: 15 min
> **Prerequisites**:
> - Python 3.11+ on your `PATH` (`python --version` should print 3.11 or newer)
> - `git` 2.40+
> - A terminal you are comfortable in (bash, zsh, or PowerShell — all work)
> - About 200 MB free disk for the clone + Python install

Take this tour cold. Do NOT read the rest of the docs first. The point is to feel the shape of the repo with your hands; depth comes after.

---

## 1. What ai-playbook is (≤1 min)

`ai-playbook` is a normative repository: a small, opinionated set of universal rules, contracts, validators, and tutorials that every consumer project consumes as a git submodule. It is **LLM-agnostic** — Claude Code, Gemini CLI, Cursor, and Antigravity all read the same files — and it **dogfoods** itself: every script the playbook ships to consumers also runs against the playbook's own tree.

It is not a framework. It is not a library you depend on at runtime. It is a contract: write your project so that `AGENTS.md` inherits from a pinned playbook tag, install the pre-commit hooks the playbook ships, and the four validators below stay green forever.

If you want the deeper "why" before continuing, click through to [enforcement layers](../concepts/enforcement-layers.md) — but skim, then come back. This tour assumes you have not read it yet.

---

## 2. The four doc types (≤2 min)

The repo follows a [Diátaxis](https://diataxis.fr/)-inspired layout with a normative-reference subcategory. Open `docs/` and you will see four sibling folders:

| Folder | Purpose | What it looks like | Example |
|---|---|---|---|
| `docs/rules/` | **Normative reference** — paired with a Python hook; binds behaviour | RFC 2119 vocabulary (MUST / MUST NOT / SHOULD), short body, frontmatter `paired_hardrule:` | [verdict-contract.rule.md](../rules/verdict-contract.rule.md) |
| `docs/concepts/` | **Conceptual reference + explanation** — no enforcement language | Declarative prose; "Why / What / How it relates / Concrete example" sections | [enforcement-layers.md](../concepts/enforcement-layers.md) |
| `docs/runbooks/` | **How-to** — multi-step procedures for known goals | Numbered steps, expected outputs, failure recovery | [windows-dev-environment.md](../runbooks/windows-dev-environment.md) |
| `docs/tutorials/` | **Learning-oriented** — lead-by-the-hand walkthroughs | "What you'll learn / Estimated time / Prerequisites" preamble | This file |

The discriminator between **rules** and **concepts** is mechanical: a rule has `paired_hardrule:` in its frontmatter pointing at a Python file under `scripts/rules/`; a concept does not. The validator `scripts/validate_pairing.py` enforces this disjointness — you will run it in step 7.

Click each example link in the table above. Spend ~15 seconds in each file. Feel the difference between a rule (terse, binding) and a concept (narrative, declarative). That muscle memory is the goal of this section — not memorising any specific content.

---

## 3. Clone and install (≤2 min)

Open a terminal in a directory where you keep code (say `~/code` or `C:\Projects`) and run:

```bash
git clone https://github.com/Wizarck/ai-playbook.git
cd ai-playbook
```

Expected output: a fresh clone, ~7000+ files, no errors. Confirm with `ls`:

```
AGENTS.md  CHANGELOG.md  README.md  VERSION  configs/  docs/  openspec/
pyproject.toml  schemas/  scripts/  skills/  specs/  templates/  tests/
```

Install the playbook as an editable Python package so the validators are importable:

```bash
pip install -e .
```

Expected output (final line):

```
Successfully installed ai-playbook-<version>
```

If you see `ModuleNotFoundError` in any later step, this is the line that failed silently — re-run with `pip install -e . --verbose` and read the last 20 lines.

---

## 4. Run the test suite (≤2 min)

The playbook ships ~1000 tests as of v0.18.3. They run in under a minute on a modern laptop:

```bash
python -m pytest tests/ -q
```

Expected tail of output (numbers move slice over slice):

```
~1080 passed, 2 skipped in 25.00s
```

The 2 skipped tests are end-to-end integration tests that require remote services (`AIPLAYBOOK_E2E=1`, Hindsight URL, Cloudflare Access tokens). They are designed to skip in local environments; that is correct.

If you see a `FAILED` line, stop the tour and read [windows-dev-environment.md](../runbooks/windows-dev-environment.md) (Windows) or check that your Python is actually 3.11+ (`python --version`). Tests should be green on `main`.

---

## 5. Run the cleanup-zombies validator (≤2 min)

A "zombie" is a path that used to exist in a previous version of the playbook and that consumer repos still reference. The playbook tracks them in `specs/zombies-manifest.yaml` so consumers can auto-migrate on the next playbook bump. This is the closest thing the playbook has to a migration tool.

Run the validator:

```bash
python scripts/rules/cleanup-zombies.rule.py validate
```

Expected output:

```
✓ manifest .../specs/zombies-manifest.yaml valid (28 entries, version 2026-05-19.4)
```

What just happened: the script loaded the YAML manifest, validated every entry against its schema, and confirmed no contradictions. The same script runs as an L1 PreToolUse hook in Claude Code (terminal-side enforcement) and as an L3 GitHub Action (server-side enforcement) — same rubric, three enforcers. Click through to [enforcement layers](../concepts/enforcement-layers.md) for the L1/L2/L3 model.

---

## 6. Run the doc-language linter (≤2 min)

Per decision D6, every doc body in `docs/` MUST be English. Spanish belongs in personal notes (`ELIGIA.md`) but never in normative docs that ship to consumers.

Run the linter:

```bash
python scripts/check_doc_language.py docs/
```

Expected output:

```
check_doc_language: OK (98 files; 1 non-English / 1.0%; threshold 5%)
```

What just happened: the script walked `docs/`, sampled prose blocks, and classified each as English or not. It reports as long as the non-English share stays under 5% (lenient floor during reorg slices; will tighten later). The single non-English flag is a known false positive (a quoted Spanish phrase inside an English doc) — it does not fail.

Try it on a single file:

```bash
python scripts/check_doc_language.py docs/concepts/enforcement-layers.md
```

You will see the per-file verdict. This is the same script CI runs at PR time.

---

## 7. Run the pairing validator (≤2 min)

The keystone invariant: every rule under `docs/rules/<slug>.rule.md` MUST have a paired Python hook at `scripts/rules/<slug>.rule.py`, and vice versa. The slug binds the four artefacts (`.rule.md`, `.rule.py`, `tests/test_<slug>.py`, `.github/workflows/<slug>.rule.yml`) at a single name.

Run the validator:

```bash
python scripts/validate_pairing.py
```

Expected output:

```
validate_pairing: OK
```

What just happened: the script enumerated every `docs/rules/*.rule.md`, parsed each frontmatter, and verified the `paired_hardrule:` path exists. Exceptions (advisory-only rules with `paired_hardrule: null`) are documented in [enforcement-pairing-exceptions.md](../concepts/enforcement-pairing-exceptions.md) and the validator allows them.

If any rule's pair is missing, you would see a line like `FAIL: docs/rules/foo.rule.md → scripts/rules/foo.rule.py (missing)`. This is the gate that catches "I forgot to commit the hook" before a PR ever opens.

---

## 8. (Optional) Run the AGENTS.md size guard (≤1 min)

The dispatcher file at the repo root (`AGENTS.md`) has a 500-line cap per decision D14. The cap exists because every LLM session reloads it, and long dispatchers degrade rule-following per IFEval (arXiv 2311.07911).

```bash
python scripts/check_agents_md_size.py
```

Expected output:

```
check_agents_md_size: OK (AGENTS.md: <N> lines, cap 500)
```

If you ever see a cap violation, the fix is to extract long sections to `docs/concepts/<slug>.md` and replace them with one-line pointers, not to raise the cap.

---

## 9. What you can build next

You have run four validators against the playbook itself. The same APIs power consumer tooling. Five small projects you can take from here to internalise the L1 / L2 / L3 model:

- **Modify a real rule + watch CI catch you.** Edit `docs/rules/verdict-contract.rule.md` so its body contradicts its frontmatter (e.g. set `paired_hardrule: null` in the frontmatter but leave the binding clause that says "the hardrule…"). Re-run `python scripts/validate_pairing.py`. The validator should refuse — and that refusal is the L1 layer working as designed.
- **Generate a telemetry report on your own session.** Run `python -m scripts.telemetry.report monthly` after a real Claude Code session. The report exits 0 even with zero events on a fresh clone; the markdown output documents the empty state and points you at the event log location.
- **Add a new concept doc.** Pick a small idea you encountered in this tour (e.g. "what makes a rule advisory vs enforced") and author `docs/concepts/<your-slug>.md` against the [STYLE.md](../concepts/STYLE.md) exemplar. Run `python scripts/check_doc_language.py docs/<your-slug>.md` and `mkdocs build --strict` — both should be green before you propose a PR.
- **Wire a Cursor mirror.** Run `python scripts/materialise_cursor_rules.py` and inspect `.cursor/rules/` — every `docs/rules/<slug>.rule.md` materialises as a `.cursor/rules/<slug>.mdc` with Cursor's 4-mode activation field set from the frontmatter `activation:`.
- **Add a smoke test for one of your own scripts.** Pick any script under `scripts/` that does not yet have a `tests/test_<name>.py`. Author 3 fixture cases. Run them. The fast-feedback loop (under 1 second per test) is the playbook's preferred dev cycle.

The full breakdown of every rule's L1 / L2 / L3 surface lives in [rule-use-cases-matrix.md](../concepts/rule-use-cases-matrix.md). The academic grounding for the layered model lives in [academic-foundations.md](../concepts/academic-foundations.md).

## 10. What's next

You now have:

- A working local clone with the playbook installed (`pip install -e .`).
- A green test suite.
- A green pass through three of the playbook's own validators.
- A mental model of the four doc types and how they pair.

Pick the next tutorial based on what you came here to do:

| You want to... | Read this next |
|---|---|
| Get the 60-second elevator pitch and the dispatcher diagram | [02-start-here.md](02-start-here.md) — 1 min |
| Onboard a real new consumer project end-to-end | [03-quickstart.md](03-quickstart.md) — 25–40 min |
| Use the one-shot bootstrap script instead of doing it by hand | [04-bootstrap-new-project.md](04-bootstrap-new-project.md) — 10 min |
| Follow a self-paced reading order as a contributor | [05-learning-path.md](05-learning-path.md) |
| Understand the design decisions (why submodule, why LLM-agnostic) | [06-why-these-choices.md](06-why-these-choices.md) — 15 min |
| Track the upstream forks the project maintains | [07-fork-inventory.md](07-fork-inventory.md) — 10 min |

If you want depth before doing more tutorials, read these concept docs in this order:

1. [enforcement-layers.md](../concepts/enforcement-layers.md) — the L1 / L2 / L3 paired-enforcement model you just felt three times.
2. [dispatcher-chain.md](../concepts/dispatcher-chain.md) — how `AGENTS.md` inherits from the playbook.
3. [taxonomy.md](../concepts/taxonomy.md) — the vocabulary (slug, paired_hardrule, rubric, dispatcher) used everywhere.
4. [cross-llm-activation.md](../concepts/cross-llm-activation.md) — how the same rule loads in Claude Code vs Gemini vs Cursor.

If something is broken on your machine, [windows-dev-environment.md](../runbooks/windows-dev-environment.md) is the most-frequently-needed runbook. If the playbook itself looks broken (a validator that should be green prints red on a fresh clone of `main`), that is a real bug — open an issue.

Welcome to the playbook.
