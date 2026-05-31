"""Single-source skills materialiser — additive, provenance-aware.

Reads `<consumer>/.ai-playbook/skills/` (the single source of truth) and
mirrors it to three gitignored destinations at the consumer side:

    <consumer>/skills/
    <consumer>/.claude/skills/
    <consumer>/.gemini/skills/

**Additive contract.** Materialisation synchronises only the skill directories
the playbook authored. A per-mirror installed-manifest
(`<consumer>/.ai-playbook-state/skills-manifest.json`, see
`scripts/_skills_manifest.py`) records which directories the playbook installed.
On each run the materialiser:

- creates/updates the playbook's desired skill directories (per-skill, only when
  the directory's content fingerprint differs),
- removes only the directories it previously installed that are no longer desired
  (source removal or disable),
- NEVER deletes or modifies a skill directory it did not install — user-added
  skills survive untouched.

When no manifest entry exists for a mirror (a consumer whose mirrors predate this
capability), the owned set is seeded as ``present ∩ desired`` and NOTHING is
deleted on that first run (one cycle of eventual consistency, surfaced by the
next check).

Idempotent: re-running with no upstream changes produces zero filesystem
modifications.

Contract: `docs/concepts/skills-distribution.md` (single-source design).

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
import os
import shutil
import stat
import sys
from pathlib import Path

# UTF-8 stdio — Windows cp1252 console safety.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts import _skills_manifest  # noqa: E402
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
    stale_removed: list[str] = dataclasses.field(default_factory=list)
    user_dirs_preserved: list[str] = dataclasses.field(default_factory=list)
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
# Filesystem helpers
# ---------------------------------------------------------------------------


def _dir_fingerprint(root: Path) -> str:
    """Stable sha256 over (relative-path, file-bytes) pairs of a tree.

    Returns empty string for missing / non-directory roots. Sort order is
    forward-slash relative path, ensuring cross-platform stability.
    """
    if not root.is_dir():
        return ""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*"), key=lambda x: x.as_posix()):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            h.update(rel.encode("utf-8"))
            h.update(b"\0")
            h.update(p.read_bytes())
            h.update(b"\0")
    return h.hexdigest()


def _source_skill_names(source: Path, *, exclude: set[str]) -> set[str]:
    """Immediate children of ``source`` that contain a ``SKILL.md``, minus
    the excluded (disabled) slugs."""
    if not source.is_dir():
        return set()
    return {
        child.name
        for child in source.iterdir()
        if child.is_dir()
        and child.name not in exclude
        and (child / "SKILL.md").is_file()
    }


def _present_dirs(target: Path) -> set[str]:
    """Immediate child directory names of ``target`` (empty set if missing)."""
    if not target.is_dir():
        return set()
    return {child.name for child in target.iterdir() if child.is_dir()}


def _rmtree(path: Path) -> None:
    """``shutil.rmtree`` tolerant of Windows read-only files (git perms)."""

    def _onerror(func, p, _exc_info):  # noqa: ANN001
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    shutil.rmtree(path, onerror=_onerror)


# ---------------------------------------------------------------------------
# Single-mirror sync (additive, provenance-aware)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _MirrorSync:
    changed: bool
    error: str | None
    owned_now: set[str]
    stale_removed: list[str]
    user_preserved: list[str]


def _sync_one(
    source: Path,
    target: Path,
    *,
    desired: set[str],
    owned_prev: set[str] | None,
    dry_run: bool,
    quiet: bool,
) -> _MirrorSync:
    """Additively sync the playbook-owned skills source -> target mirror.

    ``owned_prev`` is the set the playbook installed last time, or ``None`` when
    the manifest has no entry for this mirror (migration: seed ``present ∩
    desired`` and delete nothing this run). A directory that is neither
    playbook-owned nor desired is a user skill and is left untouched.
    """
    # Symlinked mirror: treat as already in sync; do not manage provenance.
    if target.is_symlink():
        if not quiet:
            print(f"  · {target}: symlinked mirror, skipped")
        return _MirrorSync(False, None, set(owned_prev or set()), [], [])

    present = _present_dirs(target)
    if owned_prev is None:
        owned_prev = present & desired  # migration seed: delete nothing

    user_preserved = sorted(present - owned_prev - desired)
    stale = sorted((owned_prev - desired) & present)

    changed = False
    errors: list[str] = []

    # 1. Remove playbook-owned directories that are no longer desired.
    for name in stale:
        changed = True
        if not dry_run:
            try:
                _rmtree(target / name)
            except OSError as exc:
                errors.append(f"{target / name}: {exc}")

    # 2. Per-skill sync of the desired skills — create/update OUR dirs only.
    for name in sorted(desired):
        src_dir = source / name
        tgt_dir = target / name
        if _dir_fingerprint(src_dir) == _dir_fingerprint(tgt_dir) and tgt_dir.is_dir():
            continue
        changed = True
        if not dry_run:
            try:
                target.mkdir(parents=True, exist_ok=True)
                if tgt_dir.exists():
                    _rmtree(tgt_dir)
                shutil.copytree(src_dir, tgt_dir)
            except OSError as exc:
                errors.append(f"{tgt_dir}: {exc}")

    err = "; ".join(errors) if errors else None
    if not quiet:
        if dry_run:
            verb = "would update" if changed else "in sync"
        else:
            verb = "updated" if changed else "in sync"
        glyph = "✓" if changed else "·"
        prefix = "  (dry-run) " if dry_run else f"  {glyph} "
        print(
            f"{prefix}{target}: {verb} "
            f"({len(desired)} skills; {len(user_preserved)} user-kept)"
        )
    return _MirrorSync(changed, err, set(desired), stale, user_preserved)


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

    Additive and provenance-aware: user-added skill directories are never
    deleted or modified. See module docstring for the contract.

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
    desired = _source_skill_names(source, exclude=disabled)
    result.skills_total = len(desired)

    if not quiet:
        rel_source = (
            str(source.relative_to(consumer_dir))
            if source.is_relative_to(consumer_dir)
            else str(source)
        )
        action = "Would sync" if dry_run else "Syncing"
        suffix = ""
        if disabled:
            suffix = (
                f" ({len(disabled)} skill(s) disabled via "
                ".ai-playbook-state/skills-enforce.json)"
            )
        print(
            f"{action} skills from {rel_source}/ "
            f"({result.skills_total} skills) to {len(MIRROR_RELS)} mirror(s){suffix}"
        )

    manifest = _skills_manifest.read(consumer_dir)
    new_manifest: dict[str, set[str]] = dict(manifest)

    for mirror_rel in MIRROR_RELS:
        target = consumer_dir / mirror_rel
        rel_key = mirror_rel.as_posix()
        sync = _sync_one(
            source,
            target,
            desired=desired,
            owned_prev=manifest.get(rel_key),  # None => migration seed
            dry_run=dry_run,
            quiet=quiet,
        )
        new_manifest[rel_key] = sync.owned_now
        result.stale_removed.extend(f"{rel_key}/{n}" for n in sync.stale_removed)
        result.user_dirs_preserved.extend(
            f"{rel_key}/{n}" for n in sync.user_preserved
        )
        if sync.error is not None:
            result.errors.append(sync.error)
        if sync.changed:
            result.mirrors_rewritten += 1
        else:
            result.mirrors_in_sync += 1

    # Persist provenance (skip in dry-run). Best-effort: a manifest write
    # failure is surfaced but does not undo the synced mirrors.
    if not dry_run:
        try:
            _skills_manifest.write(consumer_dir, new_manifest)
        except OSError as exc:
            result.errors.append(f"manifest write failed: {exc}")

    if result.errors:
        result.summary = f"materialisation failed: {len(result.errors)} error(s)."
        return result

    if result.mirrors_rewritten == 0:
        result.summary = (
            f"all {len(MIRROR_RELS)} mirror(s) in sync "
            f"({result.skills_total} skills); no-op."
        )
    else:
        result.summary = (
            f"updated {result.mirrors_rewritten} mirror(s) "
            f"({result.skills_total} skills); "
            f"{result.mirrors_in_sync} in sync."
        )
    if result.user_dirs_preserved and not quiet:
        print(f"  preserved {len(result.user_dirs_preserved)} user-added skill dir(s)")
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
