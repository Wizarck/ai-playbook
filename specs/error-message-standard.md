# error-message-standard.md

> **Status**: stub, v0.1.0. Populated in **T07a**.

## Canonical form

Every error surfaced to a human (CLI, log, dashboard) MUST carry four parts:

```
❌ <WHY> at <WHERE>
   FIX: <suggested remediation>
   OVERRIDE: <break-glass command if safe to bypass, or "none">
```

- **WHY** — one sentence, present tense, names the invariant that failed.
- **WHERE** — file path + line number, or symbolic location (e.g. `mcp-servers.yaml:servers.hindsight.auth`).
- **FIX** — action the reader can take. No hand-waving.
- **OVERRIDE** — if this check can be bypassed, show the exact `--force-with-reason=<text>` invocation. Otherwise `OVERRIDE: none`.

## Example

```
❌ AGENTS.md missing required field `inherits_from` at C:\Projects\consumer-c-legacy\AGENTS.md:1
   FIX: add `inherits_from: [github.com/Wizarck/ai-playbook@v0.1.0]` to the frontmatter.
   OVERRIDE: python scripts/schema_validate.py --force-with-reason="bootstrapping, playbook not submoduled yet"
```

## Populated in T07a

Lint rule (`scripts/verdict_lint.py` + CI), interaction with exit codes, and linkage to OTel `exception` events.
