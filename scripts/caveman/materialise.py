"""Inject/strip the caveman ruleset block in a project's ``AGENTS.md``.

The block is marker-fenced using the existing ``auto-managed`` convention
from ``scripts/auto_managed.py`` so it's visible to ``git diff`` and to the
auto-managed drift checker. Content is derived from
``skills/caveman/SKILL.md`` so the skill stays the single source of truth.

Block shape
-----------

    <!-- BEGIN auto-managed: caveman/ruleset:<mode> -->
    **Caveman mode: ON · intensity <mode>**

    Core rules:
    <bullets from SKILL.md "## Core rules">

    Mode (<mode>):
    <body from SKILL.md "## <mode> mode ruleset">

    Auto-clarity exceptions:
    <body from SKILL.md "## Auto-clarity exceptions">

    Boundaries:
    <body from SKILL.md "## Boundaries">

    Toggle off: `python -m scripts.caveman off`. Full rule:
    [skills/caveman/SKILL.md](skills/caveman/SKILL.md).
    <!-- END auto-managed -->

Public API
----------
    CAVEMAN_BLOCK_PREFIX     — const, ``caveman/ruleset:``
    render_block_content()   — compose body from SKILL.md sections
    materialise(...)         — inject or refresh the block; backs up first
    strip(...)               — remove the block; backs up first; idempotent
    is_materialised(...)     — check if AGENTS.md currently carries a block
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
from scripts.caveman.backup import make_backup  # noqa: E402
from scripts.caveman.toggle import find_playbook_root  # noqa: E402

CAVEMAN_BLOCK_PREFIX = "caveman/ruleset:"
VALID_MODES = ("lite", "full", "ultra")


def _resolve_playbook_root(playbook_root: Path | None) -> Path:
    root = playbook_root or find_playbook_root()
    if root is None:
        raise FileNotFoundError(
            "ai-playbook root not found (need specs/ + scripts/ + schemas/ on parent chain)."
        )
    return root


def render_block_content(mode: str, *, playbook_root: Path | None = None) -> str:
    """Compose the materialised ruleset body from ``skills/caveman/SKILL.md``.

    Raises ``LookupError`` if any required SKILL.md section is missing,
    ``ValueError`` on an invalid mode, ``FileNotFoundError`` if the playbook
    or SKILL.md is unreachable.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode '{mode}'. Valid: {', '.join(VALID_MODES)}")

    root = _resolve_playbook_root(playbook_root)
    skill_path = root / "skills" / "caveman" / "SKILL.md"
    if not skill_path.is_file():
        raise FileNotFoundError(f"SKILL.md not found: {skill_path}")
    skill_md = skill_path.read_text(encoding="utf-8")

    sections = {
        "core": _extract_heading_section(skill_md, "core rules"),
        "mode": _extract_heading_section(skill_md, f"{mode} mode ruleset"),
        "clarity": _extract_heading_section(skill_md, "auto-clarity exceptions"),
        "boundaries": _extract_heading_section(skill_md, "boundaries"),
    }
    missing = [k for k, v in sections.items() if v is None]
    if missing:
        raise LookupError(
            f"SKILL.md missing required section(s) for materialise: {missing}. "
            f"Expected H2 headings: 'Core rules', '{mode} mode ruleset', "
            f"'Auto-clarity exceptions', 'Boundaries'."
        )

    return (
        f"**Caveman mode: ON · intensity {mode}**\n"
        f"\n"
        f"Core rules:\n"
        f"{sections['core']}\n"
        f"\n"
        f"Mode ({mode}):\n"
        f"{sections['mode']}\n"
        f"\n"
        f"Auto-clarity exceptions:\n"
        f"{sections['clarity']}\n"
        f"\n"
        f"Boundaries:\n"
        f"{sections['boundaries']}\n"
        f"\n"
        f"Toggle off: `python -m scripts.caveman off`. "
        f"Full rule: [skills/caveman/SKILL.md](skills/caveman/SKILL.md)."
    )


def _caveman_sections(text: str) -> list:
    return [s for s in find_sections(text) if s.source.startswith(CAVEMAN_BLOCK_PREFIX)]


