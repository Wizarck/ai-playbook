"""Single-source skills materialiser — ai-playbook v0.17.0.

Reads `<consumer>/.ai-playbook/skills/` (the single source of truth) and
mirrors it to three gitignored destinations at the consumer side:

    <consumer>/skills/
    <consumer>/.claude/skills/
    <consumer>/.gemini/skills/

Idempotent: re-running with no upstream changes produces zero filesystem
modifications (fingerprint-equal targets are skipped). Orphan removal:
files present at a target but absent in the source are wiped (the target is
fully regenerated via shutil.rmtree + shutil.copytree when fingerprints
differ).

Contract: `docs/concepts/skills-distribution.md` v2.0.0 (single-source design).
Architectural decisions: D1 (single-source), D2 (scripts not mirrored),
D17 (skills perpendicular rules).

Supersedes:
- `scripts/_skills_materialiser.py` (multi-source RFC-0001; deleted in v0.17.0)
- `scripts/propagate_skills_bump.py` (per-source propagation; deleted)
- `scripts/validate_skills_mirror.py` (drift validator; obsoleted by the
  hash-equality short-circuit in this script)

CLI
---
    python -m scripts.materialise_skills                # default consumer = cwd
    python -m scripts.materialise_skills --consumer <p> # override consumer root
    python -m scripts.materialise_skills --source <p>   # override source path
    python -m scripts.materialise_skills --dry-run      # report-only
    python -m scripts.materialise_skills --quiet        # suppress stdout

Exit codes
----------
    0  success (or no-op).
    1  filesystem write failure (target dir not writable).
    2  source missing (run `git submodule update --init .ai-playbook` first).
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import shutil
import sys
from pathlib import Path

# UTF-8 stdio — Windows cp1252 console safety.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts._enforce_state import disabled_skills as _disabled_skills_state  # noqa: E402


SCRIPT_BASENAME = "materialise_skills.py"
SOURCE_REL = Path(".ai-playbook") / "skills"
MIRROR_RELS = (
    Path("skills"),
    Path(".claude") / "skills",
    Path(".gemini") / "skills",
)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class SkillsMaterialisationResult:
    """Outcome of a single materialise_skills call."""

    skills_total: int = 0
    mirrors_rewritten: int = 0
    mirrors_in_sync: int = 0
    errors: list[str] = dataclasses.field(default_factory=list)
    summary: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# Canonical error emission (mirrors error-message-standard.md)
# ---------------------------------------------------------------------------


def _emit_error(*, why: str, where: str, fix: str, override: str | None = None) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(f"   OVERRIDE: {override if override else 'none'}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Fingerprint (idempotency)
# ---------------------------------------------------------------------------


def _dir_fingerprint(root: Path, *, exclude_top_dirs: frozenset[str] | set[str] | None = None) -> str:
    """Stable sha256 over (relative-path, file-bytes) pairs of a tree.

    Returns empty string for missing / non-directory roots. Sort order is
    forward-slash relative path, ensuring cross-platform stability.

    If ``exclude_top_dirs`` is provided, files whose path starts with one of
    those top-level directory names are skipped from the digest — used to
    derive an "enforcement-aware" source fingerprint that matches what the
    target will look like after disabled-skill filtering.
    """
    if not root.is_dir():
        return ""
    excludes = exclude_top_dirs or frozenset()
    h = hashlib.sha256()
    for p in sorted(root.rglob("*"), key=lambda x: x.as_posix()):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            if excludes:
                top = rel.split("/", 1)[0]
                if top in excludes:
                    continue
            h.update(rel.encode("utf-8"))
            h.update(b"\0")
            h.update(p.read_bytes())
            h.update(b"\0")
    return h.hexdigest()


def _count_skill_dirs(root: Path, *, exclude: frozenset[str] | set[str] | None = None) -> int:
    """Number of immediate children of root that contain a SKILL.md file.

    Optionally exclude top-level slugs (used to report the *enforced* skill
    count after filtering out disabled entries).
    """
    if not root.is_dir():
        return 0
    excludes = exclude or frozenset()
    return sum(
        1
        for child in root.iterdir()
        if child.is_dir()
        and child.name not in excludes
        and (child / "SKILL.md").is_file()
    )


def _make_ignore_filter(source: Path, disabled: set[str]):
    """Return a ``shutil.copytree`` ``ignore=`` callable that skips disabled
    skill directories at the SOURCE TOP LEVEL only.

    Skipping only at the top level avoids accidentally excluding nested
    files that happen to share a name with a disabled slug.
    """
    source_resolved = source.resolve()

    def _ignore(dirpath: str, names: list[str]) -> list[str]:
        if not disabled:
            return []
        try:
            current = Path(dirpath).resolve()
        except OSError:
            return []
        if current == source_resolved:
            return [n for n in names if n in disabled]
        return []

    return _ignore


# ---------------------------------------------------------------------------
# Single-mirror sync
# ---------------------------------------------------------------------------


def _sync_one(
    source: Path,
    target: Path,
    *,
    dry_run: bool,
    quiet: bool,
    disabled: set[str] | None = None,
) -> tuple[bool, str | None]:
    """Sync source -> target. Returns (rewritten, error).

    rewritten=True when filesystem was mutated; False when fingerprint matched.
    error is None on success, a string on failure (caller appends to result).

    If ``disabled`` is provided (non-empty), the listed top-level skill
    directories are filtered out of the materialised target. The source
    fingerprint is computed with the same exclusions so a no-op stays a
    no-op when only the disabled set changes-and-changes-back.
    """
    disabled = disabled or set()
    src_fp = _dir_fingerprint(source, exclude_top_dirs=disabled)
    tgt_fp = _dir_fingerprint(target)
    enforced_count = _count_skill_dirs(source, exclude=disabled)
    if src_fp and src_fp == tgt_fp:
        if not quiet:
            print(f"  · {target}: in sync ({enforced_count} skills)")
        return False, None

    if dry_run:
        action = "would rewrite" if tgt_fp else "would create"
        if not quiet:
            print(f"  (dry-run) {target}: {action} ({enforced_count} skills)")
        return True, None

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            # rmtree -> orphan removal; copytree -> fresh state.
            shutil.rmtree(target)
        if disabled:
            shutil.copytree(source, target, ignore=_make_ignore_filter(source, disabled))
        else:
            shutil.copytree(source, target)
    except OSError as exc:
        return True, f"{target}: {exc}"

    if not quiet:
        print(f"  ✓ {target}: rewritten ({_count_skill_dirs(target)} skills)")
    return True, None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def materialise_skills(
    consumer_dir: Path,
    *,
    source_override: Path | None = None,
    dry_run: bool = False,
    quiet: bool = False,
) -> SkillsMaterialisationResult:
    """Materialise `.ai-playbook/skills/` into the three consumer mirrors.

    Parameters
    ----------
    consumer_dir : Path
        Root of the consumer project (where `.ai-playbook/` is mounted).
    source_override : Path | None
        Override the default source location. Useful for tests + non-submodule
        consumers (e.g. local development checkout).
    dry_run : bool
        Report planned actions without modifying the filesystem.
    quiet : bool
        Suppress per-target progress lines.

    Returns
    -------
    SkillsMaterialisationResult
        Counts + collected error strings. Inspect `.errors` to decide whether
        the materialisation succeeded.
    """
    consumer_dir = consumer_dir.resolve()
    result = SkillsMaterialisationResult()

    source = (source_override or (consumer_dir / SOURCE_REL)).resolve()
    if not source.is_dir():
        _emit_error(
            why=f"source skills directory not found at {source}",
            where=f"{SCRIPT_BASENAME}:source",
            fix="run `git submodule update --init .ai-playbook` from the consumer "
                "root (or pass --source <path> for a non-submodule checkout).",
        )
        result.errors.append(f"source missing: {source}")
        return result

    disabled = _disabled_skills_state(consumer_dir)
    skills_total = _count_skill_dirs(source, exclude=disabled)
    result.skills_total = skills_total

    if not quiet:
        rel_source = (
            str(source.relative_to(consumer_dir))
            if source.is_relative_to(consumer_dir)
            else str(source)
        )
        action = "Would sync" if dry_run else "Syncing"
        suffix = ""
        if disabled:
            suffix = f" ({len(disabled)} skill(s) disabled via .ai-playbook-state/skills-enforce.json)"
        print(
            f"{action} skills from {rel_source}/ "
            f"({skills_total} skills) to {len(MIRROR_RELS)} mirror(s){suffix}"
        )

    for mirror_rel in MIRROR_RELS:
        target = consumer_dir / mirror_rel
        rewritten, err = _sync_one(
            source, target, dry_run=dry_run, quiet=quiet, disabled=disabled,
        )
        if err is not None:
            result.errors.append(err)
            continue
        if rewritten:
            result.mirrors_rewritten += 1
        else:
            result.mirrors_in_sync += 1

    if result.errors:
        result.summary = (
            f"materialisation failed: {len(result.errors)} error(s)."
        )
        return result

    if result.mirrors_rewritten == 0:
        result.summary = (
            f"all {len(MIRROR_RELS)} mirror(s) in sync ({skills_total} skills); no-op."
        )
    else:
        result.summary = (
            f"rewrote {result.mirrors_rewritten} mirror(s) "
            f"({skills_total} skills); "
            f"{result.mirrors_in_sync} in sync."
        )
    if not quiet:
        print(f"Done. {result.summary}")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="materialise_skills",
        description=__doc__.split("\n\n", 1)[0],
    )
    parser.add_argument(
        "--consumer",
        type=Path,
        default=None,
        help="Consumer root (defaults to cwd).",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Source skills directory override "
        "(defaults to <consumer>/.ai-playbook/skills/).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report planned writes; do not touch the filesystem.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-target progress lines.",
    )
    args = parser.parse_args(argv)

    consumer_dir = (args.consumer or Path.cwd()).expanduser()
    result = materialise_skills(
        consumer_dir,
        source_override=args.source,
        dry_run=args.dry_run,
        quiet=args.quiet,
    )
    if not result.ok:
        # Exit code 2 when the source is missing; 1 for any other failure.
        if any(err.startswith("source missing:") for err in result.errors):
            return 2
        return 1
    return 0


__all__ = [
    "MIRROR_RELS",
    "SOURCE_REL",
    "SkillsMaterialisationResult",
    "materialise_skills",
]


if __name__ == "__main__":
    sys.exit(main())
