"""Zero-touch release automation on semver tag push.

Intended to be run from a GitHub Action wired to ``push`` events that match
``v*.*.*``. Also runnable manually for ops / testing.

Steps (public repo)
-------------------
1. Resolve current tag (``git describe --tags --exact-match``).
2. Extract the CHANGELOG.md section matching the tag.
3. Collect OpenSpec changes archived since the previous tag.
4. ``gh release create <tag> --notes-file <section>``.

Steps (private repo)
--------------------
1. Same resolution as above.
2. Create (or reuse) a Jira fixVersion named ``<repo>-<semver>``.
3. Mark every ``tracker_id`` from archived changes as ``Released`` with the
   fixVersion set.

Notifications (every step)
--------------------------
- ``release_cut.start`` — info.
- ``release_cut.changes_collected`` — info.
- ``release_cut.github_released`` — info (public path).
- ``release_cut.jira_fixversion_created`` — info (private path).
- ``release_cut.failed`` — error.
- ``release_cut.complete`` — info.

CLI
---
    python -m scripts.release_cut [--tag TAG] [--dry-run] [--force-with-reason TEXT]

Exit codes
----------
    0 — success (including dry-run)
    1 — logical failure (missing CHANGELOG section, tag not found, GH release exists)
    2 — setup error (not a git repo, gh/jira auth missing when required)
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

# Force UTF-8 stdio.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


from scripts import issue_sync  # noqa: E402  # reuse parse_frontmatter, creds, etc.
from scripts import notify as notify_mod  # noqa: E402
from scripts._break_glass import add_break_glass_flag, apply_break_glass  # noqa: E402

SCRIPT_BASENAME = "release_cut.py"
GATE_NAME = "release-cut-preflight"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ReleaseContext:
    tag: str
    previous_tag: str | None
    repo_root: Path
    changelog_section: str
    archived_changes: list[Path]
    tracker_ids: list[str]
    is_public: bool
    repo_nwo: str | None


@dataclass
class ReleaseOutcome:
    ok: bool
    steps: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Canonical error
# ---------------------------------------------------------------------------


def emit_error(
    *, why: str, where: str, fix: str, override_invocation: str | None,
) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    if override_invocation is None:
        print("   OVERRIDE: none", file=sys.stderr)
    else:
        print(f"   OVERRIDE: {override_invocation}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=30, cwd=cwd,
        )
        return out.returncode, out.stdout, out.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", f"{exc.__class__.__name__}:{exc}"


def resolve_tag(cwd: Path, *, explicit: str | None = None) -> str | None:
    if explicit:
        # Confirm the tag actually exists.
        rc, out, _ = _run_git(["tag", "-l", explicit], cwd)
        if rc == 0 and out.strip() == explicit:
            return explicit
        return None
    rc, out, _ = _run_git(["describe", "--tags", "--exact-match"], cwd)
    if rc != 0:
        return None
    return out.strip() or None


def resolve_previous_tag(cwd: Path, current: str) -> str | None:
    rc, out, _ = _run_git(
        ["describe", "--tags", "--abbrev=0", f"{current}^"], cwd,
    )
    if rc != 0:
        return None
    return out.strip() or None


def archived_change_proposals(
    cwd: Path, *, since_tag: str | None, current_tag: str,
) -> list[Path]:
    """Return proposal.md paths archived between since_tag..current_tag."""
    rev_range = (
        f"{since_tag}..{current_tag}" if since_tag else current_tag
    )
    rc, out, _ = _run_git(
        ["log", "--diff-filter=A", "--name-only", "--pretty=format:",
         rev_range, "--", "openspec/changes/archive/"],
        cwd,
    )
    if rc != 0:
        return []
    seen: set[str] = set()
    results: list[Path] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        if not line.endswith("/proposal.md"):
            continue
        if line in seen:
            continue
        seen.add(line)
        p = cwd / line
        results.append(p)
    return results


def tracker_ids_from_proposals(paths: list[Path]) -> list[str]:
    ids: list[str] = []
    for p in paths:
        if not p.is_file():
            continue
        try:
            fm, _ = issue_sync.parse_frontmatter(p.read_text(encoding="utf-8"))
        except OSError:
            continue
        key = fm.get("tracker_id") or fm.get("tracker_issue")
        if key:
            ids.append(key)
    return ids


# ---------------------------------------------------------------------------
# CHANGELOG parsing
# ---------------------------------------------------------------------------


def extract_changelog_section(changelog_path: Path, tag: str) -> str | None:
    """Return the section text for a given tag (strip header).

    Accepts headings like ``## v1.2.3`` / ``## 1.2.3`` / ``## [1.2.3]`` — the
    version must appear verbatim (with or without the ``v`` prefix).
    """
    if not changelog_path.is_file():
        return None
    try:
        text = changelog_path.read_text(encoding="utf-8")
    except OSError:
        return None
    text = text.replace("\r\n", "\n")

    candidates = {tag, tag.lstrip("v"), f"v{tag.lstrip('v')}"}
    lines = text.split("\n")
    start: int | None = None
    end: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("##"):
            continue
        # Level-2 header.
        heading = stripped.lstrip("#").strip()
        # Take the first token of the heading (strip brackets).
        token = heading.split()[0] if heading else ""
        token_clean = token.strip("[]():")
        if start is None and token_clean in candidates:
            start = i + 1
            continue
        if start is not None and stripped.startswith("## "):
            end = i
            break
    if start is None:
        return None
    body = "\n".join(lines[start:end]).strip("\n")
    return body or None


# ---------------------------------------------------------------------------
# GH release
# ---------------------------------------------------------------------------


def gh_release_exists(tag: str, cwd: Path) -> bool:
    try:
        out = subprocess.run(
            ["gh", "release", "view", tag], capture_output=True, text=True,
            timeout=15, cwd=cwd,
        )
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def gh_release_create(
    *, tag: str, notes_file: Path, cwd: Path, dry_run: bool = False,
) -> tuple[bool, str]:
    if dry_run:
        return True, "dry-run"
    try:
        out = subprocess.run(
            ["gh", "release", "create", tag, "--notes-file", str(notes_file)],
            capture_output=True, text=True, timeout=60, cwd=cwd,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"subprocess:{exc.__class__.__name__}"
    if out.returncode != 0:
        return False, (out.stderr.strip() or f"rc-{out.returncode}")
    return True, "ok"


# ---------------------------------------------------------------------------
# Jira fixVersion
# ---------------------------------------------------------------------------


def _jira_authorised_request(
    *, creds: issue_sync.JiraCreds, method: str, path: str,
    body: dict[str, Any] | None = None, timeout: float = 10.0,
) -> tuple[int, Any, str]:
    """Return (status, parsed_json_or_None, reason). `parsed` may be a dict OR list
    depending on the endpoint (e.g. `/project/KEY/versions` returns a list)."""
    endpoint = f"{creds.url}{path}"
    auth = base64.b64encode(
        f"{creds.username}:{creds.api_token}".encode()
    ).decode("ascii")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urlrequest.Request(
        endpoint, data=data, method=method,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ai-playbook/release_cut",
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = None
            status = getattr(resp, "status", None) or getattr(resp, "code", 200)
            return status, parsed, "ok"
    except urlerror.HTTPError as exc:
        raw = ""
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
        return exc.code, None, raw or f"http-{exc.code}"
    except urlerror.URLError as exc:
        return 0, None, f"url:{exc.reason}"
    except (OSError, TimeoutError) as exc:
        return 0, None, f"os:{exc}"


def jira_find_or_create_fixversion(
    *, creds: issue_sync.JiraCreds, project_key: str, name: str,
) -> tuple[str | None, str]:
    """Return (fixversion_id, reason). Idempotent — reuses existing name."""
    status, payload, msg = _jira_authorised_request(
        creds=creds, method="GET",
        path=f"/rest/api/3/project/{project_key}/versions",
    )
    if status == 200 and isinstance(payload, (list, dict)):
        items = payload if isinstance(payload, list) else payload.get("values", [])
        for v in items or []:
            if isinstance(v, dict) and v.get("name") == name:
                vid = v.get("id")
                if isinstance(vid, (str, int)):
                    return str(vid), "exists"
    # Create
    status, payload, msg = _jira_authorised_request(
        creds=creds, method="POST", path="/rest/api/3/version",
        body={"name": name, "project": project_key},
    )
    if status in (200, 201) and isinstance(payload, dict) and payload.get("id"):
        return str(payload["id"]), "created"
    return None, f"create-failed:{msg}"


def jira_mark_released(
    *, creds: issue_sync.JiraCreds, tracker_id: str, fixversion_name: str,
) -> tuple[bool, str]:
    """Add fixVersion + transition to ``Released`` where possible."""
    status, _, msg = _jira_authorised_request(
        creds=creds, method="PUT",
        path=f"/rest/api/3/issue/{tracker_id}",
        body={"update": {"fixVersions": [{"add": {"name": fixversion_name}}]}},
    )
    if status not in (200, 204):
        return False, f"update:{msg}"

    # Try to find a "Released" transition id and apply it.
    status, payload, msg = _jira_authorised_request(
        creds=creds, method="GET",
        path=f"/rest/api/3/issue/{tracker_id}/transitions",
    )
    released_id: str | None = None
    if status == 200 and isinstance(payload, dict):
        for t in payload.get("transitions", []) or []:
            if isinstance(t, dict) and (t.get("name") or "").lower() in ("released", "done"):
                released_id = t.get("id")
                if released_id:
                    break
    if released_id:
        _jira_authorised_request(
            creds=creds, method="POST",
            path=f"/rest/api/3/issue/{tracker_id}/transitions",
            body={"transition": {"id": str(released_id)}},
        )
    return True, "ok"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def build_context(
    *, repo_root: Path, tag_override: str | None,
) -> tuple[ReleaseContext | None, str]:
    tag = resolve_tag(repo_root, explicit=tag_override)
    if not tag:
        return None, "tag-not-found"

    previous = resolve_previous_tag(repo_root, tag)
    section = extract_changelog_section(repo_root / "CHANGELOG.md", tag)
    if section is None:
        return None, "changelog-section-missing"

    archived = archived_change_proposals(repo_root, since_tag=previous, current_tag=tag)
    tracker_ids = tracker_ids_from_proposals(archived)

    visibility = issue_sync._gh_repo_visibility(repo_root)
    is_public = visibility == "PUBLIC"
    nwo = issue_sync._gh_repo_nwo(repo_root)

    return ReleaseContext(
        tag=tag,
        previous_tag=previous,
        repo_root=repo_root,
        changelog_section=section,
        archived_changes=archived,
        tracker_ids=tracker_ids,
        is_public=is_public,
        repo_nwo=nwo,
    ), "ok"


def run_release(
    *, repo_root: Path, tag_override: str | None = None, dry_run: bool = False,
) -> tuple[int, ReleaseOutcome]:
    outcome = ReleaseOutcome(ok=False)

    notify_mod.notify(
        event="release_cut.start",
        severity="info",
        summary="release_cut starting",
        attrs={"repo_root": str(repo_root), "tag_override": tag_override},
    )

    ctx, reason = build_context(repo_root=repo_root, tag_override=tag_override)
    if ctx is None:
        notify_mod.notify(
            event="release_cut.failed",
            severity="error",
            summary=f"release_cut preflight failed: {reason}",
            attrs={"step": "build_context", "reason": reason},
        )
        outcome.errors.append(reason)
        return (1 if reason in ("tag-not-found", "changelog-section-missing") else 2, outcome)

    notify_mod.notify(
        event="release_cut.changes_collected",
        severity="info",
        summary=f"{len(ctx.archived_changes)} archived changes / {len(ctx.tracker_ids)} tracker ids",
        attrs={
            "tag": ctx.tag,
            "previous_tag": ctx.previous_tag,
            "n_changes": len(ctx.archived_changes),
            "n_tracker_ids": len(ctx.tracker_ids),
        },
    )
    outcome.steps.append("changes_collected")

    if ctx.is_public:
        if gh_release_exists(ctx.tag, ctx.repo_root):
            notify_mod.notify(
                event="release_cut.failed",
                severity="error",
                summary=f"GH release {ctx.tag} already exists; refusing to overwrite",
                attrs={"step": "gh-release-exists", "tag": ctx.tag},
            )
            outcome.errors.append("gh-release-exists")
            return 1, outcome

        notes_path = ctx.repo_root / ".ai-playbook" / f"release-notes-{ctx.tag}.md"
        try:
            notes_path.parent.mkdir(parents=True, exist_ok=True)
            notes_path.write_text(ctx.changelog_section, encoding="utf-8")
        except OSError as exc:
            notify_mod.notify(
                event="release_cut.failed",
                severity="error",
                summary=f"cannot write notes file: {exc}",
                attrs={"step": "notes-file"},
            )
            outcome.errors.append(f"notes-file:{exc}")
            return 2, outcome

        ok, info = gh_release_create(
            tag=ctx.tag, notes_file=notes_path, cwd=ctx.repo_root, dry_run=dry_run,
        )
        if not ok:
            notify_mod.notify(
                event="release_cut.failed",
                severity="error",
                summary=f"gh release create failed: {info}",
                attrs={"step": "gh-release-create", "reason": info},
            )
            outcome.errors.append(f"gh-release-create:{info}")
            return 1, outcome
        notify_mod.notify(
            event="release_cut.github_released",
            severity="info",
            summary=f"GH release created for {ctx.tag}",
            attrs={"tag": ctx.tag, "repo": ctx.repo_nwo, "dry_run": dry_run},
        )
        outcome.steps.append("github_released")
    else:
        creds = issue_sync._load_jira_creds()
        if not creds:
            notify_mod.notify(
                event="release_cut.failed",
                severity="error",
                summary="Jira credentials missing for private release",
                attrs={"step": "jira-creds"},
            )
            outcome.errors.append("jira-creds")
            return 2, outcome

        project_key = issue_sync._jira_project_for(issue_sync._consumer_name(ctx.repo_root))
        fv_name = f"{ctx.repo_root.name}-{ctx.tag.lstrip('v')}"

        if dry_run:
            notify_mod.notify(
                event="release_cut.jira_fixversion_created",
                severity="info",
                summary=f"(dry-run) Would create/reuse Jira fixVersion {fv_name}",
                attrs={"project": project_key, "fixVersion": fv_name, "dry_run": True},
            )
            outcome.steps.append("jira_fixversion_created")
        else:
            fv_id, fv_reason = jira_find_or_create_fixversion(
                creds=creds, project_key=project_key, name=fv_name,
            )
            if not fv_id:
                notify_mod.notify(
                    event="release_cut.failed",
                    severity="error",
                    summary=f"Jira fixVersion create failed: {fv_reason}",
                    attrs={"step": "jira-fixversion", "reason": fv_reason},
                )
                outcome.errors.append(f"jira-fixversion:{fv_reason}")
                return 1, outcome
            notify_mod.notify(
                event="release_cut.jira_fixversion_created",
                severity="info",
                summary=f"Jira fixVersion {fv_name} ({fv_reason})",
                attrs={"project": project_key, "fixVersion": fv_name, "state": fv_reason},
            )
            outcome.steps.append("jira_fixversion_created")

            for tid in ctx.tracker_ids:
                ok_m, msg_m = jira_mark_released(
                    creds=creds, tracker_id=tid, fixversion_name=fv_name,
                )
                if not ok_m:
                    notify_mod.notify(
                        event="release_cut.failed",
                        severity="warn",
                        summary=f"could not mark {tid} released: {msg_m}",
                        attrs={"step": "jira-mark-released", "tracker_id": tid},
                    )

    outcome.ok = True
    notify_mod.notify(
        event="release_cut.complete",
        severity="info",
        summary=(
            f"release_cut complete for {ctx.tag}: "
            f"{'public' if ctx.is_public else 'private'} surface; "
            f"{len(ctx.tracker_ids)} trackers touched"
        ),
        attrs={
            "tag": ctx.tag,
            "surface": "github" if ctx.is_public else "jira",
            "n_tracker_ids": len(ctx.tracker_ids),
            "dry_run": dry_run,
        },
    )
    return 0, outcome


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="release_cut",
        description="Zero-touch release automation (GH release or Jira fixVersion).",
    )
    p.add_argument("--tag", default=None, help="Tag to release (default: current HEAD tag).")
    p.add_argument("--repo-root", type=Path, default=None, help="Repo root (default: cwd).")
    p.add_argument("--dry-run", action="store_true", help="Do everything except create/publish.")
    add_break_glass_flag(p)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = (args.repo_root or Path.cwd()).expanduser().resolve()

    if not (repo_root / ".git").exists():
        # Honour break-glass.
        result = apply_break_glass(
            gate=GATE_NAME, script=SCRIPT_BASENAME,
            reason=args.force_reason, override_allowed=True,
            repo_root=repo_root,
        )
        if result.applied:
            print(f"⚠️ OVERRIDE APPLIED: {result.reason}", file=sys.stderr)
            notify_mod.notify(
                event="release_cut.start",
                severity="warn",
                summary="not a git repo; override applied",
                attrs={"override_reason": result.reason},
            )
            return 0
        emit_error(
            why="not a git repository",
            where=str(repo_root),
            fix="run from a git repo or pass --repo-root <path>.",
            override_invocation=f'{SCRIPT_BASENAME} --force-with-reason="..."',
        )
        return 2

    rc, outcome = run_release(
        repo_root=repo_root, tag_override=args.tag, dry_run=args.dry_run,
    )
    if rc == 0:
        print(
            f"✅ release_cut complete: steps={','.join(outcome.steps)}",
            file=sys.stderr,
        )
    return rc


__all__ = [
    "ReleaseContext",
    "ReleaseOutcome",
    "archived_change_proposals",
    "build_context",
    "extract_changelog_section",
    "gh_release_create",
    "gh_release_exists",
    "jira_find_or_create_fixversion",
    "jira_mark_released",
    "main",
    "resolve_previous_tag",
    "resolve_tag",
    "run_release",
    "tracker_ids_from_proposals",
]


if __name__ == "__main__":
    raise SystemExit(main())
