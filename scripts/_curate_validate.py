"""Structural validation of an LLM ``curate-plan/v1`` move-plan.

The curate LLM proposes a plan of prose MOVES (dispatcher → leaf doc / AGENTS.md).
Because the model is untrusted for filesystem effects, this module enforces — in
pure Python, no LLM, no I/O — that every move is SAFE and NON-FABRICATING before
``scripts/curate.py`` touches a single byte:

* each ``source_excerpt`` is a verbatim substring of its named source file
  (the model may only relocate existing content, never invent or paraphrase it);
* destinations stay inside the repo (no absolute paths, no ``..`` traversal) and
  resolve to a leaf doc or the canonical ``AGENTS.md``;
* the pointer left behind is genuinely pointer-shaped and references the dest;
* the excerpt is substantive (not itself just a pointer/blank).

A plan that fails ANY check is rejected wholesale — curate is one-shot and
all-or-nothing, never a partial apply of a half-trusted plan.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

from scripts._dispatcher_shape import CANONICAL_DISPATCHER, is_leaf_doc

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

PLAN_SCHEMA = "curate-plan/v1"
_MD_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")


@dataclass(frozen=True)
class CurateMove:
    source_rel_path: str
    source_excerpt: str
    dest_rel_path: str
    pointer: str


@dataclass
class CurateValidation:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    moves: list[CurateMove] = field(default_factory=list)

    def _fail(self, msg: str) -> None:
        self.ok = False
        self.errors.append(msg)


def _norm(text: str) -> str:
    """Line-ending normalisation only — the excerpt must be VERBATIM content of
    the source (modulo CRLF/LF), so that ``curate.py`` can relocate it with a
    plain exact replace. Internal whitespace is NOT forgiven (that would let the
    model paraphrase under the guise of reflow)."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _dest_is_safe(dest: str) -> bool:
    norm = dest.replace("\\", "/")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm):
        return False  # absolute
    if ".." in norm.split("/"):
        return False  # traversal
    if not norm.endswith(".md"):
        return False
    return is_leaf_doc(norm) or norm == CANONICAL_DISPATCHER


def _pointer_is_shaped(pointer: str, dest_rel_path: str) -> bool:
    if not _MD_LINK_RE.search(pointer):
        return False
    # The pointer should reference the destination path (basename is enough —
    # the link target may be relative to the dispatcher's directory).
    dest_base = dest_rel_path.replace("\\", "/").rsplit("/", 1)[-1]
    if dest_base not in pointer and dest_rel_path.replace("\\", "/") not in pointer:
        return False
    # Pointer-shaped ⇒ short (principle #2). Generous ceiling for one link line.
    return len(pointer.strip().splitlines()) <= 2


def validate_plan(plan: object, sources: dict[str, str]) -> CurateValidation:
    """Validate a curate-plan dict against the source files it claims to edit.

    ``sources`` maps ``rel_path → current file content`` for every dispatcher
    curate detected drift in. Returns a ``CurateValidation``; ``moves`` is
    populated only when ``ok`` is True (all-or-nothing).
    """
    result = CurateValidation()

    if not isinstance(plan, dict):
        result._fail("plan is not an object")
        return result
    if plan.get("schema") != PLAN_SCHEMA:
        result._fail(f"plan.schema must be {PLAN_SCHEMA!r}, got {plan.get('schema')!r}")
        return result
    moves = plan.get("moves")
    if not isinstance(moves, list):
        result._fail("plan.moves must be a list")
        return result

    validated: list[CurateMove] = []
    for i, mv in enumerate(moves):
        tag = f"move[{i}]"
        if not isinstance(mv, dict):
            result._fail(f"{tag} is not an object")
            continue
        src = mv.get("source_rel_path")
        excerpt = mv.get("source_excerpt")
        dest = mv.get("dest_rel_path")
        pointer = mv.get("pointer")

        if not isinstance(src, str) or src not in sources:
            result._fail(f"{tag}.source_rel_path {src!r} is not a detected source file")
            continue
        if not isinstance(excerpt, str) or not excerpt.strip():
            result._fail(f"{tag}.source_excerpt is empty")
            continue
        if not isinstance(dest, str) or not _dest_is_safe(dest):
            result._fail(f"{tag}.dest_rel_path {dest!r} is unsafe (must be a leaf doc or AGENTS.md, no traversal)")
            continue
        if not isinstance(pointer, str) or not _pointer_is_shaped(pointer, dest):
            result._fail(f"{tag}.pointer is not a short markdown link to {dest!r}")
            continue
        # Anti-fabrication: the excerpt must already exist in the source.
        if _norm(excerpt) not in _norm(sources[src]):
            result._fail(f"{tag}.source_excerpt is not verbatim content of {src!r} (fabrication rejected)")
            continue
        # The excerpt must be substantive prose, not itself just a link/blank.
        residue = _MD_LINK_RE.sub("", excerpt).strip()
        if len(residue) < 20:
            result._fail(f"{tag}.source_excerpt is not substantive prose")
            continue

        validated.append(CurateMove(
            source_rel_path=src, source_excerpt=excerpt,
            dest_rel_path=dest, pointer=pointer,
        ))

    if result.ok:
        result.moves = validated
    return result


__all__ = ["CurateMove", "CurateValidation", "PLAN_SCHEMA", "validate_plan"]
