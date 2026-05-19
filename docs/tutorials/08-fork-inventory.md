---
schema: tutorial/v1
slug: fork-inventory
title: Fork inventory — walk the upstream-tracked forks Arturo maintains
description: A guided walk through the upstream-tracked forks the playbook touches. Read the catalog, then practise the 5-step onboarding checklist by mentally adding a sixth fork.
estimated_time: "10 min"
prerequisite_concepts: [upstream-sync]
audience: developer
order: 8
---

# Fork inventory — walk the upstream-tracked forks Arturo maintains

> **What you'll learn**: How the playbook keeps track of upstream-tracked forks, what each row in the inventory means, and how to onboard a new fork end-to-end via the 5-step checklist. By the end you will be able to read a row of the table aloud and explain why each column exists.
> **Estimated time**: 10 min
> **Prerequisites**:
> - [01-architecture-tour.md](01-architecture-tour.md) — feel the repo shape
> - [Concept: upstream-sync](../concepts/upstream-sync.md) — the governance contract this catalog implements

This tutorial is intentionally short. Treat it as a guided read of the fork catalog plus a thought experiment: at the end you mentally onboard a sixth fork using the checklist.

---

## 1. Why the inventory exists (≤2 min)

- **Discoverability.** A single-file answer to "which forks do we run, and who owns them?"
- **Onboarding.** Every new fork follows the same 5-step checklist (§3).
- **Cross-ref for automation.** `scripts/upstream_sync.py` and the LangGraph
  `upstream_refresher.py` workflow consume this inventory via `~/.ai-playbook/forks.yaml`.

The per-dev YAML registry at `~/.ai-playbook/forks.yaml` is the machine-readable source of
truth; this Markdown file is the human-readable catalog.

## 2. Inventory

| Fork | Upstream | Our repo | Branch | Owner | Purpose |
|---|---|---|---|---|---|
| hindsight | — (consumed as upstream image `ghcr.io/vectorize-io/hindsight`; not forked) | — | — | — | Not a fork. Upstream container image consumed directly by k3s Deployment. If divergence needed later, fork `vectorize-io/hindsight` and update this row. |
| hermes | `NousResearch/hermes-agent` | [`Wizarck/hermes-agent`](https://github.com/Wizarck/hermes-agent) | `consumer-d/main` | Arturo | Personal assistant agent deployed 24/7 on VPS per `consumer-d.md` (`/opt/hermes/`, Telegram gateway, API `:8642`). Upstream moves fast; weekly `upstream_refresher` targets this fork. **This is THE Hermes** — Arturo's single personal-assistant runtime. |
| paperclip-mcp | — (own repo; Paperclip itself lives elsewhere) | [`Wizarck/paperclip-mcp`](https://github.com/Wizarck/paperclip-mcp) | `main` | Arturo | MCP server wrapping the Paperclip orchestration platform. NOT a fork — original work. Tracked here because Paperclip upstream changes may require MCP interface updates. |
| awesome-paperclip | `gsxdsm/awesome-paperclip` | [`Wizarck/awesome-paperclip`](https://github.com/Wizarck/awesome-paperclip) | `main` | Arturo | Curated plugin list; low-churn fork. |
| lightrag | — (not yet forked on Wizarck org) | — | — | — | Not found in Wizarck GitHub org at inventory time. If / when a fork is needed, create `Wizarck/lightrag` and update this row. |

Each row's `Our repo` links to a local clone whose `PATCHES.md` is the authoritative patch list
for that fork. When adding a new fork, populate this table AND append to
`~/.ai-playbook/forks.yaml` (see §3 step 5).

## 3. Onboarding a new fork

Follow in order. Do not skip.

1. **Fork on GitHub.** Create the fork under the `Wizarck` (or tenant-appropriate) org.
2. **Set `upstream` remote.** In the local clone:
   ```bash
   git remote add upstream <upstream-url>
   git fetch upstream
   git branch --set-upstream-to=upstream/main main
   ```
3. **Add `PATCHES.md` at the fork root.** Copy from
   [`../../templates/PATCHES.md.tmpl`](../../templates/PATCHES.md.tmpl); fill `{{FORK_NAME}}`,
   `{{UPSTREAM_URL}}`, `{{LAST_REFRESH_ISO}}`, and `{{TODAY}}`. Commit.
4. **Add an entry to this inventory.** Append a new row to §2 with the correct prefix
   (`consumer-d/...` or `consumer-b/...`) and a one-line Purpose.
5. **Register in `~/.ai-playbook/forks.yaml`.** Append an entry:
   ```yaml
   forks:
     <fork-name>:
       path: C:/Projects/<fork-name>
       upstream: <upstream-url>
       owner: <email>
   ```
   Verify with `python -m scripts.upstream_sync list` — the new fork MUST appear.

## 4. Removing a fork

If we stop tracking a fork (upstream dead, we no longer use it, we vendored permanently):

1. Mark every active patch in `PATCHES.md` as `lost` or `merged` with a final decision note.
2. Move the row in §2 to a struck-through archive block at the end of this file (retain for
   history; don't delete).
3. Remove the entry from `~/.ai-playbook/forks.yaml`.
4. `hindsight.retain` a decision entry in the `ops-forks` bank explaining the retirement.

## 5. What's next

- [Concept: upstream-sync](../concepts/upstream-sync.md) — the governance spec this catalog implements.
- [`../../templates/PATCHES.md.tmpl`](../../templates/PATCHES.md.tmpl) — per-fork manifest template you use in §3 step 3.
- `scripts/upstream_sync.py` — CLI inspection + triage tool that reads `~/.ai-playbook/forks.yaml`.
- [06-curriculum.md](06-curriculum.md) — fork onboarding sits inside the week-3 contributor scope.

---

**Inventory research 2026-04-23** — all URLs verified via `gh repo list Wizarck --limit 40`. Remaining clarifications
above; the placeholders are best-effort and need Arturo's verification before the workflow's
first run.
