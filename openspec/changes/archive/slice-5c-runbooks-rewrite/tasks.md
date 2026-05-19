## Tasks

### Schema + tooling

- [x] Author `schemas/schema-runbook-v1.json` (disjoint with rule + concept schemas; required: schema/slug/description/audience/estimated_time).

### Runbook rewrites (14 files)

- [x] `cascade-failure-template.md` — outcome + steps for authoring a per-service cascade runbook.
- [x] `coderabbit-fallback.md` — Profile B self-review walkthrough when CodeRabbit unavailable.
- [x] `git-worktree-bare-setup.md` — bare-repo + per-branch worktree setup (greenfield / migrate / daily flow).
- [x] `hindsight-retain.md` — persist a lesson to the Hindsight memory layer.
- [x] `onboard-new-project.md` — attach a new repo to the playbook.
- [x] `propagate-bump-troubleshooting.md` — diagnose propagate-bump workflow failures.
- [x] `release.md` — cut a new ai-playbook version tag.
- [x] `rotate-secrets.md` — rotate playbook-managed secrets.
- [x] `runbook-db-corruption.md` — recover from Hindsight DB corruption.
- [x] `runbook-key-rotation-emergency.md` — emergency rotation of leaked credentials.
- [x] `runbook-secrets-leak-containment.md` — wide-scope leak containment + disclosure.
- [x] `runbook-vps-down.md` — recover from VPS unreachable.
- [x] `skills-version-bump.md` — cut a new skills source-repo tag.
- [x] `windows-dev-environment.md` — Windows + WSL2 dev-loop gotchas.

### Validation

- [x] `python scripts/check_doc_language.py docs/runbooks/` exits 0.
- [x] `python scripts/check_link_integrity.py docs/runbooks/` exits 0.
- [x] `pytest tests/` green.

### Index + cross-refs

- [x] Refresh `docs/runbooks/INDEX.md` (regenerated from frontmatter via `gen_indexes.py` or manually mirroring its format).
- [x] Cross-refs to `docs/concepts/*.md` use the locked 5.B anchors.
