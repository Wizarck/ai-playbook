# upstream-sync.md

> **Status**: v1.0.0. Populated in T23a.

Fork governance for upstream-tracked projects. Arturo runs forks of a handful of fast-moving
upstream repos (Hindsight, Hermes, Paperclip, LightRAG, and others). Upstream commits land at
hundreds-per-day rates in some of them; a naive `git pull upstream main` silently clobbers local
patches. This spec defines how forks are tracked, how local patches are inventoried, and how the
fork is refreshed without losing our work.

---

## 1. Purpose

- Make every local patch **discoverable** (named, tracked, reviewable).
- Make every upstream refresh **observable** (what changed upstream, what conflicts, which of our
  patches landed upstream or got rewritten out).
- Keep refresh **propose-only** — the same ceiling as all T18 workflows. Humans merge.

## 2. Fork governance model

For each tracked fork the repository has:

| Artefact | Location | Purpose |
|---|---|---|
| `upstream` git remote | configured via `git remote add upstream <url>` | the canonical upstream repo |
| `origin` git remote | our fork on GitHub | read/write for our team |
| `main` branch | tracks `upstream/main` (or `upstream/master`) | clean mirror; never hand-commit here |
| `consumer-d/<feature>` or `consumer-b/<feature>` branches | named, per-patch | each local patch carries its own branch |
| `PATCHES.md` | fork repo root | enumerates every local patch with status |

Rules:

- `main` is a **pure mirror**. Any commit that isn't a fast-forward from `upstream/main` is a red
  flag (`untracked_state_mutation` per [agentic-failures.md](agentic-failures.md)).
- A local patch exists ONLY on a named branch. No orphan commits on `main`.
- Every patch has exactly one row in `PATCHES.md`. An unlisted branch is drift; a listed patch
  without a branch is drift. `scripts/upstream_sync.py status` reports both.
- Prefix convention: `consumer-d/...` for personal/consumer-d tenant; `consumer-b/...` for consumer-b
  tenant. Other tenants add their prefix per ADR.

## 3. `PATCHES.md` contract

Template: [`templates/PATCHES.md.tmpl`](../templates/PATCHES.md.tmpl). Every fork MUST have one
at its root. Columns:

| Column | Semantics |
|---|---|
| Patch ID | `P01`, `P02`, … unique within the fork, monotonically assigned. |
| Title | ≤60 chars. What this patch does at a glance. |
| Branch | The named branch carrying the patch (`consumer-d/<feature>` or `consumer-b/<feature>`). |
| Upstream PR | PR number on the upstream repo if we've submitted the patch, else `—`. |
| Status | One of: `staged` \| `submitted` \| `merged` \| `rejected` \| `lost`. See §5. |
| Last rebase | ISO date when the patch was last rebased onto `upstream/main`. |
| Notes | Free text; rationale, blockers, linked ADRs. |

`PATCHES.md` also carries three secondary tables — *Merged upstream*, *Rejected upstream*, and
*Lost / needs re-author* — so the history of resolved patches survives even when the branch is
deleted. See the template.

## 4. Refresh cadence

- **Weekly**, automated via the `UpstreamRefresher` LangGraph workflow
  ([consumer-d/langgraph-aiops/workflows/upstream_refresher.py](../../consumer-d/langgraph-aiops/workflows/upstream_refresher.py)).
- **On-demand**, manual via `scripts/upstream_sync.py --refresh <fork>` — this only fetches and
  reports; it never merges.
- The workflow's write actions are **all gated** by
  [T18 HITL](../../consumer-d/langgraph-aiops/workflows/hitl.py). Every proposed auto-merge,
  every PATCHES.md rewrite, every branch deletion requests human approval first.

## 5. Diff triage rubric

After a fetch, for each patch in `PATCHES.md` and each new upstream commit, the workflow
classifies the outcome. Exactly one row applies per patch.

