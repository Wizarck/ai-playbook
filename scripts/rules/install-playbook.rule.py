"""L1 hardrule: install-playbook (paired with docs/rules/install-playbook.rule.md).

Verifies that the consumer repository has `.ai-playbook/` mounted as a
Git submodule pinned to a semver tag.

CLI:
    python scripts/rules/install-playbook.rule.py validate

Exit codes:
    0 — submodule present and pinned to a semver tag.
    1 — submodule missing or not pinned to a semver tag (violation).
    2 — schema break / fatal (not invoked from a Git working tree).
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
        return 1
    try:
        out = subprocess.check_output(
            ["git", "-C", str(submodule), "describe", "--tags", "--exact-match"],
            stderr=subprocess.STDOUT, text=True,
        ).strip()
    except subprocess.CalledProcessError:
        print("error: .ai-playbook HEAD is not on a tag", file=sys.stderr)
        return 1
    if not SEMVER_RE.match(out):
        print(f"error: .ai-playbook pinned to non-semver tag {out!r}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="install-playbook")
    parser.add_argument("subcommand", choices=["validate"])
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    return 2


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("install-playbook", main))
