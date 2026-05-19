# auto-managed-sections.md

> **Status**: v1.0.0.

Contract for the `<!-- BEGIN auto-managed: <source_spec> -->` / `<!-- END auto-managed -->` markers used to keep consumer documents aligned with canonical playbook specs without hand-copying.

Enforced by `scripts/auto_managed.py` (`--check` / `--fix`) and by `scripts/drift_check.py --check auto-managed` in pre-commit and the weekly `drift-check.yml` CI job.

---

## 1 Marker format

Every auto-managed section is delimited by **exactly two HTML-comment lines**, each occupying its own line with no surrounding prose on the same line:

```
<!-- BEGIN auto-managed: <source_spec> -->
...regenerated content...
<!-- END auto-managed -->
```

Rules:

- `<source_spec>` is the token the extractor consumes (see §2). Leading/trailing whitespace inside the BEGIN comment is ignored; the stored source is trimmed.
- The BEGIN and END markers are both preserved verbatim on every `--fix` run. The regenerator only replaces the bytes **between** them.
- A file may contain any number of auto-managed sections, each with its own `source_spec`.
- Nesting is **not** allowed; see §6.

## 2 Supported source shapes

| `source_spec` | Source file | Extracted content |
|---|---|---|
| `specs/taxonomy:runtime` | `docs/concepts/taxonomy.md` | §1 *Runtime entities* table + surrounding prose up to the next `## ` heading. |
| `specs/taxonomy:config` | `docs/concepts/taxonomy.md` | §2 *Config artefacts*. |
| `specs/verdict-contract:levels` | `docs/rules/verdict-contract.rule.md` | §2 *Severity levels* table. |
| `specs/universal-principles` | _(not yet checked in)_ | Hard-fails with a FIX pointing at the canonical file to create. |

A **generic** fallback is also accepted for any `<spec-file>:<anchor>` shape: the extractor opens `<playbook>/<spec-file>.md` (adding a `.md` suffix if missing), finds the first `## ` heading whose text contains or begins with `<anchor>` (case-insensitive, optional numeric prefix ignored), and returns everything up to the next `## ` heading.

### Adding a new source shape

1. Open a PR.
2. Add an entry to `scripts/auto_managed._SUPPORTED_SOURCES` (or rely on the generic fallback when a dedicated key is not warranted).
3. Add at least one extractor test in `tests/test_auto_managed.py`.
4. Document the new shape in the table above.

## 3 Idempotency contract

- `--check` is strictly read-only. It prints stale sections and exits 1 if any exist.
- `--fix` rewrites stale sections **in place** and exits 0.
- `--fix` applied a second time to an already-clean file produces a zero-byte diff and writes nothing to disk.
- Trailing newline behaviour of the original file is preserved.

## 4 Merge strategy

- Pre-commit runs `drift_check --check auto-managed` against staged files. A stale section blocks the commit with the canonical error shape from [error-message-standard.md](error-message-standard.md), pointing at `python -m scripts.auto_managed <file> --fix`.
- The weekly `drift-check` GitHub Action (`.github/workflows/drift-check.yml`) runs `--check all` and surfaces drift as a `::warning::` annotation, without auto-merging a fix.
- `--force-with-reason="<text>"` is accepted on both scripts and logged to `.ai-playbook/overrides.log` per [break-glass.md](break-glass.md).

## 5 Rationale

Universal principles and taxonomy terms change once per release, but every consumer needs the latest wording visible inside its own documents. Copy-paste rots invisibly; auto-managed sections make drift a lint failure instead of a human-discovery bug, and the `--fix` flag turns remediation into a one-liner instead of a git archaeology exercise.

## 6 Anti-patterns

- **Nested auto-managed sections.** A BEGIN inside a BEGIN is a parser error. Flatten or split.
- **Non-deterministic content.** Do not wrap timestamps, generated IDs, or command output that changes between runs — every `--fix` would record diff churn in git.
- **Editing within the markers by hand.** The next `--fix` will revert the edit. Instead, edit the **source** spec and regenerate.
- **Markers on the same line as text.** The parser anchors on full, trimmed lines. `foo <!-- BEGIN auto-managed: x -->` is ignored.
- **Anchors that do not match a `## ` heading.** The extractor walks level-2 headings only; `### ` subsections are not addressable.

## 7 Cross-references

- [dispatcher-chain.md](dispatcher-chain.md) — why consumers inherit rather than copy.
- [migration-guide.md](migration-guide.md) — how to convert an existing copied block into an auto-managed section.
- [error-message-standard.md](error-message-standard.md) — canonical error shape emitted on stale sections.
- [break-glass.md](break-glass.md) — override semantics for both scripts.
- `scripts/auto_managed.py` — implementation (regenerator + CLI).
- `scripts/drift_check.py` — weekly and pre-commit enforcement.
