# error-message-standard.md

> **Status**: v1.0.0.

Canonical error format for any message a playbook script emits to a human (CLI stderr, log, dashboard cell, notification). Agents parsing playbook output rely on this shape; linters enforce it.

---

## Canonical form

Every user-visible error carries four parts in this fixed order:

```
❌ <WHY> at <WHERE>
   FIX: <suggested remediation>
   OVERRIDE: <break-glass invocation or "none">
```

Optionally followed by a blank line and an expanded multi-line detail block (for complex failures). The four-line header above is **non-negotiable** — linters grep for it.

### Field contract

| Field | Required | Constraints |
|---|---|---|
| `WHY` | yes | 1 sentence, present tense, names the invariant that failed. ≤120 chars. No trailing period inside the sigil line. |
| `WHERE` | yes | File path + line number, or a symbolic location (`mcp-servers.yaml:servers.hindsight.auth`, `AGENTS.md frontmatter`). Absolute paths on Windows use forward slashes to avoid ambiguity when the message is piped. |
| `FIX` | yes | Imperative. Actionable. ≤200 chars. Name the exact command or file change. No hand-waving ("investigate", "check logs" are forbidden). |
| `OVERRIDE` | yes | Either an exact `--force-with-reason="..."` invocation (see [break-glass.md](break-glass.md)) or the literal string `none` when bypass is unsafe. |

---

## Examples

### Validation failure (AGENTS.md frontmatter)

```
❌ AGENTS.md missing required field `inherits_from` at C:/Projects/acme-shop/AGENTS.md:1
   FIX: add `inherits_from: [github.com/Wizarck/ai-playbook@v0.1.0]` to the YAML frontmatter.
   OVERRIDE: python scripts/schema_validate.py AGENTS.md --force-with-reason="bootstrapping, playbook not submoduled yet"
```

### Secret scan match

```
❌ Secret-like pattern matched (Anthropic API key) at C:/Projects/consumer-d/notes/draft.md:42
   FIX: move the key to `secrets/secrets.env` (SOPS-encrypted) and replace the literal with `$ANTHROPIC_API_KEY`.
   OVERRIDE: none
```

`OVERRIDE: none` when the check protects credentials, safety invariants, or data loss. An agent attempting to bypass a `none` override is a [agentic-failures.md] "goal drift" signal.

### MCP SSOT drift

```
❌ mcp-servers.yaml rendered output diverges from committed .mcp.json at C:/Projects/consumer-c-legacy/.mcp.json
   FIX: run `python .ai-playbook/scripts/mcp/render.py --project consumer-c-legacy` and commit the regenerated file.
   OVERRIDE: python .ai-playbook/scripts/mcp/render.py --dry-run --force-with-reason="intentional local experiment before committing registry change"
```

### Multi-line detail (expanded form)

```
❌ openspec/specs/ingredients.md edited directly (not via openspec archive) at openspec/specs/ingredients.md
   FIX: revert the hand-edit; land the change through `openspec apply` + `openspec archive` of an open change instead.
   OVERRIDE: none

Detail:
The block_manual_spec_edit pre-commit hook blocks commits that touch `openspec/specs/*.md`
because specs drift silently otherwise. If this edit is from an `openspec archive` run,
the hook ignores it automatically (it recognises the archive marker in the commit message).
If you see this error during an archive, something is wrong with the archive flow — inspect
the working copy with `openspec status` and report under FEEDBACK.md.
```

---

## Exit codes

Playbook scripts use a small, stable set:

| Code | Meaning |
|---|---|
| `0` | Success. |
| `1` | User-actionable failure (the canonical-format error was emitted). |
| `2` | Environment/setup failure (missing dep, wrong Python, etc.) — script refused to start. Error shape still applies but `FIX` typically names the setup step. |
| `3` | Hard block (safety/security gate). `OVERRIDE: none`. |
| `10+` | Reserved per-script (documented in each script's docstring). |

Scripts SHOULD NOT exit with generic 1 for environment issues — use 2 so CI jobs can distinguish "spec fix" from "infra fix".

---

## OpenTelemetry mapping

When an error is surfaced inside a traced span, the emitting script ALSO attaches:

- `exception.type` — Python exception class (e.g. `SchemaValidationError`) or the error category (`mcp_drift`, `secret_leak`).
- `exception.message` — the `<WHY>` sentence verbatim.
- `exception.stacktrace` — only for unexpected/internal errors; never for normal validation failures.
- `ai_playbook.error.where` — the `<WHERE>` field.
- `ai_playbook.error.fix` — the `<FIX>` field (indexable; enables "most common fix" retro queries).
- `ai_playbook.error.override_available` — boolean derived from `OVERRIDE` field being `"none"` or not.
- `ai_playbook.error.override_used` — boolean, set by `_break_glass.py` when bypass actually fires.

See [agentic-failures.md](agentic-failures.md) for how these attributes drive failure-kind detection in retros.

---

## Linter

`scripts/verdict_lint.py --shape error` enforces:

- Exactly one `❌` line per error.
- `FIX:` and `OVERRIDE:` lines are present with 3-space continuation indent.
- `OVERRIDE:` is either `none` or starts with `--force-with-reason=`.
- `WHERE` contains either a filesystem path segment OR a symbolic-location pattern (`file:path.key`).
- Line lengths within the caps above; over-long `WHY` triggers `S3` in review.

Pre-commit config surfaces this on any script that writes to stderr or stdout during validation.

---

## Anti-patterns

- **Stack traces as errors.** Python tracebacks are for crashes, not validation failures. Wrap expected failures in the canonical shape.
- **"Something went wrong".** Always name the invariant. If the cause is genuinely unknown, the `WHY` is *"unexpected failure during <operation>"* and the `FIX` is *"report with full stacktrace to FEEDBACK.md"*.
- **Multi-error stuffing.** One `❌` per invariant. If a script finds 7 problems, it prints 7 blocks.
- **Colorized emoji pollution.** The `❌` is the only emoji we require. `⚠️`, `✅`, `❓` belong to verdict messages (see [verdict-contract.md](verdict-contract.md)), not errors.
- **Translating the `FIX` line.** English only for machine-parseability. UI layers may translate for display; the raw log stays English.

---

## Cross-references

- [break-glass.md](break-glass.md) — the `OVERRIDE:` invocation contract.
- [verdict-contract.md](verdict-contract.md) — ⚠️/❓/✅ rubric used separately from errors.
- [agentic-failures.md](agentic-failures.md) — catalog of failure modes (some emit errors, some don't).
- `scripts/verdict_lint.py` — enforces this shape in CI.
