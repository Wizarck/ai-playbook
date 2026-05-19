"""One-shot path migration for Slice 4 (v0.18.0).

Walks all `.md`, `.py`, `.yaml`, `.yml`, and `.json` files under the repo root
(excluding `.git/`, virtualenvs, caches, the openspec slice that documents the
migration, and this script itself) and rewrites cross-references per the
static mapping below.

This script is **deleted in the same PR after the migration verifies green**
(CHANGELOG v0.18.0 entry is the historical record).

Idempotence: each substitution checks that the target ("new") form does not
already appear in the text in a way that would cause double-substitution.
Because we use `str.replace(old, new)` once per pair, and "new" never contains
"old" as a substring for any pair in this mapping, the operation is safe even
if applied twice.
"""
from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Static rename mapping (longest-first, no overlap between old and new strings)
# ---------------------------------------------------------------------------

RENAMES: list[tuple[str, str]] = [
    # -- Paired scripts -----------------------------------------------------
    ("scripts/cleanup_zombies.py", "scripts/rules/cleanup-zombies.rule.py"),
    # -- Rule-style specs ---------------------------------------------------
    ("specs/cleanup-zombies.md", "docs/rules/cleanup-zombies.rule.md"),
    ("specs/apply-skill-enforcement.md", "docs/rules/apply-skill-enforcement.rule.md"),
    ("specs/bootstrap-directive.md", "docs/rules/bootstrap-directive.rule.md"),
    ("specs/verdict-contract.md", "docs/rules/verdict-contract.rule.md"),
    ("specs/output-completeness.md", "docs/rules/output-completeness.rule.md"),
    ("specs/verification-before-completion.md", "docs/rules/verification-before-completion.rule.md"),
    ("specs/error-message-standard.md", "docs/rules/error-message-standard.rule.md"),
    ("specs/break-glass.md", "docs/rules/break-glass.rule.md"),
    ("specs/doc-drift-enforcement.md", "docs/rules/doc-drift-enforcement.rule.md"),
    ("specs/apply-fix-contract.md", "docs/rules/apply-fix-contract.rule.md"),
    ("specs/conflict-resolution-policy.md", "docs/rules/conflict-resolution-policy.rule.md"),
    ("specs/cross-slice-additive-extension.md", "docs/rules/cross-slice-additive-extension.rule.md"),
    ("specs/migration-slot-reservation.md", "docs/rules/migration-slot-reservation.rule.md"),
    ("specs/hitl-approval-pattern.md", "docs/rules/hitl-approval-pattern.rule.md"),
    # -- Concept-style specs (specs/<slug>.md -> docs/concepts/<slug>.md) ---
    ("specs/agent-contract.md", "docs/concepts/agent-contract.md"),
    ("specs/agent-telemetry.md", "docs/concepts/agent-telemetry.md"),
    ("specs/agentic-failures.md", "docs/concepts/agentic-failures.md"),
    ("specs/auto-managed-sections.md", "docs/concepts/auto-managed-sections.md"),
    ("specs/bmad-openspec-bridge.md", "docs/concepts/bmad-openspec-bridge.md"),
    ("specs/channels.md", "docs/concepts/channels.md"),
    ("specs/cross-language-tooling.md", "docs/concepts/cross-language-tooling.md"),
    ("specs/data-retention.md", "docs/concepts/data-retention.md"),
    ("specs/database-numeric-boundaries.md", "docs/concepts/database-numeric-boundaries.md"),
    ("specs/degradation-modes.md", "docs/concepts/degradation-modes.md"),
    ("specs/dependency-injection-patterns.md", "docs/concepts/dependency-injection-patterns.md"),
    ("specs/dispatcher-chain.md", "docs/concepts/dispatcher-chain.md"),
    ("specs/enforcement-status.md", "docs/concepts/enforcement-status.md"),
    ("specs/env-vars.md", "docs/concepts/env-vars.md"),
    ("specs/event-and-data-patterns.md", "docs/concepts/event-and-data-patterns.md"),
    ("specs/fusion-integration-pattern.md", "docs/concepts/fusion-integration-pattern.md"),
    ("specs/git-worktree-bare-layout.md", "docs/concepts/git-worktree-bare-layout.md"),
    ("specs/incident-response.md", "docs/concepts/incident-response.md"),
    ("specs/issue-tracking.md", "docs/concepts/issue-tracking.md"),
    ("specs/mcp-servers-schema.md", "docs/concepts/mcp-servers-schema.md"),
    ("specs/memory-hierarchy.md", "docs/concepts/memory-hierarchy.md"),
    ("specs/merge-policy.md", "docs/concepts/merge-policy.md"),
    ("specs/migration-guide.md", "docs/concepts/migration-guide.md"),
    ("specs/model-routing.md", "docs/concepts/model-routing.md"),
    ("specs/multi-layer-defense-single-operator.md", "docs/concepts/multi-layer-defense-single-operator.md"),
    ("specs/notification-policy.md", "docs/concepts/notification-policy.md"),
    ("specs/notification-queue.md", "docs/concepts/notification-queue.md"),
    ("specs/parallel-review.md", "docs/concepts/parallel-review.md"),
    ("specs/post-mortem.md", "docs/concepts/post-mortem.md"),
    ("specs/project-board-sync.md", "docs/concepts/project-board-sync.md"),
    ("specs/projects-registry.md", "docs/concepts/projects-registry.md"),
    ("specs/prompt-caching.md", "docs/concepts/prompt-caching.md"),
    ("specs/protocol-fake-deferred-install.md", "docs/concepts/protocol-fake-deferred-install.md"),
    ("specs/release-management.md", "docs/concepts/release-management.md"),
    ("specs/retrospective-cadence.md", "docs/concepts/retrospective-cadence.md"),
    ("specs/role-matrix.md", "docs/concepts/role-matrix.md"),
    ("specs/rollout-strategy.md", "docs/concepts/rollout-strategy.md"),
    ("specs/runbook-bmad-openspec.md", "docs/concepts/runbook-bmad-openspec.md"),
    ("specs/skills-distribution.md", "docs/concepts/skills-distribution.md"),
    ("specs/skills-registry.md", "docs/concepts/skills-registry.md"),
    ("specs/slos.md", "docs/concepts/slos.md"),
    ("specs/taxonomy.md", "docs/concepts/taxonomy.md"),
    ("specs/upstream-sync.md", "docs/concepts/upstream-sync.md"),
    ("specs/ux-track.md", "docs/concepts/ux-track.md"),
    ("specs/v0.8.0-roadmap.md", "docs/concepts/v0.8.0-roadmap.md"),
    ("specs/v0.9.0-roadmap.md", "docs/concepts/v0.9.0-roadmap.md"),
    # -- Tutorial docs (numbered) ------------------------------------------
    ("docs/start-here.md", "docs/tutorials/01-start-here.md"),
    ("docs/quickstart.md", "docs/tutorials/02-quickstart.md"),
    ("docs/bootstrap-new-project.md", "docs/tutorials/03-bootstrap-new-project.md"),
    ("docs/quickstart-lessons.md", "docs/tutorials/04-quickstart-lessons.md"),
    ("docs/curriculum.md", "docs/tutorials/05-curriculum.md"),
    ("docs/why-these-choices.md", "docs/tutorials/06-why-these-choices.md"),
    ("docs/fork-inventory.md", "docs/tutorials/07-fork-inventory.md"),
    # -- Remaining docs/<file>.md -> docs/concepts/ ------------------------
    ("docs/architecture-diagrams.md", "docs/concepts/architecture-diagrams.md"),
    ("docs/contributing.md", "docs/concepts/contributing.md"),
    ("docs/development-flow.md", "docs/concepts/development-flow.md"),
    ("docs/model-migration.md", "docs/concepts/model-migration.md"),
    ("docs/session-start-hook.md", "docs/concepts/session-start-hook.md"),
    ("docs/zero-touch-automation.md", "docs/concepts/zero-touch-automation.md"),
    # -- Runbooks ----------------------------------------------------------
    ("runbooks/cascade-failure-template.md", "docs/runbooks/cascade-failure-template.md"),
    ("runbooks/coderabbit-fallback.md", "docs/runbooks/coderabbit-fallback.md"),
    ("runbooks/git-worktree-bare-setup.md", "docs/runbooks/git-worktree-bare-setup.md"),
    ("runbooks/hindsight-retain.md", "docs/runbooks/hindsight-retain.md"),
    ("runbooks/onboard-new-project.md", "docs/runbooks/onboard-new-project.md"),
    ("runbooks/propagate-bump-troubleshooting.md", "docs/runbooks/propagate-bump-troubleshooting.md"),
    ("runbooks/release.md", "docs/runbooks/release.md"),
    ("runbooks/rotate-secrets.md", "docs/runbooks/rotate-secrets.md"),
    ("runbooks/runbook-db-corruption.md", "docs/runbooks/runbook-db-corruption.md"),
    ("runbooks/runbook-key-rotation-emergency.md", "docs/runbooks/runbook-key-rotation-emergency.md"),
    ("runbooks/runbook-secrets-leak-containment.md", "docs/runbooks/runbook-secrets-leak-containment.md"),
    ("runbooks/runbook-vps-down.md", "docs/runbooks/runbook-vps-down.md"),
    ("runbooks/skills-version-bump.md", "docs/runbooks/skills-version-bump.md"),
    ("runbooks/windows-dev-environment.md", "docs/runbooks/windows-dev-environment.md"),
    ("runbooks/INDEX.md", "docs/runbooks/INDEX.md"),
    # -- Schemas -----------------------------------------------------------
    ("specs/agent-contract.schema.json", "schemas/schema-agent-contract.json"),
    # -- Workflows ---------------------------------------------------------
    (".github/workflows/doc-drift-check.yml", ".github/workflows/doc-drift-enforcement.rule.yml"),
]

