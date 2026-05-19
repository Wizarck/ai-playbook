"""ENGLISH-only docs lint per D6.

Walks docs/ markdown files. For each file: strips fenced code blocks, splits
into prose, and uses `langdetect` (when available) to estimate the dominant
language. Fails when >5% of files under docs/ are non-English.

CLI:

    python -m scripts.check_doc_language          # default: docs/
    python -m scripts.check_doc_language path/to/dir1 path/to/dir2

Exit codes:
    0 — all clean
    2 — non-English content detected (prints offending paths)

`langdetect` is an OPTIONAL dependency (not in install_requires). If absent,
the script falls back to a heuristic: ASCII-only with no Spanish-typical
diacritics (á/é/í/ó/ú/ñ/¿/¡). This keeps CI green on minimal environments.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Fenced code blocks (``` ... ``` or ~~~ ... ~~~).
_FENCE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
# Inline code (`...`).
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
# YAML frontmatter at top.
_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
# Markdown links — keep the visible text, drop the URL.
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^\)]+\)")

# Heuristic Spanish diacritics + punctuation.
_ES_DIACRITICS = re.compile(r"[áéíóúüñÁÉÍÓÚÜÑ¿¡]")


def _strip_code_and_frontmatter(text: str) -> str:
    text = _FRONTMATTER_RE.sub("", text)
    text = _FENCE_RE.sub("", text)
    text = _INLINE_CODE_RE.sub("", text)
    text = _LINK_RE.sub(r"\1", text)
    return text


def _is_english_heuristic(prose: str) -> bool:
    """Fallback heuristic when langdetect unavailable.

    Treats prose with high Spanish-diacritic density as non-English. Tolerates
    isolated proper nouns (Ramírez, Diátaxis) — the threshold is 1 diacritic
    per 200 characters of prose, calibrated to the v0.18.0 corpus.
    """
    if not prose.strip():
        return True
    diacritics = len(_ES_DIACRITICS.findall(prose))
    if diacritics == 0:
        return True
    density = diacritics / max(len(prose), 1)
    return density < 0.005  # < 1 diacritic per 200 chars


def _try_langdetect(prose: str) -> str | None:
    """Return ISO 639-1 code or None if langdetect unavailable."""
    try:
        from langdetect import DetectorFactory, detect  # type: ignore

        DetectorFactory.seed = 0
        if len(prose.strip()) < 50:
            return None
        return detect(prose)
    except Exception:  # pragma: no cover — best-effort
        return None


def check_file(path: Path) -> tuple[bool, str]:
    """Return (is_english, reason)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return True, "binary/unreadable — skipped"
    prose = _strip_code_and_frontmatter(raw)
    if not prose.strip():
        return True, "empty after stripping code"
    detected = _try_langdetect(prose)
    if detected is not None:
        return detected == "en", f"langdetect={detected}"
    ok = _is_english_heuristic(prose)
    return ok, "heuristic (langdetect unavailable)"


def walk(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_file() and p.suffix == ".md":
            out.append(p)
        elif p.is_dir():
            out.extend(sorted(p.rglob("*.md")))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ENGLISH-only docs lint (D6).")
    parser.add_argument("paths", nargs="*", default=[str(REPO_ROOT / "docs")], help="Files/dirs to scan (default: docs/).")
    parser.add_argument("--threshold-percent", type=int, default=5, help="Max %% of non-English files allowed (default 5).")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    files = walk([Path(p) for p in args.paths])
    bad: list[tuple[Path, str]] = []
    for f in files:
        ok, reason = check_file(f)
        if not ok:
            bad.append((f, reason))

    total = max(len(files), 1)
    pct = (len(bad) / total) * 100
    if pct > args.threshold_percent:
        for p, reason in bad:
            print(f"non-english: {p} ({reason})", file=sys.stderr)
        print(f"FAIL: {len(bad)}/{total} files ({pct:.1f}%) non-English; threshold {args.threshold_percent}%", file=sys.stderr)
        return 2

    if not args.quiet:
        print(f"check_doc_language: OK ({len(files)} files; {len(bad)} non-English / {pct:.1f}%; threshold {args.threshold_percent}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
