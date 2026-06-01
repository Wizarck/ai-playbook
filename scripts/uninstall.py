"""Uninstall ai-playbook integration from a consumer project.

Removes the submodule + state files + playbook-managed marker blocks. Files
that the consumer customised remain — only the playbook-canonical blocks
are stripped (or restored from the oldest ``.bak`` snapshot if available).

Pipeline
--------
1. Read ``.ai-playbook-state/backups/index.json``. For each managed file,
   the oldest record IS the pre-playbook snapshot (if the consumer ran
   ``apply_config`` at all). When ``--restore-from-bak`` is passed, those
   originals are restored verbatim.
2. For files without a pre-playbook .bak, strip the marker blocks
   (``parse_blocks`` → write back only the custom segments).
3. ``git submodule deinit -f .ai-playbook`` + ``git rm -f .ai-playbook``.
4. Remove ``.ai-playbook-state/``.
5. Print summary.

Idempotent: running twice has no incremental effect.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts._backup_helper import (  # noqa: E402
    BackupRecord,
    base_record_for,
    read_index,
    restore_backup,
)
from scripts._marker_blocks import (  # noqa: E402
    parse_blocks,
    style_for_filename,
)

MANAGED_PATHS = [
    "AGENTS.md",
    ".gitignore",
    ".pre-commit-config.yaml",
    ".coderabbit.yaml",
    ".claude/settings.json",
    ".claude/settings.local.json",
    "mcp-servers.project.yaml",
    "mcp-servers.yaml",
]


@dataclass
class UninstallReport:
    target: Path
    restored: list[str] = field(default_factory=list)
    stripped: list[str] = field(default_factory=list)
    submodule_removed: bool = False
    state_dir_removed: bool = False
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Restore from pre-playbook .bak
# ---------------------------------------------------------------------------


def _oldest_backup_for(records: list[BackupRecord], rel_path: str) -> BackupRecord | None:
    matches = [r for r in records if r.rel_path == rel_path]
    return matches[0] if matches else None  # records are oldest-first


def _restore_record_for(
    consumer_root: Path, records: list[BackupRecord], rel_path: str,
) -> BackupRecord | None:
    """Prefer the explicit BASE (pre-playbook) snapshot; fall back to the oldest
    ordinary backup. The base tag is the authoritative pre-playbook anchor (D8)
    even when later backups have shuffled the index ordering."""
    base = base_record_for(consumer_root, rel_path)
    if base is not None:
        return base
    return _oldest_backup_for(records, rel_path)


def restore_originals(consumer_root: Path, report: UninstallReport) -> None:
    records = read_index(consumer_root)
    if not records:
        return
    for rel in MANAGED_PATHS:
        record = _restore_record_for(consumer_root, records, rel)
        if record is None:
            continue
        try:
            dest = restore_backup(consumer_root, record)
            report.restored.append(f"{rel} ← {record.backup_rel_path}")
            del dest  # silence linter
        except FileNotFoundError as exc:
            report.errors.append(f"restore {rel}: {exc}")


# ---------------------------------------------------------------------------
# Strip marker blocks
# ---------------------------------------------------------------------------


def strip_markers_from_file(path: Path) -> bool:
    """Remove every ai-playbook marker block from ``path``. Returns True if changed."""
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    style = style_for_filename(path.name)
    try:
        parsed = parse_blocks(text, style)
    except ValueError:
        return False
    if not parsed.blocks:
        return False
    # Keep only the custom segments (joined verbatim).
    new_text = "".join(parsed.custom_segments)
    # Avoid leaving the file with a single trailing newline mismatch when the
    # last segment was an empty string.
    if new_text != text:
        path.write_text(new_text, encoding="utf-8", newline="\n")
        return True
    return False


def strip_managed_markers(consumer_root: Path, report: UninstallReport) -> None:
    already_restored = {entry.split(" ", 1)[0] for entry in report.restored}
    for rel in MANAGED_PATHS:
        if rel in already_restored:
            continue
        p = consumer_root / rel
        if not p.is_file():
            continue
        try:
            changed = strip_markers_from_file(p)
        except OSError as exc:
            report.errors.append(f"strip {rel}: {exc}")
            continue
        if changed:
            report.stripped.append(rel)


# ---------------------------------------------------------------------------
# Remove submodule + state dir
# ---------------------------------------------------------------------------


def _run_git(*args: str, cwd: Path) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
    except FileNotFoundError:
        return 127, "git executable not found on PATH"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def remove_submodule(consumer_root: Path, report: UninstallReport) -> None:
    submodule = consumer_root / ".ai-playbook"
    if not submodule.exists():
        return
    rc, out = _run_git("submodule", "deinit", "-f", ".ai-playbook", cwd=consumer_root)
    if rc != 0:
        report.errors.append(f"git submodule deinit failed: {out}")
    rc, out = _run_git("rm", "-f", ".ai-playbook", cwd=consumer_root)
    if rc != 0:
        # Submodule may not be tracked yet — fall back to recursive rmtree.
        try:
            shutil.rmtree(submodule)
            report.submodule_removed = True
        except OSError as exc:
            report.errors.append(f"failed to remove .ai-playbook/: {exc}")
            return
    else:
        report.submodule_removed = True

    # Also remove .git/modules/.ai-playbook if it exists.
    git_modules = consumer_root / ".git" / "modules" / ".ai-playbook"
    if git_modules.exists():
        try:
            shutil.rmtree(git_modules)
        except OSError:
            pass


def remove_state_dir(consumer_root: Path, report: UninstallReport) -> None:
    state_dir = consumer_root / ".ai-playbook-state"
    if not state_dir.exists():
        return
    try:
        shutil.rmtree(state_dir)
        report.state_dir_removed = True
    except OSError as exc:
        report.errors.append(f"failed to remove .ai-playbook-state/: {exc}")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def uninstall(
    consumer_root: Path,
    *,
    restore_from_bak: bool = True,
    keep_state_dir: bool = False,
    dry_run: bool = False,
) -> UninstallReport:
    report = UninstallReport(target=consumer_root)

    if dry_run:
        records = read_index(consumer_root)
        for rel in MANAGED_PATHS:
            if restore_from_bak and _restore_record_for(consumer_root, records, rel) is not None:
                report.restored.append(f"(dry-run) would restore {rel}")
            elif (consumer_root / rel).is_file():
                report.stripped.append(f"(dry-run) would strip markers from {rel}")
        if (consumer_root / ".ai-playbook").exists():
            report.submodule_removed = True
        if not keep_state_dir and (consumer_root / ".ai-playbook-state").exists():
            report.state_dir_removed = True
        return report

    if restore_from_bak:
        restore_originals(consumer_root, report)
    strip_managed_markers(consumer_root, report)
    remove_submodule(consumer_root, report)
    if not keep_state_dir:
        remove_state_dir(consumer_root, report)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="uninstall",
        description=(
            "Uninstall ai-playbook integration from a consumer project. "
            "Restores files from the oldest .bak snapshot (or strips marker "
            "blocks if no .bak exists), removes the submodule + state dir."
        ),
    )
    parser.add_argument("--target", type=Path, default=None,
                        help="Consumer root (default: cwd).")
    parser.add_argument("--no-restore", action="store_true",
                        help="Skip restore-from-.bak. Just strip markers.")
    parser.add_argument("--keep-state-dir", action="store_true",
                        help="Keep .ai-playbook-state/ on disk (useful for inspection).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Describe actions without performing them.")
    parser.add_argument("--yes", action="store_true",
                        help="Skip the interactive confirmation prompt.")
    args = parser.parse_args(argv)

    target = (args.target or Path.cwd()).expanduser().resolve()
    if not target.is_dir():
        print(f"ERROR: target {target} is not a directory", file=sys.stderr)
        return 2

    if not args.yes and not args.dry_run:
        print(f"This will uninstall ai-playbook from: {target}")
        print(f"  - {'restore from .bak when available' if not args.no_restore else 'strip markers only'}")
        print("  - remove .ai-playbook/ submodule")
        print(f"  - {'remove' if not args.keep_state_dir else 'keep'} .ai-playbook-state/")
        answer = "y" if os.environ.get("PLAYBOOK_NO_PROMPT") else input("Continue? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("aborted.")
            return 1

    report = uninstall(
        target,
        restore_from_bak=not args.no_restore,
        keep_state_dir=args.keep_state_dir,
        dry_run=args.dry_run,
    )

    print()
    print("# uninstall report" + (" (dry-run)" if args.dry_run else ""))
    print(f"target: {report.target}")
    if report.restored:
        print(f"restored from .bak ({len(report.restored)}):")
        for entry in report.restored:
            print(f"  - {entry}")
    if report.stripped:
        print(f"stripped markers ({len(report.stripped)}):")
        for entry in report.stripped:
            print(f"  - {entry}")
    print(f"submodule removed: {report.submodule_removed}")
    print(f"state dir removed: {report.state_dir_removed}")
    if report.errors:
        print(f"errors ({len(report.errors)}):")
        for entry in report.errors:
            print(f"  - {entry}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
