# break-glass.md

> **Status**: stub, v0.1.0. Populated in **T07b**.

## Contract

Every blocking check in a playbook script MUST support `--force-with-reason="<text>"`:

- Reason string is **non-empty**, non-whitespace, ≥10 chars.
- Emits an OTel span with `ai_playbook.override=true`, `ai_playbook.override_reason="<text>"`, and `ai_playbook.override_actor=<git user>`.
- Appends an entry to `.ai-playbook/overrides.log` (local, not committed) for post-hoc audit.
- Never silences the original error — the error still prints; the script simply proceeds.

## What break-glass is NOT

- Not a convenience flag. Using it leaves a trail the retros (T14i lifecycle-check) will surface.
- Not a way to bypass `deny` rules in `settings.json` — those are enforced by the CLI harness, not playbook scripts.

## Populated in T07b

Python helper (`scripts/_break_glass.py`), CLI argparse integration pattern, and the retro-surface query (show all overrides in last 7 days).
