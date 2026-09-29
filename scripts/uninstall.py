"""Uninstall ai-playbook integration from a consumer project.

Removes the submodule + state files + playbook-managed marker blocks. Files
that the consumer customised remain — only the playbook-canonical blocks
are stripped (or restored from the BASE pre-playbook snapshot if available).

Pipeline
--------
1. Read ``.ai-playbook-state/backups/index.json`` and restore EVERY
   ``session_id == "base"`` record (the pre-playbook snapshot bootstrap took
   of each file it overwrote: AGENTS.md, CLAUDE.md, docs/runbook.md, ...).
   Ordinary (post-playbook) backups are never restored: they would roll the
   consumer's latest edits back to a stale playbook-rendered version.
2. For files without a BASE snapshot, strip the marker blocks
   (``parse_blocks`` → write back only the custom segments) and the
   caveman/ponytail/graphify ``auto-managed`` ruleset blocks in AGENTS.md.
3. Drop every hook in ``.claude/settings*.json`` whose command points into
   ``.ai-playbook/`` (once the submodule is gone it exits 2, which blocks
   every Claude Code tool call).
4. ``git submodule deinit -f .ai-playbook`` + ``git rm -f .ai-playbook``.
5. Remove ``.ai-playbook-state/`` — unless it holds a BASE snapshot that was
   not restored (the only copy of the consumer's original): kept + warned.
6. Print summary.

Idempotent: running twice has no incremental effect.
"""
from __future__ import annotations

import argparse
import json
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


# Make `from scripts...` resolve when run by path (`python .ai-playbook/scripts/...`), not just via -m.
_PLAYBOOK_ROOT = str(Path(__file__).resolve().parents[1])
if _PLAYBOOK_ROOT not in sys.path:
    sys.path.insert(0, _PLAYBOOK_ROOT)

from scripts._backup_helper import (  # noqa: E402
    BASE_SESSION_ID,
    BackupRecord,
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
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Restore from pre-playbook .bak
# ---------------------------------------------------------------------------


def _base_records(records: list[BackupRecord]) -> list[BackupRecord]:
    """Earliest BASE (pre-playbook, D8) record per file, for every file.

    Only BASE is restored: an ordinary backup is a post-playbook version, and
    restoring it would overwrite the consumer's latest edits with stale content.
    """
    earliest: dict[str, BackupRecord] = {}
    for r in sorted(records, key=lambda rec: rec.timestamp):
        if r.session_id == BASE_SESSION_ID:
            earliest.setdefault(r.rel_path, r)
    return list(earliest.values())


def restore_originals(consumer_root: Path, report: UninstallReport) -> None:
    for record in _base_records(read_index(consumer_root)):
        rel = record.rel_path
        try:
            restore_backup(consumer_root, record)
            report.restored.append(f"{rel} ← {record.backup_rel_path}")
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


def _restored_paths(report: UninstallReport) -> set[str]:
    return {entry.split(" ← ", 1)[0] for entry in report.restored}


def strip_managed_markers(consumer_root: Path, report: UninstallReport) -> None:
    already_restored = _restored_paths(report)
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
    if "AGENTS.md" not in already_restored:
        _strip_feature_blocks(consumer_root, report)


def _strip_feature_blocks(consumer_root: Path, report: UninstallReport) -> None:
    """Remove the caveman/ponytail/graphify ``auto-managed`` ruleset blocks from
    AGENTS.md; they instruct the agent to run toggles that no longer exist."""
    from scripts.caveman import materialise as caveman_m
    from scripts.graphify import materialise as graphify_m
    from scripts.ponytail import materialise as ponytail_m

    for name, mod in (("caveman", caveman_m), ("ponytail", ponytail_m), ("graphify", graphify_m)):
        try:
            if mod.strip(consumer_root) is not None:
                report.stripped.append(f"AGENTS.md ({name} block)")
        except (OSError, ValueError) as exc:
            report.errors.append(f"strip {name} block from AGENTS.md: {exc}")


def _is_playbook_hook(hook: object) -> bool:
    if not isinstance(hook, dict):
        return False
    return ".ai-playbook/" in str(hook.get("command", "")).replace("\\", "/")


def remove_playbook_hooks(consumer_root: Path, report: UninstallReport) -> None:
    """Drop hooks whose command runs a script inside ``.ai-playbook/``.

    Once the submodule is removed those commands fail with exit 2, which
    Claude Code treats as "block": every matched tool call would be vetoed.
    """
    for rel in (".claude/settings.json", ".claude/settings.local.json"):
        p = consumer_root / rel
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report.errors.append(
                f"{rel}: cannot parse ({exc}); remove hooks referencing .ai-playbook/ by hand"
            )
            continue
        hooks = data.get("hooks") if isinstance(data, dict) else None
        if not isinstance(hooks, dict):
            continue
        changed = False
        for event in list(hooks):
            groups = hooks[event]
            if not isinstance(groups, list):
                continue
            kept_groups = []
            for group in groups:
                inner = group.get("hooks") if isinstance(group, dict) else None
                if isinstance(inner, list):
                    kept = [h for h in inner if not _is_playbook_hook(h)]
                    if len(kept) != len(inner):
                        changed = True
                        if not kept:
                            continue
                        group = {**group, "hooks": kept}
                kept_groups.append(group)
            if kept_groups:
                hooks[event] = kept_groups
            else:
                del hooks[event]
        if not changed:
            continue
        if not hooks:
            del data["hooks"]
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                     encoding="utf-8", newline="\n")
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


