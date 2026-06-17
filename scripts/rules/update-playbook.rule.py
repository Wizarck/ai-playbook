"""L1 hardrule: update-playbook (paired with docs/rules/update-playbook.rule.md).

Verifies that the `.ai-playbook/` submodule pin advances only to a semver
tag (`vX.Y.Z`) and never regresses to an older tag. The `apply` subcommand is
plan-only by default (prints the bump commands); pass `--execute` to perform
the bump (fetch + checkout latest tag + re-pin `inherits_from` in AGENTS.md +
stage both). It deliberately does NOT commit — run the reconcile
(`bootstrap.py --update`) first, then commit everything together.

CLI:
    python scripts/rules/update-playbook.rule.py validate
    python scripts/rules/update-playbook.rule.py apply [--dry-run]
    python scripts/rules/update-playbook.rule.py apply --execute [--dry-run]

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


def _repin_inherits_from(agents_md: Path, new_tag: str) -> bool:
    """Rewrite the `…/ai-playbook@vX.Y.Z` pin in AGENTS.md to ``new_tag``.

    Returns True if the file changed. Scoped to the ai-playbook inherits_from
    line so other ``@vX`` occurrences are untouched.
    """
    if not agents_md.is_file():
        return False
    text = agents_md.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r"(github\.com/[\w.\-]+/ai-playbook@)v\d+\.\d+\.\d+",
        rf"\g<1>{new_tag}",
        text,
    )
    if n == 0 or new_text == text:
        return False
    agents_md.write_text(new_text, encoding="utf-8")
    return True


def _execute_bump(root: Path, submodule: Path, pinned: str, latest: str, *, dry_run: bool) -> int:
    """Perform the bump: fetch + checkout + re-pin AGENTS.md + stage. No commit."""
    if dry_run:
        print(f"[dry-run] would bump .ai-playbook {pinned} → {latest}, "
              "re-pin inherits_from in AGENTS.md, and stage both.")
        return 0
    try:
        subprocess.check_call(
            ["git", "-C", str(submodule), "fetch", "--tags", "--quiet"], timeout=60
        )
        subprocess.check_call(
            ["git", "-C", str(submodule), "checkout", "--quiet", latest], timeout=60
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"error: git bump failed: {exc}", file=sys.stderr)
        return 2

    agents = root / "AGENTS.md"
    repinned = _repin_inherits_from(agents, latest)

    try:
        subprocess.check_call(["git", "-C", str(root), "add", ".ai-playbook"], timeout=30)
        if repinned:
            subprocess.check_call(["git", "-C", str(root), "add", "AGENTS.md"], timeout=30)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"warning: bump applied but `git add` failed: {exc}", file=sys.stderr)

    print(f"✅ bumped .ai-playbook {pinned} → {latest}")
    print(f"   inherits_from in AGENTS.md: {'re-pinned' if repinned else 'no change'}")
    print("   next (reconcile + verify, then commit in ONE commit):")
    print(f"     python .ai-playbook/scripts/bootstrap.py --update --path {root}")
    print("     (cd .ai-playbook && python -m scripts.doctor)")
    print(f'     git -C {root} commit -m "chore(playbook): bump ai-playbook {pinned} → {latest}"')
    return 0


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


def apply(*, dry_run: bool, execute: bool = False) -> int:
    """Bump the pin. Plan-only by default; ``execute=True`` performs the bump."""
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

    if latest != "<unknown>" and pinned == latest:
        print(f"ok: .ai-playbook pinned to latest tag {pinned} (no-op)")
        return 0

    if execute:
        if latest == "<unknown>":
            print("error: could not resolve latest tag from origin", file=sys.stderr)
            return 2
        return _execute_bump(root, submodule, pinned, latest, dry_run=dry_run)

    banner = "[plan only — pass --execute to perform the bump]"
    if dry_run:
        banner = "[dry-run] " + banner

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
    parser.add_argument("--dry-run", action="store_true", help="With 'apply': add a dry-run banner / preview.")
    parser.add_argument(
        "--execute", action="store_true",
        help="With 'apply': perform the bump (fetch+checkout+re-pin+stage) instead of printing the plan.",
    )
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    if args.subcommand == "apply":
        return apply(dry_run=args.dry_run, execute=args.execute)
    return 2


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("update-playbook", main))
