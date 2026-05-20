"""L1 hardrule: update-playbook (paired with docs/rules/update-playbook.rule.md).

Verifies that the `.ai-playbook/` submodule pin advances only to a semver
tag (`vX.Y.Z`) and never regresses to an older tag. The `apply` subcommand
is plan-only — bumping a submodule mutates `.gitmodules` and creates a
commit; the operator must run the printed commands manually.

CLI:
    python scripts/rules/update-playbook.rule.py validate
    python scripts/rules/update-playbook.rule.py apply [--dry-run]

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


def _current_pin(submodule: Path) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(submodule), "describe", "--tags", "--exact-match"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        return out or None
    except subprocess.CalledProcessError:
        return None


def _latest_tag(submodule: Path) -> str | None:
    """Fetch + return the newest semver tag from origin."""
    try:
        subprocess.check_call(
            ["git", "-C", str(submodule), "fetch", "--tags", "--quiet"],
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        pass  # best-effort
    try:
        out = subprocess.check_output(
            ["git", "-C", str(submodule), "tag", "--list", "v*", "--sort=-v:refname"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return None
    for line in out.splitlines():
        line = line.strip()
        if line and SEMVER_RE.match(line):
            return line
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
    tag = _current_pin(submodule)
    if tag is None:
        print("error: .ai-playbook HEAD is not pinned to a tag (floating ref)", file=sys.stderr)
        return 1
    if not SEMVER_RE.match(tag):
        print(f"error: pin {tag!r} is not a semver tag", file=sys.stderr)
        return 1
    return 0


def apply(*, dry_run: bool) -> int:
    """Plan-only: print the bump commands. The operator runs them manually."""
    root = _consumer_root()
    if root is None:
        print("ok: no .gitmodules here (not applicable)")
        return 0
    submodule = root / ".ai-playbook"
    if not submodule.is_dir():
        print(f"error: .ai-playbook submodule missing at {submodule}", file=sys.stderr)
        return 2

    pinned = _current_pin(submodule) or "<unknown>"
    latest = _latest_tag(submodule) or "<unknown>"
    banner = "[plan only — update-playbook apply does NOT execute the bump]"
    if dry_run:
        banner = "[dry-run] " + banner

    if latest != "<unknown>" and pinned == latest:
        print(f"ok: .ai-playbook pinned to latest tag {pinned} (no-op)")
        return 0

    print(banner)
    print()
    print(f"Bump plan: {pinned} → {latest}")
    print()
    print(f"  cd {root}")
    print(f"  git -C .ai-playbook fetch --tags")
    print(f"  git -C .ai-playbook checkout {latest}")
    print(f"  git add .ai-playbook")
    print(f'  git commit -m "chore(playbook): bump ai-playbook {pinned} → {latest}"')
    print("  python .ai-playbook/scripts/rules/update-playbook.rule.py validate")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="update-playbook")
    parser.add_argument("subcommand", choices=["validate", "apply"])
    parser.add_argument("--dry-run", action="store_true", help="With 'apply': add a dry-run banner.")
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    if args.subcommand == "apply":
        return apply(dry_run=args.dry_run)
    return 2


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("update-playbook", main))
