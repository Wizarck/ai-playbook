"""Regenerate ``<!-- BEGIN auto-managed: <source> -->`` sections in consumer files.

Populated in T17. See ``specs/auto-managed-sections.md`` for the marker format,
the supported source shapes, and the idempotency contract.

CLI
---
    python -m scripts.auto_managed <path>... [--check] [--fix]

- ``--check`` (default): list files with stale sections; exit 1 if any.
- ``--fix``: rewrite sections in-place, preserving markers. Prints a diff summary.

Applying ``--fix`` twice to already-clean content is a no-op (zero diff).

Public API
----------
    compute_expected(source_spec, playbook_root) -> str
    find_sections(text) -> list[Section]
    regenerate(file_path, playbook_root) -> list[Diff]

Exit codes (per ``specs/error-message-standard.md``)
    0 success or clean
    1 stale sections found (``--check``) or unrecoverable marker syntax
    2 environment/setup failure (playbook root not found, source file missing)
    3 reserved
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Force UTF-8 stdio — Windows default cp1252 cannot encode the sigils we emit.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts._break_glass import add_break_glass_flag, apply_break_glass  # noqa: E402

SCRIPT_BASENAME = "auto_managed.py"
GATE_NAME = "auto-managed-sections"

BEGIN_RE = re.compile(r"^<!--\s*BEGIN auto-managed:\s*(?P<source>[^\s>][^>]*?)\s*-->\s*$")
END_RE = re.compile(r"^<!--\s*END auto-managed\s*-->\s*$")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Section:
    """A single auto-managed section discovered in a file.

    Line numbers are 1-indexed and refer to the **marker** lines. Content
    between them lives on ``start_line + 1 .. end_line - 1``.
    """

    source: str
    start_line: int
    end_line: int
    current_content: str
    marker_line: str


@dataclass
class Diff:
    """Summary of a single section that needs regeneration (or was regenerated)."""

    source: str
    start_line: int
    end_line: int
    before: str
    after: str

    @property
    def changed(self) -> bool:
        return self.before != self.after


@dataclass
class PlaybookLookup:
    """Resolved playbook root + cached file reads used by extractors."""

    root: Path
    _cache: dict[Path, str] = field(default_factory=dict)

    def read(self, rel: str) -> str:
        abs_path = (self.root / rel).resolve()
        if abs_path in self._cache:
            return self._cache[abs_path]
        if not abs_path.is_file():
            raise FileNotFoundError(str(abs_path))
        text = abs_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        self._cache[abs_path] = text
        return text


# ---------------------------------------------------------------------------
# Canonical error emission
# ---------------------------------------------------------------------------


def _emit_error(
    *, why: str, where: str, fix: str, override_invocation: str | None = None
) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    if override_invocation is None:
        print("   OVERRIDE: none", file=sys.stderr)
    else:
        print(f"   OVERRIDE: {override_invocation}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Playbook root discovery
# ---------------------------------------------------------------------------


def find_playbook_root(start: Path | None = None) -> Path | None:
    """Locate the ai-playbook repo root (contains ``specs/`` + ``scripts/``).

    Walks up from ``start`` (defaults to this script's directory).
    """
    here = (start or Path(__file__)).resolve()
    if here.is_file():
        here = here.parent
    for candidate in (here, *here.parents):
        if (candidate / "specs").is_dir() and (candidate / "scripts").is_dir():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Section parser
# ---------------------------------------------------------------------------


def find_sections(text: str) -> list[Section]:
    """Parse all ``<!-- BEGIN auto-managed: ... -->`` sections in ``text``.

    Raises ``ValueError`` if markers are nested, unbalanced, or an END comes
    before a BEGIN. The matching is done on full, trimmed lines; markers MUST
    occupy their own line (no surrounding text on the same line).

    Lines inside fenced code blocks (``\x60\x60\x60``) are ignored — spec files
    legitimately show marker examples inside code blocks.
    """
    normalized = text.replace("\r\n", "\n")
    lines = normalized.split("\n")

    sections: list[Section] = []
    current_begin: int | None = None
    current_source: str | None = None
    current_marker: str | None = None
    in_code_fence = False

    for idx, line in enumerate(lines, start=1):
        if line.lstrip().startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        begin = BEGIN_RE.match(line)
        end = END_RE.match(line)

        if begin:
            if current_begin is not None:
                raise ValueError(
                    f"Nested BEGIN auto-managed at line {idx}; previous BEGIN "
                    f"on line {current_begin} has no matching END."
                )
            current_begin = idx
            current_source = begin.group("source").strip()
            current_marker = line
            continue

        if end:
            if current_begin is None:
                raise ValueError(
                    f"Unbalanced END auto-managed at line {idx} without a preceding BEGIN."
                )
            body = "\n".join(lines[current_begin:idx - 1])
            assert current_source is not None
            assert current_marker is not None
            sections.append(
                Section(
                    source=current_source,
                    start_line=current_begin,
                    end_line=idx,
                    current_content=body,
                    marker_line=current_marker,
                )
            )
            current_begin = None
            current_source = None
            current_marker = None

    if current_begin is not None:
        raise ValueError(
            f"Unterminated BEGIN auto-managed opened at line {current_begin}."
        )
    return sections


# ---------------------------------------------------------------------------
# Source extractors — supported ``source_spec`` shapes
# ---------------------------------------------------------------------------


def _extract_heading_section(
    md_text: str, heading_token: str
) -> str | None:
    """Return content under the first ``## N <heading_token>``-style heading.

    The extractor finds the heading line, then grabs everything up to (but not
    including) the next ``## `` heading. Surrounding blank padding is stripped
    but inner formatting is preserved verbatim.

    Matching is case-insensitive on ``heading_token``; the token may be the
    exact suffix (e.g. ``"Runtime entities"``) or a short slug/anchor
    (e.g. ``"runtime"`` matches ``"## 1 Runtime entities"``).
    """
    lines = md_text.replace("\r\n", "\n").split("\n")
    token = heading_token.strip().lower()

    start: int | None = None
    for i, line in enumerate(lines):
        if not line.startswith("## "):
            continue
        heading_rest = line[3:].strip().lower()
        # Strip optional leading "N " numeric prefix for anchor-style match.
        heading_core = re.sub(r"^\d+\s+", "", heading_rest)
        if (
            token in heading_rest
            or heading_core.startswith(token)
            or token == heading_rest
        ):
            start = i + 1
            break
    if start is None:
        return None

    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break

    # Strip leading blank lines; trim trailing whitespace / blank lines.
    while start < end and lines[start].strip() == "":
        start += 1
    while end > start and lines[end - 1].strip() == "":
        end -= 1
    return "\n".join(lines[start:end])


_SUPPORTED_SOURCES = {
    "specs/taxonomy:runtime": ("specs/taxonomy.md", "Runtime entities"),
    "specs/taxonomy:config": ("specs/taxonomy.md", "Config artefacts"),
    "specs/verdict-contract:levels": ("specs/verdict-contract.md", "Severity levels"),
}

# ``specs/universal-principles`` intentionally hard-fails in v1.0 until we
# expose a canonical source file inside this repo (the principles currently
# live in ``~/.claude/CLAUDE.md``, which is not checked into the playbook).
_UNIVERSAL_PRINCIPLES_SPEC = "specs/universal-principles"


def compute_expected(source_spec: str, playbook_root: Path) -> str:
    """Return the expected section body for ``source_spec``.

    The return value does NOT include the trailing newline that glues it to
    the closing marker. ``regenerate`` handles that.

    Raises
    ------
    ValueError
        If ``source_spec`` shape is not recognised.
    FileNotFoundError
        If the underlying spec file is missing.
    LookupError
        If the heading/anchor cannot be located in the source file.
    """
    lookup = PlaybookLookup(root=playbook_root)
    spec = source_spec.strip()

    if spec == _UNIVERSAL_PRINCIPLES_SPEC:
        raise ValueError(
            "source_spec='specs/universal-principles' is not yet available in "
            "the playbook. FIX: open a PR that adds a canonical "
            "'specs/universal-principles.md' file with the 8 principles, then "
            "wire it into scripts/auto_managed._SUPPORTED_SOURCES."
        )

    if spec in _SUPPORTED_SOURCES:
        rel, heading_token = _SUPPORTED_SOURCES[spec]
        text = lookup.read(rel)
        extracted = _extract_heading_section(text, heading_token)
        if extracted is None:
            raise LookupError(
                f"heading matching '{heading_token}' not found in {rel}"
            )
        return extracted

    # Generic fallback: ``<spec-file>:<anchor>`` with the spec-file relative to
    # the playbook root and ending in ``.md``. This keeps the extractor
    # extensible without requiring a registry edit for trivial additions.
    if ":" in spec:
        rel_part, anchor = spec.split(":", 1)
        rel = rel_part if rel_part.endswith(".md") else f"{rel_part}.md"
        text = lookup.read(rel)
        extracted = _extract_heading_section(text, anchor)
        if extracted is None:
            raise LookupError(
                f"heading matching '{anchor}' not found in {rel}"
            )
        return extracted

    raise ValueError(
        f"unknown source_spec '{source_spec}'. Supported shapes: "
        f"{sorted(_SUPPORTED_SOURCES.keys())} or '<spec-file>:<anchor>'."
    )


# ---------------------------------------------------------------------------
# Regeneration
# ---------------------------------------------------------------------------


def _splice(
    original_lines: list[str],
    section: Section,
    new_content: str,
) -> list[str]:
    """Return a new list with ``section`` body replaced by ``new_content``.

    Markers are preserved verbatim. ``new_content`` is split on ``\\n``; any
    trailing newline is stripped (we do NOT want a blank line right before the
    END marker unless the source content itself has one).
    """
    new_body_lines = new_content.split("\n") if new_content else []
    # Trim trailing empty lines so the END marker sits flush against content.
    while new_body_lines and new_body_lines[-1] == "":
        new_body_lines.pop()

    before = original_lines[: section.start_line]
    after = original_lines[section.end_line - 1 :]
    return before + new_body_lines + after


def regenerate(file_path: Path, playbook_root: Path) -> list[Diff]:
    """Compute + (optionally) apply regeneration.

    This function returns a list of ``Diff`` entries describing what would
    change. It does NOT write to disk — callers decide ``--check`` vs
    ``--fix`` behaviour.
    """
    raw = file_path.read_text(encoding="utf-8")
    normalized = raw.replace("\r\n", "\n")
    sections = find_sections(normalized)

    diffs: list[Diff] = []
    for section in sections:
        expected = compute_expected(section.source, playbook_root)
        diffs.append(
            Diff(
                source=section.source,
                start_line=section.start_line,
                end_line=section.end_line,
                before=section.current_content,
                after=expected,
            )
        )
    return diffs


def apply_fix(file_path: Path, playbook_root: Path) -> list[Diff]:
    """Rewrite ``file_path`` in-place with regenerated sections.

    Returns the list of ``Diff`` entries that actually changed. If no diffs
    are stale, the file is left untouched (byte-for-byte).
    """
    raw = file_path.read_text(encoding="utf-8")
    normalized = raw.replace("\r\n", "\n")
    sections = find_sections(normalized)

    if not sections:
        return []

    original_lines = normalized.split("\n")
    diffs: list[Diff] = []

    # Rebuild from the bottom up so start_line / end_line indices stay valid.
    working_lines = list(original_lines)
    sections_desc = sorted(sections, key=lambda s: s.start_line, reverse=True)
    for section in sections_desc:
        expected = compute_expected(section.source, playbook_root)
        diffs.append(
            Diff(
                source=section.source,
                start_line=section.start_line,
                end_line=section.end_line,
                before=section.current_content,
                after=expected,
            )
        )
        working_lines = _splice(working_lines, section, expected)

    diffs.reverse()

    new_text = "\n".join(working_lines)
    # Preserve the file's original trailing-newline behaviour (common case: YES).
    if raw.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"

    if new_text != normalized:
        file_path.write_text(new_text, encoding="utf-8")
    return [d for d in diffs if d.changed]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _process_one(
    path: Path,
    playbook_root: Path,
    *,
    fix: bool,
) -> tuple[int, list[Diff]]:
    """Return (exit_code, diffs) for a single file."""
    try:
        diffs = regenerate(path, playbook_root) if not fix else apply_fix(path, playbook_root)
    except ValueError as e:
        _emit_error(
            why=str(e),
            where=f"{path.as_posix()}",
            fix="fix the marker syntax or source_spec and re-run "
            "`python -m scripts.auto_managed <file> --check`.",
        )
        return 1, []
    except FileNotFoundError as e:
        _emit_error(
            why=f"auto-managed source file not found: {e}",
            where=f"{path.as_posix()}",
            fix="verify the playbook submodule is current and the spec path "
            "in the BEGIN marker points at an existing file.",
        )
        return 2, []
    except LookupError as e:
        _emit_error(
            why=f"auto-managed source anchor not found: {e}",
            where=f"{path.as_posix()}",
            fix="either rename the heading in the source spec or update the "
            "source_spec token in the BEGIN marker.",
        )
        return 2, []

    stale = [d for d in diffs if d.changed]
    if fix:
        return 0, stale
    return (1 if stale else 0), stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="auto_managed",
        description="Check / regenerate auto-managed sections in markdown files.",
    )
    parser.add_argument("paths", nargs="+", type=Path, help="Files to inspect.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", default=True,
                       help="Report stale sections; exit 1 if any (default).")
    group.add_argument("--fix", action="store_true",
                       help="Rewrite stale sections in-place.")
    parser.add_argument("--playbook-root", type=Path, default=None,
                        help="Path to the ai-playbook repo root "
                             "(default: auto-detected).")
    add_break_glass_flag(parser)
    args = parser.parse_args(argv)

    playbook_root = (
        args.playbook_root.expanduser().resolve()
        if args.playbook_root is not None
        else find_playbook_root()
    )
    if playbook_root is None or not (playbook_root / "specs").is_dir():
        _emit_error(
            why="ai-playbook root not found (no specs/ + scripts/ pair)",
            where=f"{SCRIPT_BASENAME}:playbook-root",
            fix="pass --playbook-root <path>, or run from inside an "
            "ai-playbook checkout.",
        )
        return 2

    any_stale = False
    total_changed = 0
    for path in args.paths:
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            _emit_error(
                why=f"file not found: {resolved}",
                where=f"{SCRIPT_BASENAME}:input",
                fix="pass an existing file path.",
            )
            return 2
        rc, diffs = _process_one(resolved, playbook_root, fix=args.fix)
        if rc == 2:
            return 2
        stale = [d for d in diffs if d.changed] if not args.fix else diffs
        if stale:
            any_stale = True
            total_changed += len(stale)
            verb = "rewrote" if args.fix else "stale"
            for d in stale:
                print(
                    f"  - {verb} {path.as_posix()} "
                    f"[{d.source}] lines {d.start_line}..{d.end_line}"
                )

    if args.fix:
        if total_changed:
            print(f"✅ Rewrote {total_changed} auto-managed section(s).")
        else:
            print("✅ No auto-managed sections needed rewriting.")
        return 0

    if any_stale:
        # Non-override path: caller sees exit 1.
        result = apply_break_glass(
            gate=GATE_NAME,
            script=SCRIPT_BASENAME,
            reason=args.force_reason,
            override_allowed=True,
            repo_root=playbook_root,
        )
        if result.applied:
            print(f"⚠️ OVERRIDE APPLIED: {result.reason}")
            return 0
        _emit_error(
            why=f"{total_changed} auto-managed section(s) are stale",
            where="auto_managed:check",
            fix="run `python -m scripts.auto_managed <file>... --fix` "
            "and commit the result.",
            override_invocation='python -m scripts.auto_managed '
            '--force-with-reason="<why>"',
        )
        return 1

    print("✅ All auto-managed sections are up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
