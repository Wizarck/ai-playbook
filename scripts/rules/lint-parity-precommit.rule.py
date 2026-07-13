"""L1 hardrule: lint-parity-precommit (paired with docs/rules/lint-parity-precommit.rule.md).

Verifies that linters gating the consumer's CI also run at pre-commit with the
same pin. v1 scope: ruff (the Python linter every playbook consumer's backend
CI runs). A linter that only exists in CI is a linter developers discover
post-push; without branch protection the red merges and becomes ambient debt
(geeplo 2026-07-13: a wave merged with 41 ruff errors nobody saw locally).

`apply` appends the canonical ruff-pre-commit block to `.pre-commit-config.yaml`
using the pin detected from the CI workflows (append-only, preserving user
comments and formatting — same strategy as pre-commit-hooks.rule.py).

CLI:
    python scripts/rules/lint-parity-precommit.rule.py validate
    python scripts/rules/lint-parity-precommit.rule.py apply [--dry-run] [--rev vX.Y.Z]

Exit codes:
    0 — parity holds, OR rule not applicable (no workflows, no ruff in CI,
        or repo does not use pre-commit at all).
    1 — ruff gates CI but is absent from .pre-commit-config.yaml.
    2 — fatal (no consumer root, unreadable files).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

SKIP_ENV = "AIPLAYBOOK_LINT_PARITY_PRECOMMIT_SKIP"
RUFF_PRECOMMIT_REPO = "https://github.com/astral-sh/ruff-pre-commit"

# A ruff invocation that GATES (check / format --check), on a non-comment line.
_RUFF_CI_RE = re.compile(r"\bruff\b(?:\s+\S+)*\s+(?:check|format)\b")
# A CI pin: `ruff==0.9.3`, `ruff == 0.9.3`, or `ruff@0.9.3`.
_RUFF_PIN_RE = re.compile(r"\bruff\s*(?:==|@)\s*v?([0-9][\w.]*)")
# A pre-commit rev line.
_REV_RE = re.compile(r"^\s*rev:\s*['\"]?v?([\w.]+)['\"]?", re.MULTILINE)


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


def _workflow_texts(root: Path) -> list[tuple[Path, str]]:
    wf_dir = root / ".github" / "workflows"
    if not wf_dir.is_dir():
        return []
    out: list[tuple[Path, str]] = []
    for path in sorted(wf_dir.glob("*.y*ml")):
        try:
            out.append((path, path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return out


def _noncomment_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        stripped = raw.split("#", 1)[0]
        if stripped.strip():
            lines.append(stripped)
    return lines


def _ruff_gates_ci(workflows: list[tuple[Path, str]]) -> Path | None:
    """Return the first workflow file whose non-comment lines invoke ruff check/format."""
    for path, text in workflows:
        for line in _noncomment_lines(text):
            if _RUFF_CI_RE.search(line):
                return path
    return None


def _ci_ruff_pin(workflows: list[tuple[Path, str]]) -> str | None:
    for _, text in workflows:
        for line in _noncomment_lines(text):
            m = _RUFF_PIN_RE.search(line)
            if m:
                return m.group(1)
    return None


def _precommit_has_ruff(config_text: str) -> bool:
    for line in _noncomment_lines(config_text):
        if "ruff-pre-commit" in line:
            return True
        # Local-hook form: `entry: ruff check` / `entry: python -m ruff`.
        if re.search(r"\bentry:.*\bruff\b", line) or re.search(r"\bid:\s*ruff\b", line):
            return True
    return False


def _precommit_ruff_rev(config_text: str) -> str | None:
    """rev of the ruff-pre-commit repo block, if present."""
    lines = config_text.splitlines()
    for i, line in enumerate(lines):
        if "ruff-pre-commit" in line.split("#", 1)[0]:
            for follow in lines[i + 1 : i + 4]:
                m = _REV_RE.search(follow)
                if m:
                    return m.group(1)
    return None


def _canonical_block(rev: str) -> str:
    return (
        "\n"
        "  # lint-parity-precommit (ai-playbook): ruff gates CI, so it runs here too.\n"
        f"  - repo: {RUFF_PRECOMMIT_REPO}\n"
        f"    rev: v{rev.lstrip('v')}\n"
        "    hooks:\n"
        "      - id: ruff\n"
        "        args: [--fix]\n"
    )


def validate(cwd: Path | None = None) -> int:
    if os.environ.get(SKIP_ENV) == "1":
        print(f"skip: {SKIP_ENV}=1")
        return 0

    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2

    workflows = _workflow_texts(root)
    gating = _ruff_gates_ci(workflows)
    if gating is None:
        print("ok: no ruff gate found in CI workflows (rule not applicable)")
        return 0

    config = root / ".pre-commit-config.yaml"
    if not config.is_file():
        print("ok: repo does not use pre-commit (pre-commit-hooks rule governs bootstrap)")
        return 0

    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"error: cannot read {config}: {exc}", file=sys.stderr)
        return 2

    if not _precommit_has_ruff(text):
        _emit_error(
            why=f"ruff gates CI ({gating.name}) but .pre-commit-config.yaml never runs it",
            where=str(config),
            fix="run `python .ai-playbook/scripts/rules/lint-parity-precommit.rule.py apply`.",
        )
        return 1

    ci_pin = _ci_ruff_pin(workflows)
    pc_rev = _precommit_ruff_rev(text)
    if ci_pin and pc_rev and ci_pin.lstrip("v") != pc_rev.lstrip("v"):
        print(
            f"warning: ruff pin drift — CI pins {ci_pin}, pre-commit rev is {pc_rev}; "
            "align them so laptop and CI disagree on nothing.",
            file=sys.stderr,
        )
    return 0


def apply(*, dry_run: bool, rev: str | None = None, cwd: Path | None = None) -> int:
    """Append the canonical ruff block to `.pre-commit-config.yaml`. Idempotent."""
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2

    config = root / ".pre-commit-config.yaml"
    if not config.is_file():
        _emit_error(
            why=".pre-commit-config.yaml missing",
            where=str(config),
            fix="bootstrap pre-commit first (`pip install pre-commit && pre-commit install`).",
        )
        return 1

    try:
        existing = config.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"error: cannot read {config}: {exc}", file=sys.stderr)
        return 2

    if _precommit_has_ruff(existing):
        print(f"ok: {config} already runs ruff (no-op)")
        return 0

    pin = rev or _ci_ruff_pin(_workflow_texts(root))
    if not pin:
        _emit_error(
            why="cannot determine the ruff rev to pin (CI does not pin ruff)",
            where=str(config),
            fix="pin ruff in CI (`pip install ruff==X.Y.Z`) or pass --rev vX.Y.Z.",
        )
        return 1

    block = _canonical_block(pin)
    if dry_run:
        print(f"[dry-run] would append to {config} (rev=v{pin.lstrip('v')}):")
        print(block, end="")
        return 0

    new_text = existing
    if new_text and not new_text.endswith("\n"):
        new_text += "\n"
    new_text += block
    try:
        config.write_text(new_text, encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write {config}: {exc}", file=sys.stderr)
        return 2
    print(f"appended ruff-pre-commit block to {config} (rev=v{pin.lstrip('v')})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lint-parity-precommit")
    parser.add_argument("subcommand", choices=["validate", "apply"])
    parser.add_argument("--dry-run", action="store_true", help="With 'apply': print plan, mutate nothing.")
    parser.add_argument("--rev", help="With 'apply': explicit ruff-pre-commit rev (overrides CI pin detection).")
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    if args.subcommand == "apply":
        return apply(dry_run=args.dry_run, rev=args.rev)
    return 2


if __name__ == "__main__":
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("lint-parity-precommit", main))