| Upstream state for our patch's surface | Classification | Proposed action | PATCHES.md update |
|---|---|---|---|
| No upstream change touches the patch's files | `clean` | fast-forward `main`; rebase each `staged` branch | `last rebase = today` |
| Upstream added code, no textual conflict with our patch | `auto-merge-candidate` | rebase; run upstream tests only after human approves | `last rebase = today` |
| Upstream added code, **textual conflict** with our patch | `flag-conflict` | HITL decides: rewrite, drop, or escalate | `notes += "conflict on <files>"` |
| Our exact patch merged upstream | `merged-upstream` | mark status `merged`, move row to *Merged upstream* archive table, delete local branch | status = `merged` |
| Upstream rejected our PR (closed, not merged) | `rejected-upstream` | mark status `rejected`, move row to *Rejected upstream* table with rationale; we keep carrying | status = `rejected` |
| Upstream rewrote the surface such that our patch no longer applies | `lost` | mark status `lost`; human decides whether to re-author | status = `lost` |

Tight reading:

- **`auto-merge-candidate`** is *candidate*, not automatic. The workflow proposes; HITL approves.
- **`flag-conflict`** never produces an in-workflow resolution. The human does the 3-way merge.
- **`merged-upstream`** detection uses the git patch-id (`git patch-id`); a heuristic, so HITL
  confirms before the branch is deleted.

## 6. Integration with T18 HITL

Any action that would rewrite `main` or force-push any branch routes through
[`hitl.request_approval`](../../consumer-d/langgraph-aiops/workflows/hitl.py) with:

```python
request_approval(
    action="upstream-refresh:<fork>:<classification>",
    payload={"fork": "...", "patch_id": "P03", "files": [...], "command_preview": "..."},
    severity="warn",
)
```

Severity ladder:

- `info` for `clean` and `merged-upstream` (the safe outcomes).
- `warn` for `auto-merge-candidate` (we're about to rewrite history).
- `error` for `flag-conflict` and `lost` (human attention required before anything moves).

## 7. Security

- **Upstream tests do not auto-run after refresh.** A compromised upstream could ship a malicious
  test or build step that would execute in our environment. The workflow's action proposals
  contain only `command_preview` strings; the human copy-pastes the merge command into their own
  shell after review.
- **No auto-push.** The workflow never invokes `git push`. Force-pushes to shared branches
  require explicit break-glass per [break-glass.md](break-glass.md).
- **Upstream URL trust.** The fork registry records the upstream URL; a registry edit that
  changes `upstream:` is a supply-chain event and is surfaced as `warn` in the next refresh.

## 8. Memory retention

Every merge event (our patch landing upstream, or our branch being rebased cleanly) is retained
per [memory-hierarchy.md](memory-hierarchy.md) with:

```json
{
  "bank": "<project>-fork-governance",
  "kind": "decision",
  "why": "patch P03 landed in upstream#482; dropped local branch",
  "tags": ["upstream-sync", "hindsight", "merged"]
}
```

Conflicts and lost patches retain as `kind=failure` with subtype `upstream_lost_patch` so retros
can surface repeat offenders (an upstream surface we keep losing patches on is a signal to stop
patching that file and open an upstream RFC instead).

## 9. Cross-references

- [break-glass.md](break-glass.md) — override contract for force-pushes.
- [agentic-failures.md](agentic-failures.md) — `untracked_state_mutation` applies to orphan
  commits on `main`.
- [verdict-contract.md](verdict-contract.md) — HITL uses verdicts.
- [memory-hierarchy.md](memory-hierarchy.md) — retain on every merge / lost event.
- [`../docs/fork-inventory.md`](../docs/fork-inventory.md) — the authoritative catalog of forks.
- [`../templates/PATCHES.md.tmpl`](../templates/PATCHES.md.tmpl) — per-fork manifest template.
- [`../../consumer-d/langgraph-aiops/workflows/upstream_refresher.py`](../../consumer-d/langgraph-aiops/workflows/upstream_refresher.py) —
  the workflow.

---

**TODO: clarify with maintainer** — the tagging convention for `Last rebase` timestamps (ISO
date vs. git-tag style) will firm up once the first real refresh cycle runs; until then ISO-8601
date (YYYY-MM-DD) is the default.
