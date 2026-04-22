# model-migration.md

> **Status**: stub, Phase 5. Populated when we hit our first retirement of a model that's pinned in `specs/model-routing.md`.

## When to use this runbook

A provider (Anthropic, Google, etc.) deprecates a model ID that the playbook's model-routing matrix depends on. Example: `claude-opus-4-7` retired for `claude-opus-5-0`.

## Flow (v0 shape — refined in practice)

1. Deprecation watcher (T22) surfaces the upcoming retirement ≥30 days ahead.
2. Open RFC in `rfcs/` proposing the replacement entry in `model-routing.md`.
3. Dry-run: pilot the new model on low-stakes task classes first.
4. Update `specs/model-routing.md`, bump playbook minor version.
5. Notify consumers (CHANGELOG entry + `systemMessage` in next session).

Full procedure materializes in Phase 5 when we face the first real migration.
