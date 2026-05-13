# proposal — `upstream-sync-image-pin-discipline`

> **Status**: in-flight (slice/`upstream-sync-image-pin-discipline`).
> **Wave**: ai-playbook v0.13.2 candidate (additive PATCH — docs only).
> **Authored**: 2026-05-13.
> **Parent project**: `Wizarck/hermes-agent` deploy hotfix (PR #6). This proposal upstreams the
> lesson into the playbook spec so other forks (Hindsight, Paperclip, LightRAG, …) see the warning.

## Problem

`specs/upstream-sync.md` v1.0.0 covers fork governance for source-tree drift but does NOT mention
the containerised-fork pattern. When a fork ships as a Docker overlay (`Dockerfile.overlay` that
`COPY`s our custom source on top of an upstream-pinned base image), the source tree and the
base-image pin **must advance together** during every upstream sync. We learned this the hard way
on 2026-05-13:

- `Wizarck/hermes-agent` PR #4 merged 780 commits from `nousresearch/hermes-agent` into our fork
  tree. The merge introduced a new module `agent.account_usage` that some of our patched files
  (`gateway/run.py`) import.
- The overlay still pinned the OLD base image (sha256:c47d28...), so after rebuild the container
  copied our updated source over a base image that didn't contain `agent.account_usage` →
  `ModuleNotFoundError` at startup → `unhealthy` for ~10 minutes until PR #6 bumped the pin.

Without an explicit spec rule, every future containerised-fork sync risks repeating the same
mistake.

## Proposed change

Extend `specs/upstream-sync.md` with a new §9 "Containerised forks — base-image pin discipline":

- Names the pattern (overlay Dockerfile + pinned upstream base image).
- States the rule: bump source AND pin together.
- Failure mode: `ModuleNotFoundError` on any new import a synced source adds.
- Operational recipe: 4-step routine (merge → resolve digest → bump pin → rebuild).
- Tags the rule with the same memory-retention contract as §8 so the lesson lands in Hindsight.

Renumber existing §9 "Cross-references" → §10. Bump spec version v1.0.0 → v1.1.0 (additive).

## Acceptance

- [x] `specs/upstream-sync.md` gains §9 "Containerised forks — base-image pin discipline".
- [x] Spec frontmatter version bumped to v1.1.0.
- [x] Cross-references updated to cite the parent incident (Wizarck/hermes-agent PR #6).
- [ ] Lesson retained in Hindsight (bank `consumer-d`, kind `gotcha`, tag `upstream-sync,containerised-fork,fork-image-pin`).

## Cross-references

- Parent incident: [Wizarck/hermes-agent#6](https://github.com/Wizarck/hermes-agent/pull/6).
- Companion doc: [Wizarck/hermes-agent deploy/consumer-d-vps/README.md §"Upstream sync routine"](https://github.com/Wizarck/hermes-agent/blob/main/deploy/consumer-d-vps/README.md).
- Spec extended: [`specs/upstream-sync.md`](../../../specs/upstream-sync.md) v1.0.0 → v1.1.0.
