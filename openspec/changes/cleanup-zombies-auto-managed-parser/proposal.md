# cleanup-zombies-auto-managed-parser

> **Status**: SCRATCH. Satisfies branch-name-validator. openspec/changes/ gitignored — force-added.

## Why

Discovered 2026-08-01 in the geeplo consumer. The `auto-managed-orphan-blocks`
manifest entry shipped as Tier 1 (auto-delete) on top of a hand-rolled marker
parser that disagreed with the canonical one in `scripts/auto_managed.py`. Run
from the consumer's post-merge hook it destroyed 623 lines across 7 files of
this repository's own tree — truncating several mid-sentence and removing the
`verdict-contract` FOOTER, an instructional-defense control. It ran with
`--quiet`, so the damage sat in the working tree for three weeks unnoticed.

Three parser defects compounded: `re.search` matched a BEGIN marker anywhere in
a line (so prose *documenting* the syntax parsed as a live block); the skip
state was never reset when no END followed (so it deleted to end of file); and
`<source>` resolved against the consumer root (so every live `caveman/*` and
`ponytail/*` block read as an orphan). The safety check shared the first defect,
so it confirmed the false positive it existed to gate.

Two structural faults sat underneath. Tier and safety were coupled 1:1, so any
entry wanting real detection had to also claim auto-delete rights — that is why
this entry was Tier 1 at all. And Tier 3's documented "never modifies the
filesystem regardless of flags" held only by accident, because `report_only`
always failed its safety and short-circuited before the action dispatch.

## What

- Safety `auto_managed_orphan` delegates to `auto_managed.find_sections` instead
  of re-implementing it; `_do_prune_blocks` shares the same helper so the two
  cannot drift apart again.
- Orphan classification is namespace-aware: `specs/*` via `compute_expected`,
  `caveman/*` and `ponytail/*` via their toggle state files, and an unrecognised
  namespace is never an orphan.
- `**/*.md` no longer walks the `.ai-playbook/` submodule.
- `TIER_SAFETY_MATRIX` decouples tier from safety; Tier 3 may carry a detection
  safety. `_process_entry` enforces Tier 3's no-mutation contract structurally.
- Manifest entry demoted Tier 1 → Tier 3 (`action: report`);
  `manifest_version` → `2026-08-01.1`.
- 12 regression tests over reduced forms of the files actually damaged.

## Release

`VERSION` → 0.19.29. Patch (bug fix + manifest demotion). Pull model — consumers
on ≤0.19.28 are still losing documentation on every `git pull`.
