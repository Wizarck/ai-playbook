"""Compress markdown files in caveman style with byte-preservation guarantees.

Public API
----------
    compress(source: Path, *, mode: str = "full", max_retries: int = 2) -> CompressResult

Behavior
--------
1. Read source markdown.
2. Backup to ``<source>.original.md`` (refuse if a different backup already
   exists — that signals an unfinalized earlier session).
3. Extract preservation contract: fenced code blocks (``` and ~~~, at any
   indentation), inline code spans, headings (whole line, same level),
   URLs, file paths.
4. Call the LLM via ``scripts._llm.call`` with task_class ``doc_writing_edit``,
   system prompt = caveman ruleset + preservation contract.
5. Validate the response (CRLF normalised to LF): every preserved token must
   appear in the output byte-for-byte, and at least ``MIN_PROSE_KEPT`` of the
   source's prose words must survive (no token-only skeleton).
6. On validation failure, send a targeted retry prompt naming the missing
   tokens. Up to ``max_retries`` retries.
7. After max_retries exhausted, restore source from backup and raise
   ``CompressionFailedError`` with the list of unrecoverable violations.
8. On success, write the compressed text to ``source`` (overwriting) and
   return a ``CompressResult``.

The LLM call routes through ``scripts._llm`` per the playbook's
``add-litellm-enforcement`` contract. Tests mock that import.
"""
from __future__ import annotations

import re
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


VALID_MODES = ("lite", "full", "ultra")
DEFAULT_MAX_RETRIES = 2
MAX_FILE_BYTES = 100 * 1024  # 100 KB — anything larger requires --force in the CLI
# Skeleton guard: output that keeps every protected token but (nearly) none of
# the prose passes the token checks. Keeping under 10% of the prose words is a
# skeleton, not a compression (even ultra targets ~75% fewer bytes); a source
# with fewer prose words than the floor is not judged.
MIN_PROSE_WORDS = 10
MIN_PROSE_KEPT = 0.10

# Regexes for the preservation contract.
# Fence opener/closer at any indentation (list items indent their fences).
_FENCE_OPEN_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
# Matched per paragraph (see _scan_inline_code), so a span may wrap onto the next line.
_INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)(?:[^\n]|\n(?![ \t]*\n))+?(?<!`)\1(?!`)")
_LINE_BREAK_RE = re.compile(r"[ \t]*\n[ \t]*")
# Lines that open a block (heading, table row, quote, list item): a span never
# continues from the previous line into them.
_BLOCK_LINE_RE = re.compile(r"[ \t]*(?:#|\||>|[-*+][ \t]|\d{1,9}[.)][ \t])")
_TABLE_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_URL_RE = re.compile(r"https?://[^\s)\]>}'\"`]+")
# File path heuristic: contains a `/` and a `.<ext>` or ends with a `/`; excludes URLs (already captured).
_PATH_RE = re.compile(r"(?<![\w/])(?:\.{0,2}/)?[\w.-]+/(?:[\w.-]+/)*[\w.-]+(?:\.[\w]+)?\b")


@dataclass
class PreservationContract:
    code_blocks: list[str] = field(default_factory=list)
    inline_code: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    prose_words: int = 0  # source words outside every protected token (0 = not checked)

    def as_prompt_block(self) -> str:
        """Format the contract as a string the LLM can read."""
        parts = ["PRESERVE BYTE-FOR-BYTE (every token below MUST appear verbatim in your output):"]
        if self.headings:
            parts.append("Headings:")
            parts.extend(f"  {h}" for h in self.headings)
        if self.code_blocks:
            parts.append(f"Code blocks: {len(self.code_blocks)} block(s) — copy each byte-identical to source.")
        if self.inline_code:
            parts.append("Inline code:")
            parts.extend(f"  {_flat(c)}" for c in self.inline_code)
        if self.urls:
            parts.append("URLs:")
            parts.extend(f"  {u}" for u in self.urls)
        if self.paths:
            parts.append("File paths:")
            parts.extend(f"  {p}" for p in self.paths)
        return "\n".join(parts)


@dataclass
class CompressResult:
    source: Path
    backup: Path
    original_bytes: int
    compressed_bytes: int
    retries_used: int
    model_actual: str | None = None

    @property
    def percent_saved(self) -> float:
        if self.original_bytes == 0:
            return 0.0
        return 100.0 * (self.original_bytes - self.compressed_bytes) / self.original_bytes


