# Spec: caveman-toggle v1

**Schema version:** `caveman-toggle/v1`
**JSON Schema:** [`schemas/schema-caveman-toggle-v1.json`](../schemas/schema-caveman-toggle-v1.json)
**Owner:** the ai-playbook caveman feature.

## Purpose

Define the contract for the per-project caveman feature toggle so that:
- the CLI (`scripts/caveman/cli.py`) and the on-disk JSON cannot drift
  out of sync,
- future UI implementations have a stable API to integrate against,
- schema migrations (v1 → v2) follow a predictable shape.

This document is the source of truth. The JSON Schema is generated from
this spec (manually for v1; codegen if/when v2 lands).

## State location

Per-project at `<project>/.ai-playbook/caveman.json`. No global default.
If a developer wants caveman ON for one project but OFF for another,
that is achieved by writing different state files in different
projects — there is no fallback chain.

## Fields

### `schema` (string, required, const)

Always `"caveman-toggle/v1"` for this version. Used by the read path
to detect on-disk staleness and trigger a migration (when v2 lands).

### `enabled` (boolean, required)

Master switch. When `false`, all components are inert regardless of
their individual flags. Effectively: `enabled == false → off`.

The UI MUST display the master switch separately from the component
toggles. Setting `enabled: false` is the universal kill switch.

### `mode` (string, required, enum)

One of `"lite"` | `"full"` | `"ultra"`. Only consulted when
`components.response_style` is `true`.

Intensities defined in [skills/caveman/SKILL.md](../skills/caveman/SKILL.md)
under the H2 sections `## lite mode ruleset`, `## full mode ruleset`,
`## ultra mode ruleset` — that file is the LLM-facing source of truth.

Why `mode` lives at top level (not inside `components`): a user
toggling between `lite` and `ultra` for the response-style component
should not have to also flip the `response_style` boolean. Conceptually
one field.

### `components` (object, required, additionalProperties: false)

Six boolean flags, all required. The UI MUST render all six even if
some are inert in the current `enabled` state — toggling them while
`enabled: false` is allowed (pre-stages intent) but has no side effects
until `enabled: true`.

| Key                   | Type    | Persistent? | Side effect when ON (and enabled) |
|-----------------------|---------|-------------|------------------------------------|
| `response_style`      | bool    | yes         | Marker-fenced ruleset block in AGENTS.md + per-turn reinforcement hook fires |
| `compress_docs`       | bool    | no          | Capability flag — gates the `compress` subcommand. No persistent file mutation. |
| `subagents_cavecrew`  | bool    | no          | Capability flag — allows agent to delegate to cavecrew subagents. No persistent mutation. |
| `commit_caveman`      | bool    | no          | Capability flag — gates the `caveman-commit` skill. No persistent mutation. |
| `review_caveman`      | bool    | no          | Capability flag — gates the `caveman-review` skill. No persistent mutation. |
| `mcp_shrink`          | bool    | yes         | Wraps `.mcp.json` + `.gemini/settings.json` stdio entries with `npx caveman-shrink --`. |

**Persistent** components mutate files on disk and require backups; the
toggle CLI orchestrates those mutations. **Non-persistent** components
are pure capability flags — flipping them changes nothing on disk; they
only matter when other code (the skills, the compress CLI) reads them.

### `applied_at` (string, required, format: date-time)

ISO 8601 UTC timestamp of the last write. Set automatically by the CLI
on every `on`/`off`. Used by audit/telemetry. The UI may display "last
changed N minutes ago".

### `applied_by` (string, optional, maxLength: 128)

Identifier of who/what triggered the last write. Sourced from `$USER`
or `$USERNAME` env vars by the CLI. UI consumers SHOULD set explicitly
(e.g. `"ui:dashboard-v1"`) so the audit trail distinguishes CLI from
UI writes.

## Forbidden states

The schema enforces:
- No unknown top-level keys (`additionalProperties: false`).
- No unknown component keys.
- `mode` outside the enum is rejected.
- `schema` other than `"caveman-toggle/v1"` is rejected on read
  (triggers a migration in a future version).

Out of the schema's reach, but enforced by the CLI:
- `enabled: true` with all `components: false` is allowed (the user
  has the master switch on but disabled everything — equivalent to
  OFF but distinct in intent).
- `mode: ultra` with `components.response_style: false` is allowed
  (the mode value is ignored; flipping response_style later picks it up).

## Migration policy (v1 → v2 hypothetical)

When v2 lands:

1. A new schema file `schemas/schema-caveman-toggle-v2.json` is added,
   with a `schema` const of `"caveman-toggle/v2"`.
2. A migration script `scripts/caveman/migrations/v1_to_v2.py` is
   added with a single public function `migrate(state: dict) -> dict`.
3. `scripts/caveman/toggle.read_state` is extended to dispatch on the
   `schema` field: v1 → run migrate → validate against v2 → return.
4. The on-disk file is rewritten in v2 format on the next `read_state`
   call, with a backup at `.ai-playbook/backups/state/caveman.json.<ts>.bak`.
5. UI consumers continue to call `status --json` and receive v2 data;
   schema version surfaced under `state.schema`. UIs built for v1 MUST
   refuse with a clear error if they see v2.

No silent drift. No best-effort migrations. Every version bump is
explicit, audited, and reversible from the backup.

## Test coverage

- [`tests/test_caveman_toggle.py`](../tests/test_caveman_toggle.py) —
  schema validation, default-state shape, round-trip read/write,
  atomic-write guarantees.

## Change log

| Version | Date       | Notes                                                                            |
|---------|------------|----------------------------------------------------------------------------------|
| v1      | 2026-05-23 | Initial. Six components, three modes, per-project state, marker-fenced materialise. |

## See also

- [docs/operations/caveman-architecture.md](../docs/operations/caveman-architecture.md) — UI integration contract (subprocess recipes, state-machine diagram, failure semantics).
- [docs/runbooks/caveman-toggle.md](../docs/runbooks/caveman-toggle.md) — operator how-to.
- [docs/concepts/caveman-mode.md](../docs/concepts/caveman-mode.md) — design overview and motivation.
