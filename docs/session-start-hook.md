# session-start-hook.md

> **Status**: v1.0.0. Populated in T12.

How to wire `scripts/inject_context.py` into a consumer's Claude Code (or equivalent) `SessionStart` hook so Hindsight memory lands in the agent's context at every session.

---

## Claude Code — `SessionStart` hook

Add to the consumer's `.claude/settings.json` (project-level) OR the dev's `~/.claude/settings.json` (user-level):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "sops exec-env secrets/secrets.env -- python -m scripts.inject_context 2>/dev/null || true",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

Notes:

- `sops exec-env secrets/secrets.env --` decrypts `HINDSIGHT_URL` + `HINDSIGHT_API_KEY` + `HINDSIGHT_BANK_ID` into the subprocess's env. Without SOPS, set the three vars in the shell profile instead.
- `2>/dev/null || true` suppresses stderr from the hook (`inject_context.py` prints a one-line `✅` on success and a canonical error on missing credentials). Hooks that print noisily clutter the startup UX.
- `timeout: 15` covers the Hindsight HTTP roundtrip + sanitisation. If Hindsight is degraded the script bails in ≤10s (`DEFAULT_TIMEOUT_SECS`) and writes a `DEGRADED_CONTEXT` banner — the session still starts healthy.
- The output file (`.claude/injected-context.md`) is read by Claude Code's own bootstrap and surfaced alongside the project's `AGENTS.md`.

## Gemini CLI / Antigravity

No canonical hook-binding surface as of playbook v0.2 — run manually:

```bash
# Once per session, before launching gemini / antigravity:
sops exec-env secrets/secrets.env -- python -m scripts.inject_context
```

The `.claude/injected-context.md` file is read by the Gemini router (via the dispatcher reference in `~/.gemini/GEMINI.md`). If/when Gemini ships a hook surface, this section gets the same snippet as Claude Code above.

## Cursor

Cursor reads `.cursor/rules/*.mdc` at session start; it does not run arbitrary hooks. Instead, the consumer's `.cursor/rules/00-dispatcher.mdc` (thin router) points at `AGENTS.md`, which in turn points at `.claude/injected-context.md`. The dev MUST manually run `python -m scripts.inject_context` before opening Cursor when Hindsight content matters for the session.

## Dry-run (validation, no write)

When wiring this up for the first time:

```bash
sops exec-env secrets/secrets.env -- python -m scripts.inject_context --dry-run
```

Prints the rendered markdown to stdout without touching `.claude/injected-context.md`. Confirms credentials + bank_id + recall shape.

## Break-glass

If SOPS is unavailable or the team dev doesn't have the age key yet:

```bash
python -m scripts.inject_context --force-with-reason="bootstrapping local dev before SOPS age key provisioned"
```

Writes an empty `DEGRADED_CONTEXT` banner and exits 0. Logged to `.ai-playbook/overrides.log` for the monthly lifecycle retro. See `specs/break-glass.md`.

## Cross-references

- `specs/memory-hierarchy.md` — how the injected content fits in tier 3 (durable/personal).
- `specs/degradation-modes.md` — how `DEGRADED_CONTEXT` is surfaced in the session.
- `specs/env-vars.md` — full list of env vars the script reads.
- `scripts/inject_context.py` — the script itself; CLI help via `--help`.
