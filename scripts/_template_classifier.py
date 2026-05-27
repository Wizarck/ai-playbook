"""Classify a managed file's content as canonical / drifted / custom.

Given a file's current text plus a manifest of expected SHAs for the
marker blocks it should contain, this module produces a
``FileClassification`` describing each segment of the file as one of:

* ``"canonical"`` — inside an ai-playbook marker block whose content SHA
  matches the expected SHA from the template manifest. The consumer has
  not touched this block; ``apply_config`` may overwrite it without loss.
* ``"drifted"`` — inside an ai-playbook marker block, but the content SHA
  does NOT match what the manifest expects. Someone edited canonical
  content locally. The UI surfaces these for human review; ``apply_config``
  MUST NOT silently overwrite them without explicit consent.
* ``"custom"`` — text OUTSIDE any marker block. Consumer-owned, preserved
  verbatim across re-renders.

The classifier is purely stateless: it consumes already-parsed blocks
(``_marker_blocks.parse_blocks``) plus an ``expected_shas`` mapping; it
does not read or write the filesystem.

SHA convention
--------------
``compute_sha(text)`` returns the first 12 hex chars of the SHA-256 of
the UTF-8 bytes of ``text``. Short enough for marker visibility,
collision-resistant enough for an O(100) sections-per-file domain.
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field

from scripts._marker_blocks import CommentStyle, parse_blocks

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


SHA_PREFIX_LEN = 12


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

ORIGIN_CANONICAL = "canonical"
ORIGIN_DRIFTED = "drifted"
ORIGIN_CUSTOM = "custom"


@dataclass(frozen=True)
class ClassifiedSection:
    """One segment of a parsed file, classified by origin.

    For marker blocks: ``id`` is the block id, ``expected_sha`` is what the
    manifest predicted, ``actual_sha`` is the SHA of the current content,
    ``origin`` is ``"canonical"`` or ``"drifted"`` depending on match.

    For custom segments: ``id`` is ``None``, both SHAs are ``None``,
    ``origin`` is ``"custom"``.
    """

    id: str | None
    origin: str  # ORIGIN_*
    content: str
    expected_sha: str | None = None
    actual_sha: str | None = None


@dataclass
class FileClassification:
    rel_path: str
    sections: list[ClassifiedSection] = field(default_factory=list)
    """Sections in document order — both blocks and surrounding custom text."""
    style: CommentStyle = CommentStyle.HTML

    @property
    def custom_count(self) -> int:
        return sum(1 for s in self.sections if s.origin == ORIGIN_CUSTOM and s.content.strip())

    @property
    def canonical_count(self) -> int:
        return sum(1 for s in self.sections if s.origin == ORIGIN_CANONICAL)

    @property
    def drifted_count(self) -> int:
        return sum(1 for s in self.sections if s.origin == ORIGIN_DRIFTED)

    @property
    def orphan_block_ids(self) -> list[str]:
        """Block ids present in the file but unknown to the current manifest.

        Populated by ``classify`` when ``expected_shas`` lacks an entry for a
        block id that appears in the file. Typically means the consumer is
        running a newer playbook than when the file was last rendered.
        """
        return [
            s.id for s in self.sections
            if s.origin == ORIGIN_DRIFTED
            and s.id is not None
            and s.expected_sha is None
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def compute_sha(text: str) -> str:
    """Return the first ``SHA_PREFIX_LEN`` hex chars of SHA-256 of UTF-8 bytes."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:SHA_PREFIX_LEN]


# ---------------------------------------------------------------------------
# Classify
# ---------------------------------------------------------------------------


def classify(
    text: str,
    style: CommentStyle,
    expected_shas: dict[str, str],
    *,
    rel_path: str = "",
) -> FileClassification:
    """Classify every segment of ``text`` into canonical / drifted / custom.

    Parameters
    ----------
    text
        Full file content as read from disk.
    style
        Comment style used by the file (see ``_marker_blocks.CommentStyle``).
    expected_shas
        ``{block_id: expected_sha}`` from the template manifest. Missing
        block_ids classify as drifted (orphan).
    rel_path
        Optional file path for the resulting ``FileClassification.rel_path``.
    """
    parsed = parse_blocks(text, style)
    result = FileClassification(rel_path=rel_path, style=style)

    # custom_segments has len == len(order) + 1 — segments interleave with blocks.
    custom_segments = list(parsed.custom_segments)
    # Pad with empty trailing segment if the file ended right after a block.
    while len(custom_segments) < len(parsed.order) + 1:
        custom_segments.append("")

    for idx, segment in enumerate(custom_segments):
        if segment:
            result.sections.append(ClassifiedSection(
                id=None, origin=ORIGIN_CUSTOM, content=segment,
            ))
        if idx < len(parsed.order):
            block_id = parsed.order[idx]
            block = parsed.blocks[block_id]
            actual_sha = compute_sha(block.content)
            expected_sha = expected_shas.get(block_id)
            origin = (
                ORIGIN_CANONICAL
                if expected_sha is not None and expected_sha == actual_sha
                else ORIGIN_DRIFTED
            )
            result.sections.append(ClassifiedSection(
                id=block_id,
                origin=origin,
                content=block.content,
                expected_sha=expected_sha,
                actual_sha=actual_sha,
            ))

    return result


# ---------------------------------------------------------------------------
# Build manifest from canonical-source blocks
# ---------------------------------------------------------------------------


def build_manifest(canonical_blocks: dict[str, str]) -> dict[str, str]:
    """Given a mapping of ``{block_id: canonical_content}``, return the
    manifest mapping ``{block_id: sha}`` suitable to feed into ``classify``.

    Used at template-render time: the renderer produces the canonical
    block contents, calls this to compute SHAs, and persists the result
    in ``.ai-playbook-state/file-manifest.json`` so the next ``classify``
    invocation can detect drift.
    """
    return {bid: compute_sha(content) for bid, content in canonical_blocks.items()}


__all__ = [
    "ClassifiedSection",
    "FileClassification",
    "ORIGIN_CANONICAL",
    "ORIGIN_CUSTOM",
    "ORIGIN_DRIFTED",
    "SHA_PREFIX_LEN",
    "build_manifest",
    "classify",
    "compute_sha",
]
