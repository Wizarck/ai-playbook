"""D18 — warn at PR-time when touching a rule whose status is 'deprecated'.

Deprecated rules ship with a removal window. Editors should consider whether
the edit (a) keeps the rule on its deprecation schedule (acceptable) or
(b) revives a rule that should be retired (questionable).

CLI:

    python -m scripts.check_deprecated_rules <file1> <file2> ...

Exit codes:
    0 — no deprecated rules touched (or no rule files passed)
    1 — at least one deprecated rule edited (warn-only by design)
    2 — frontmatter parse error
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _parse_frontmatter(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        data = yaml.safe_load(text[3:end].strip())
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="D18 — warn when touching status: deprecated rules.")
    parser.add_argument("files", nargs="*")
    parser.add_argument("--strict", action="store_true", help="Exit 2 instead of 1 on deprecated-rule edits.")
    args = parser.parse_args(argv)

    touched: list[Path] = []
    for f in args.files:
        p = Path(f)
        if not p.is_file():
            continue
        if ".rule.md" not in p.name:
            continue
        fm = _parse_frontmatter(p)
        if fm is None:
            continue
        if fm.get("status") == "deprecated":
            touched.append(p)

    if touched:
        print("WARN: touched rules with status: deprecated (consider retirement instead):", file=sys.stderr)
        for p in touched:
            print(f"  - {p}", file=sys.stderr)
        return 2 if args.strict else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
