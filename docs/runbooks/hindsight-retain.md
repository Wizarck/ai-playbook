---
schema: runbook/v1
slug: hindsight-retain
description: Persist a lesson, decision, gotcha, or failure pattern to the Hindsight memory layer so future agent sessions can recall it.
audience: developer
estimated_time: 2-5 min
last_validated: "2026-05-19"
---

# Retain a lesson to the Hindsight memory layer

## Outcome

A lesson is durably stored in the chosen Hindsight bank with the right `kind`, `project`, and tags. Future agent sessions in any project and any LLM CLI can `recall` it. This is the canonical write path described in [Concept: memory-hierarchy](../concepts/memory-hierarchy.md).

## When to use this

Trigger the retain at the boundary of a meaningful event:

| Event | Kind | Bank |
|---|---|---|
| ADR chosen over a named alternative | `decision` | project bank (`consumer-c`, `consumer-d`, `consumer-b`) |
| Gotcha discovered (wrong port, weird env, breaking API quirk) | `gotcha` | project bank |
| Agentic-failure mode fired and was resolved | `failure` | project bank |
| Retro extracted a reusable pattern | `lesson` | project bank |
| Cross-project policy or convention | `lesson` | `consumer-d` (universal personal) |
| Production fact about an external system | `fact` | project or `consumer-d` |

Skip retain when the content is already trivially recoverable from `git log`, `git blame`, the code itself, or a recent doc commit. The Claude Code per-project auto-memory folder is not a substitute — it only reloads in the same project's CLI.

## Prerequisites

- `secrets/secrets.env` (SOPS-decryptable) exists with `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`, `HINDSIGHT_URL`: `sops -d ../consumer-d/secrets/secrets.env | grep ^HINDSIGHT_URL=`.
- `sops` and `age` installed: `sops --version && age --version`.
- The retain script is reachable: `ls .ai-playbook/scripts/retain_memory.py`.

## Steps

1. **Single-item retain** — the common path:
   ```bash
   sops exec-env ../consumer-d/secrets/secrets.env -- \
     python .ai-playbook/scripts/retain_memory.py \
       --bank consumer-d \
       --kind decision \
       --project ai-playbook \
       --content "Rotated GITHUB_TOKEN from god-mode PAT to fine-grained scoped" \
       --why "Least-privilege; god-mode PAT was a 1-week stop-gap" \
       --tag rotation --tag security
   ```
   Expected output: `✅ retained 1 item(s) to bank=consumer-d; usage=2884 tokens`.

2. **Bulk retain (optional)** — when several lessons land in one session:
   ```bash
   cat > /tmp/lessons.jsonl <<'EOF'
   {"content": "Lesson 1 body...", "kind": "decision", "project": "ai-playbook", "why": "..."}
   {"content": "Lesson 2 body...", "kind": "gotcha", "project": "consumer-c", "tags": ["build", "ci"]}
   EOF

   sops exec-env ../consumer-d/secrets/secrets.env -- \
     python .ai-playbook/scripts/retain_memory.py --bank consumer-d --bulk /tmp/lessons.jsonl
   ```
   Each line is one item. Required field: `content`. Optional: `why`, `kind`, `project`, `tags`, `trace_id`, `context`, `ttl_days`, `timestamp`, `document_id`.

3. **Dry-run when the body is risky** — multi-line text, near a secret-shaped pattern:
   ```bash
   python .ai-playbook/scripts/retain_memory.py \
       --bank consumer-d --content "..." --kind lesson --dry-run
   ```
   Prints the JSON that would be POSTed; no network call. Confirm the rendered payload before retaining for real.

4. **Verify the retain landed** by recalling the same query:
   ```bash
   sops exec-env ../consumer-d/secrets/secrets.env -- \
     python -c "
   from scripts._hindsight import load_credentials, post_recall
   c = load_credentials()
   r = post_recall(c, 'consumer-d', 'your search query here', max_tokens=2000)
   print(r.body if r.ok else r.reason)
   "
   ```
   The newly retained item appears in `results[]`. Semantic search ranks by relevance, so the item is not necessarily first.

## Verification

- Step 1 prints `✅ retained 1 item(s) to bank=<name>`.
- Step 4 recalls the lesson body verbatim from the bank.
- `events.jsonl` shows a `hindsight.retain` event with the new item's `document_id`.

## Troubleshooting

### Symptom: script exits 3 with `OVERRIDE: none` after a content scan
**Cause**: the merged `content` + `why` text contains a shape matching a hard-blocked secret pattern (e.g., `anthropic-api-key`, `openai-api-key`, `github-pat`, `aws-secret`). `scripts.secrets_scan.sanitise` runs before POST and hard-blocks these. No break-glass is available for this gate.
**Fix**: clean up the lesson body — paraphrase the key reference, or replace the token-shaped substring with `<redacted>`. Re-run.

### Symptom: item retained but tagged `sanitised`
**Cause**: a softer pattern matched (URL with embedded token, base64-ish string). The script redacted the match and added the `sanitised` tag.
**Fix**: expected behaviour. If the redaction was over-eager, re-author the lesson with the redacted span as an explicit placeholder and retain again.

### Symptom: `degraded:retain_failed` or network error
**Cause**: `HINDSIGHT_URL` unset OR Hindsight unreachable. The script appended the item to `<consumer>/.ai-playbook/hindsight-queue.jsonl` (gitignored) and exited 0.
**Fix**: in most cases you don't need to do anything — the queue drains automatically:

- **On next successful `retain_memory.py` run**: after a POST returns ok, any
  queued items for the same bank are drained opportunistically. You'll see
  `📤 opportunistically drained N previously queued item(s)` on stderr.
- **On the next `SessionStart` hook fire** (i.e. when you open Claude Code):
  after a successful recall, the queue is drained the same way. You'll see
  `📤 SessionStart drain: replayed N queued item(s)` on stderr.

If you want to force a manual drain (e.g. you have queued items but won't
retain/open a session for a while):
```bash
sops exec-env ../consumer-d/secrets/secrets.env -- \
  python .ai-playbook/scripts/retain_memory.py --bank consumer-d --replay-queue
```
The script POSTs each queued item, removes it on success, and keeps it for the next replay attempt on failure.

### Symptom: SOPS path differs because the repo is not co-located with `consumer-d/`
**Cause**: the canonical wrapper assumes `../consumer-d/secrets/secrets.env` is the SOPS source.
**Fix**: either point `sops exec-env` at an explicit absolute path (`sops exec-env /absolute/path/to/secrets.env -- python ...`), or export the three env vars (`CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`, `HINDSIGHT_URL`) in the shell profile and drop the `sops exec-env` wrapper.

## Related

- [Runbook: release](release.md) — when retain is part of the release flow.
- [Concept: memory-hierarchy](../concepts/memory-hierarchy.md) — write rules and bank conventions.
- [Concept: env-vars](../concepts/env-vars.md) — `HINDSIGHT_*` and `CF_ACCESS_*` env contract.
- [Concept: session-start-hook](../concepts/session-start-hook.md) — the read side; the partner hook recalls memory at session start.
