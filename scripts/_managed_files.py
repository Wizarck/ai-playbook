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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts._backup_helper import BackupLocation, backup_once, restore_session  # noqa: E402
from scripts._marker_blocks import CommentStyle, MarkerBlock, parse_blocks, write_blocks  # noqa: E402
from scripts._renderers import (  # noqa: E402
    render_agents_md,
    render_claude_settings_local,
    render_coderabbit,
    render_gitignore,
    render_mcp_project,
    render_pre_commit,
    render_settings_json,
)
from scripts._template_classifier import compute_file_sha, compute_sha  # noqa: E402
from scripts.tracing import trace_emit  # noqa: E402

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
        rel_path=".claude/settings.json",
        template_rel=".claude/settings.json.tmpl",
        renderer=render_settings_json,
        trigger_section="settings",
        style=None,  # plain JSON — provenance preserved by identity deep-merge
        use_current_text=True,  # re-ensure the PreToolUse invariant on every reconcile
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
_LIST_ITEM_RE = re.compile(r"^\s*-\s*(.+?)\s*$")


def _extract_agents_md_frontmatter(consumer_root: Path) -> dict[str, str]:
    """Read project/owner/inherits_from from <consumer>/AGENTS.md frontmatter.

    Values may be inline scalars (``key: value``) OR YAML lists (a ``key:`` line
    with an empty value, followed by ``- item`` lines). For a list the first item
    is stored; for ``inherits_from`` an item carrying ``@`` (the pinned ref) is
    preferred so the playbook pin survives regardless of item order. The template's
    own frontmatter writes ``inherits_from`` as a list, so the scalar-only parse
    would otherwise blank PLAYBOOK_PIN on every template-shaped consumer.
    """
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
    lines = m.group(1).split("\n")
    out: dict[str, str] = {}
    i = 0
    while i < len(lines):
        kv = _KV_RE.match(lines[i])
        if not kv:
            i += 1
            continue
        key, value = kv.group(1), kv.group(2)
        if value == "":
            # Empty scalar — may be a YAML list: collect following "- item" lines.
            items: list[str] = []
            j = i + 1
            while j < len(lines):
                li = _LIST_ITEM_RE.match(lines[j])
                if not li:
                    break
                items.append(li.group(1))
                j += 1
            if items:
                out[key] = next((it for it in items if "@" in it), items[0])
                i = j
                continue
        out[key] = value
        i += 1
    return out


