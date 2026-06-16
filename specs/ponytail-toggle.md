# Spec: ponytail-toggle v1

**Schema version:** `ponytail-toggle/v1`
**JSON Schema:** [`schemas/schema-ponytail-toggle-v1.json`](../schemas/schema-ponytail-toggle-v1.json)
**Owner:** the ai-playbook ponytail feature.

## Purpose

Define the contract for the per-project ponytail feature toggle so that:
- the CLI (`scripts/ponytail/cli.py`) and the on-disk JSON cannot drift out of
  sync,
- UI implementations (the config UI Features tab, future apps) have a stable
  API to integrate against,
- schema migrations (v1 → v2) follow a predictable shape.

This document is the source of truth. The JSON Schema is generated from this
spec (manually for v1; codegen if/when v2 lands). Mirrors
[caveman-toggle](caveman-toggle.md) (ponytail keeps `mode` — it has the same
lite/full/ultra intensity levels — but has fewer, code-focused components).

## State location

Per-project at `<project>/.ai-playbook/ponytail.json`. No global default. If a
developer wants ponytail ON for one project but OFF for another, that is
achieved by writing different state files in different projects — there is no
fallback chain.

## Fields

### `schema` (string, required, const)

Always `"ponytail-toggle/v1"` for this version. Used by the read path to detect
on-disk staleness and trigger a migration (when v2 lands).

### `enabled` (boolean, required)

Master switch. When `false`, all components are inert regardless of their
individual flags. Effectively: `enabled == false → off`. The UI MUST display
the master switch separately from the component toggles.

### `mode` (string, required, enum)

One of `"lite"` | `"full"` | `"ultra"`. Only consulted when
`components.code_style` is `true`.

Intensities defined in [skills/ponytail/SKILL.md](../skills/ponytail/SKILL.md)
under the H2 sections `## Lite mode ruleset`, `## Full mode ruleset`,
`## Ultra mode ruleset` — that file is the LLM-facing source of truth.

Why `mode` lives at top level (not inside `components`): a user toggling between
`lite` and `ultra` for the code-style component should not have to also flip the
`code_style` boolean. Conceptually one field.

### `components` (object, required, additionalProperties: false)

Four boolean flags, all required. The UI MUST render all four even if some are
inert in the current `enabled` state — toggling them while `enabled: false` is
allowed (pre-stages intent) but has no side effects until `enabled: true`.

| Key               | Type | Persistent? | Side effect when ON (and enabled) |
|-------------------|------|-------------|------------------------------------|
| `code_style`      | bool | yes         | Marker-fenced ladder block in AGENTS.md + per-turn reinforcement hook fires |
| `review_ponytail` | bool | no          | Capability flag — gates the `/ponytail-review` skill. No persistent mutation. |
| `audit_ponytail`  | bool | no          | Capability flag — gates the `/ponytail-audit` skill. No persistent mutation. |
| `debt_ponytail`   | bool | no          | Capability flag — gates the `/ponytail-debt` skill. No persistent mutation. |

**Persistent** components mutate files on disk and require backups; the toggle
CLI orchestrates those mutations. **Non-persistent** components are pure
capability flags — flipping them changes nothing on disk; they only matter when
the skills read them. (There is no MCP-wrapping or doc-compression component —
those are caveman-specific.)

### `applied_at` (string, required, format: date-time)

ISO 8601 UTC timestamp of the last write. Set automatically by the CLI on every
`on`/`off`. Used by audit/telemetry.

### `applied_by` (string, optional, maxLength: 128)

Identifier of who/what triggered the last write. Sourced from `$USER` or
`$USERNAME` env vars by the CLI. UI consumers SHOULD set explicitly (e.g.
`"ui:dashboard-v1"`) so the audit trail distinguishes CLI from UI writes.

## Forbidden states

The schema enforces:
- No unknown top-level keys (`additionalProperties: false`).
- No unknown component keys.
- `mode` outside the enum is rejected.
- `schema` other than `"ponytail-toggle/v1"` is rejected on read.

Out of the schema's reach, but enforced by the CLI:
- `enabled: true` with all `components: false` is allowed (master switch on but
  everything disabled — equivalent to OFF but distinct in intent).
- `mode: ultra` with `components.code_style: false` is allowed (the mode value
  is ignored; flipping `code_style` later picks it up).

## Migration policy (v1 → v2 hypothetical)

When v2 lands:

1. A new schema file `schemas/schema-ponytail-toggle-v2.json` is added, with a
   `schema` const of `"ponytail-toggle/v2"`.
2. A migration script `scripts/ponytail/migrations/v1_to_v2.py` is added with a
   single public function `migrate(state: dict) -> dict`.
3. `scripts/ponytail/toggle.read_state` is extended to dispatch on the `schema`
   field: v1 → run migrate → validate against v2 → return.
4. The on-disk file is rewritten in v2 format on the next `read_state` call,
   with a backup at `.ai-playbook/backups/state/ponytail.json.<ts>.bak`.
5. UI consumers continue to call `status --json` and receive v2 data; schema
   version surfaced under `state.schema`. UIs built for v1 MUST refuse with a
   clear error if they see v2.

No silent drift. No best-effort migrations. Every version bump is explicit,
audited, and reversible from the backup.

## Test coverage

- [`tests/test_ponytail_toggle.py`](../tests/test_ponytail_toggle.py) — schema
  validation, default-state shape, round-trip read/write, atomic-write
  guarantees.
- [`tests/test_ponytail_cli.py`](../tests/test_ponytail_cli.py) — CLI
  on/off/status behaviour.
- [`tests/test_ponytail_materialise.py`](../tests/test_ponytail_materialise.py)
  — AGENTS.md inject/strip round-trip.

## Change log

| Version | Date       | Notes                                                                       |
|---------|------------|-----------------------------------------------------------------------------|
| v1      | 2026-06-16 | Initial. Four components, three modes, per-project state, marker-fenced materialise. |

## See also

- [docs/operations/ponytail-architecture.md](../docs/operations/ponytail-architecture.md) — UI integration contract (subprocess recipes, state-machine diagram, failure semantics).
- [docs/runbooks/ponytail-toggle.md](../docs/runbooks/ponytail-toggle.md) — operator how-to.
- [docs/concepts/ponytail-mode.md](../docs/concepts/ponytail-mode.md) — design overview and motivation.
- [specs/caveman-toggle.md](caveman-toggle.md) — the prose-compression twin spec.
