"""L1 hardrule: install-playbook (paired with docs/rules/install-playbook.rule.md).

Verifies that the consumer repository has `.ai-playbook/` mounted as a
Git submodule pinned to a semver tag. The `apply` subcommand is plan-only —
it prints the install commands but does not execute them, since submodule
installation requires a target tag and remote credentials the rule cannot
safely infer.

CLI:
    python scripts/rules/install-playbook.rule.py validate
    python scripts/rules/install-playbook.rule.py apply [--dry-run]

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
PLAYBOOK_REMOTE = "https://github.com/Wizarck/ai-playbook"


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


def apply(*, dry_run: bool) -> int:
    """Plan-only: print the install commands. The operator runs them manually."""
    root = _consumer_root()
    if root is None:
        print("ok: no .gitmodules here (not applicable; this is not a git repo with submodules yet)")
        return 0
    submodule = root / ".ai-playbook"
    if submodule.is_dir():
        # Already installed — defer to update-playbook for version bumps.
        print(f"ok: .ai-playbook already installed at {submodule} (no-op; see update-playbook for bumps)")
        return 0
    banner = "[plan only — install-playbook apply does NOT execute the install]"
    if dry_run:
        banner = "[dry-run] " + banner
    print(banner)
    print()
    print("Install plan: add .ai-playbook submodule")
    print()
    print(f"  cd {root}")
    print("  # Replace <TAG> with the desired semver tag (e.g. v0.20.0).")
    print(f"  git submodule add -b <TAG> {PLAYBOOK_REMOTE} .ai-playbook")
    print("  git config -f .gitmodules submodule..ai-playbook.update merge")
    print(f"  git -C .ai-playbook checkout <TAG>")
    print('  git commit -m "chore(playbook): install ai-playbook <TAG> as submodule"')
    print("  python .ai-playbook/scripts/rules/install-playbook.rule.py validate")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="install-playbook")
    parser.add_argument("subcommand", choices=["validate", "apply"])
    parser.add_argument("--dry-run", action="store_true", help="With 'apply': add a dry-run banner.")
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    if args.subcommand == "apply":
        return apply(dry_run=args.dry_run)
    return 2


if __name__ == "__main__":
    # Allow file-path invocation from a consumer root
    # (`python .ai-playbook/scripts/rules/install-playbook.rule.py …`) — put the
    # playbook root on sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("install-playbook", main))
