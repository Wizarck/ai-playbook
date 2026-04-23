# fork-inventory.md

> **Status**: v1.0.0. Populated in T23a. Companion to [`../specs/upstream-sync.md`](../specs/upstream-sync.md).

The authoritative list of upstream-tracked forks Arturo maintains. Each entry links to its local
clone and the in-repo `PATCHES.md` that enumerates its local patches.

---

## 1. Purpose

- **Discoverability.** A single-file answer to "which forks do we run, and who owns them?"
- **Onboarding.** Every new fork follows the same 5-step checklist (§3).
- **Cross-ref for automation.** `scripts/upstream_sync.py` and the LangGraph
  `upstream_refresher.py` workflow consume this inventory via `~/.ai-playbook/forks.yaml`.

The per-dev YAML registry at `~/.ai-playbook/forks.yaml` is the machine-readable source of
truth; this Markdown file is the human-readable catalog.

## 2. Inventory

| Fork | Upstream | Our repo | Branch | Owner | Purpose |
|---|---|---|---|---|---|
| hindsight | `upstream/hindsight-repo` (**TODO: clarify with maintainer** — URL) | `Wizarck/hindsight` | `consumer-d/main` | Arturo | Episodic memory MCP; upstream is fast-moving. |
| hermes | `upstream/hermes` (**TODO: clarify with maintainer** — URL) | `Wizarck/hermes` | `consumer-d/main` | Arturo | Personal assistant + Telegram gateway. |
| paperclip | `upstream/paperclip` (**TODO: clarify with maintainer** — URL) | `Wizarck/paperclip` | `consumer-b/main` | Arturo | BizOps orchestrator; consumer-b tenant. |
| lightrag | `upstream/lightrag` (**TODO: clarify with maintainer** — URL) | `Wizarck/lightrag` | `consumer-d/main` | Arturo | RAG substrate. |

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
   [`../templates/PATCHES.md.tmpl`](../templates/PATCHES.md.tmpl); fill `{{FORK_NAME}}`,
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

## 5. Cross-references

- [`../specs/upstream-sync.md`](../specs/upstream-sync.md) — the governance spec.
- [`../templates/PATCHES.md.tmpl`](../templates/PATCHES.md.tmpl) — per-fork manifest template.
- `scripts/upstream_sync.py` — CLI inspection + triage.
- `consumer-d/langgraph-aiops/workflows/upstream_refresher.py` — weekly refresh workflow.

---

**TODO: clarify with maintainer** — confirm the exact upstream URLs for the four forks listed
above; the placeholders are best-effort and need Arturo's verification before the workflow's
first run.
