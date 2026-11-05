"""L1 hardrule: pre-commit-hooks (paired with docs/rules/pre-commit-hooks.rule.md).

Verifies that a consumer's `.pre-commit-config.yaml` declares the ai-playbook
hooks bundle — either as a remote `repo: https://github.com/Wizarck/ai-playbook`
entry or as a `repo: local` block invoking the playbook's individual hooks.

`apply` splices a canonical `repo: local` block at the end of the `repos:`
sequence, re-indented to the file's own style (text insert, not YAML rewrite),
so user comments, formatting, and unrelated hooks survive intact. The result
must parse with `yaml.safe_load` and contain the new repo, otherwise nothing is
written (exit 2). The block runs exactly the gates `.pre-commit-hooks.yaml`
exports, by path from the consumer's `.ai-playbook` submodule and against the
consumer's own files: the exported `python -m scripts.<x>` entries only resolve
where the playbook is importable, and default to the playbook's own AGENTS.md
and docs/.

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
import re
import sys
from pathlib import Path

SKIP_ENV = "AIPLAYBOOK_PRE_COMMIT_HOOKS_SKIP"
PLAYBOOK_SUBSTRING = "ai-playbook"
# Must equal the ids exported by the playbook's `.pre-commit-hooks.yaml`
# (cross-checked by tests); an id pre-commit cannot find fails every commit.
EXPORTED_HOOK_IDS = (
    "validate-pairing",
    "check-doc-language",
    "check-link-integrity",
    "check-agents-md-size",
)
# id -> (name, script under .ai-playbook/scripts/, consumer-relative args,
# files, pass_filenames); files/pass_filenames mirror `.pre-commit-hooks.yaml`.
_LOCAL_HOOKS = {
    "validate-pairing": (
        "validate-pairing (rule slug + paired_hardrule cross-reference)",
        "validate_pairing.py", "--root .", r"^(docs/rules/|scripts/rules/|tests/test_).*$", False,
    ),
    "check-doc-language": (
        "check-doc-language (ENGLISH-only docs/ enforcement)",
        "check_doc_language.py", "", r"^docs/.*\.md$", True,
    ),
    "check-link-integrity": (
        "check-link-integrity (broken markdown links under docs/)",
        "check_link_integrity.py", "--root . docs/", r"^docs/.*\.md$", False,
    ),
    "check-agents-md-size": (
        "check-agents-md-size (D14, 500-line cap)",
        "check_agents_md_size.py", "--file AGENTS.md", r"^AGENTS\.md$", False,
    ),
}
# `apply` up to v0.24.1 wrote this id under the remote repo; it was never
# exported. Line match: the fallback for configs that are not valid YAML.
_BOGUS_ID_RE = re.compile(r"^\s*-\s*id:\s*['\"]?ai-playbook['\"]?\s*(#.*)?$", re.MULTILINE)


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
      - Local : `entry: ... .ai-playbook/scripts/<hook>.py` (the block `apply` inserts)
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


def _lists_unexported_id(config_text: str) -> bool:
    """True when a remote ai-playbook repo item lists `- id: ai-playbook`.

    Only remote items count: a `repo: local` hook may use any id. A file that
    is not parseable YAML falls back to the line match.
    """
    try:
        import yaml
    except ImportError:
        return bool(_BOGUS_ID_RE.search(config_text))
    try:
        data = yaml.safe_load(config_text)
    except yaml.YAMLError:
        return bool(_BOGUS_ID_RE.search(config_text))
    repos = data.get("repos") if isinstance(data, dict) else None
    for item in repos if isinstance(repos, list) else []:
        if not isinstance(item, dict) or PLAYBOOK_SUBSTRING not in str(item.get("repo", "")):
            continue
        if any(isinstance(h, dict) and h.get("id") == "ai-playbook" for h in item.get("hooks") or []):
            return True
    return False


def _entry(script: str, args: str, pass_filenames: bool) -> str:
    """Shim like the template's: skip while the script is missing, else propagate its exit code."""
    path = f".ai-playbook/scripts/{script}"
    cmd = f"python {path}" + (f" {args}" if args else "")
    if pass_filenames:
        return f"bash -c '[ ! -f {path} ] || {cmd} \"$@\"' --"
    return f"bash -c '[ ! -f {path} ] || {cmd}'"


def _canonical_block() -> str:
    """The repo item `apply` inserts (canonical column-0 form)."""
    out = [
        "# ai-playbook gates (pre-commit-hooks rule), run from the pinned .ai-playbook submodule.\n",
        "- repo: local\n",
        "  hooks:\n",
    ]
    for hid in EXPORTED_HOOK_IDS:
        name, script, args, files, pass_filenames = _LOCAL_HOOKS[hid]
        out += [
            f"    - id: {hid}\n",
            f"      name: {name}\n",
            f"      entry: {_entry(script, args, pass_filenames)}\n",
            "      language: system\n",
            f"      files: {files}\n",
            f"      pass_filenames: {'true' if pass_filenames else 'false'}\n",
        ]
    return "".join(out)


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

    if _lists_unexported_id(text):
        _emit_error(
            why="hook id `ai-playbook` is not exported by the playbook (pre-commit fails every commit)",
            where=str(path),
            fix="replace that remote ai-playbook repo item with the `repo: local` block in "
            ".ai-playbook/docs/rules/pre-commit-hooks.rule.md (after deleting the item, `apply` "
            "inserts the block if nothing else in the file mentions ai-playbook).",
        )
        return 1

    return 0


def apply(*, dry_run: bool, cwd: Path | None = None) -> int:
    """Insert the canonical ai-playbook repo into `.pre-commit-config.yaml`. Idempotent."""
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
        # Bytes, not read_text/write_text: keep the file's own line endings
        # (insert_repo matches CRLF) instead of rewriting every line.
        existing = path.read_bytes().decode("utf-8", errors="replace")
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 2

    if _declares_playbook(existing):
        print(f"ok: {path} already declares ai-playbook bundle (no-op)")
        return 0

    block = _canonical_block()

    if dry_run:
        print(f"[dry-run] would insert into {path}:")
        print(block, end="")
        return 0

    from scripts.rules._precommit_yaml import insert_repo

    try:
        new_text = insert_repo(existing, block, repo_url="local", hook_ids=list(EXPORTED_HOOK_IDS))
    except ValueError as exc:
        _emit_error(
            why=f"cannot safely insert the ai-playbook repo ({exc}); nothing written",
            where=str(path),
            fix="add this item under `repos:` by hand:\n" + block,
        )
        return 2

    try:
        path.write_bytes(new_text.encode("utf-8"))
    except OSError as exc:
        print(f"error: cannot write {path}: {exc}", file=sys.stderr)
        return 2
    print(f"inserted the ai-playbook gates into {path}")
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
