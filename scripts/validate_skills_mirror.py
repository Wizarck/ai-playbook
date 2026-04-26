"""Validate that `<consumer>/.claude/skills/` and `<consumer>/.gemini/skills/`
are byte-for-byte copies of `<consumer>/skills/`.

Pre-commit hook for RFC-0001 (skills distribution). The materialiser writes
mirrors via `shutil.copytree`; this script enforces that no manual edits
have drifted them away from the canonical `skills/` source-of-truth.

CLI
---
    python -m scripts.validate_skills_mirror [--consumer <path>] [--fix]

Behaviour
---------
- Without `--fix`: reports every divergent file path, exits 1 if any drift.
- With `--fix`: deletes + recopies the mirrors from `skills/`, exits 0.
- If the consumer has no `skills/` (pre-RFC-0001 migration) or no mirror
  dirs yet, the script is a silent no-op (exit 0). This means it can be
  safely landed BEFORE every consumer migrates.

Exit codes
----------
    0  all mirrors match (or no mirrors exist yet — pre-migration consumer).
    1  drift detected (and --fix not specified).
    2  consumer path invalid / missing.
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


SKILLS_SUBDIR = "skills"
MIRROR_SUBDIRS = (
    Path(".claude") / "skills",
    Path(".gemini") / "skills",
)


def _diff_dirs(left: Path, right: Path) -> list[str]:
    """Return list of relative paths that differ between left and right.

    Recursive, byte-by-byte (filecmp shallow=False). Includes files only on
    one side. Path strings are forward-slash normalised for cross-platform
    consistency.
    """
    out: list[str] = []

    def _walk(cmp: filecmp.dircmp, prefix: str) -> None:
        for name in cmp.left_only:
            out.append(f"{prefix}{name} (only in skills/)")
        for name in cmp.right_only:
            out.append(f"{prefix}{name} (only in mirror)")
        # Diff files (shallow=False forces content compare).
        diff_files = filecmp.cmpfiles(
            cmp.left, cmp.right, cmp.common_files, shallow=False
        )[1]
        for name in diff_files:
            out.append(f"{prefix}{name} (content differs)")
        for sub in cmp.common_dirs:
            _walk(filecmp.dircmp(cmp.left / sub, cmp.right / sub), f"{prefix}{sub}/")

    if not right.exists():
        return [f"<entire mirror missing>: {right}"]
    if not left.exists():
        return [f"<canonical skills/ missing>: {left}"]
    _walk(filecmp.dircmp(left, right), "")
    return out


def _emit_drift_report(consumer: Path, mirror_rel: Path, diffs: list[str]) -> None:
    print(
        f"❌ skills mirror drift detected at {consumer}/{mirror_rel}",
        file=sys.stderr,
    )
    print(
        "   FIX: re-run `python -m scripts.validate_skills_mirror "
        f"--consumer {consumer} --fix` (or "
        "`python .ai-playbook/scripts/bootstrap.py --refresh-skills`).",
        file=sys.stderr,
    )
    print("   OVERRIDE: none", file=sys.stderr)
    print("", file=sys.stderr)
    print("Detail:", file=sys.stderr)
    for d in diffs[:50]:
        print(f"  - {d}", file=sys.stderr)
    if len(diffs) > 50:
        print(f"  … and {len(diffs) - 50} more", file=sys.stderr)


def _regenerate(consumer: Path, mirror_rel: Path) -> None:
    src = consumer / SKILLS_SUBDIR
    dst = consumer / mirror_rel
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)


def validate_consumer(consumer: Path, *, fix: bool = False) -> int:
    """Run the validation against a single consumer dir.

    Returns the exit code (0 ok / 1 drift / 2 invalid path).
    """
    consumer = consumer.resolve()
    if not consumer.is_dir():
        print(
            f"❌ consumer path is not a directory: {consumer}\n"
            f"   FIX: pass --consumer <existing-consumer-root>.\n"
            f"   OVERRIDE: none",
            file=sys.stderr,
        )
        return 2

    skills_dir = consumer / SKILLS_SUBDIR
    if not skills_dir.is_dir():
        # Pre-migration consumer — no canonical skills/, hook is a no-op.
        return 0

    any_mirror_present = any(
        (consumer / rel).exists() for rel in MIRROR_SUBDIRS
    )
    if not any_mirror_present:
        # No mirrors yet — no-op (consumer might be mid-migration before
        # the materialiser has run).
        return 0

    drift = False
    for rel in MIRROR_SUBDIRS:
        mirror = consumer / rel
        if not mirror.exists():
            # One side present, one missing → that's drift.
            if fix:
                _regenerate(consumer, rel)
                continue
            _emit_drift_report(consumer, rel, [f"<entire mirror missing>: {mirror}"])
            drift = True
            continue

        diffs = _diff_dirs(skills_dir, mirror)
        if not diffs:
            continue
        if fix:
            _regenerate(consumer, rel)
            continue
        _emit_drift_report(consumer, rel, diffs)
        drift = True

    if drift:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="validate_skills_mirror",
        description=__doc__.split("\n\n", 1)[0],
    )
    p.add_argument(
        "--consumer", type=Path, default=None,
        help="Consumer root (defaults to cwd).",
    )
    p.add_argument(
        "--fix", action="store_true",
        help="Re-copy `skills/` to each mirror, silencing drift.",
    )
    # Pre-commit invokes the hook with file paths; we ignore them — we always
    # validate the whole tree.
    p.add_argument("paths", nargs="*", help=argparse.SUPPRESS)
    args = p.parse_args(argv)

    consumer = (args.consumer or Path.cwd()).expanduser()
    return validate_consumer(consumer, fix=args.fix)


if __name__ == "__main__":
    sys.exit(main())