def compute_substitutions(consumer_root: Path) -> dict[str, str]:
    """Best-effort substitution mapping derived from the consumer's AGENTS.md.

    Falls back to plausible defaults when AGENTS.md is missing or malformed:
    PROJECT_NAME=<consumer dir name>, OWNER_EMAIL=unknown@example.com.
    """
    fm = _extract_agents_md_frontmatter(consumer_root)
    project_name = fm.get("project") or consumer_root.name
    inherits = fm.get("inherits_from") or ""
    playbook_pin = inherits.split("@")[-1] if "@" in inherits else ""
    if "inherits_from" in fm and not playbook_pin:
        # inherits_from was present but no pin could be recovered — surface it
        # rather than silently rendering a pinless pin (the markerless-pin bug).
        print(
            "warning: AGENTS.md inherits_from present but its pin could not be "
            "parsed; rendered pin will be empty",
            file=sys.stderr,
        )
    return {
        "PROJECT_NAME": project_name,
        "PROJECT_BANK": fm.get("project", project_name).lower(),
        "OWNER_EMAIL": fm.get("owner") or "unknown@example.com",
        "TODAY": datetime.now(UTC).date().isoformat(),
        "PLAYBOOK_PIN": playbook_pin,
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
# Conflict detection (two-state: marker sha vs computed content sha)
# ---------------------------------------------------------------------------


def _resolve_intent_action(block_id: str, intents: dict[str, Any] | None) -> str | None:
    """Return the consumer's explicit curate decision for ``block_id``, or None.

    ``"keep_mine"`` / ``"take_playbook"`` when ``bundle.file_curate_intents``
    names the block (per-block override, else the file's ``default_action``);
    ``None`` when the consumer expressed no decision — which the reconciler
    treats as an unresolved CONFLICT rather than a silent overwrite. This is
    the conflict-aware twin of ``agents_md._resolve_block_action`` (which falls
    back to ``take_playbook``); the difference is deliberate — the central gate
    must NOT assume consent.
    """
    if not intents:
        return None
    blocks = intents.get("blocks") or {}
    explicit = blocks.get(block_id)
    if explicit in ("take_playbook", "keep_mine"):
        return explicit
    default = intents.get("default_action")
    if default in ("take_playbook", "keep_mine"):
        return default
    return None


def _reconcile_blocks(
    *,
    style: CommentStyle | None,
    current_text: str | None,
    rendered: str,
    intents: dict[str, Any] | None,
) -> tuple[str | None, list[str]]:
    """Two-state conflict gate + keep_mine preservation, renderer-agnostic.

    For each canonical block present in BOTH the consumer's current file and
    the freshly-rendered output, compare the block content against the SHA
    embedded in its OWN marker on disk (``expected`` = marker sha, ``actual``
    = ``compute_sha(content)`` — the two-state model, no external manifest).
    A mismatch means the consumer edited sealed canonical content. The bundle's
    ``file_curate_intents`` decides what happens:

      * ``keep_mine``     → restore the consumer's content into the render
                            (re-sealing the sha so the next apply is clean)
      * ``take_playbook`` → let the rendered playbook content win (consented)
      * (no decision)     → CONFLICT: the file MUST NOT be written

    Returns ``(final_text | None, conflict_block_ids)``. ``final_text`` is
    ``None`` iff there is at least one unresolved conflict. Files without
    markers (``style is None``), without prior content, or with malformed
    markers pass through unchanged (no gate). Blocks whose on-disk marker
    carries no ``sha=`` (legacy / first-touch) are treated as a clean seed,
    never a conflict.
    """
    if style is None or not current_text:
        return rendered, []
    try:
        current = parse_blocks(current_text, style)
        rendered_parsed = parse_blocks(rendered, style)
    except ValueError:
        # Malformed markers — do not gate; let the renderer output stand.
        return rendered, []

    conflicts: list[str] = []
    overrides: dict[str, MarkerBlock] = {}
    for block_id, cur in current.blocks.items():
        if block_id not in rendered_parsed.blocks:
            continue
        if cur.sha is None:
            continue  # legacy / first-touch block — no prior sha to enforce
        if compute_sha(cur.content) == cur.sha:
            continue  # clean canonical — the consumer did not touch it
        # Drifted: the consumer edited a sealed canonical block.
        action = _resolve_intent_action(block_id, intents)
        if action == "keep_mine":
            overrides[block_id] = MarkerBlock(
                id=block_id, content=cur.content,
                sha=compute_sha(cur.content), style=style,
            )
        elif action == "take_playbook":
            continue  # consented overwrite — backup happens at commit
        else:
            conflicts.append(block_id)

    if conflicts:
        return None, sorted(conflicts)
    if overrides:
        rendered = write_blocks(rendered, overrides, style=style)
    return rendered, []


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

    triggered = [mf for mf in MANAGED_FILES if mf.trigger_section in bundle]
    if not triggered:
        result.detail = (
            "DRY-RUN: no managed-file sections in bundle — no-op" if dry_run
            else "no managed-file trigger sections in bundle — no-op"
        )
        return result

    substitutions = compute_substitutions(consumer_root)
    location, with_ts = _resolve_backup_pref(bundle)
    templates_root = playbook_root / "templates" / "new-project"
    timestamp_iso = datetime.now(UTC).isoformat()
    curate_intents = bundle.get("file_curate_intents") or {}
    base_shas = bundle.get("base_shas") or {}  # compare-and-swap tokens from the UI

    # --- STAGE: render everything in memory; gate conflicts; decide writes. ---
    # Runs identically for dry-run (= CHECK) and commit; only the COMMIT phase
    # below is gated on `not dry_run`. A planned write is
    # (dest, rendered_text, ManagedFile, existed_before).
    planned: list[tuple[Path, str, ManagedFile, bool]] = []
    staging_failed = False  # a render/template error ⇒ abort the whole batch
    conflicts: list[str] = []  # drifted-without-decision ⇒ per-file skip
    for mf in triggered:
        template_path = templates_root / mf.template_rel
        if not template_path.is_file():
            result.changes.append(f"⚠ {mf.rel_path}: template missing at {template_path}, skipped")
            continue
        try:
            template = template_path.read_text(encoding="utf-8")
        except OSError as exc:
            result.changes.append(f"⚠ {mf.rel_path}: cannot read template ({exc})")
            result.ok = False
            staging_failed = True
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
                staging_failed = True
                result.changes.append(f"✗ {mf.rel_path}: render failed ({exc})")
                continue
            planned.append((dest, rendered, mf, existed))
            continue

        # Compare-and-swap gate: if the UI stamped a base sha for this file and
        # the on-disk content changed since (someone edited it after the UI
        # loaded), refuse the write — the intended edit was computed against
        # stale content. Per-file skip; the rest of the batch still applies.
        base_sha = base_shas.get(mf.rel_path)
        if existed and current_text is not None and base_sha is not None:
            actual_file_sha = compute_file_sha(current_text)
            if actual_file_sha != base_sha:
                result.ok = False
                conflicts.append(f"{mf.rel_path} (CAS)")
                result.file_states[mf.rel_path] = {
                    "cas_conflict": {"base": base_sha, "actual": actual_file_sha},
                    "last_seen": timestamp_iso,
                }
                result.changes.append(
                    f"✗ {mf.rel_path}: changed on disk since the UI loaded it "
                    f"(compare-and-swap conflict) — not written"
                )
                trace_emit.add_event(
                    "reconcile.managed_files.cas_conflict",
                    {
                        "ai_playbook.managed_files.file": mf.rel_path,
                        "ai_playbook.managed_files.base_sha": base_sha,
                        "ai_playbook.managed_files.actual_sha": actual_file_sha,
                    },
                )
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
            staging_failed = True
            result.changes.append(f"✗ {mf.rel_path}: render failed ({exc})")
            continue

        # Conflict gate: never silently overwrite a canonical block the
        # consumer edited without an explicit curate decision (two-state model).
        final_text, conflict_ids = _reconcile_blocks(
            style=mf.style,
            current_text=current_text,
            rendered=rendered,
            intents=curate_intents.get(mf.rel_path),
        )
        if conflict_ids:
            result.ok = False
            conflicts.extend(f"{mf.rel_path}#{bid}" for bid in conflict_ids)
            result.file_states[mf.rel_path] = {
                "conflict": conflict_ids,
                "last_seen": timestamp_iso,
            }
            result.changes.append(
                f"✗ {mf.rel_path}: {len(conflict_ids)} drifted canonical block(s) "
                f"without a curate decision — not written "
                f"(conflict: {', '.join(conflict_ids)})"
            )
            trace_emit.add_event(
                "reconcile.managed_files.conflict",
                {
                    "ai_playbook.managed_files.file": mf.rel_path,
                    "ai_playbook.managed_files.conflict_blocks": ",".join(conflict_ids),
                },
            )
            continue
        rendered = final_text  # type: ignore[assignment]  # not None when no conflict

        # Skip no-op writes — saves backup churn but still records the manifest.
        if current_text is not None and rendered == current_text:
            result.file_states[mf.rel_path] = {
                "manifest": _build_manifest_for_file(rendered, mf.style),
                "last_applied": timestamp_iso,
            }
            result.changes.append(f"· {mf.rel_path}: identical, no write")
            continue

        planned.append((dest, rendered, mf, existed))

    # A render/template error ⇒ abort before any write so the disk is left
    # untouched (the transaction never enters the commit phase). Conflicts are
    # NOT a hard staging failure: they skip their own file but let the rest of
    # the batch commit, while still marking the section ok=False so
    # applied-config does not advance past unresolved drift.
    if staging_failed:
        result.changes.append("⚠ staging failed; no files written (transaction aborted)")
        trace_emit.add_event(
            "reconcile.managed_files.stage_failed",
            {"ai_playbook.managed_files.planned": len(planned)},
        )
        return result

    if dry_run:
        rels = [mf.rel_path for _, _, mf, _ in planned]
        parts: list[str] = []
        if rels:
            parts.append(f"DRY-RUN would render {len(rels)} managed file(s): {', '.join(rels)}")
        if conflicts:
            parts.append(f"{len(conflicts)} unresolved conflict(s): {', '.join(conflicts)}")
        result.detail = " — ".join(parts) if parts else (
            "DRY-RUN: managed files in sync — no-op"
        )
        return result

    trace_emit.add_event(
        "reconcile.managed_files.staged",
        {
            "ai_playbook.managed_files.planned": len(planned),
            "ai_playbook.managed_files.conflicts": len(conflicts),
        },
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

    if not planned and not conflicts:
        result.detail = "managed files already in sync — no writes"
    return result


__all__ = [
    "MANAGED_FILES",
    "ManagedFile",
    "ManagedFilesResult",
    "apply_managed_files",
    "compute_substitutions",
]