def is_materialised(project_root: Path) -> bool:
    """True if ``<project>/AGENTS.md`` carries a caveman ruleset block."""
    agents_md = project_root / "AGENTS.md"
    if not agents_md.is_file():
        return False
    try:
        return bool(_caveman_sections(agents_md.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return False


def materialise(
    project_root: Path,
    mode: str,
    *,
    playbook_root: Path | None = None,
) -> Path:
    """Inject or refresh the caveman ruleset block in ``<project>/AGENTS.md``.

    Backs up AGENTS.md to ``<project>/.ai-playbook/backups/agents/`` before
    mutation. If a block already exists, replaces its content (mode marker
    updated to reflect the new mode). If none exists, appends one after a
    blank-line separator.

    Returns the path of the backup just written.

    Raises
    ------
    FileNotFoundError
        AGENTS.md missing, SKILL.md missing, or playbook root unresolved.
    ValueError
        Mode not in VALID_MODES.
    LookupError
        SKILL.md is missing a required section.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode '{mode}'. Valid: {', '.join(VALID_MODES)}")

    agents_md = project_root / "AGENTS.md"
    if not agents_md.is_file():
        raise FileNotFoundError(f"AGENTS.md not found at {agents_md}")

    body = render_block_content(mode, playbook_root=playbook_root)
    backup_path = make_backup(project_root, "agents", agents_md)

    raw = agents_md.read_text(encoding="utf-8")
    normalized = raw.replace("\r\n", "\n")
    trailing_newline = raw.endswith("\n") or raw.endswith("\r\n")

    sections = _caveman_sections(normalized)
    begin_marker = f"<!-- BEGIN auto-managed: {CAVEMAN_BLOCK_PREFIX}{mode} -->"
    end_marker = "<!-- END auto-managed -->"

    if sections:
        # Replace existing block (only the first; refuse if more than one).
        if len(sections) > 1:
            raise ValueError(
                f"{agents_md} has {len(sections)} caveman blocks; "
                "expected exactly 1. Resolve manually."
            )
        sec = sections[0]
        lines = normalized.split("\n")
        # Marker line at start_line is 1-indexed; replace it with the
        # (possibly new) mode marker so refreshing into a different mode
        # is a single in-place edit.
        lines[sec.start_line - 1] = begin_marker
        before = lines[: sec.start_line]
        after = lines[sec.end_line - 1 :]  # includes the END marker line
        body_lines = body.split("\n")
        new_lines = before + body_lines + after
        new_text = "\n".join(new_lines)
    else:
        # Append at end, separated by a single blank line.
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
    """Remove the caveman ruleset block from ``<project>/AGENTS.md``.

    Backs up AGENTS.md before mutation. Returns the backup path, or
    ``None`` if there was no block to strip (idempotent).
    """
    agents_md = project_root / "AGENTS.md"
    if not agents_md.is_file():
        return None

    raw = agents_md.read_text(encoding="utf-8")
    normalized = raw.replace("\r\n", "\n")
    sections = _caveman_sections(normalized)
    if not sections:
        return None
    if len(sections) > 1:
        raise ValueError(
            f"{agents_md} has {len(sections)} caveman blocks; "
            "expected exactly 1. Resolve manually."
        )

    backup_path = make_backup(project_root, "agents", agents_md)

    sec = sections[0]
    lines = normalized.split("\n")
    start = sec.start_line - 1  # 0-indexed: BEGIN marker line
    end = sec.end_line  # 1-indexed end-line + 1 in 0-indexed slice → exclusive end

    # Eat a single blank line immediately before the BEGIN marker (we add
    # one on injection — strip should reverse that cleanly).
    if start > 0 and lines[start - 1].strip() == "":
        start -= 1
    # Do NOT eat trailing blank lines after the END marker — those may
    # belong to whatever followed in the original document.

    new_lines = lines[:start] + lines[end:]
    new_text = "\n".join(new_lines)

    trailing_newline = raw.endswith("\n") or raw.endswith("\r\n")
    if trailing_newline and not new_text.endswith("\n"):
        new_text += "\n"

    agents_md.write_text(new_text, encoding="utf-8")
    return backup_path


__all__ = [
    "CAVEMAN_BLOCK_PREFIX",
    "VALID_MODES",
    "render_block_content",
    "is_materialised",
    "materialise",
    "strip",
]
