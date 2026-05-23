---
name: caveman-compress
description: Use when the user wants to shrink a long markdown file like AGENTS.md, CLAUDE.md, a README, or a runbook to roughly half its size while keeping code blocks, headings, URLs, and file paths intact.
license: MIT
metadata:
  author: ai-playbook (ported from JuliusBrussee/caveman, MIT)
  version: "1.0"
---

# caveman-compress — shrink memory files

Rewrite long markdown documents in caveman style, byte-preserving everything that must not change.

## When to fire

User intent triggers (any of):
- "/caveman-compress <file>"
- "compress AGENTS.md", "shrink this README", "make CLAUDE.md smaller"
- "trim the docs", "reduce the runbook"

## Preconditions

- Target file is markdown (`.md`).
- Caller has read+write access to the file.
- Working tree is clean for the target file (otherwise refuse and ask the user to stash or commit first — accidentally overwriting uncommitted edits would be hard to recover).

## Steps

1. **Confirm the target.** Echo `<file>: <bytes> bytes, <lines> lines` to the user. If the file is < 200 bytes, refuse — not worth a roundtrip.

2. **Backup.** Copy the original to `<file>.original.md`. Refuse if a backup already exists with content different from the current file — that indicates an earlier compression session was not finalized.

3. **Invoke the compressor:**

   ```bash
   python -m scripts.caveman compress <file> --mode full
   ```

   Modes: `lite`, `full` (default), `ultra`. The compressor calls the LLM with the caveman ruleset and a strict preservation contract.

4. **Validate the output.** The compressor enforces, and fails the run if violated:
   - Every fenced code block (```` ``` ```` ... ```` ``` ````) is byte-identical to the original.
   - Every heading (`#`, `##`, `###`, …) text and level is identical (order preserved).
   - Every URL (`https?://...`) appears in the output exactly once and unchanged.
   - Every file path (`/`-containing tokens) appears in the output exactly once and unchanged.
   - Every bash command line (lines starting with `$ ` or inside `bash` fenced blocks) is byte-identical.

5. **Retry on validation failure.** Up to 2 retry passes with targeted patches — only the violated tokens are sent back to the LLM with the instruction to restore them. After 2 retries, restore from `<file>.original.md` and exit 1.

6. **Report.** Print:

   ```
   <file>: <orig_bytes> → <new_bytes> ({pct}% saved)
   backup: <file>.original.md
   ```

## Output shape

After completion, summarise to the user:
- Original size, compressed size, percent saved.
- Backup path.
- Whether any retries were needed.
- A two-line diff sample (first preserved heading, first prose paragraph compressed).

## Trust boundary

- Never overwrite the original without writing a backup first.
- Never run a third retry — bail out and restore.
- If the LLM call errors out (network, quota), do NOT touch the original file. The compressor handles this; this skill only orchestrates and reports.

## Guardrails

- Do not compress files that aren't markdown (refuse with `Only .md supported`).
- Do not compress files inside `.git/`, `node_modules/`, `__pycache__/`, or `dist/`.
- Do not compress files larger than 100 KB without explicit `--force` from the user — a single LLM call may not fit them and partial compression risks data loss.

## See also

- [scripts/caveman/compress.py](../../scripts/caveman/compress.py) — the compressor implementation.
- [docs/runbooks/caveman-toggle.md](../../docs/runbooks/caveman-toggle.md) — how compression fits the broader caveman feature.
