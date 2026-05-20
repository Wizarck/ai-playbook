---
schema: tutorial/v1
slug: fork-inventory
title: Fork inventory — walk the upstream-tracked forks the project maintains
description: A guided walk through the upstream-tracked forks the playbook touches. Read the catalog, then practise the 5-step onboarding checklist by mentally adding a sixth fork.
estimated_time: "10 min"
prerequisite_concepts: [upstream-sync]
audience: developer
order: 7
---

# Fork inventory — walk the upstream-tracked forks the project maintains

> **What you'll learn**: How the playbook keeps track of upstream-tracked forks, what each row in the inventory means, and how to onboard a new fork end-to-end via the 5-step checklist. By the end you will be able to read a row of the table aloud and explain why each column exists.
> **Estimated time**: 10 min
> **Prerequisites**:
> - [01-architecture-tour.md](01-architecture-tour.md) — feel the repo shape
> - [Concept: upstream-sync](../concepts/upstream-sync.md) — the governance contract this catalog implements

This tutorial is intentionally short. Treat it as a guided read of the fork catalog plus a thought experiment: at the end you mentally onboard one more fork using the checklist.

> **Note on examples**: the table in §2 uses generic example rows after the
> v0.19 privacy-flip scrub (commit `e6f640c`). Your own catalog lives in
> the consumer repo's `forks.md` (or equivalent); the rows here exist only
> to show shape, not to enumerate real upstream forks.

---

## 1. Why the inventory exists (≤2 min)

- **Discoverability.** A single-file answer to "which forks do we run, and who owns them?"
- **Onboarding.** Every new fork follows the same 5-step checklist (§3).
- **Cross-ref for automation.** `scripts/upstream_sync.py` and the LangGraph
  `upstream_refresher.py` workflow consume this inventory via `~/.ai-playbook/forks.yaml`.

The per-dev YAML registry at `~/.ai-playbook/forks.yaml` is the machine-readable source of
truth; this Markdown file is the human-readable catalog.

## 2. Inventory (example shape)

The rows below show the **shape** of a fork catalog — what each column means
and how to fill them. Your real catalog lives in a consumer repo, not in
this template.

| Fork | Upstream | Our repo | Branch | Owner | Purpose |
|---|---|---|---|---|---|
| `example-agent` | `upstream-org/example-agent` | `your-org/example-agent` | `main` | `you@example.com` | A fork tracking an active upstream; weekly `upstream_refresher` runs against it. Use this row as a template for fast-moving forks where you carry patches. |
| `example-mcp-wrapper` | — (own repo; not a fork) | `your-org/example-mcp-wrapper` | `main` | `you@example.com` | Original work tracked here because an upstream system it wraps may force interface changes. Use this row for "not a fork but watch this" entries. |
| `example-curated-list` | `community/awesome-thing` | `your-org/awesome-thing` | `main` | `you@example.com` | Low-churn fork of a curated list. Use this row for forks that need refresh ≤ monthly. |
| `example-upstream-image` | — (consumed as container image, not forked) | — | — | — | Upstream consumed as an artifact. Tracked so that if divergence becomes necessary, the row is already there waiting to be filled. |
| `example-deferred-fork` | — (not yet forked) | — | — | — | Placeholder for a fork you intend to create later. Helpful so the inventory documents intent, not just current state. |

Each row's `Our repo` should link to a local clone whose `PATCHES.md` is the
authoritative patch list for that fork (template at
[`../../templates/PATCHES.md.tmpl`](../../templates/PATCHES.md.tmpl)). When
adding a new fork, populate the catalog AND append to
`~/.ai-playbook/forks.yaml` (see §3 step 5).

## 3. Onboarding a new fork

Follow in order. Do not skip.

1. **Fork on GitHub.** Create the fork under the org (or tenant-appropriate org).
2. **Set `upstream` remote.** In the local clone:
   ```bash
   git remote add upstream <upstream-url>
   git fetch upstream
   git branch --set-upstream-to=upstream/main main
   ```
3. **Add `PATCHES.md` at the fork root.** Copy from
   [`../../templates/PATCHES.md.tmpl`](../../templates/PATCHES.md.tmpl); fill `{{FORK_NAME}}`,
   `{{UPSTREAM_URL}}`, `{{LAST_REFRESH_ISO}}`, and `{{TODAY}}`. Commit.
4. **Add an entry to your inventory.** In your consumer-side fork catalog
   (whatever file plays the role of §2 for your project) append a new row
   with a one-line Purpose. Keep the columns in the same order as the
   example table above.
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

If you stop tracking a fork (upstream dead, you no longer use it, you vendored permanently):

1. Mark every active patch in `PATCHES.md` as `lost` or `merged` with a final decision note.
2. Move the row in your inventory to a struck-through archive block at the
   end of the file (retain for history; don't delete).
3. Remove the entry from `~/.ai-playbook/forks.yaml`.
4. Record a decision entry (in Hindsight, ADR, or your team's equivalent
   memory store) explaining the retirement so future onboarding doesn't
   re-add the fork by accident.

## 5. What's next

- [Concept: upstream-sync](../concepts/upstream-sync.md) — the governance spec this catalog implements.
- [`../../templates/PATCHES.md.tmpl`](../../templates/PATCHES.md.tmpl) — per-fork manifest template you use in §3 step 3.
- `scripts/upstream_sync.py` — CLI inspection + triage tool that reads `~/.ai-playbook/forks.yaml`.
- [05-learning-path.md](05-learning-path.md) — fork onboarding sits inside the contributor stage.

---

The example rows are illustrative — they do NOT enumerate any real upstream
forks the playbook maintains. Treat them as a shape guide; your consumer
repo's fork catalog is authoritative for that project.
