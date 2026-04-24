# session-start-hook.md

> **Status**: v1.0.0.

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
            "command": "sops exec-env secrets/secrets.env -- python .ai-playbook/scripts/inject_context.py --bank-id <project-bank> 2>/dev/null || true",
            "timeout": 60
          }
        ]
      }
    ]
  }
}
```

Notes:

- `sops exec-env secrets/secrets.env --` decrypts `HINDSIGHT_URL`, `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET` (and optionally `HINDSIGHT_API_KEY` for non-CF deployments) into the subprocess env. Without SOPS, set the vars in the shell profile instead. See [`../specs/env-vars.md`](../specs/env-vars.md) §HINDSIGHT_* for the full auth contract.
- `2>/dev/null || true` suppresses stderr from the hook so a one-off Hindsight outage doesn't visually block session start. `inject_context.py` writes a `DEGRADED_CONTEXT` banner to `.claude/injected-context.md` instead.
- `timeout: 60` covers cold recall (~30 s on the production deployment) plus sanitisation overhead. The script's internal `DEFAULT_TIMEOUT_SECS` is 45 s; the hook envelope adds 15 s buffer.
- The output file (`.claude/injected-context.md`) is read by Claude Code's own bootstrap and surfaced alongside the project's `AGENTS.md`.
- Replace `<project-bank>` with the project's bank id from [`../specs/memory-hierarchy.md`](../specs/memory-hierarchy.md) §2 (e.g. `opentrattos`, `eligia`, `palafito`).

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
