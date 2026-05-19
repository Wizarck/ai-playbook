#!/usr/bin/env bash
# install-playbook-hooks.sh — one-time setup for ai-playbook consumer git hooks.
#
# Wires up the consumer's `scripts/git-hooks/` directory as the canonical
# `core.hooksPath`, then runs the first skills materialisation and zombie
# cleanup pass so the consumer tree starts in the canonical state.
#
# This template lands at `<consumer>/scripts/install-playbook-hooks.sh` via
# the playbook bootstrap. Run ONCE per clone:
#
#     bash scripts/install-playbook-hooks.sh
#
# After this, `post-checkout` and `post-merge` under `scripts/git-hooks/`
# fire automatically — including the skills mirror sync (single-source
# materialiser at `.ai-playbook/scripts/materialise_skills.py`) AND the
# playbook zombie cleanup (`.ai-playbook/scripts/cleanup_zombies.py`).
#
# Idempotent: safe to re-run after pulling new templates / bumping the
# playbook submodule.
#
# Replaces the acme-corp-local `install-skills-hooks.sh` (single-purpose, only
# wired skills sync). v0.17.0 promotes this to the upstream template so
# every consumer starts with both flows installed.

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# 1) Point git at the repo-tracked hooks dir.
git config core.hooksPath scripts/git-hooks
echo "✓ git core.hooksPath = scripts/git-hooks"

# 2) Make the hooks executable (POSIX; Windows ignores).
chmod +x scripts/git-hooks/* 2>/dev/null || true

# 3) First-run skills sync.
if [ -f .ai-playbook/scripts/materialise_skills.py ]; then
    echo "✓ Running initial skills materialiser..."
    python .ai-playbook/scripts/materialise_skills.py --quiet || {
        echo "warn: skills materialiser failed; you can re-run manually:" >&2
        echo "    python .ai-playbook/scripts/materialise_skills.py" >&2
    }
else
    echo "warn: .ai-playbook/scripts/materialise_skills.py not found." >&2
    echo "      Run 'git submodule update --init .ai-playbook' first." >&2
fi

# 4) First-run playbook zombie cleanup (Tier 1+2 auto-apply; always exit 0).
if [ -f .ai-playbook/scripts/cleanup_zombies.py ]; then
    echo "✓ Running initial playbook zombie cleanup..."
    python .ai-playbook/scripts/cleanup_zombies.py --apply --quiet || true
fi

echo ""
echo "All set. The post-checkout + post-merge hooks will now keep skills"
echo "mirrors and the consumer tree clean automatically."
