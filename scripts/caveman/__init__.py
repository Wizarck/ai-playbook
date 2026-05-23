"""Caveman feature toggle package.

Public modules:
    toggle   — single source of truth for state read/write
    backup   — backup/restore for files mutated by toggle transitions
    cli      — CLI entry point (python -m scripts.caveman ...)

See ~/.claude/plans/snappy-orbiting-peach.md and (once written)
docs/operations/caveman-architecture.md for the full architecture.
"""
