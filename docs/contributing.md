# contributing.md

> **Status**: v1.0.0 governance stub. Supersedes T02-pre stub. Populated in **T14g**. Full governance suite (deprecation watcher, post-mortem template, RBAC vs k8s ServiceAccount matrix) lands **T22**; this doc covers what a 0–3-month team needs to collaborate safely.

---

## 1. Maintainer

**Arturo Ramírez** (`23051550+Wizarck@users.noreply.github.com`) is the sole maintainer for the 0–3 month horizon. No delegated approvers. PRs merge when Arturo clicks merge; RFCs decide when Arturo writes the `Decided:` line.

When the team grows past solo, T22 governance splits the role into a **standing maintainer committee** (≥2) and codifies quorum rules. Until then, single-point-of-failure is acknowledged and logged in the monthly retro.

---

## 2. Roles matrix

| Role | Who | Rights | Responsibilities |
|---|---|---|---|
| **Maintainer** | Arturo (solo at v0.1.0). | Merge to `master`. Pin semver tags. Accept/reject RFCs. Bypass RFC for docs-only / typo fixes. | Triage weekly. Respond to RFCs within SLA (§3). Keep `specs/*` consistent. Run the monthly retro. |
| **Reviewer** | Anyone Arturo names in a CODEOWNERS-style entry per PR (lands T22). Empty at v0.1.0. | Request changes, approve. Cannot merge. | Review within 7 days. Cite sources per principle #7 of global CLAUDE.md. Use the verdict contract for formal reviews. |
| **Contributor** | Any dev with a GH account. | Open issues, file RFCs, submit PRs, append to FEEDBACK.md. | Follow commit style (§4). Ship tests with every script (§5). Not gold-plate scope. |
| **Consumer-only** | Devs on projects that submodule the playbook but don't change it. | Read the specs. Inherit. File bugs via consumer-side issues. | Pin the submodule to a semver tag. Don't hand-patch `.ai-playbook/`; open an issue here instead. |

Consumer-only devs are the majority user. The playbook is optimised for their read path; contribution paths are a secondary concern until T22.

---

## 3. RFC process

Breaking changes to the schema, dispatcher semantics, or any spec's `## Contract` section require an RFC under [../rfcs/](../rfcs/). See `rfcs/README.md` for the template.

### 3.1 When to file an RFC

- Schema bumps (`agents-md/v1` → `v2`).
- Changes to canonical verdict literals / severity taxonomy.
- New required fields in any spec.
- Changes to dispatcher resolution order.
- Removing or renaming a public script.
- Changing exit-code semantics ([error-message-standard.md](../specs/error-message-standard.md) §exit codes).

Do NOT file an RFC for: typo fixes, new examples, clarifying prose, new optional fields, new scripts that don't replace existing ones.

### 3.2 SLAs

| Stage | SLA |
|---|---|
| Triage (open → first maintainer comment) | 7 days. |
| Decision (open → `accepted` / `rejected` / `needs-info`) | 30 days. |
| Auto-close (no author response to `needs-info`) | 90 days idle. Can be reopened with one comment. |

Missing the triage SLA surfaces as a warn-level notification per [notification-policy.md](../specs/notification-policy.md) §4 (event: `rfc.triage.slo_breached`, lands alongside T22 SLOs).

### 3.3 Where to file what

| Signal | Channel |
|---|---|
| Small gripe, no fix in mind | [../FEEDBACK.md](../FEEDBACK.md). One bullet. |
| Reproducible bug in a script | GH issue with repro + `scripts/` label. |
| Proposed enhancement (additive) | GH issue tagged `proposal`; may skip RFC if maintainer agrees. |
| Breaking change or contested design | RFC. No shortcut. |

---

## 4. Code style

- **Conventional Commits.** `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `build:`. Scope optional but encouraged (`feat(mcp): …`). Enforced by a pre-commit hook under T14 follow-up.
- **Ruff** for linting and formatting (`ruff check`, `ruff format`). Configured in `pyproject.toml`.
- **Type hints on every function.** `from __future__ import annotations` at the top of every script (already standard in `scripts/_break_glass.py`).
- **Docstrings** on public functions only. Per-function docstring explains the *why* when not obvious.
- **`pathlib.Path`**, never `os.path.join` with hardcoded separators — playbook scripts must run on Windows, macOS, Linux, WSL unchanged.

---

## 5. Test discipline

- Every script ships with `tests/test_<script_name>.py`. A script merged without tests fails CI.
- Tests use `pytest`. Fixtures for filesystem and env vars are centralised in `tests/conftest.py`.
- Full suite must be green before merge. No `xfail` markers on breaking behaviour without an associated issue.
- Coverage is advisory — the goal is meaningful tests, not a number. The monthly retro notices coverage drops of >5% and flags.
- `pre-commit run --all-files` MUST pass before opening a PR.

---

## 6. Backwards compatibility

- **Additive within a major.** New optional frontmatter field, new script, new severity doc row — all fine within a semver major.
- **Breaking changes need an RFC and a semver major bump.** A change that rejects previously-valid `AGENTS.md` files is breaking. A change that renames a script is breaking.
- **Deprecation window.** Before removal, a feature is first marked deprecated in [../specs/migration-guide.md](../specs/migration-guide.md) with a target removal version and a migration recipe. The deprecation watcher (T22) flags any deprecated-but-still-used path in consumer `AGENTS.md`.
- **Never edit archived specs.** Once `specs/*.md` reaches v1.0.0 and is consumed by ≥1 project, changes flow through RFC → version bump → migration guide. Silent edits are a governance-level violation.

---

## 7. See also

- [../AGENTS.md](../AGENTS.md) — hard rules for agents editing this repo (§4).
- [../specs/migration-guide.md](../specs/migration-guide.md) — versioning and deprecation mechanics.
- [../specs/retrospective-cadence.md](../specs/retrospective-cadence.md) — where governance slipups surface.
- [../rfcs/README.md](../rfcs/README.md) — RFC template.
- [../FEEDBACK.md](../FEEDBACK.md) — low-friction gripe channel.
