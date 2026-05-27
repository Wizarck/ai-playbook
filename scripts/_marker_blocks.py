"""Marker-block parser/writer for ai-playbook canonical sections.

Every file managed by ``apply_config`` (AGENTS.md, .gitignore,
.pre-commit-config.yaml, etc.) carries one or more **marker blocks** that
delimit playbook-canonical content. Anything outside those blocks is
treated as consumer-custom content and is preserved across re-renders.

Marker grammar (per comment-style)
----------------------------------

* HTML / Markdown (``style="html"``)::

      <!-- ai-playbook:begin id=§4 sha=ab12 -->
      ...canonical content...
      <!-- ai-playbook:end §4 -->

* Hash-comment (shell, gitignore, yaml; ``style="hash"``)::

      # >>> ai-playbook:begin id=hooks sha=ab12 >>>
      ...canonical content...
      # <<< ai-playbook:end hooks <<<

* JSON5 / JS (``style="slash"``)::

      // ai-playbook:begin id=hooks sha=ab12
      ...canonical content...
      // ai-playbook:end hooks

Notes
-----
* ``sha`` is optional. When present, ``parse_blocks`` records it so a
  caller can detect tampering (canonical content edited locally). The
  helpers do not enforce it — that policy lives one layer up.
* Block ``id`` must be unique within a file. ``parse_blocks`` raises on
  duplicate ids to surface authoring bugs early.
* Nested blocks are NOT supported by design — keeps the parser simple
  and matches the way templates are written.
* ``write_blocks`` performs a stable replacement: existing block
  content is overwritten in place, preserving the surrounding consumer
  text. Blocks present in the desired set but missing from the file
  are APPENDED at the end with a blank line separator.

Stdlib-only.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from enum import Enum

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


class CommentStyle(str, Enum):
    HTML = "html"      # <!-- ... -->
    HASH = "hash"      # # ...
    SLASH = "slash"    # // ...


@dataclass(frozen=True)
class MarkerBlock:
    """One canonical block extracted from a file.

    ``content`` is the text BETWEEN the begin/end marker lines, without
    a trailing newline (so callers can append uniformly).
    """

    id: str
    content: str
    sha: str | None = None
    style: CommentStyle = CommentStyle.HTML


@dataclass
class ParsedFile:
    """Result of ``parse_blocks`` — blocks + non-block (custom) text."""

    blocks: dict[str, MarkerBlock] = field(default_factory=dict)
    custom_segments: list[str] = field(default_factory=list)
    """Text segments OUTSIDE any block, in document order, split where blocks
    were removed. For a file with custom-text → block A → custom-text →
    block B → trailing-text, ``custom_segments`` will be
    ``[before_a, between_ab, trailing]``."""
    order: list[str] = field(default_factory=list)
    """Ordered list of block IDs as they appear in the file (for stable
    re-rendering)."""


# ---------------------------------------------------------------------------
# Regex patterns per comment style
# ---------------------------------------------------------------------------

_PATTERNS: dict[CommentStyle, dict[str, re.Pattern[str]]] = {
    CommentStyle.HTML: {
        "begin": re.compile(
            r"<!--\s*ai-playbook:begin\s+id=(?P<id>\S+?)"
            r"(?:\s+sha=(?P<sha>[0-9a-fA-F]+))?\s*-->"
        ),
        "end": re.compile(r"<!--\s*ai-playbook:end\s+(?P<id>\S+?)\s*-->"),
    },
    CommentStyle.HASH: {
        "begin": re.compile(
            r"#\s*>>>\s*ai-playbook:begin\s+id=(?P<id>\S+?)"
            r"(?:\s+sha=(?P<sha>[0-9a-fA-F]+))?\s*>>>"
        ),
        "end": re.compile(r"#\s*<<<\s*ai-playbook:end\s+(?P<id>\S+?)\s*<<<"),
    },
    CommentStyle.SLASH: {
        "begin": re.compile(
            r"//\s*ai-playbook:begin\s+id=(?P<id>\S+?)"
            r"(?:\s+sha=(?P<sha>[0-9a-fA-F]+))?[ \t]*$",
            re.MULTILINE,
        ),
        "end": re.compile(
            r"//\s*ai-playbook:end\s+(?P<id>\S+?)[ \t]*$",
            re.MULTILINE,
        ),
    },
}


def _render_begin(block: MarkerBlock) -> str:
    sha_part = f" sha={block.sha}" if block.sha else ""
    if block.style is CommentStyle.HTML:
        return f"<!-- ai-playbook:begin id={block.id}{sha_part} -->"
    if block.style is CommentStyle.HASH:
        return f"# >>> ai-playbook:begin id={block.id}{sha_part} >>>"
    return f"// ai-playbook:begin id={block.id}{sha_part}"


def _render_end(block: MarkerBlock) -> str:
    if block.style is CommentStyle.HTML:
        return f"<!-- ai-playbook:end {block.id} -->"
    if block.style is CommentStyle.HASH:
        return f"# <<< ai-playbook:end {block.id} <<<"
    return f"// ai-playbook:end {block.id}"


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def parse_blocks(text: str, style: CommentStyle) -> ParsedFile:
    """Extract every ai-playbook marker block from ``text``.

    Raises
    ------
    ValueError
        If a begin marker has no matching end (or vice versa), or if a
        block id appears twice in the same file.
    """
    pat = _PATTERNS[style]
    parsed = ParsedFile()

    pos = 0
    while pos < len(text):
        begin_match = pat["begin"].search(text, pos)
        if begin_match is None:
            parsed.custom_segments.append(text[pos:])
            break

        # Pre-block text becomes a custom segment.
        parsed.custom_segments.append(text[pos:begin_match.start()])

        block_id = begin_match.group("id")
        if block_id in parsed.blocks:
            raise ValueError(f"duplicate marker block id: {block_id!r}")

        end_match = pat["end"].search(text, begin_match.end())
        if end_match is None:
            raise ValueError(
                f"unmatched marker begin (id={block_id!r}): no closing end marker"
            )
        # The "id" on the end marker must match the begin id.
        if end_match.group("id") != block_id:
            raise ValueError(
                f"marker mismatch: begin id={block_id!r}, "
                f"end id={end_match.group('id')!r}"
            )

        # Inner content = lines BETWEEN the begin marker line and the
        # end marker line, stripped of the leading/trailing newlines that
        # surround the markers themselves.
        inner = text[begin_match.end():end_match.start()]
        inner = inner.lstrip("\n").rstrip("\n")

        parsed.blocks[block_id] = MarkerBlock(
            id=block_id,
            content=inner,
            sha=begin_match.group("sha"),
            style=style,
        )
        parsed.order.append(block_id)
        pos = end_match.end()
    else:
        # Loop exited via the `while pos < len(text)` condition (no break);
        # nothing left to append.
        return parsed
    return parsed


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def write_blocks(
    current_text: str,
    desired: dict[str, MarkerBlock],
    *,
    style: CommentStyle,
    append_missing: bool = True,
) -> str:
    """Return ``current_text`` with each block in ``desired`` updated.

    Behaviour
    ---------
    * Blocks present in both the file and ``desired`` are REPLACED in
      place. Surrounding custom text is preserved.
    * Blocks in ``desired`` but not in the file are APPENDED at the end
      when ``append_missing=True`` (default). Set False to skip them
      silently.
    * Blocks in the file but not in ``desired`` are LEFT UNCHANGED
      (they're still canonical; the caller just didn't supply a new
      version).
    * Block ``style`` from ``desired`` overrides any existing style in
      the file — useful when a file gains markers for the first time.
    """
    parsed = parse_blocks(current_text, style)

    # Re-render existing blocks (preserve order + custom segments).
    out_parts: list[str] = []
    for idx, segment in enumerate(parsed.custom_segments):
        out_parts.append(segment)
        if idx < len(parsed.order):
            block_id = parsed.order[idx]
            block = desired.get(block_id, parsed.blocks[block_id])
            out_parts.append(_render_block(block))

    rendered = "".join(out_parts)

    if append_missing:
        existing_ids = set(parsed.order)
        missing = [bid for bid in desired if bid not in existing_ids]
        for bid in missing:
            # Ensure exactly one blank line separator before appending the
            # new block, and a trailing newline after.
            if rendered:
                rendered = rendered.rstrip("\n") + "\n\n"
            rendered += _render_block(desired[bid]) + "\n"
    return rendered


def _render_block(block: MarkerBlock) -> str:
    """Render one block including its begin/end marker lines.

    The output does NOT end with a trailing newline — the caller is
    responsible for splicing the block into the surrounding text with
    whatever separators the source layout requires. This keeps in-place
    replacement byte-exact when nothing actually changed (round-trip
    parse → write idempotency).
    """
    inner = block.content.rstrip("\n")
    body = f"{inner}\n" if inner else ""
    return f"{_render_begin(block)}\n{body}{_render_end(block)}"


# ---------------------------------------------------------------------------
# Convenience: detect style from filename
# ---------------------------------------------------------------------------


def style_for_filename(name: str) -> CommentStyle:
    """Best-effort guess of comment style from a filename.

    Falls back to ``CommentStyle.HASH`` for unknown extensions (the most
    common in this project: yaml, gitignore, shell).
    """
    lower = name.lower()
    if lower.endswith((".md", ".mdc", ".html", ".htm")):
        return CommentStyle.HTML
    if lower.endswith((".json", ".json5", ".js", ".ts", ".mjs")):
        return CommentStyle.SLASH
    return CommentStyle.HASH


__all__ = [
    "CommentStyle",
    "MarkerBlock",
    "ParsedFile",
    "parse_blocks",
    "style_for_filename",
    "write_blocks",
]
