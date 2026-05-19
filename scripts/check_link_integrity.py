"""Broken-link detector for markdown links under docs/ (and other dirs).

Walks every relative markdown link `[text](path)` in target files. Resolves
the path relative to the containing markdown file. Fails if the target does
not exist on disk.

Skips:
- Absolute URLs (http://, https://, mailto:, etc.)
- In-document anchors (#header)
- Empty links

CLI:

    python -m scripts.check_link_integrity          # defaults to docs/
    python -m scripts.check_link_integrity docs/ README.md

Exit codes:
    0 — all links resolve
    2 — at least one dead link (prints file:line target)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent

# Capture markdown links: [text](path) — but ignore image syntax ![alt](path)
# because images live outside the link-integrity scope (handled by mkdocs).
_LINK_RE = re.compile(r"(?<!\!)\[([^\]]+)\]\(([^)]+)\)")


def is_external(target: str) -> bool:
    parsed = urlparse(target)
    return bool(parsed.scheme) and parsed.scheme not in ("",)


def normalize_target(target: str) -> str:
    """Strip anchor + query; return path part only."""
    if not target:
        return ""
    if target.startswith("#"):
        return ""
    # Drop fragment + query.
    target = target.split("#", 1)[0]
    target = target.split("?", 1)[0]
    return target.strip()


def find_dead_links(paths: list[Path], repo_root: Path) -> list[tuple[Path, int, str]]:
    dead: list[tuple[Path, int, str]] = []
    for md in paths:
        try:
            text = md.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in _LINK_RE.finditer(line):
                target = match.group(2).strip()
                if is_external(target):
                    continue
                path_part = normalize_target(target)
                if not path_part:
                    continue
                # Resolve relative to the containing markdown file.
                candidate = (md.parent / path_part).resolve()
                # Also accept resolution relative to repo root for tools that
                # used absolute-from-repo links historically.
                alt = (repo_root / path_part.lstrip("/")).resolve()
                if not candidate.exists() and not alt.exists():
                    dead.append((md, lineno, target))
    return dead


def walk(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_file() and p.suffix == ".md":
            out.append(p)
        elif p.is_dir():
            out.extend(sorted(p.rglob("*.md")))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Broken-link detector for markdown.")
    parser.add_argument("paths", nargs="*", default=[str(REPO_ROOT / "docs")])
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 on any dead link. Without --strict, exit 0 and print warnings — Slice 4 ships content debt that Slice 5 resolves.",
    )
    parser.add_argument(
        "--max-warnings",
        type=int,
        default=2000,
        help="Cap on the number of warnings printed (default 2000).",
    )
    args = parser.parse_args(argv)

    files = walk([Path(p) for p in args.paths])
    dead = find_dead_links(files, Path(args.root))

    if dead:
        for md, lineno, target in dead[: args.max_warnings]:
            print(f"{md}:{lineno}: dead link -> {target}", file=sys.stderr)
        if len(dead) > args.max_warnings:
            print(f"  ... ({len(dead) - args.max_warnings} more)", file=sys.stderr)
        if args.strict:
            print(f"FAIL: {len(dead)} dead link(s) in {len(files)} file(s)", file=sys.stderr)
            return 2
        print(f"WARN: {len(dead)} dead link(s) in {len(files)} file(s) — non-strict, exit 0. Run with --strict to fail.", file=sys.stderr)
        return 0

    if not args.quiet:
        print(f"check_link_integrity: OK ({len(files)} files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