class CompressionFailedError(RuntimeError):
    """Raised when the LLM cannot produce output that satisfies the contract
    after max_retries. Source is restored from backup before raising."""


# ---------------------------------------------------------------------------
# Preservation extraction
# ---------------------------------------------------------------------------


def _split_fences(text: str) -> tuple[list[str], str]:
    """Return (fenced blocks verbatim, text with those blocks removed).

    CommonMark-ish: ``` or ~~~ fences at any indentation; a block closes on
    a line of the same fence char, at least as long, and nothing else. An
    unclosed fence runs to end of document.
    """
    blocks: list[str] = []
    prose: list[str] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = _FENCE_OPEN_RE.match(lines[i])
        if not m or (m.group(1)[0] == "`" and "`" in lines[i][m.end():]):
            prose.append(lines[i])
            i += 1
            continue
        fence = m.group(1)
        close_re = re.compile(rf"^[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$")
        j = i + 1
        while j < len(lines) and not close_re.match(lines[j]):
            j += 1
        blocks.append("\n".join(lines[i : j + 1]))
        prose.append("")  # a block ends the paragraph: no code span pairs across it
        i = j + 1
    return blocks, "\n".join(prose)


def _flat(text: str) -> str:
    """Each line break (with the blanks around it) as one space, as CommonMark renders a wrapped span."""
    return _LINE_BREAK_RE.sub(" ", text)


def _scan_inline_code(prose: str) -> tuple[list[str], str]:
    """``(inline code spans, prose with each span blanked out)``.

    Spans pair within a paragraph: a span may wrap onto a continuation line,
    never across a blank line or into a new block line. Headings never
    continue; table rows pair per cell (GFM splits cells first).
    """
    spans: list[str] = []
    rest: list[str] = []
    para: list[str] = []

    def scan(text: str) -> None:
        spans.extend(m.group(0) for m in _INLINE_CODE_RE.finditer(text))
        rest.append(_INLINE_CODE_RE.sub(" ", text))

    def flush() -> None:
        if para:
            scan("\n".join(para))
            para.clear()

    for line in prose.split("\n"):
        head = line.lstrip()
        if not head or _BLOCK_LINE_RE.match(line):
            flush()
        if head.startswith("|"):
            for cell in _TABLE_CELL_SPLIT_RE.split(line):
                scan(cell)
        elif head.startswith("#"):
            scan(line)
        elif head:
            para.append(line)
    flush()
    return spans, "\n".join(rest)


def _prose_words(prose: str) -> int:
    """Words in fence-free text outside inline code, headings, URLs and paths."""
    rest = _scan_inline_code(prose)[1]
    for rx in (_HEADING_RE, _URL_RE, _PATH_RE):
        rest = rx.sub(" ", rest)
    return len(re.findall(r"\w+", rest))


def extract_contract(text: str) -> PreservationContract:
    """Walk ``text`` and capture every token that must survive compression."""
    code_blocks, stripped = _split_fences(text)
    # Code blocks are stripped before scanning for the rest so things inside
    # code are not double-counted (they survive via the code-block contract).
    inline_code = list(dict.fromkeys(_scan_inline_code(stripped)[0]))
    headings = [match.group(0).strip() for match in _HEADING_RE.finditer(stripped)]
    urls = sorted(set(_URL_RE.findall(stripped)))
    # Paths: filter out URL fragments and obvious noise.
    raw_paths = _PATH_RE.findall(stripped)
    paths = sorted({p for p in raw_paths if "/" in p and not p.startswith("http")})

    return PreservationContract(
        code_blocks=code_blocks,
        inline_code=inline_code,
        headings=headings,
        urls=urls,
        paths=paths,
        prose_words=_prose_words(stripped),
    )


