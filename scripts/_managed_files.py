"""Apply bundle to managed consumer files.

This module orchestrates the file rendering portion of ``apply_config``:
backup_once → render → atomic write, per file. The catalog of managed
files lives here so the renderer modules stay decoupled from policy.

The flow per file:

1. Locate the template at ``<playbook>/templates/new-project/<template_rel>``.
   If missing, the file is skipped with a detail line (defensive — should
   never happen on a fresh checkout).
2. Compute substitutions: PROJECT_NAME, OWNER_EMAIL, TODAY, PLAYBOOK_PIN,
   PROJECT_BANK. Sourced from the existing AGENTS.md frontmatter when
   present; falls back to bundle hints or empty strings.
3. Call the renderer with (template, substitutions, bundle) plus
   optional ``current_text``.
4. If the destination already exists, ``backup_once`` it using the
   ``bundle.backup_preferences`` settings.
5. Write the new content via ``_atomic_write_text``.
6. Record the SHA manifest for the file under
   ``bundle.file_states[<rel_path>].manifest`` so the next apply / UI
   open can detect drift.

Triggering: a file is only re-rendered when its ``trigger_section`` is
present in the bundle. This keeps legacy bundles (no managed-files
intent) backwards-compatible — they take no action against these files.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts._backup_helper import BackupLocation, backup_once, restore_session
from scripts._marker_blocks import CommentStyle, parse_blocks
from scripts.tracing import trace_emit
from scripts._renderers import (
    render_agents_md,
    render_claude_settings,
    render_claude_settings_local,
    render_coderabbit,
    render_gitignore,
    render_mcp_project,
    render_pre_commit,
)
from scripts._template_classifier import compute_sha


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManagedFile:
    rel_path: str               # path relative to consumer root
    template_rel: str           # path relative to templates/new-project/
    renderer: Callable[..., str]
    trigger_section: str        # bundle key — render only when present
    style: CommentStyle | None  # for manifest computation
    use_current_text: bool = False  # pass current consumer text to renderer
    seed_only: bool = False     # only create if missing (e.g. settings.local.json)


MANAGED_FILES: list[ManagedFile] = [
    ManagedFile(
        rel_path="AGENTS.md",
        template_rel="AGENTS.md.tmpl",
        renderer=render_agents_md,
        trigger_section="project_meta",
        style=CommentStyle.HTML,
        use_current_text=True,  # for keep_mine curate intents
    ),
    ManagedFile(
        rel_path=".gitignore",
        template_rel=".gitignore.tmpl",
        renderer=render_gitignore,
        trigger_section="gitignore_extras",
        style=CommentStyle.HASH,
        use_current_text=True,
    ),
    ManagedFile(
        rel_path=".pre-commit-config.yaml",
        template_rel=".pre-commit-config.yaml.tmpl",
        renderer=render_pre_commit,
        trigger_section="pre_commit_extras",
        style=CommentStyle.HASH,
    ),
    ManagedFile(
        rel_path=".coderabbit.yaml",
        template_rel=".coderabbit.yaml.tmpl",
        renderer=render_coderabbit,
        trigger_section="coderabbit_extras",
        style=None,  # no marker blocks today
    ),
    ManagedFile(
        rel_path=".claude/settings.local.json",
        template_rel=".claude/settings.local.json.tmpl",
        renderer=render_claude_settings_local,
        trigger_section="claude_settings_extras",
        style=None,
        seed_only=True,
    ),
    ManagedFile(
        rel_path="mcp-servers.project.yaml",
        template_rel="mcp-servers.project.yaml.tmpl",
        renderer=render_mcp_project,
        trigger_section="mcp_project_servers",
        style=CommentStyle.HASH,
    ),
]


# ---------------------------------------------------------------------------
# Section result (mirrors apply_config.SectionResult to avoid circular import)
# ---------------------------------------------------------------------------


@dataclass
class ManagedFilesResult:
    name: str = "managed_files"
    ok: bool = True
    detail: str = ""
    changes: list[str] = field(default_factory=list)
    file_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Per-file SHA manifest of the post-render content. To be merged into
    the bundle's `file_states` before persistence."""
    restart_session_needed: bool = False
    """Set when any LLM-read file (AGENTS.md, CLAUDE.md, GEMINI.md, .claude/*)
    was modified. apply_config surfaces this as a restart-session banner."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_KV_RE = re.compile(r"^([A-Za-z0-9_]+)\s*:\s*(.*?)\s*$")


def _extract_agents_md_frontmatter(consumer_root: Path) -> dict[str, str]:
    """Read project/owner from <consumer>/AGENTS.md frontmatter if present."""
    p = consumer_root / "AGENTS.md"
    if not p.is_file():
        return {}
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).split("\n"):
        kv = _KV_RE.match(line)
        if kv:
            out[kv.group(1)] = kv.group(2)
    return out


def compute_substitutions(consumer_root: Path) -> dict[str, str]:
    """Best-effort substitution mapping derived from the consumer's AGENTS.md.

    Falls back to plausible defaults when AGENTS.md is missing or malformed:
    PROJECT_NAME=<consumer dir name>, OWNER_EMAIL=unknown@example.com.
    """
    fm = _extract_agents_md_frontmatter(consumer_root)
    project_name = fm.get("project") or consumer_root.name
    return {
        "PROJECT_NAME": project_name,
        "PROJECT_BANK": fm.get("project", project_name).lower(),
        "OWNER_EMAIL": fm.get("owner") or "unknown@example.com",
        "TODAY": datetime.now(UTC).date().isoformat(),
        "PLAYBOOK_PIN": fm.get("inherits_from", "").split("@")[-1] if fm.get("inherits_from") else "",
    }


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _resolve_backup_pref(bundle: dict[str, Any]) -> tuple[BackupLocation, bool]:
    prefs = bundle.get("backup_preferences") or {}
    location_str = prefs.get("location", "next")
    location = (
        BackupLocation.CENTRAL if location_str == "central"
        else BackupLocation.NEXT_TO_FILE
    )
    with_ts = bool(prefs.get("with_timestamp", True))
    return location, with_ts


def _build_manifest_for_file(text: str, style: CommentStyle | None) -> dict[str, str]:
    """Compute {block_id: sha} for the marker blocks in ``text``.

    Returns an empty dict when style is None (file has no marker blocks).
    """
    if style is None:
        return {}
    parsed = parse_blocks(text, style)
    return {bid: compute_sha(block.content) for bid, block in parsed.blocks.items()}


_LLM_READ_FILES = frozenset({
    "AGENTS.md", "CLAUDE.md", "GEMINI.md",
    ".claude/settings.json", ".claude/settings.local.json",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_managed_files(
    *,
    consumer_root: Path,
    playbook_root: Path,
    bundle: dict[str, Any],
    session_id: str | None = None,
    dry_run: bool = False,
) -> ManagedFilesResult:
    """Render each managed file whose trigger_section is present in the bundle.

    Returns a ``ManagedFilesResult`` carrying:
      - ``changes``: human-readable description of what happened per file
      - ``file_states``: ``{rel_path: {manifest: {block_id: sha}, last_applied: iso}}``
        to be merged into the bundle's persistence
      - ``restart_session_needed``: True when AGENTS.md / CLAUDE.md / GEMINI.md /
        .claude/* were modified (consumer should restart Claude Code / Gemini CLI)
    """
    result = ManagedFilesResult()

    if dry_run:
        triggered = [mf.rel_path for mf in MANAGED_FILES if mf.trigger_section in bundle]
        result.detail = (
            f"DRY-RUN would render {len(triggered)} managed file(s): {', '.join(triggered)}"
            if triggered else "DRY-RUN: no managed-file sections in bundle — no-op"
        )
        return result

    substitutions = compute_substitutions(consumer_root)
    location, with_ts = _resolve_backup_pref(bundle)
    templates_root = playbook_root / "templates" / "new-project"
    timestamp_iso = datetime.now(UTC).isoformat()

    # --- STAGE: render everything in memory; decide writes; detect failures. ---
    # A planned write is (dest, rendered_text, ManagedFile, existed_before).
    planned: list[tuple[Path, str, ManagedFile, bool]] = []
    for mf in MANAGED_FILES:
        if mf.trigger_section not in bundle:
            continue
        template_path = templates_root / mf.template_rel
        if not template_path.is_file():
            result.changes.append(f"⚠ {mf.rel_path}: template missing at {template_path}, skipped")
            continue
        try:
            template = template_path.read_text(encoding="utf-8")
        except OSError as exc:
            result.changes.append(f"⚠ {mf.rel_path}: cannot read template ({exc})")
            result.ok = False
            continue

        dest = consumer_root / mf.rel_path
        existed = dest.is_file()
        current_text: str | None = None
        if existed:
            try:
                current_text = dest.read_text(encoding="utf-8")
            except OSError:
                current_text = None

        if mf.seed_only:
            if existed:
                result.changes.append(f"· {mf.rel_path}: seed-only, kept as-is")
                continue
            try:
                rendered = mf.renderer(
                    template=template, substitutions=substitutions, bundle=bundle,
                )
            except Exception as exc:  # noqa: BLE001
                result.ok = False
                result.changes.append(f"✗ {mf.rel_path}: render failed ({exc})")
                continue
            planned.append((dest, rendered, mf, existed))
            continue

        try:
            if mf.use_current_text:
                rendered = mf.renderer(
                    template=template, substitutions=substitutions,
                    bundle=bundle, current_text=current_text,
                )
            else:
                rendered = mf.renderer(
                    template=template, substitutions=substitutions, bundle=bundle,
                )
        except Exception as exc:  # noqa: BLE001
            result.ok = False
            result.changes.append(f"✗ {mf.rel_path}: render failed ({exc})")
            continue

        # Skip no-op writes — saves backup churn but still records the manifest.
        if current_text is not None and rendered == current_text:
            result.file_states[mf.rel_path] = {
                "manifest": _build_manifest_for_file(rendered, mf.style),
                "last_applied": timestamp_iso,
            }
            result.changes.append(f"· {mf.rel_path}: identical, no write")
            continue

        planned.append((dest, rendered, mf, existed))

    # Staging failure (a render/template error) ⇒ abort before any write so the
    # disk is left untouched (the transaction never enters the commit phase).
    if not result.ok:
        result.changes.append("⚠ staging failed; no files written (transaction aborted)")
        trace_emit.add_event(
            "reconcile.managed_files.stage_failed",
            {"ai_playbook.managed_files.planned": len(planned)},
        )
        return result

    trace_emit.add_event(
        "reconcile.managed_files.staged",
        {"ai_playbook.managed_files.planned": len(planned)},
    )

    # --- COMMIT: backup + atomic-write the planned set under one session_id. ---
    created_fresh: list[Path] = []
    for dest, rendered, mf, existed in planned:
        try:
            if existed:
                backup_once(
                    consumer_root, dest,
                    location=location, with_timestamp=with_ts,
                    session_id=session_id,
                )
            _atomic_write_text(dest, rendered)
        except (OSError, ValueError) as exc:
            # Roll the whole batch back: restore overwritten files from the
            # session backups and delete files this batch newly created.
            result.ok = False
            result.changes.append(f"✗ {mf.rel_path}: commit failed ({exc})")
            if session_id:
                restored, warnings = restore_session(consumer_root, session_id)
                result.changes.append(
                    f"↩ rolled back {len(restored)} overwritten file(s) "
                    f"from session {session_id}"
                )
                result.changes.extend(f"⚠ rollback: {w}" for w in warnings)
            for fresh in created_fresh:
                try:
                    fresh.unlink()
                except OSError:
                    pass
            if created_fresh:
                result.changes.append(
                    f"↩ removed {len(created_fresh)} newly-created file(s)"
                )
            trace_emit.add_event(
                "reconcile.managed_files.rolled_back",
                {
                    "ai_playbook.managed_files.session_id": session_id or "",
                    "ai_playbook.managed_files.failed_file": mf.rel_path,
                    "ai_playbook.managed_files.removed": len(created_fresh),
                },
            )
            return result

        if not existed:
            created_fresh.append(dest)
        manifest = _build_manifest_for_file(rendered, mf.style)
        result.file_states[mf.rel_path] = {
            "manifest": manifest, "last_applied": timestamp_iso,
        }
        if mf.seed_only and not existed:
            result.changes.append(f"✓ {mf.rel_path}: seeded (new file)")
        else:
            result.changes.append(
                f"✓ {mf.rel_path}: rendered ({len(manifest)} canonical block(s))"
            )
        if mf.rel_path in _LLM_READ_FILES:
            result.restart_session_needed = True

    trace_emit.add_event(
        "reconcile.managed_files.committed",
        {"ai_playbook.managed_files.written": len(planned)},
    )

    if not result.changes:
        result.detail = "no managed-file trigger sections in bundle — no-op"
    return result


__all__ = [
    "MANAGED_FILES",
    "ManagedFile",
    "ManagedFilesResult",
    "apply_managed_files",
    "compute_substitutions",
]
