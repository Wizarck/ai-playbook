"""L1 hardrule: skills-sync (paired with docs/rules/skills-sync.rule.md).

Verifies that a consumer repository which uses Claude Code skills reflects
the playbook's skill registry under `.claude/skills/`. The exact transport
(symlink on POSIX, directory copy on Windows via `materialise_skills.py`)
is unspecified — the invariant is that AT LEAST ONE subdirectory under the
consumer's `.claude/skills/` matches a skill slug present in
`.ai-playbook/skills/`.

CLI:
    python scripts/rules/skills-sync.rule.py validate
    python scripts/rules/skills-sync.rule.py apply [--dry-run]

Exit codes:
    0 — mirror reflects at least one playbook skill, OR no `.claude/skills/`
        (consumer opted out of Claude Code skills entirely).
    1 — `.claude/skills/` exists but contains no recognisable playbook skill,
        OR `apply` cannot remediate (materialise_skills.py absent).
    2 — fatal (no consumer root, unreadable filesystem).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SKIP_ENV = "AIPLAYBOOK_SKILLS_SYNC_SKIP"
CLAUDE_SKILLS_REL = Path(".claude") / "skills"
PLAYBOOK_SKILLS_REL = Path(".ai-playbook") / "skills"
MATERIALISER_REL = Path(".ai-playbook") / "scripts" / "materialise_skills.py"


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(f"   OVERRIDE: {SKIP_ENV}=1", file=sys.stderr)


def _consumer_root(cwd: Path | None = None) -> Path | None:
    """Locate the consumer root: nearest ancestor containing AGENTS.md."""
    cur = (cwd or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / "AGENTS.md").is_file():
            return p
    return None


def _playbook_skill_slugs(root: Path) -> set[str]:
    """Return the set of skill slugs declared by the playbook submodule.

    A "skill slug" is the immediate subdirectory name under
    `.ai-playbook/skills/` that contains a `SKILL.md` file. Returns an
    empty set when the submodule directory is missing.
    """
    src = root / PLAYBOOK_SKILLS_REL
    if not src.is_dir():
        return set()
    out: set[str] = set()
    for child in src.iterdir():
        if child.is_dir() and (child / "SKILL.md").is_file():
            out.add(child.name)
    return out


def _mirrored_skill_names(consumer_skills_dir: Path) -> set[str]:
    """Names of immediate subdirectories under the consumer's `.claude/skills/`.

    Each subdirectory is considered a candidate mirror; whether it is a
    symlink (POSIX) or a real directory copy (Windows) does not matter —
    `Path.is_dir()` follows symlinks. The directory entry alone is the
    signal.
    """
    if not consumer_skills_dir.is_dir():
        return set()
    return {child.name for child in consumer_skills_dir.iterdir() if child.is_dir()}


def validate(cwd: Path | None = None) -> int:
    if os.environ.get(SKIP_ENV):
        return 0
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2

    claude_skills = root / CLAUDE_SKILLS_REL
    if not claude_skills.is_dir():
        # Consumer opted out of Claude Code skills entirely — not applicable.
        return 0

    playbook_slugs = _playbook_skill_slugs(root)
    if not playbook_slugs:
        # Playbook submodule not initialised here — can't decide drift either way.
        # Treat as not-applicable rather than failing the rule (install-playbook
        # is the rule that catches a missing submodule).
        return 0

    mirrored = _mirrored_skill_names(claude_skills)
    if not (mirrored & playbook_slugs):
        _emit_error(
            why=".claude/skills/ exists but mirrors no playbook skills",
            where=str(claude_skills),
            fix=(
                "run `python .ai-playbook/scripts/rules/skills-sync.rule.py apply` "
                "(invokes materialise_skills.py); on Windows ensure the script "
                "ran without errors."
            ),
        )
        return 1

    return 0


def apply(*, dry_run: bool, cwd: Path | None = None) -> int:
    """Invoke `materialise_skills.py` when present; otherwise instruct manual fix.

    Idempotent: `materialise_skills.py` short-circuits on fingerprint equality,
    so re-running on a converged state produces zero filesystem mutations and
    exits 0.
    """
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2

    materialiser = root / MATERIALISER_REL
    if not materialiser.is_file():
        print(
            "manual fix: materialise_skills.py is not present under "
            f"{materialiser}. See "
            "docs/concepts/skills-distribution.md for how to populate "
            ".claude/skills/ for this consumer.",
            file=sys.stderr,
        )
        return 1

    cmd = [sys.executable, str(materialiser), "--consumer", str(root)]
    if dry_run:
        cmd.append("--dry-run")
        print(f"[dry-run] would invoke: {' '.join(cmd)}")
        # Still run the underlying script in its own dry-run mode so the
        # operator sees the plan; the script does not mutate the FS in that
        # mode, so dry-run parity is preserved.

    try:
        proc = subprocess.run(cmd, check=False, cwd=str(root))
    except OSError as exc:
        print(f"error: cannot invoke materialise_skills.py: {exc}", file=sys.stderr)
        return 2

    if proc.returncode == 0:
        return 0
    if proc.returncode == 2:
        # Source missing — surface as fatal, not violation.
        return 2
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skills-sync")
    parser.add_argument("subcommand", choices=["validate", "apply"])
    parser.add_argument("--dry-run", action="store_true", help="With 'apply': print plan, mutate nothing.")
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    if args.subcommand == "apply":
        return apply(dry_run=args.dry_run)
    return 2


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("skills-sync", main))
