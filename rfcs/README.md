# RFCs

Breaking changes to the playbook schema or dispatcher semantics go through an RFC here.

## Template

```markdown
# RFC N — <title>

- Status: draft | accepted | rejected | superseded-by-RFC-M
- Author: <name>
- Opened: YYYY-MM-DD
- Decided: YYYY-MM-DD
- Affects: schema | dispatcher-chain | mcp-schema | model-routing | verdict-contract | …

## Context

Why now? What changed in the world to force this?

## Proposal

Concrete change. Before / after YAML or paths. Semver bump: patch | minor | major.

## Consumer impact

Which consumers break? What's the migration recipe? Does it need a deprecation window?

## Alternatives considered

At least two. Why rejected.

## Decision

If accepted: which CHANGELOG release carries the change?
```

## Numbering

Sequential integers, zero-padded to 4 digits: `RFC-0001.md`, `RFC-0002.md`, …

## v0.1.0 state

No RFCs yet. First RFC will likely be T02 → dispatcher refactor landing across all consumers.