def violations(contract: PreservationContract, output: str) -> list[str]:
    """Return a list of contract violations found in ``output``."""
    output = output.replace("\r\n", "\n")
    missing: list[str] = []
    for h in contract.headings:
        # Whole-line match: "# T" must not be satisfied by "## T".
        if not re.search(rf"^[ \t]*{re.escape(h)}[ \t]*$", output, re.MULTILINE):
            missing.append(f"heading: {h!r}")
    for cb in contract.code_blocks:
        if cb not in output:
            missing.append(
                f"code block (first 40 chars): {cb[:40]!r}..."
            )
    flat_output = _flat(output)
    for ic in contract.inline_code:
        # A span wrapped across lines may come back on one line (or re-wrapped).
        if ic not in output and ("\n" not in ic or _flat(ic) not in flat_output):
            missing.append(f"inline code: {_flat(ic)}")
    for u in contract.urls:
        if u not in output:
            missing.append(f"url: {u}")
    for p in contract.paths:
        if p not in output:
            missing.append(f"path: {p}")
    if contract.prose_words >= MIN_PROSE_WORDS:
        kept = _prose_words(_split_fences(output)[1])
        if kept < contract.prose_words * MIN_PROSE_KEPT:
            missing.append(
                f"prose: only {kept} of the source's {contract.prose_words} prose words survive; "
                "compress the prose, do not drop it"
            )
    return missing


# ---------------------------------------------------------------------------
# LLM glue
# ---------------------------------------------------------------------------


_SYSTEM_TEMPLATE = """You are a markdown compressor running in caveman mode (intensity: {mode}).

CAVEMAN RULES:
- Drop articles (a/an/the), filler words, pleasantries, hedging.
- Fragments OK. Short synonyms. Technical terms exact.
- Pattern: [thing] [action] [reason]. [next step].

INTENSITY ({mode}):
{mode_rules}

PRESERVATION CONTRACT (NON-NEGOTIABLE):
{contract}

YOU MUST:
1. Output a complete compressed markdown document. Same structure, same
   meaning, but caveman style for prose.
2. Copy every heading byte-for-byte (same characters, same level).
3. Copy every fenced code block (``` or ~~~, including indentation) and
   every inline `code` span byte-for-byte.
4. Preserve every URL and file path verbatim.
5. Output ONLY the compressed markdown. No preamble. No "Here is...". No
   explanation. Just the document.
"""

_MODE_RULES = {
    "lite": "Drop filler and hedging only. Keep articles and full sentences. ~25% reduction target.",
    "full": "Drop articles. Fragments OK. ~60% reduction target.",
    "ultra": (
        "Drop articles. Abbreviate: DB, auth, cfg, env, repo, fn, ref, ptr, ctx. "
        "Use arrows for causality: 'a → b → c'. Preserve code symbols. ~75% reduction target."
    ),
}


# Indirection lets tests inject a mock without touching scripts._llm.
def _default_llm_call(prompt: str, system: str, max_tokens: int) -> tuple[str, str | None]:
    """Returns (text, model_actual). Raises on routing failure."""
    from scripts._llm import call as _llm_call

    resp = _llm_call(
        "doc_writing_edit",
        prompt,
        system=system,
        max_tokens=max_tokens,
        application="caveman-compress",
    )
    return resp.text, resp.model_actual


LLMCaller = Callable[[str, str, int], tuple[str, str | None]]


# ---------------------------------------------------------------------------
# Backup / restore helpers
# ---------------------------------------------------------------------------


def _backup_path(source: Path) -> Path:
    return source.with_name(source.name + ".original.md")


