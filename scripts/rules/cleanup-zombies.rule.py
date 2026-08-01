"""Consumer-side zombie cleanup driven by a declarative manifest.

Slice: add-cleanup-zombies-hook (v0.15.0).

Reads `specs/zombies-manifest.yaml`. Walks the consumer tree from the
invocation cwd's nearest ancestor containing a `.ai-playbook/` submodule.
For each manifest entry: runs the entry's safety check, then either
deletes (Tier 1), applies a textual change (Tier 2), or records an
advisory (Tier 3).

Always exits 0 in the default (hook) invocation. The only non-zero exit
path is `validate` (exit 2 on schema failure) — that subcommand is the
pre-commit gate on edits to the manifest itself.

Contracts:
- docs/rules/cleanup-zombies.rule.md (this script's contract, in full)
- specs/zombies-manifest.yaml (canonical manifest)
- docs/rules/break-glass.rule.md (AIPLAYBOOK_CLEANUP_SKIP env)
- docs/rules/error-message-standard.rule.md (only `validate` emits structured errors)

CLI
---
    python -m scripts.cleanup_zombies                       # default: report-only
    python -m scripts.cleanup_zombies --apply               # execute Tier 1+2
    python -m scripts.cleanup_zombies --quiet               # suppress stdout summary
    python -m scripts.cleanup_zombies --manifest <path>     # override (tests)
    python -m scripts.cleanup_zombies --consumer-root <p>   # override (tests)
    python -m scripts.cleanup_zombies validate              # schema check; exit 0/2
    python -m scripts.cleanup_zombies version               # print manifest_version
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

# UTF-8 stdio for Windows cp1252 consoles (also benign on POSIX).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


SCRIPT_NAME = "cleanup_zombies"
MANIFEST_REL = Path("specs/zombies-manifest.yaml")
REPORT_REL = Path(".ai-playbook/zombie-report.md")
INJECTED_CONTEXT_REL = Path(".claude/injected-context.md")
INJECTED_CONTEXT_MARKER = "playbook-cleanup found pending items"

MANIFEST_VERSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d+$")
ALLOWED_TIERS = {1, 2, 3}
ALLOWED_ACTIONS = {"delete", "rename", "prune_blocks", "rotate", "report"}
ALLOWED_SAFETIES = {
    "check_gitmodules_first",
    "directory_orphan",
    "auto_managed_orphan",
    "file_mtime_and_drained",
    "yaml_literal_rename",
    "report_only",
}
TIER_ACTION_MATRIX = {
    1: {"delete", "prune_blocks", "rotate"},
    2: {"rename"},
    3: {"report"},
}
TIER_SAFETY_MATRIX = {
    1: {
        "check_gitmodules_first",
        "directory_orphan",
        "file_mtime_and_drained",
    },
    2: {"yaml_literal_rename"},
    # Tier governs mutation; safety governs detection. Coupling them 1:1 forced
    # any entry that wanted real detection to also claim auto-delete rights —
    # which is how `auto-managed-orphan-blocks` shipped as Tier 1. A Tier 3
    # entry may run a detection safety to make its advisory specific; the
    # structural guard in `_process_entry` keeps it from ever mutating.
    3: {"report_only", "auto_managed_orphan"},
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class SafetyResult:
    passed: bool
    reason: str


@dataclasses.dataclass
class EntryOutcome:
    entry_id: str
    tier: int
    # action_taken ∈ {deleted, would-delete, renamed, would-rename, pruned, rotated, advisory, skipped}
    action_taken: str
    path: str
    detail: str         # human-readable; renders into the report file


@dataclasses.dataclass
class RunReport:
    manifest_version: str
    started_at: str
    outcomes: list[EntryOutcome]

    def counts(self) -> dict[str, int]:
        deleted = sum(1 for o in self.outcomes if o.action_taken in ("deleted", "pruned", "rotated"))
        would_delete = sum(1 for o in self.outcomes if o.action_taken.startswith("would-"))
        renamed = sum(1 for o in self.outcomes if o.action_taken == "renamed")
        advisories = sum(1 for o in self.outcomes if o.action_taken == "advisory")
        return {
            "deleted": deleted,
            "would_delete": would_delete,
            "renamed": renamed,
            "advisories": advisories,
        }

    def has_any(self) -> bool:
        return bool(self.outcomes)


# ---------------------------------------------------------------------------
# Manifest loader + validator
# ---------------------------------------------------------------------------


class ManifestError(Exception):
    """Raised when the manifest fails schema validation. Used by `validate`."""


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ManifestError(f"manifest missing at {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManifestError(f"manifest unparseable: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError("manifest top-level must be a mapping")
    return data


def _validate_manifest(data: dict[str, Any]) -> list[str]:
    """Return list of validation errors (empty → valid)."""
    errors: list[str] = []
    if data.get("version") != 1:
        errors.append("`version` must equal 1")
    mv = data.get("manifest_version")
    if not isinstance(mv, str) or not MANIFEST_VERSION_RE.match(mv):
        errors.append("`manifest_version` must match YYYY-MM-DD.N")
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("`entries` must be a non-empty list")
        return errors

    seen_ids: set[str] = set()
    required = {"id", "tier", "action", "safety", "path", "introduced_in", "removed_in", "reason", "evidence"}
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entry[{idx}] must be a mapping")
            continue
        missing = required - set(entry.keys())
        if missing:
            errors.append(f"entry[{idx}] missing required keys: {sorted(missing)}")
            continue
        eid = entry["id"]
        if eid in seen_ids:
            errors.append(f"duplicate id `{eid}`")
        seen_ids.add(eid)
        tier = entry["tier"]
        action = entry["action"]
        safety = entry["safety"]
        if tier not in ALLOWED_TIERS:
            errors.append(f"entry[{eid}] tier must be 1, 2, or 3 (got {tier})")
            continue
        if action not in ALLOWED_ACTIONS:
            errors.append(f"entry[{eid}] action `{action}` unknown")
        if safety not in ALLOWED_SAFETIES:
            errors.append(f"entry[{eid}] safety `{safety}` unknown")
        if action not in TIER_ACTION_MATRIX[tier]:
            errors.append(f"entry[{eid}] tier {tier} does not allow action `{action}`")
        if safety not in TIER_SAFETY_MATRIX[tier]:
            errors.append(f"entry[{eid}] tier {tier} does not allow safety `{safety}`")
        # Action-specific extras
        if action == "rename":
            for k in ("rename_from", "rename_to", "rename_in_files"):
                if k not in entry:
                    errors.append(f"entry[{eid}] action=rename requires `{k}`")
        if action == "rotate" and "rotation_days" not in entry:
            errors.append(f"entry[{eid}] action=rotate requires `rotation_days`")
    return errors


# ---------------------------------------------------------------------------
# Consumer-root discovery
# ---------------------------------------------------------------------------


def _find_consumer_root(start: Path) -> Path | None:
    start = start.resolve()
    for candidate in [start, *start.parents]:
        if (candidate / ".ai-playbook").is_dir():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------


def _safety_check_gitmodules_first(target: Path, entry: dict[str, Any], consumer_root: Path) -> SafetyResult:
    if not target.exists():
        return SafetyResult(False, "target absent — no zombie")
    gitmodules = consumer_root / ".gitmodules"
    if not gitmodules.is_file():
        return SafetyResult(True, ".gitmodules absent — directory is orphan")
    text = gitmodules.read_text(encoding="utf-8")
    rel = str(target.relative_to(consumer_root)).replace("\\", "/")
    # Match a `path = <rel>` line under any [submodule "..."] block.
    pattern = re.compile(rf"^\s*path\s*=\s*{re.escape(rel)}\s*$", re.MULTILINE)
    if pattern.search(text):
        return SafetyResult(False, f"submodule path `{rel}` still registered in .gitmodules")
    return SafetyResult(True, ".gitmodules does not register this path")


def _safety_directory_orphan(target: Path, entry: dict[str, Any], consumer_root: Path) -> SafetyResult:
    if not target.exists():
        return SafetyResult(False, "target absent — no zombie")
    if not target.is_dir():
        return SafetyResult(False, "target is not a directory")
    rel = str(target.relative_to(consumer_root)).replace("\\", "/")
    try:
        result = subprocess.run(
            ["git", "ls-files", "--", rel],
            cwd=str(consumer_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return SafetyResult(False, f"git ls-files failed: {exc}")
    if result.stdout.strip():
        return SafetyResult(False, "directory has tracked files")
    return SafetyResult(True, "no tracked files under directory")


# Namespaces that own auto-managed blocks, and the toggle state file that says
# whether the owning feature is currently ON. `auto_managed.py` owns `specs/*`
# (whitelisted in its `_SUPPORTED_SOURCES`); the caveman and ponytail toggles
# own their own prefixes and materialise a block whenever the feature is
# enabled. A block whose namespace is not listed here has an owner this script
# cannot reason about, and is therefore NEVER an orphan — silence beats a
# confident deletion.
_BLOCK_OWNERS = {
    "caveman/": "caveman.json",
    "ponytail/": "ponytail.json",
}


def _feature_enabled(state_path: Path) -> bool:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return bool(state.get("enabled"))


def _consumer_markdown(consumer_root: Path, glob: str) -> Iterable[Path]:
    """`_iter_glob`, minus the playbook submodule's own tree.

    A `**/*.md` glob from the consumer root otherwise walks into
    `.ai-playbook/`, i.e. this playbook's own documentation — files that are
    not the consumer's to clean and that legitimately discuss marker syntax.
    """
    submodule = (consumer_root / ".ai-playbook").resolve()
    for md in _iter_glob(consumer_root, glob):
        try:
            md.resolve().relative_to(submodule)
        except ValueError:
            yield md


def _auto_managed_orphans(md: Path, consumer_root: Path) -> list[str]:
    """Sources of genuinely-orphan auto-managed blocks in one markdown file.

    Parsing delegates to `auto_managed.find_sections` — the canonical parser,
    which anchors on full trimmed lines and skips fenced code blocks, so prose
    that *documents* the marker syntax is never mistaken for a live block. It
    raises on nested/unterminated markers; that means "cannot analyse", and we
    report zero orphans rather than guess.
    """
    from scripts.auto_managed import compute_expected, find_sections

    try:
        text = md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        sections = find_sections(text)
    except ValueError:
        return []

    playbook_root = consumer_root / ".ai-playbook"
    orphans: list[str] = []
    for section in sections:
        source = section.source
        owner_state = next(
            (state for prefix, state in _BLOCK_OWNERS.items() if source.startswith(prefix)),
            None,
        )
        if owner_state is not None:
            if not _feature_enabled(playbook_root / owner_state):
                orphans.append(source)
        elif source.startswith("specs/"):
            try:
                compute_expected(source, playbook_root)
            except (ValueError, FileNotFoundError, LookupError):
                orphans.append(source)
    return orphans


def _safety_auto_managed_orphan(target: Path, entry: dict[str, Any], consumer_root: Path) -> SafetyResult:
    auto_managed = consumer_root / ".ai-playbook" / "scripts" / "auto_managed.py"
    if not auto_managed.is_file():
        return SafetyResult(False, "auto_managed.py not available in submodule")
    hits: list[str] = []
    for md in _consumer_markdown(consumer_root, entry["path"]):
        hits.extend(f"{md.relative_to(consumer_root).as_posix()}: {src}" for src in _auto_managed_orphans(md, consumer_root))
    if hits:
        return SafetyResult(True, f"{len(hits)} orphan auto-managed block(s): {'; '.join(hits[:5])}")
    return SafetyResult(False, "no orphan blocks")


def _safety_file_mtime_and_drained(target: Path, entry: dict[str, Any], consumer_root: Path) -> SafetyResult:
    if not target.is_file():
        return SafetyResult(False, "target absent — no zombie")
    rotation_days = int(entry.get("rotation_days", 30))
    age = dt.datetime.now() - dt.datetime.fromtimestamp(target.stat().st_mtime)
    if age.days < rotation_days:
        return SafetyResult(False, f"file mtime within last {rotation_days} days")
    try:
        for line in target.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                # Corrupt line: treat as not-drained to be conservative.
                return SafetyResult(False, "corrupt JSONL line found; not safe to rotate")
            if record.get("state") != "drained":
                return SafetyResult(False, "at least one record not drained")
    except OSError as exc:
        return SafetyResult(False, f"failed reading JSONL: {exc}")
    return SafetyResult(True, "all entries drained and file is stale")


def _safety_yaml_literal_rename(target: Path, entry: dict[str, Any], consumer_root: Path) -> SafetyResult:
    rename_from = entry.get("rename_from")
    if not rename_from:
        return SafetyResult(False, "missing rename_from")
    files = entry.get("rename_in_files", []) or []
    hits = 0
    for rel in files:
        path = consumer_root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
            data = yaml.safe_load(text)
        except (OSError, yaml.YAMLError):
            continue
        if _yaml_has_scalar_value(data, rename_from):
            hits += 1
    if hits:
        return SafetyResult(True, f"{hits} file(s) contain literal `{rename_from}` as scalar value")
    return SafetyResult(False, "no scalar matches")


def _yaml_has_scalar_value(node: Any, needle: str) -> bool:
    if isinstance(node, str):
        return node == needle
    if isinstance(node, dict):
        return any(_yaml_has_scalar_value(v, needle) for v in node.values())
    if isinstance(node, list):
        return any(_yaml_has_scalar_value(x, needle) for x in node)
    return False


def _safety_report_only(target: Path, entry: dict[str, Any], consumer_root: Path) -> SafetyResult:
    return SafetyResult(False, "report-only entry")


SAFETY_CHECKS = {
    "check_gitmodules_first": _safety_check_gitmodules_first,
    "directory_orphan": _safety_directory_orphan,
    "auto_managed_orphan": _safety_auto_managed_orphan,
    "file_mtime_and_drained": _safety_file_mtime_and_drained,
    "yaml_literal_rename": _safety_yaml_literal_rename,
    "report_only": _safety_report_only,
}


# ---------------------------------------------------------------------------
# Glob helpers
# ---------------------------------------------------------------------------


def _iter_glob(root: Path, pattern: str) -> Iterable[Path]:
    """Walk root for files matching pattern; ignores .git/ and node_modules/."""
    pattern = pattern.replace("\\", "/")
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for name in files:
            full = Path(current) / name
            rel = str(full.relative_to(root)).replace("\\", "/")
            if fnmatch.fnmatchcase(rel, pattern):
                yield full


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def _do_delete(target: Path) -> str:
    if target.is_dir():
        shutil.rmtree(target)
        return f"deleted directory {target}"
    target.unlink()
    return f"deleted file {target}"


def _do_rename(entry: dict[str, Any], consumer_root: Path) -> str:
    rename_from = entry["rename_from"]
    rename_to = entry["rename_to"]
    files = entry.get("rename_in_files", []) or []
    edited: list[str] = []
    for rel in files:
        path = consumer_root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if rename_from not in text:
            continue
        # Parse to guard against renaming inside comments unintentionally.
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        if not _yaml_has_scalar_value(data, rename_from):
            continue
        new_text = text.replace(rename_from, rename_to)
        path.write_text(new_text, encoding="utf-8", newline="\n")
        edited.append(rel)
    if not edited:
        return "no files mutated (literal vanished between check and apply)"
    return f"renamed `{rename_from}` → `{rename_to}` in: {', '.join(edited)}"


def _do_prune_blocks(entry: dict[str, Any], consumer_root: Path) -> str:
    """Remove genuinely-orphan auto-managed blocks, marker lines included.

    Fixed rather than deleted: `prune_blocks` stays in the action schema, so a
    future manifest entry can still reach it. It now shares the canonical
    parser and the orphan test with the safety check above — those two having
    drifted apart is precisely what let a false positive be both detected and
    executed.
    """
    from scripts.auto_managed import find_sections

    pruned = 0
    for md in _consumer_markdown(consumer_root, entry["path"]):
        orphan_sources = set(_auto_managed_orphans(md, consumer_root))
        if not orphan_sources:
            continue
        text = md.read_text(encoding="utf-8")
        lines = text.replace("\r\n", "\n").split("\n")
        try:
            sections = find_sections(text)
        except ValueError:
            continue
        drop: set[int] = set()
        for section in sections:
            if section.source in orphan_sources:
                # start_line/end_line are 1-indexed and name the marker lines.
                drop.update(range(section.start_line - 1, section.end_line))
                pruned += 1
        if not drop:
            continue
        kept = [line for idx, line in enumerate(lines) if idx not in drop]
        md.write_text("\n".join(kept), encoding="utf-8", newline="")
    return f"pruned {pruned} orphan auto-managed block(s)"


def _do_rotate(target: Path) -> str:
    today = dt.date.today().isoformat()
    archive = target.with_suffix(f".{today}.jsonl.archive")
    shutil.move(str(target), str(archive))
    target.write_text("", encoding="utf-8", newline="\n")
    return f"rotated {target.name} → {archive.name}"


# ---------------------------------------------------------------------------
# Entry processing
# ---------------------------------------------------------------------------


def _process_entry(entry: dict[str, Any], consumer_root: Path, apply: bool) -> EntryOutcome | None:
    safety_name = entry["safety"]
    check = SAFETY_CHECKS.get(safety_name)
    if check is None:
        return EntryOutcome(
            entry_id=entry["id"],
            tier=entry["tier"],
            action_taken="advisory",
            path=str(entry["path"]),
            detail=f"unknown safety `{safety_name}` — manifest schema bug",
        )

    # Resolve concrete target Path for actions that take a single path arg.
    # Globs are interpreted by safety checks / actions themselves.
    target = consumer_root / entry["path"]
    try:
        safety_result = check(target, entry, consumer_root)
    except Exception as exc:  # never let safety raise into the hook
        return EntryOutcome(
            entry_id=entry["id"],
            tier=entry["tier"],
            action_taken="advisory",
            path=str(entry["path"]),
            detail=f"safety raised: {exc}",
        )

    if not safety_result.passed:
        # Tier 3 always lands here (report_only); Tier 1/2 lands here on failed safety.
        if entry["tier"] == 3:
            return EntryOutcome(
                entry_id=entry["id"],
                tier=3,
                action_taken="advisory",
                path=str(entry["path"]),
                detail=entry["reason"],
            )
        # Tier 1/2 with failed safety: only emit advisory if the safety reason
        # is something other than "target absent" (no point reporting non-zombies).
        if "target absent" in safety_result.reason:
            return None
        return EntryOutcome(
            entry_id=entry["id"],
            tier=entry["tier"],
            action_taken="advisory",
            path=str(entry["path"]),
            detail=f"downgraded: {safety_result.reason}",
        )

    if entry["tier"] == 3:
        # Structural guard for the documented Tier 3 contract ("never modifies
        # the filesystem regardless of flags"). Until now that held only by
        # accident, because `report_only` always failed its safety check and
        # short-circuited above; a Tier 3 entry with a *passing* safety would
        # have fallen straight through to the action dispatch below.
        return EntryOutcome(
            entry_id=entry["id"],
            tier=3,
            action_taken="advisory",
            path=str(entry["path"]),
            detail=f"{entry['reason']} — {safety_result.reason}",
        )

    action = entry["action"]
    if not apply:
        # Dry-run: announce intent, do nothing.
        return EntryOutcome(
            entry_id=entry["id"],
            tier=entry["tier"],
            action_taken=f"would-{action}",
            path=str(entry["path"]),
            detail=safety_result.reason,
        )

    # Execute the action.
    try:
        if action == "delete":
            detail = _do_delete(target)
            kind = "deleted"
        elif action == "rename":
            detail = _do_rename(entry, consumer_root)
            kind = "renamed"
        elif action == "prune_blocks":
            detail = _do_prune_blocks(entry, consumer_root)
            kind = "pruned"
        elif action == "rotate":
            detail = _do_rotate(target)
            kind = "rotated"
        else:
            return EntryOutcome(
                entry_id=entry["id"],
                tier=entry["tier"],
                action_taken="advisory",
                path=str(entry["path"]),
                detail=f"unknown action `{action}` — manifest schema bug",
            )
    except Exception as exc:
        return EntryOutcome(
            entry_id=entry["id"],
            tier=entry["tier"],
            action_taken="advisory",
            path=str(entry["path"]),
            detail=f"action raised: {exc}",
        )
    return EntryOutcome(
        entry_id=entry["id"],
        tier=entry["tier"],
        action_taken=kind,
        path=str(entry["path"]),
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Channel writers
# ---------------------------------------------------------------------------


def _write_stdout_summary(report: RunReport, quiet: bool) -> None:
    if quiet:
        return
    if not report.has_any():
        return
    counts = report.counts()
    parts: list[str] = []
    if counts["deleted"]:
        parts.append(f"{counts['deleted']} deleted")
    if counts["would_delete"]:
        parts.append(f"{counts['would_delete']} would-delete")
    if counts["renamed"]:
        parts.append(f"{counts['renamed']} renamed")
    if counts["advisories"]:
        parts.append(f"{counts['advisories']} report{'s' if counts['advisories'] != 1 else ''}")
    summary = "🧹 cleanup_zombies: " + ", ".join(parts) + " — see .ai-playbook/zombie-report.md"
    print(summary)


def _write_report_file(report: RunReport, consumer_root: Path) -> None:
    report_path = consumer_root / REPORT_REL
    if not report.has_any():
        if report_path.is_file():
            report_path.unlink()
        return
    lines: list[str] = []
    lines.append(f"# Playbook zombie cleanup — {report.started_at} (manifest {report.manifest_version})")
    lines.append("")
    counts = report.counts()
    lines.append(
        f"**Counts**: {counts['deleted']} deleted · {counts['would_delete']} would-delete · "
        f"{counts['renamed']} renamed · {counts['advisories']} advisories"
    )
    lines.append("")
    for tier in (1, 2, 3):
        tier_outcomes = [o for o in report.outcomes if o.tier == tier]
        if not tier_outcomes:
            continue
        lines.append(f"## Tier {tier}")
        lines.append("")
        lines.append("| id | path | action_taken | detail |")
        lines.append("|---|---|---|---|")
        for outcome in tier_outcomes:
            lines.append(
                f"| `{outcome.entry_id}` | `{outcome.path}` | {outcome.action_taken} | {outcome.detail} |"
            )
        lines.append("")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def _write_injected_context(report: RunReport, consumer_root: Path) -> None:
    if not report.has_any():
        return
    path = consumer_root / INJECTED_CONTEXT_REL
    if not path.is_file():
        return
    try:
        existing = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    if INJECTED_CONTEXT_MARKER in existing:
        return  # already announced from a prior run; don't duplicate
    notice = (
        f"\n⚠ {INJECTED_CONTEXT_MARKER} on {report.started_at} — "
        f"see .ai-playbook/zombie-report.md\n"
    )
    try:
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(notice)
    except OSError as exc:
        print(f"warn: failed appending to {path}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Entry-points
# ---------------------------------------------------------------------------


def _run(
    *,
    manifest_path: Path,
    consumer_root: Path | None,
    apply: bool,
    quiet: bool,
) -> int:
    if os.environ.get("AIPLAYBOOK_CLEANUP_SKIP", "").strip():
        if not quiet:
            print(f"⚠ {SCRIPT_NAME}: skipped via AIPLAYBOOK_CLEANUP_SKIP", file=sys.stderr)
        return 0

    if consumer_root is None:
        consumer_root = _find_consumer_root(Path.cwd())
    if consumer_root is None:
        if not quiet:
            print(f"{SCRIPT_NAME}: no consumer root found (no .ai-playbook/ in any parent); skip", file=sys.stderr)
        return 0

    try:
        data = _load_manifest(manifest_path)
    except ManifestError as exc:
        print(f"warn: {SCRIPT_NAME}: {exc}", file=sys.stderr)
        return 0

    started_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    outcomes: list[EntryOutcome] = []
    for entry in data.get("entries", []):
        outcome = _process_entry(entry, consumer_root, apply)
        if outcome is not None:
            outcomes.append(outcome)

    report = RunReport(
        manifest_version=str(data.get("manifest_version", "unknown")),
        started_at=started_at,
        outcomes=outcomes,
    )

    try:
        _write_report_file(report, consumer_root)
    except Exception as exc:
        print(f"warn: failed writing report file: {exc}", file=sys.stderr)
    try:
        _write_injected_context(report, consumer_root)
    except Exception as exc:
        print(f"warn: failed writing injected-context: {exc}", file=sys.stderr)
    _write_stdout_summary(report, quiet=quiet)

    return 0


def _cmd_validate(manifest_path: Path) -> int:
    try:
        data = _load_manifest(manifest_path)
    except ManifestError as exc:
        # Per error-message-standard.md — emit WHY / WHERE / FIX / OVERRIDE shape.
        print(f"❌ {exc}", file=sys.stderr)
        print(f"   WHERE: {manifest_path}", file=sys.stderr)
        print("   FIX: restore the file to valid YAML per docs/rules/cleanup-zombies.rule.md §2", file=sys.stderr)
        print("   OVERRIDE: none (schema gate is structural)", file=sys.stderr)
        return 2
    errors = _validate_manifest(data)
    if errors:
        print(f"❌ manifest schema errors ({len(errors)}):", file=sys.stderr)
        for err in errors:
            print(f"   - {err}", file=sys.stderr)
        print(f"   WHERE: {manifest_path}", file=sys.stderr)
        print("   FIX: align entries with docs/rules/cleanup-zombies.rule.md §2", file=sys.stderr)
        print("   OVERRIDE: none (schema gate is structural)", file=sys.stderr)
        return 2
    print(f"✓ manifest {manifest_path} valid ({len(data['entries'])} entries, version {data['manifest_version']})")
    return 0


def _cmd_version(manifest_path: Path) -> int:
    try:
        data = _load_manifest(manifest_path)
    except ManifestError as exc:
        print(f"unknown ({exc})")
        return 0
    print(data.get("manifest_version", "unknown"))
    return 0


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cleanup_zombies",
        description="Consumer-side zombie cleanup driven by a declarative manifest.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Override manifest path (default: <playbook>/specs/zombies-manifest.yaml).",
    )
    parser.add_argument(
        "--consumer-root",
        type=Path,
        default=None,
        help="Override consumer root (default: cwd's nearest .ai-playbook/ ancestor).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute Tier 1 + Tier 2 actions (default: dry-run).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress stdout summary; still write report file + injected-context.",
    )
    sub = parser.add_subparsers(dest="subcommand")
    sub.add_parser("validate", help="Validate the manifest schema and exit (exit 2 on failure).")
    sub.add_parser("version", help="Print the manifest_version and exit.")
    return parser


def _resolve_default_manifest() -> Path:
    # v0.18.0: the script ships under <playbook>/scripts/rules/; the manifest
    # sits at <playbook>/specs/. Walk two parents up to reach the playbook root.
    return Path(__file__).resolve().parent.parent.parent / MANIFEST_REL


def main(argv: list[str] | None = None) -> int:
    parser = _build_argparser()
    args = parser.parse_args(argv)
    manifest_path = args.manifest if args.manifest else _resolve_default_manifest()
    if args.subcommand == "validate":
        return _cmd_validate(manifest_path)
    if args.subcommand == "version":
        return _cmd_version(manifest_path)
    try:
        return _run(
            manifest_path=manifest_path,
            consumer_root=args.consumer_root,
            apply=args.apply,
            quiet=args.quiet,
        )
    except Exception as exc:  # last-line defence: never break the hook
        print(f"warn: {SCRIPT_NAME}: unexpected error: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    # File-path invocation from a consumer root: put the playbook root on
    # sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("cleanup-zombies", main))
