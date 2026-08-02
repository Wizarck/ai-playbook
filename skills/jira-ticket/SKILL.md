---
name: jira-ticket
description: Use when creating a Jira ticket for the GPLO project — the user types /jira-ticket, asks to "open a ticket", "file a bug", "create an issue", or asks you to record work in Jira. Builds the ticket from the canonical template, fills what it can infer from the session, and refuses to emit one that misses a required section. Pairs with the jira-ticket-standard rule, which blocks the raw MCP call.
license: MIT
metadata:
  author: ai-playbook
  version: "1.0"
---

# jira-ticket — author a ticket that survives contact with the backlog

You are filling in a form whose contract is machine-checked. The contract is
`specs/jira-ticket-standard.yaml`; the human face of it is
`templates/jira-ticket.md.tmpl`; the canonical worked example is
[GPLO-1350](https://geeplo.atlassian.net/browse/GPLO-1350).

**Draft first, then submit.** The PreToolUse hook will reject a non-conformant
`createJiraIssue` call, and a rejected call costs a round trip. Assemble the
whole description, check it against the checklist below, and only then call the
MCP tool.

## Your job is to fill it in, not to hand over a blank form

A skill that only refuses is a linter, and if using it is slower than calling
the MCP tool directly, nobody uses it. So do the work:

- **Infer `Contexto / Problema` from the session.** You almost always know why
  this ticket exists — you just hit the bug, or read the code, or measured the
  thing. Cite the evidence you already have: `file.py:line`, a measurement, a
  failing test, the commit that introduced it.
- **Infer `Alcance / Entregables`** from what was actually discussed. Name real
  paths.
- **Propose the metric and its type**, then say which you chose and why in one
  line. Users correct a proposal far more readily than they fill a blank.
- **Only leave `<<...>>` where you genuinely cannot know** — and then ask, in one
  question, for exactly those. Never submit with a sentinel still in place; the
  validator rejects it, by design.

## The required shape

Read `templates/jira-ticket.md.tmpl` for the skeletons. In short:

| Issue type | Sections |
|---|---|
| Feature / Big Improvement · Small Improvement | Contexto / Problema · Alcance / Entregables · Plan de prueba (A/B/C) · Métricas |
| Bug | Contexto / Problema · Repro · Esperado vs Actual · Test de regresión · Métricas |
| Subtask · Epic | Contexto / Problema · Alcance / Entregables |

Headings are Spanish, matched case- and accent-insensitively, tolerant of a `2.`
prefix and a trailing `(parenthetical)`.

**The five metric types, and nothing else:**

- `cobertura / compliance` — what fraction of X satisfies Y
- `calidad / exactitud` — how often the thing is RIGHT; false positives, accuracy
- `tendencia / burn-down` — a count moving over time, in the direction you claimed
- `rendimiento / eficiencia` — time, throughput, resource use
- `coste` — money, tokens, CI minutes

Each metric line reads `- <what you measure> → <type>`.

## Your failure mode is plausibility

The validator checks shape. You are the only thing checking *substance*, and the
characteristic way this goes wrong is that every section is present, well
written, and says nothing. Four specific traps, each observed:

1. **A metric with no measurement behind it.** "Mejora de la calidad del código →
   calidad / exactitud" names a type and measures nothing. Ask: *who runs what
   command, and what number comes out?* If there is no answer, the honest move is
   `N/A — <por qué>` for that section, which is allowed and counted.

2. **A B that is not a negative control.** "Comprobar que falla" is a wish. B must
   name the **exact assertion you invert** and the error you expect —
   "quito la sección `## Métricas` del payload y el hook devuelve `deny` con
   `missing-section`". A test plan whose A passes proves only that you did not
   test; B is the half that proves the gate bites. Boilerplate phrasings are
   rejected by name in the contract, so writing one costs you a round trip.

3. **A C that names nothing.** "No romper nada" is not a regression test. Name a
   path or an id — `tests/test_jira_ticket_standard.py` — or write
   `ninguno aún — <por qué>` and mean it.

4. **Header stuffing.** Every heading present, every body "TBD"/"pendiente".
   This is the failure the whole standard exists to catch. If you find yourself
   writing filler to satisfy a section, that is the signal to use the escape
   hatch honestly instead.

## The escape hatch

`N/A — <razón>` is valid **per section**, never for a whole ticket. Its usage
rate is reported by `check`. A high rate is information about the template, not
an infraction — but a reason that says "no aplica" is not a reason.

## Before you call the MCP tool

- Every required section present, with real content.
- No `<<...>>` left anywhere.
- Every metric line parses as `- <métrica> → <tipo>`, type from the five.
- B names the assertion that flips. C names a test or admits none, with a reason.
- Epic parent set (`parent`) and labels chosen.

Then call `createJiraIssue`. If the hook blocks you, it returns every problem at
once — fix them all in one pass rather than resubmitting per finding.

## Checking existing tickets

```
python .ai-playbook/scripts/rules/jira-ticket-standard.rule.py explain <KEY>
python .ai-playbook/scripts/rules/jira-ticket-standard.rule.py check --since 2026-08-02
```

`explain` shows the match section by section — use it when a rejection surprises
you, because the answer is usually a heading the resolver did not recognise
rather than a section you forgot.

## When NOT to fire

- **Tracker stubs from `issue_sync`.** Those carry `ai-playbook-managed` and are
  exempt: their content of record is the OpenSpec proposal, and duplicating an
  A/B/C into the stub creates a second copy that drifts from the first.
- **Editing a ticket's fields other than the description** — nothing to validate.
- **Non-GPLO projects.** The contract is scoped to this project's conventions.

## See also

- `specs/jira-ticket-standard.yaml` — the contract, including the closed list.
- `docs/rules/jira-ticket-standard.rule.md` — the binding rule and the enforcement
  topology, including what it deliberately cannot cover.
- `templates/jira-ticket.md.tmpl` — the skeletons.
