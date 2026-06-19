"""L1 hardrule: pre-commit-hooks (paired with docs/rules/pre-commit-hooks.rule.md).

Verifies that a consumer's `.pre-commit-config.yaml` declares the ai-playbook
hooks bundle — either as a remote `repo: https://github.com/Wizarck/ai-playbook`
entry or as a `repo: local` block invoking the playbook's individual hooks.

`apply` appends a canonical block to the existing file. The append-only
strategy (text-line append, not YAML rewrite) preserves user comments,
formatting, and unrelated hooks intact — which matters more than canonical
YAML output for a config file that is hand-tuned per-project.

CLI:
    python scripts/rules/pre-commit-hooks.rule.py validate
    python scripts/rules/pre-commit-hooks.rule.py apply [--dry-run]

Exit codes:
    0 — bundle present, OR pre-commit not in use here.
    1 — bundle missing.
    2 — fatal (no readable consumer root, or unreadable config file).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SKIP_ENV = "AIPLAYBOOK_PRE_COMMIT_HOOKS_SKIP"
PLAYBOOK_REPO_URL = "https://github.com/Wizarck/ai-playbook"
PLAYBOOK_SUBSTRING = "ai-playbook"


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(f"   OVERRIDE: {SKIP_ENV}=1", file=sys.stderr)


def _consumer_root(cwd: Path | None = None) -> Path | None:
    """Locate the consumer root: directory containing AGENTS.md."""
    cur = (cwd or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / "AGENTS.md").is_file():
            return p
    return None


def _pre_commit_in_use(root: Path) -> bool:
    """Heuristic: `.pre-commit-config.yaml` exists at root."""
    return (root / ".pre-commit-config.yaml").is_file()


def _config_path(root: Path) -> Path:
    return root / ".pre-commit-config.yaml"


def _declares_playbook(config_text: str) -> bool:
    """Substring match for `ai-playbook` inside any non-comment line of the YAML.

    Accepts BOTH forms:
      - Remote: `- repo: https://github.com/Wizarck/ai-playbook`
      - Local : `entry: python -m scripts.<hook>` with `.ai-playbook/scripts/` path
    The local form is detected by the `ai-playbook` substring in entry paths.
    Comment-only references (`# ai-playbook is great`) are ignored.
    """
    for raw_line in config_text.splitlines():
        # Strip inline comments — anything after a `#` not inside a quoted string.
        # Pre-commit config rarely uses quoted strings with `#`, so a simple split
        # is correct enough for substring detection.
        code_part = raw_line.split("#", 1)[0]
        if PLAYBOOK_SUBSTRING in code_part:
            return True
    return False


def _detect_pinned_rev(root: Path) -> str:
    """Read the consumer's pinned ai-playbook submodule tag. Fallback: `HEAD`."""
    submodule = root / ".ai-playbook"
    if not submodule.is_dir():
        return "HEAD"
    try:
        out = subprocess.check_output(
            ["git", "-C", str(submodule), "describe", "--tags", "--exact-match"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        tag = out.strip()
        return tag or "HEAD"
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "HEAD"


def _canonical_block(rev: str) -> str:
    """The block appended by `apply`. Leading blank line + trailing newline."""
    return (
        "\n"
        f"  - repo: {PLAYBOOK_REPO_URL}\n"
        f"    rev: {rev}\n"
        "    hooks:\n"
        "      - id: ai-playbook\n"
    )


def validate(cwd: Path | None = None) -> int:
    if os.environ.get(SKIP_ENV):
        return 0
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2
    if not _pre_commit_in_use(root):
        return 0  # not applicable for this consumer

    path = _config_path(root)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _emit_error(why=str(exc), where=str(path), fix="check file permissions.")
        return 2

    if not _declares_playbook(text):
        _emit_error(
            why=".pre-commit-config.yaml does not declare ai-playbook hooks bundle",
            where=str(path),
            fix="run `python .ai-playbook/scripts/rules/pre-commit-hooks.rule.py apply`.",
        )
        return 1

    return 0


def apply(*, dry_run: bool, cwd: Path | None = None) -> int:
    """Append the canonical ai-playbook block to `.pre-commit-config.yaml`. Idempotent."""
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2

    path = _config_path(root)
    if not path.is_file():
        _emit_error(
            why=".pre-commit-config.yaml missing",
            where=str(path),
            fix="bootstrap pre-commit first (`pip install pre-commit && pre-commit install`).",
        )
        return 1

    try:
        existing = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 2

    if _declares_playbook(existing):
        print(f"ok: {path} already declares ai-playbook bundle (no-op)")
        return 0

    rev = _detect_pinned_rev(root)
    block = _canonical_block(rev)

    if dry_run:
        print(f"[dry-run] would append to {path} (rev={rev}):")
        print(block, end="")
        return 0

    # Ensure trailing newline before append so the block starts on its own line.
    new_text = existing
    if new_text and not new_text.endswith("\n"):
        new_text += "\n"
    new_text += block

    try:
        path.write_text(new_text, encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write {path}: {exc}", file=sys.stderr)
        return 2
    print(f"appended ai-playbook block to {path} (rev={rev})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pre-commit-hooks")
    parser.add_argument("subcommand", choices=["validate", "apply"])
    parser.add_argument("--dry-run", action="store_true", help="With 'apply': print plan, mutate nothing.")
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    if args.subcommand == "apply":
        return apply(dry_run=args.dry_run)
    return 2


if __name__ == "__main__":
    # File-path invocation from a consumer root: put the playbook root on
    # sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("pre-commit-hooks", main))
