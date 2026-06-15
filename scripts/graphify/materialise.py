"""Inject/strip the graphify guidance block in a project's ``AGENTS.md``.

Marker-fenced with the existing ``auto-managed`` convention (from
``scripts/auto_managed.py``) so it's visible to ``git diff`` and the drift
checker. Content is derived from ``skills/graphify/SKILL.md`` so the skill stays
the single source of truth. Mirrors ``scripts/caveman/materialise.py`` but has
no ``mode`` (graphify has no intensity levels), so the block source is a plain
``graphify/ruleset`` (no suffix).

Block shape
-----------

    <!-- BEGIN auto-managed: graphify/ruleset -->
    **Graphify: ON — query the knowledge graph before grepping**

    When to use:
    <body from SKILL.md "## When to use">

    Discipline:
    <body from SKILL.md "## Discipline">

    Boundaries:
    <body from SKILL.md "## Boundaries">

    Toggle off: `python -m scripts.graphify off`. Full skill:
    [skills/graphify/SKILL.md](skills/graphify/SKILL.md).
    <!-- END auto-managed -->
"""
from __future__ import annotations

import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts.auto_managed import (  # noqa: E402
    _extract_heading_section,  # private helper; reuse keeps SKILL.md the SSOT
    find_sections,
)
from scripts.caveman.backup import make_backup  # noqa: E402 — generic (area, source) backup
from scripts.graphify.toggle import find_playbook_root  # noqa: E402

GRAPHIFY_BLOCK_PREFIX = "graphify/ruleset"
_REQUIRED_SECTIONS = ("when to use", "discipline", "boundaries")


def _resolve_playbook_root(playbook_root: Path | None) -> Path:
    root = playbook_root or find_playbook_root()
    if root is None:
        raise FileNotFoundError(
            "ai-playbook root not found (need specs/ + scripts/ + schemas/ on parent chain)."
        )
    return root


def render_block_content(*, playbook_root: Path | None = None) -> str:
    """Compose the materialised guidance body from ``skills/graphify/SKILL.md``.

    Raises ``LookupError`` if a required SKILL.md section is missing,
    ``FileNotFoundError`` if the playbook or SKILL.md is unreachable.
    """
    root = _resolve_playbook_root(playbook_root)
    skill_path = root / "skills" / "graphify" / "SKILL.md"
    if not skill_path.is_file():
        raise FileNotFoundError(f"SKILL.md not found: {skill_path}")
    skill_md = skill_path.read_text(encoding="utf-8")

    sections = {name: _extract_heading_section(skill_md, name) for name in _REQUIRED_SECTIONS}
    missing = [k for k, v in sections.items() if v is None]
    if missing:
        raise LookupError(
            f"SKILL.md missing required section(s) for materialise: {missing}. "
            f"Expected H2 headings: 'When to use', 'Discipline', 'Boundaries'."
        )

    return (
        f"**Graphify: ON — query the knowledge graph before grepping**\n"
        f"\n"
        f"When to use:\n"
        f"{sections['when to use']}\n"
        f"\n"
        f"Discipline:\n"
        f"{sections['discipline']}\n"
        f"\n"
        f"Boundaries:\n"
        f"{sections['boundaries']}\n"
        f"\n"
        f"Toggle off: `python -m scripts.graphify off`. "
        f"Full skill: [skills/graphify/SKILL.md](skills/graphify/SKILL.md)."
    )


def _graphify_sections(text: str) -> list:
    return [s for s in find_sections(text) if s.source.startswith(GRAPHIFY_BLOCK_PREFIX)]


def is_materialised(project_root: Path) -> bool:
    """True if ``<project>/AGENTS.md`` carries a graphify guidance block."""
    agents_md = project_root / "AGENTS.md"
    if not agents_md.is_file():
        return False
    try:
        return bool(_graphify_sections(agents_md.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return False


def materialise(project_root: Path, *, playbook_root: Path | None = None) -> Path:
    """Inject or refresh the graphify guidance block in ``<project>/AGENTS.md``.

    Backs up AGENTS.md before mutation. Returns the backup path.

    Raises
    ------
    FileNotFoundError  AGENTS.md missing, SKILL.md missing, or playbook unresolved.
    LookupError        SKILL.md is missing a required section.
    ValueError         AGENTS.md has more than one graphify block.
    """
    agents_md = project_root / "AGENTS.md"
    if not agents_md.is_file():
        raise FileNotFoundError(f"AGENTS.md not found at {agents_md}")

    body = render_block_content(playbook_root=playbook_root)
    backup_path = make_backup(project_root, "agents", agents_md)

    raw = agents_md.read_text(encoding="utf-8")
    normalized = raw.replace("\r\n", "\n")
    trailing_newline = raw.endswith("\n") or raw.endswith("\r\n")

    sections = _graphify_sections(normalized)
    begin_marker = f"<!-- BEGIN auto-managed: {GRAPHIFY_BLOCK_PREFIX} -->"
    end_marker = "<!-- END auto-managed -->"

    if sections:
        if len(sections) > 1:
            raise ValueError(
                f"{agents_md} has {len(sections)} graphify blocks; expected exactly 1. "
                "Resolve manually."
            )
        sec = sections[0]
        lines = normalized.split("\n")
        lines[sec.start_line - 1] = begin_marker
        before = lines[: sec.start_line]
        after = lines[sec.end_line - 1 :]  # includes the END marker line
        new_lines = before + body.split("\n") + after
        new_text = "\n".join(new_lines)
    else:
        prefix = normalized
        if not prefix.endswith("\n"):
            prefix += "\n"
        if not prefix.endswith("\n\n"):
            prefix += "\n"
        new_text = f"{prefix}{begin_marker}\n{body}\n{end_marker}\n"

    if trailing_newline and not new_text.endswith("\n"):
        new_text += "\n"

    agents_md.write_text(new_text, encoding="utf-8")
    return backup_path


def strip(project_root: Path) -> Path | None:
    """Remove the graphify guidance block from ``<project>/AGENTS.md``.

    Backs up AGENTS.md before mutation. Returns the backup path, or ``None`` if
    there was no block to strip (idempotent).
    """
    agents_md = project_root / "AGENTS.md"
    if not agents_md.is_file():
        return None

    raw = agents_md.read_text(encoding="utf-8")
    normalized = raw.replace("\r\n", "\n")
    sections = _graphify_sections(normalized)
    if not sections:
        return None
    if len(sections) > 1:
        raise ValueError(
            f"{agents_md} has {len(sections)} graphify blocks; expected exactly 1. "
            "Resolve manually."
        )

    backup_path = make_backup(project_root, "agents", agents_md)

    sec = sections[0]
    lines = normalized.split("\n")
    start = sec.start_line - 1
    end = sec.end_line
    if start > 0 and lines[start - 1].strip() == "":
        start -= 1

    new_lines = lines[:start] + lines[end:]
    new_text = "\n".join(new_lines)

    trailing_newline = raw.endswith("\n") or raw.endswith("\r\n")
    if trailing_newline and not new_text.endswith("\n"):
        new_text += "\n"

    agents_md.write_text(new_text, encoding="utf-8")
    return backup_path


__all__ = [
    "GRAPHIFY_BLOCK_PREFIX",
    "render_block_content",
    "is_materialised",
    "materialise",
    "strip",
]
