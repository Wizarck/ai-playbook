#!/usr/bin/env bash
# Build the ai-playbook static docs site (mkdocs-material) and the Pagefind
# static search index.
#
# Usage:
#     bash scripts/build_docs.sh            # full build + index
#     bash scripts/build_docs.sh --no-index # skip Pagefind (Node not installed)
#
# Exit codes:
#     0 — mkdocs build OK; Pagefind OK (or intentionally skipped via --no-index).
#     1 — mkdocs build failed.
#     2 — Pagefind requested but `npx` not found / pagefind failed.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

WANT_INDEX=1
if [[ "${1:-}" == "--no-index" ]]; then
    WANT_INDEX=0
fi

echo ">> mkdocs build --strict"
python -m mkdocs build --strict

if [[ "$WANT_INDEX" -eq 1 ]]; then
    if ! command -v npx >/dev/null 2>&1; then
        echo "!! npx not found on PATH; install Node 18+ or rerun with --no-index" >&2
        exit 2
    fi
    echo ">> npx pagefind --site site"
    npx --yes pagefind --site site
fi

echo ">> done: site/ ready to deploy"
