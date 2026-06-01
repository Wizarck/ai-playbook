"""Structural drift detector for ``.md`` dispatcher files.

A *dispatcher* (AGENTS.md, CLAUDE.md, GEMINI.md, the Cursor rule files) is meant
to be **pointer-shaped**: frontmatter, headers, ai-playbook canonical marker
blocks, and short pointers to leaf docs — per universal principle #2 ("any
section >10 lines → pointer to external detail"). When a dispatcher accumulates
paragraphs of free prose OUTSIDE its sanctioned slots, that is *curate drift*:
content that should be consolidated into the canonical ``AGENTS.md`` or
dispatched to a leaf doc with a pointer left behind.

This module is the deterministic engine that both surfaces feed:

* the config-UI aggregated ``.md`` drift view (read-only: shows each loose-prose
  chunk with provenance + a suggested destination), and
* ``scripts/curate.py`` (the LLM-assisted one-shot that actually moves it).

Idempotency hinges here (D3): drift is defined STRUCTURALLY ("is there loose
prose in a dispatcher slot?"), never as byte-equality to an LLM output. Once the
prose is moved to a leaf doc (which is exempt), the dispatcher has no loose prose
→ a re-run is a no-op → curate converges.

Pure / stdlib-only: reads no filesystem, mutates nothing.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

from scripts._marker_blocks import CommentStyle, parse_blocks

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


# Universal principle #2: a section over this many substantive lines should be a
# pointer, not inline prose. A dispatcher segment that exceeds it is drift.
LOOSE_PROSE_LINE_THRESHOLD = 10

_DISPATCHER_BASENAMES = frozenset({
    "AGENTS.md", "CLAUDE.md", "GEMINI.md", "GEMINI.MD",
    ".cursorrules",
})

# The canonical (model-agnostic) dispatcher: loose prose elsewhere is suggested
# to be absorbed HERE; loose prose HERE is suggested to dispatch to a leaf doc.
CANONICAL_DISPATCHER = "AGENTS.md"

_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n?", re.DOTALL)
_HEADER_RE = re.compile(r"^\s{0,3}#{1,6}\s")
_MD_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+")
_TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
_POINTER_HINT_RE = re.compile(r"^\s*(see|see also|→|->|ref:|pointer:)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

DEST_ABSORB_AGENTS = "absorb_into_agents_md"
DEST_DISPATCH_LEAF = "dispatch_to_leaf_doc"
DEST_OTHER_DISPATCH = "move_to_other_dispatch"


@dataclass(frozen=True)
class LooseProse:
    """One chunk of substantive prose found OUTSIDE the sanctioned slots of a
    dispatcher file — a curate candidate."""

    rel_path: str
    heading: str | None        # nearest preceding markdown heading, for context
    line_count: int            # substantive (non-pointer, non-header) line count
    preview: str
    suggestion: str            # DEST_* — where this chunk should go


@dataclass
class DispatcherDrift:
    rel_path: str
    chunks: list[LooseProse] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.chunks)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def is_dispatcher_file(rel_path: str) -> bool:
    """True for the thin-router dispatcher files (per-model + canonical)."""
    name = rel_path.replace("\\", "/").rsplit("/", 1)[-1]
    if name in _DISPATCHER_BASENAMES:
        return True
    # Cursor rule files: .cursor/rules/*.mdc
    norm = rel_path.replace("\\", "/")
    return norm.startswith(".cursor/rules/") and norm.endswith(".mdc")


def is_leaf_doc(rel_path: str) -> bool:
    """True for leaf documentation files, which ARE allowed to hold prose and are
    therefore EXEMPT from curate drift (moving prose here is the fix, not the
    problem). Any ``.md`` under a ``docs/`` segment qualifies."""
    norm = rel_path.replace("\\", "/")
    if not norm.endswith(".md"):
        return False
    return norm == "docs" or norm.startswith("docs/") or "/docs/" in norm


def _suggestion_for(rel_path: str) -> str:
    name = rel_path.replace("\\", "/").rsplit("/", 1)[-1]
    if name == CANONICAL_DISPATCHER:
        # AGENTS.md is canonical — overflow prose belongs in a leaf doc.
        return DEST_DISPATCH_LEAF
    # Per-model dispatchers should be thin pointers to AGENTS.md.
    return DEST_ABSORB_AGENTS


def _is_pointer_line(line: str) -> bool:
    """A line that is structurally a pointer (link / reference), not prose."""
    stripped = line.strip()
    if not stripped:
        return True  # blank — not prose
    if _HEADER_RE.match(line):
        return True  # heading — structure, not prose
    if _TABLE_RE.match(line):
        return True  # table row (pointer tables are common in dispatchers)
    if _POINTER_HINT_RE.match(stripped):
        return True
    link = _MD_LINK_RE.search(stripped)
    if link:
        # Pointer iff the non-link residue is short (a label, not a paragraph).
        residue = _MD_LINK_RE.sub("", stripped)
        residue = _BULLET_RE.sub("", residue).strip(" :|-—•")
        if len(residue) <= 40:
            return True
    return False


def _heading_before(lines: list[str], idx: int) -> str | None:
    for j in range(idx, -1, -1):
        if _HEADER_RE.match(lines[j]):
            return lines[j].strip().lstrip("#").strip()
    return None


def loose_prose_sections(
    text: str,
    *,
    rel_path: str = "",
    style: CommentStyle = CommentStyle.HTML,
) -> list[LooseProse]:
    """Return the substantive prose chunks living outside marker blocks.

    Marker-block content is playbook-canonical (sanctioned) and ignored.
    Frontmatter is stripped. Within each custom segment, contiguous runs of
    substantive (non-pointer, non-header) lines are accumulated; a run longer
    than ``LOOSE_PROSE_LINE_THRESHOLD`` is reported as a curate candidate.
    """
    try:
        parsed = parse_blocks(text, style)
    except ValueError:
        # Malformed markers — treat the whole file as one segment for safety.
        segments = [text]
    else:
        segments = list(parsed.custom_segments)

    suggestion = _suggestion_for(rel_path)
    out: list[LooseProse] = []

    for segment in segments:
        body = _FRONTMATTER_RE.sub("", segment, count=1)
        lines = body.split("\n")
        run: list[str] = []
        run_start = 0

        def _flush(start_idx: int, run_lines: list[str], all_lines: list[str]) -> None:
            substantive = [ln for ln in run_lines if ln.strip()]
            if len(substantive) > LOOSE_PROSE_LINE_THRESHOLD:
                out.append(LooseProse(
                    rel_path=rel_path,
                    heading=_heading_before(all_lines, start_idx),
                    line_count=len(substantive),
                    preview="\n".join(substantive[:3])[:200],
                    suggestion=suggestion,
                ))

        for i, line in enumerate(lines):
            if _is_pointer_line(line):
                if run:
                    _flush(run_start, run, lines)
                    run = []
                continue
            if not run:
                run_start = i
            run.append(line)
        if run:
            _flush(run_start, run, lines)

    return out


def has_curate_drift(
    text: str,
    *,
    rel_path: str = "",
    style: CommentStyle = CommentStyle.HTML,
) -> bool:
    """True iff the dispatcher carries loose prose beyond the pointer threshold."""
    return bool(loose_prose_sections(text, rel_path=rel_path, style=style))


def collect_drift(files: dict[str, str]) -> list[DispatcherDrift]:
    """Aggregate drift across a set of ``{rel_path: content}`` dispatcher files.

    Leaf docs are skipped (exempt). Non-dispatcher, non-leaf files are also
    skipped. The result carries per-file provenance for the UI drift view.
    """
    results: list[DispatcherDrift] = []
    for rel_path, content in files.items():
        if is_leaf_doc(rel_path) or not is_dispatcher_file(rel_path):
            continue
        chunks = loose_prose_sections(content, rel_path=rel_path)
        if chunks:
            results.append(DispatcherDrift(rel_path=rel_path, chunks=chunks))
    return results


__all__ = [
    "CANONICAL_DISPATCHER",
    "DEST_ABSORB_AGENTS",
    "DEST_DISPATCH_LEAF",
    "DEST_OTHER_DISPATCH",
    "DispatcherDrift",
    "LOOSE_PROSE_LINE_THRESHOLD",
    "LooseProse",
    "collect_drift",
    "has_curate_drift",
    "is_dispatcher_file",
    "is_leaf_doc",
    "loose_prose_sections",
]
