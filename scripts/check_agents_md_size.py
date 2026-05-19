"""D14 — fail CI when AGENTS.md exceeds 500 lines.

AGENTS.md is loaded into every turn's context. Without a cap, it grows to
dominate the context window. 500 lines x ~10 tokens/line = ~5k tokens,
which is the per-turn premium ceiling.

CLI:

    python -m scripts.check_agents_md_size
    python -m scripts.check_agents_md_size --cap 750  # raise the cap

Exit codes:
    0 — under cap
    2 — over cap
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CAP = 500


def line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except (UnicodeDecodeError, OSError):
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="D14 — AGENTS.md size cap enforcer.")
    parser.add_argument("--file", default=str(REPO_ROOT / "AGENTS.md"))
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    path = Path(args.file)
    if not path.is_file():
        print(f"FAIL: {path} not found", file=sys.stderr)
        return 2

    count = line_count(path)
    if count > args.cap:
        print(f"FAIL: {path} has {count} lines; cap is {args.cap}", file=sys.stderr)
        return 2
    if not args.quiet:
        print(f"check_agents_md_size: OK ({path}: {count}/{args.cap} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
