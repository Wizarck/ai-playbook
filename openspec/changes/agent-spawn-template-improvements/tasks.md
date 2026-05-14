# Tasks: agent-spawn-template-improvements

- [ ] 1. `specs/release-management.md` — add §4.5.5 "Worker-agent delegation: STOP-after-`gh pr create` directive" per proposal.
- [ ] 2. `specs/release-management.md` — add §4.5.6 "Worker-agent delegation: AI-reviewer signoff canonical block in prompt" per proposal.
- [ ] 3. `CHANGELOG.md` — add `[0.13.4]` patch entry summarising the two additive subsections + iguanatrader reference parent (PRs #149-#152 + #152 L2 cycle).
- [ ] 4. Local lint: `ruff` + any markdown linter applicable; no Python script changes needed.
- [ ] 5. Push + open PR with §4.5 self-review (Profile B — docs-only).
- [ ] 6. STOP after `gh pr create` returns the PR URL. Parent monitors CI.
