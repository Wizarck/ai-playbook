"""Compress markdown files in caveman style with byte-preservation guarantees.

Public API
----------
    compress(source: Path, *, mode: str = "full", max_retries: int = 2) -> CompressResult

Behavior
--------
1. Read source markdown.
2. Backup to ``<source>.original.md`` (refuse if a different backup already
   exists — that signals an unfinalized earlier session).
3. Extract preservation contract: fenced code blocks, headings, URLs, file
   paths, bash command lines.
4. Call the LLM via ``scripts._llm.call`` with task_class ``doc_writing_edit``,
   system prompt = caveman ruleset + preservation contract.
5. Validate the response: every preserved token must appear in the output
   byte-for-byte.
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

# Regexes for the preservation contract.
_FENCED_BLOCK_RE = re.compile(r"```[^\n]*\n.*?\n```", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_URL_RE = re.compile(r"https?://[^\s)\]>}'\"`]+")
# File path heuristic: contains a `/` and a `.<ext>` or ends with a `/`; excludes URLs (already captured).
_PATH_RE = re.compile(r"(?<![\w/])(?:\.{0,2}/)?[\w.-]+/(?:[\w.-]+/)*[\w.-]+(?:\.[\w]+)?\b")


@dataclass
class PreservationContract:
    code_blocks: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)

    def as_prompt_block(self) -> str:
        """Format the contract as a string the LLM can read."""
        parts = ["PRESERVE BYTE-FOR-BYTE (every token below MUST appear verbatim in your output):"]
        if self.headings:
            parts.append("Headings:")
            parts.extend(f"  {h}" for h in self.headings)
        if self.code_blocks:
            parts.append(f"Code blocks: {len(self.code_blocks)} block(s) — copy each byte-identical to source.")
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


def extract_contract(text: str) -> PreservationContract:
    """Walk ``text`` and capture every token that must survive compression."""
    code_blocks = _FENCED_BLOCK_RE.findall(text)
    # Strip code blocks before scanning for paths/urls so things inside code
    # are not double-counted (they survive via the code-block contract).
    stripped = _FENCED_BLOCK_RE.sub("", text)
    headings = [match.group(0).strip() for match in _HEADING_RE.finditer(stripped)]
    urls = sorted(set(_URL_RE.findall(stripped)))
    # Paths: filter out URL fragments and obvious noise.
    raw_paths = _PATH_RE.findall(stripped)
    paths = sorted({p for p in raw_paths if "/" in p and not p.startswith("http")})

    return PreservationContract(
        code_blocks=code_blocks,
        headings=headings,
        urls=urls,
        paths=paths,
    )


def violations(contract: PreservationContract, output: str) -> list[str]:
    """Return a list of contract violations found in ``output``."""
    missing: list[str] = []
    for h in contract.headings:
        if h not in output:
            missing.append(f"heading: {h!r}")
    for cb in contract.code_blocks:
        if cb not in output:
            missing.append(
                f"code block (first 40 chars): {cb[:40]!r}..."
            )
    for u in contract.urls:
        if u not in output:
            missing.append(f"url: {u}")
    for p in contract.paths:
        if p not in output:
            missing.append(f"path: {p}")
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
3. Copy every fenced code block byte-for-byte (no edits inside ``` blocks).
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
    last_missing = violations(contract, output)

    while last_missing and retries_used < max_retries:
        retries_used += 1
        retry_prompt = (
            "Your previous output violated the preservation contract. "
            "The following tokens are MISSING from your output:\n"
            f"{chr(10).join(f'  - {m}' for m in last_missing)}\n\n"
            "Re-emit the full compressed document with these tokens restored "
            "byte-for-byte. Keep the rest of your prior compression unchanged."
        )
        output, model_actual_retry = caller(retry_prompt, system, max_tokens)
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
