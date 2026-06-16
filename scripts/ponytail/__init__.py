"""Ponytail feature toggle package.

Public modules:
    toggle      — single source of truth for state read/write
    materialise — inject/strip the ponytail ladder block in AGENTS.md
    cli         — CLI entry point (python -m scripts.ponytail ...)

Ponytail is the code-minimalism twin of caveman: caveman compresses how the
agent *talks* (telegraphic prose, fewer output tokens); ponytail disciplines
what the agent *builds* (YAGNI → stdlib → native → installed dep → one line →
minimum). The two are orthogonal and compose. A Python port of
JuliusBrussee/caveman's sibling project DietrichGebert/ponytail (MIT), scoped to
the playbook's existing infrastructure (skills, hooks, materialise) and reusing
the caveman feature shape (toggle + materialise + CLI + delegation from
scripts/apply_config.py) so ponytail is a first-class, toggleable config-UI
feature.

See docs/concepts/ponytail-mode.md and docs/operations/ponytail-architecture.md.
"""
