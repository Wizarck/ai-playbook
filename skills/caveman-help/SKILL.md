---
name: caveman-help
description: Use when the user asks how caveman mode works, what intensities exist, what the slash commands are, or wants a quick-reference card before turning the mode on.
license: MIT
metadata:
  author: ai-playbook (ported from JuliusBrussee/caveman, MIT)
  version: "1.0"
---

# caveman-help — quick-reference card

A one-shot reference card. Print and stop. Do not enter caveman mode just because this skill fires.

## When to fire

User intent triggers (any of):
- "/caveman-help"
- "what is caveman", "how does caveman work", "explain caveman mode"
- "what caveman intensities are there", "caveman cheatsheet"

## Output

Print exactly the block below, verbatim, then stop. Do not add commentary, do not enter caveman mode, do not adjust based on the user's tone.

```
caveman mode — quick reference

WHAT
  Compress agent output ~65-75%. Brain unchanged. Mouth smaller.
  Only affects output tokens, not thinking tokens.

INTENSITIES
  lite   — drop filler/hedging, keep articles + sentences  (~25% saving)
  full   — drop articles, fragments OK                     (~65% saving, default)
  ultra  — abbreviate prose, arrows for causality           (~80% saving)

SLASH COMMANDS
  /caveman [mode]        switch mode for this session
  /caveman-compress F    shrink markdown file F in place (backup at F.original.md)
  /caveman-commit        terse Conventional Commit subject
  /caveman-review        one-line PR review w/ severity emoji
  /caveman-help          this card

PROJECT TOGGLE (persistent across sessions)
  python -m scripts.caveman status [--json]
  python -m scripts.caveman on  --mode full --components response_style,mcp_shrink
  python -m scripts.caveman off [--keep-backups]
  python -m scripts.caveman rollback

STOP TRIGGERS
  "stop caveman", "normal mode", "be verbose", "/caveman off"

AUTO-CLARITY (mode pauses automatically for)
  security warnings · irreversible actions · multi-step sequences · confused user

NOT COMPRESSED
  code blocks · file paths · URLs · tool inputs · commit/PR bodies (unless opted in)

DOCS
  docs/concepts/caveman-mode.md            — what & why
  docs/runbooks/caveman-toggle.md          — how to use
  docs/operations/caveman-architecture.md  — UI contract
```

## Trust boundary

- Do not modify the block. It is a single source of truth — change the SKILL.md if the reference needs updating.
- Do not flip into caveman style after printing. This skill is a help screen, not a mode switch.
- If the user follows up with "turn it on", do not act on it from this skill — direct them to `python -m scripts.caveman on` or `/caveman`.