# Sort longest-first so e.g. `specs/x-y-z.md` is matched before `specs/x-y.md`.
RENAMES.sort(key=lambda pair: -len(pair[0]))

# Pre-flight check: ensure no "new" string contains any other pair's "old"
# as a substring (would cause double-rewrites).
_OLD_SET = {old for old, _ in RENAMES}
for old, new in RENAMES:
    for other in _OLD_SET:
        if other == old:
            continue
        if other in new:
            raise SystemExit(f"FATAL: rename mapping has overlap: '{other}' appears in '{new}'")

# ---------------------------------------------------------------------------
# Walker
# ---------------------------------------------------------------------------

EXTS = {".md", ".py", ".yaml", ".yml", ".json"}

# Directories never walked into.
EXCLUDE_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "ai_playbook.egg-info",
    "node_modules",
    "site",  # mkdocs build output
}

# Specific files never rewritten (would corrupt their content).
EXCLUDE_RELATIVE_PATHS = {
    # This script holds the mapping; rewriting would mangle the literal strings.
    "scripts/migrate_paths_v0.18.py",
    # The slice's design.md documents the migration table as `old -> new`;
    # rewriting the LHS would defeat the purpose.
    "openspec/changes/filesystem-reorg-v018/design.md",
    "openspec/changes/filesystem-reorg-v018/proposal.md",
    "openspec/changes/filesystem-reorg-v018/tasks.md",
}