def _ensure_backup(source: Path) -> Path:
    """Copy source to ``<source>.original.md``. Refuse if a different backup
    already exists (unfinalized prior session). Returns the backup path."""
    bp = _backup_path(source)
    src_bytes = source.read_bytes()
    if bp.is_file():
        existing = bp.read_bytes()
        if existing != src_bytes:
            raise FileExistsError(
                f"backup at {bp} differs from source. Resolve manually: "
                "either restore from backup or delete the backup if you want to recompress."
            )
        return bp
    shutil.copy2(source, bp)
    return bp


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def compress(
    source: Path,
    *,
    mode: str = "full",
    max_retries: int = DEFAULT_MAX_RETRIES,
    force_large: bool = False,
    llm_call: LLMCaller | None = None,
) -> CompressResult:
    """Compress ``source`` in caveman style with byte-preservation validation.

    Parameters
    ----------
    source : Path
        Markdown file to compress. Must end in ``.md``.
    mode : str
        One of ``lite`` | ``full`` | ``ultra``.
    max_retries : int
        Number of targeted retry passes when validation fails. Default 2.
    force_large : bool
        Allow files larger than 100 KB. Default False — large files
        often blow past max_tokens and risk partial output.
    llm_call : callable, optional
        Injection point for tests. Default routes via ``scripts._llm.call``.

    Returns
    -------
    CompressResult

    Raises
    ------
    ValueError
        Invalid mode, non-markdown file, empty source, source too large.
    FileNotFoundError
        Source does not exist.
    FileExistsError
        Stale backup detected.
    CompressionFailedError
        LLM could not produce a contract-satisfying output after retries.
        Source restored from backup before raising.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode {mode!r}; valid: {VALID_MODES}")
    if source.suffix.lower() != ".md":
        raise ValueError(f"only .md files supported; got {source.suffix!r}")
    if not source.is_file():
        raise FileNotFoundError(f"source not found: {source}")

    src_bytes_count = source.stat().st_size
    if src_bytes_count == 0:
        raise ValueError("source is empty; nothing to compress.")
    if src_bytes_count > MAX_FILE_BYTES and not force_large:
        raise ValueError(
            f"source is {src_bytes_count} bytes (>{MAX_FILE_BYTES}); "
            "pass force_large=True to override."
        )

    original = source.read_text(encoding="utf-8")
    backup = _ensure_backup(source)

    contract = extract_contract(original)
    system = _SYSTEM_TEMPLATE.format(
        mode=mode,
        mode_rules=_MODE_RULES[mode],
        contract=contract.as_prompt_block(),
    )

    caller = llm_call or _default_llm_call
    # Conservative cap: 2x the source token-count approximation (chars/4)
    # plus 1000 slack. Most compressions land 40-65% smaller.
    max_tokens = max(2048, (src_bytes_count // 2) + 1000)

    output: str = ""
    model_actual: str | None = None
    retries_used = 0
    last_missing: list[str] = []

    user_prompt = (
        "Compress the following markdown document in caveman style. "
        "Honour the preservation contract above. Output the compressed "
        "document only.\n\n"
        "--- SOURCE ---\n"
        f"{original}\n"
        "--- END SOURCE ---\n"
    )

    output, model_actual = caller(user_prompt, system, max_tokens)
    output = output.replace("\r\n", "\n")  # the source is read LF; compare and write LF
    last_missing = violations(contract, output)

    while last_missing and retries_used < max_retries:
        retries_used += 1
        # Each call is stateless, so the retry MUST carry the source and the
        # previous attempt — otherwise the model rewrites from nothing.
        retry_prompt = (
            f"{user_prompt}\n"
            "--- PREVIOUS OUTPUT ---\n"
            f"{output}\n"
            "--- END PREVIOUS OUTPUT ---\n\n"
            "Your previous output violated the preservation contract. "
            "The following tokens are MISSING from your output:\n"
            f"{chr(10).join(f'  - {m}' for m in last_missing)}\n\n"
            "Re-emit the full compressed document of the SOURCE with these "
            "tokens restored byte-for-byte. Keep the rest of your previous "
            "output unchanged."
        )
        output, model_actual_retry = caller(retry_prompt, system, max_tokens)
        output = output.replace("\r\n", "\n")
        if model_actual_retry:
            model_actual = model_actual_retry
        last_missing = violations(contract, output)

    if last_missing:
        # Restore source from backup so the caller's file is unchanged.
        shutil.copy2(backup, source)
        raise CompressionFailedError(
            f"compression failed after {retries_used} retries; "
            f"unrecoverable violations: {last_missing[:5]}"
            + (f" (and {len(last_missing) - 5} more)" if len(last_missing) > 5 else "")
        )

    # Trim a single trailing newline + ensure exactly one.
    final = output.rstrip("\n") + "\n"
    source.write_text(final, encoding="utf-8")

    return CompressResult(
        source=source,
        backup=backup,
        original_bytes=src_bytes_count,
        compressed_bytes=len(final.encode("utf-8")),
        retries_used=retries_used,
        model_actual=model_actual,
    )


__all__ = [
    "VALID_MODES",
    "DEFAULT_MAX_RETRIES",
    "MAX_FILE_BYTES",
    "PreservationContract",
    "CompressResult",
    "CompressionFailedError",
    "extract_contract",
    "violations",
    "compress",
]
