"""Graphify feature toggle package.

Public modules:
    toggle      — single source of truth for state read/write
    materialise — inject/strip the graphify guidance block in AGENTS.md
    cli         — CLI entry point (python -m scripts.graphify ...)

Mirrors the caveman feature shape (toggle + materialise + CLI + delegation
from scripts/apply_config.py) so graphify is a first-class, toggleable feature
in the config UI. Unlike caveman, graphify wraps an EXTERNAL tool (PyPI
`graphifyy`): the CLI here manages the in-repo side effects (AGENTS.md guidance
block, .gitignore hygiene) and surfaces — but cannot run — the per-machine
`uv tool install graphifyy` + per-clone `graphify hook install` steps.

See docs/concepts/graphify.md and docs/runbooks/graphify-setup.md.
"""
