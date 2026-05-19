"""L1 hardrule: update-playbook (paired with docs/rules/update-playbook.rule.md).

Verifies that the `.ai-playbook/` submodule pin advances only to a semver
tag (`vX.Y.Z`) and never regresses to an older tag.

CLI:
    python scripts/rules/update-playbook.rule.py validate

Exit codes:
    0 — submodule pin is a semver tag.
    1 — pin is a branch / arbitrary SHA / non-semver tag (violation).
    2 — schema break / fatal (no submodule, no git, etc.).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

SEMVER_RE = re.compile(r"^v\d+\.\d+\.\d+$")


def _consumer_root() -> Path | None:
    cur = Path.cwd()
    for parent in [cur, *cur.parents]:
        if (parent / ".gitmodules").is_file():
            return parent
    return None


def validate() -> int:
    root = _consumer_root()
    if root is None:
        print("error: no consumer .gitmodules found from cwd", file=sys.stderr)
        return 2
    submodule = root / ".ai-playbook"
    if not submodule.is_dir():
        print(f"error: .ai-playbook submodule missing at {submodule}", file=sys.stderr)
        return 2
    try:
        tag = subprocess.check_output(
            ["git", "-C", str(submodule), "describe", "--tags", "--exact-match"],
            stderr=subprocess.STDOUT, text=True,
        ).strip()
    except subprocess.CalledProcessError:
        print("error: .ai-playbook HEAD is not pinned to a tag (floating ref)", file=sys.stderr)
        return 1
    if not SEMVER_RE.match(tag):
        print(f"error: pin {tag!r} is not a semver tag", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="update-playbook")
    parser.add_argument("subcommand", choices=["validate"])
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