def should_visit_dir(d: Path, root: Path) -> bool:
    parts = d.relative_to(root).parts
    return not any(part in EXCLUDE_DIR_NAMES for part in parts)


def should_rewrite_file(p: Path, root: Path) -> bool:
    rel = p.relative_to(root).as_posix()
    return rel not in EXCLUDE_RELATIVE_PATHS


def apply_renames(text: str) -> tuple[str, int]:
    """Apply all renames; return (new_text, total replacement count)."""
    count = 0
    for old, new in RENAMES:
        if old in text:
            n = text.count(old)
            text = text.replace(old, new)
            count += n
    return text, count


def migrate_file(path: Path) -> int:
    try:
        original = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0
    new_text, count = apply_renames(original)
    if count and new_text != original:
        path.write_text(new_text, encoding="utf-8")
    return count


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    total_files = 0
    total_subs = 0
    touched: list[tuple[str, int]] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix not in EXTS:
            continue
        if not should_visit_dir(p.parent, root):
            continue
        if not should_rewrite_file(p, root):
            continue
        n = migrate_file(p)
        if n > 0:
            touched.append((p.relative_to(root).as_posix(), n))
            total_subs += n
        total_files += 1
    print(f"Scanned {total_files} files; rewrote {len(touched)} files; {total_subs} substitutions.")
    for rel, n in touched[:80]:
        print(f"  {rel}: {n}")
    if len(touched) > 80:
        print(f"  ... ({len(touched) - 80} more)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
