# runbook: hindsight-retain.md — store a lesson / decision / gotcha

> **Audience**: the AI or a human maintainer at the end of any meaningful
> work — a discovered gotcha, an architectural decision, an agentic-failure
> resolved, a retro pattern.
> **Status**: v1.0.0. Companion to [release.md](release.md) +
> [propagate-bump-troubleshooting.md](propagate-bump-troubleshooting.md).
> **Prereqs**: SOPS-decryptable `secrets/secrets.env` with CF Access creds
> (`CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`, `HINDSIGHT_URL`).

## What this runbook does

Persists a lesson to the Hindsight memory layer so any future agent session —
in any project, in any CLI — can `recall` it. This is the canonical write
path described in [`specs/memory-hierarchy.md`](../specs/memory-hierarchy.md)
§5. The Claude Code per-project auto-memory folder is **not** a substitute —
it only reloads in the same project's CLI.

## When to retain

Trigger the retain at the boundary of a meaningful event, NOT for routine
facts (those live in the code or in `docs/`). Per memory-hierarchy.md §5:

| Event | Kind | Bank |
|---|---|---|
| ADR chosen over a named alternative | `decision` | project bank (`consumer-c-legacy`, `consumer-d`, `consumer-b`) |
| Gotcha discovered (wrong port, weird env, breaking API quirk) | `gotcha` | project bank |
| Agentic-failure mode fired and was resolved | `failure` | project bank |
| Retro extracted a pattern worth reusing | `lesson` | project bank |
| Cross-project policy or convention | `lesson` | `consumer-d` (universal personal) |
| Production fact about an external system | `fact` | project or `consumer-d` |

Skip retain when the content is already trivially recoverable from `git log`,
`git blame`, the code itself, or a recent doc commit.

## Single-item retain

```bash
sops exec-env ../consumer-d/secrets/secrets.env -- \
  python .ai-playbook/scripts/retain_lesson.py \
    --bank consumer-d \
    --kind decision \
    --project ai-playbook \
    --content "Rotated PLAYBOOK_PROPAGATION_TOKEN from god-mode PAT to fine-grained scoped to consumers.yaml" \
    --why "Least-privilege; god-mode PAT was a 1-week stop-gap" \
    --tag rotation --tag security
```

Expected output:

```
✅ retained 1 item(s) to bank=consumer-d; usage=2884 tokens
```

## Bulk retain (replay session memory)

When you've made several lessons in one session, dump them to a JSONL file and
retain in one round-trip:

```bash
cat > /tmp/lessons.jsonl <<'EOF'
{"content": "Lesson 1 body...", "kind": "decision", "project": "ai-playbook", "why": "..."}
{"content": "Lesson 2 body...", "kind": "gotcha", "project": "consumer-c-legacy", "tags": ["build", "ci"]}
EOF

sops exec-env ../consumer-d/secrets/secrets.env -- \
  python .ai-playbook/scripts/retain_lesson.py --bank consumer-d --bulk /tmp/lessons.jsonl
```

Each line is one item. Required field: `content`. Optional: `why`, `kind`,
`project`, `tags`, `trace_id`, `context`, `ttl_days`, `timestamp`,
`document_id`.

## Dry-run before retaining

When the lesson body is tricky (multi-line, near a secret-shaped pattern),
dry-run first to confirm the rendered Hindsight payload looks right:

```bash
python .ai-playbook/scripts/retain_lesson.py \
    --bank consumer-d --content "..." --kind lesson --dry-run
```

Prints the JSON that would be POSTed; no network call.

## Sanitisation contract

`retain_lesson.py` runs the merged (`content` + `why`) text through
`scripts.secrets_scan.sanitise` before POSTing.

- **Hard block** on shapes that look like API keys (`anthropic-api-key`,
  `openai-api-key`, `github-pat`, `aws-secret`). The script exits with code 3
  + canonical error + `OVERRIDE: none`. The lesson body must be cleaned up;
  there is no break-glass for this gate.
- **Soft redact** on softer matches (URLs with embedded tokens, base64-ish).
  The redacted text is sent + a `sanitised` tag is added to the item.
- **Pass-through** on clean content.

## Degraded mode (Hindsight unreachable)

When `HINDSIGHT_URL` is unset OR Hindsight returns network errors, the script
appends the item to `<consumer>/.ai-playbook/hindsight-queue.jsonl` (gitignored)
and exits 0. The session continues healthy. Drain the queue when Hindsight
comes back:

```bash
sops exec-env ../consumer-d/secrets/secrets.env -- \
  python .ai-playbook/scripts/retain_lesson.py --bank consumer-d --replay-queue
```

The script POSTs each queued item, removes it from the queue on success,
keeps it on failure for the next replay attempt.

## Verifying the retain landed

Recall the same query you'd run from a future session:

```bash
sops exec-env ../consumer-d/secrets/secrets.env -- \
  python -c "
from scripts._hindsight import load_credentials, post_recall
c = load_credentials()
r = post_recall(c, 'consumer-d', 'your search query here', max_tokens=2000)
print(r.body if r.ok else r.reason)
"
```

The newly-retained item should appear in `results[]` (semantic search; not
necessarily first if other entries are more relevant).

## Cross-references

- [`specs/memory-hierarchy.md`](../specs/memory-hierarchy.md) §5 — write rules.
- [`specs/env-vars.md`](../specs/env-vars.md) §HINDSIGHT_* — env contract.
- [`scripts/retain_lesson.py`](../scripts/retain_lesson.py) — the script.
- [`scripts/_hindsight.py`](../scripts/_hindsight.py) — shared HTTP client.
- [`docs/session-start-hook.md`](../docs/session-start-hook.md) — read side; the partner hook recalls memory at session start.