def _unrestored_base(consumer_root: Path, report: UninstallReport) -> list[str]:
    restored = _restored_paths(report)
    return sorted(
        r.rel_path for r in _base_records(read_index(consumer_root))
        if r.rel_path not in restored
    )


def remove_state_dir(consumer_root: Path, report: UninstallReport) -> None:
    state_dir = consumer_root / ".ai-playbook-state"
    if not state_dir.exists():
        return
    pending = _unrestored_base(consumer_root, report)
    if pending:
        # BASE snapshots are the only copy of the consumer's originals.
        report.warnings.append(
            "kept .ai-playbook-state/: BASE (pre-playbook) snapshot not restored for "
            f"{', '.join(pending)}. Copy what you need from .ai-playbook-state/backups/ "
            "(index.json maps each file), then delete the dir by hand."
        )
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
        base = {r.rel_path for r in _base_records(read_index(consumer_root))}
        for rel in sorted(base) if restore_from_bak else []:
            report.restored.append(f"(dry-run) would restore {rel}")
        for rel in MANAGED_PATHS:
            if (rel not in base or not restore_from_bak) and (consumer_root / rel).is_file():
                report.stripped.append(f"(dry-run) would strip markers from {rel}")
        if (consumer_root / ".ai-playbook").exists():
            report.submodule_removed = True
        if (
            not keep_state_dir
            and (consumer_root / ".ai-playbook-state").exists()
            and (restore_from_bak or not base)
        ):
            report.state_dir_removed = True
        return report

    if restore_from_bak:
        restore_originals(consumer_root, report)
    strip_managed_markers(consumer_root, report)
    remove_playbook_hooks(consumer_root, report)
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
            "Restores files from their BASE (pre-playbook) snapshot (or strips "
            "marker blocks if none exists), drops hooks pointing into "
            ".ai-playbook/, removes the submodule + state dir."
        ),
    )
    parser.add_argument("--target", type=Path, default=None,
                        help="Consumer root (default: cwd).")
    parser.add_argument("--no-restore", action="store_true",
                        help="Skip restore-from-BASE. Just strip markers "
                             "(.ai-playbook-state/ is then kept when it holds BASE snapshots).")
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
    for entry in report.warnings:
        print(f"WARN: {entry}")
    if report.errors:
        print(f"errors ({len(report.errors)}):")
        for entry in report.errors:
            print(f"  - {entry}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
