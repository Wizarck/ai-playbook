"""Zero-touch sync of OpenSpec changes → Jira (private) OR GitHub Issues (public).

Scans a consumer repo for ``openspec/changes/*/proposal.md`` files lacking a
``tracker_id`` (Jira) or ``tracker_issue`` (GitHub) entry in their YAML
frontmatter, creates the ticket on the correct surface, and embeds the id back
into the proposal.

Surface choice
--------------
1. If the consumer's registry entry is ``personal: true`` OR ``gh repo view``
   reports the repo as private but Atlassian creds are missing, we create a
   **GitHub Issue in the repo itself** (lightweight, no Project board).
2. Else if ``gh repo view --json visibility`` returns ``PUBLIC``, we create a
   GH Issue + (optionally) add it to the org Project from
   ``$AIPLAYBOOK_GH_PROJECT_NUMBER``.
3. Else (private enterprise) we create a Jira issue in one of
   ``consumer-b`` / ``consumer-a`` depending on the consumer name.

Notifications
-------------
Every step emits a ``scripts.notify.notify`` event:

- ``issue_sync.scan_start`` — info (before the scan walks).
- ``issue_sync.skipped`` — silent (proposal already has a tracker id).
- ``issue_sync.created`` — info (per successful create).
- ``issue_sync.failed`` — warn (API error / credentials missing; queued for retry).
- ``issue_sync.complete`` — info (summary: created/skipped/failed counts).

CLI
---
    python -m scripts.issue_sync [--consumer-root PATH] [--dry-run] [--force-with-reason TEXT]

Exit codes
----------
    0 — success (including dry-run, even when items were queued)
    1 — logical failure (proposal frontmatter malformed)
    2 — setup error (consumer root missing, gh unavailable AND Jira unavailable)

Idempotency
-----------
Second invocation with no new proposals is a no-op and emits
``issue_sync.complete`` with ``created=0``.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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


from scripts import notify as notify_mod
from scripts._break_glass import add_break_glass_flag, apply_break_glass


SCRIPT_BASENAME = "issue_sync.py"
GATE_NAME = "issue-sync-preflight"

consumer-b_PROJECTS = {"consumer-d", "consumer-b", "consumer-b-hub"}
consumer-a_PROJECTS = {"diakopa", "ESILDA"}

DEFAULT_JIRA_ISSUE_TYPE = "Story"
JIRA_LABELS = ["openspec", "ai-playbook-managed"]
QUEUE_TTL_DAYS = 7


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class ProposalRef:
    path: Path          # absolute proposal.md path
    change_id: str      # slug (parent dir name)
    frontmatter: dict   # parsed frontmatter
    body: str           # everything after frontmatter


@dataclass
class SyncOutcome:
    created: int = 0
    skipped: int = 0
    failed: int = 0
    entries: list[dict] = field(default_factory=list)


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
# Frontmatter handling (simple key: value parser — stdlib-only)
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter_dict, remaining_body). Frontmatter-less → ({}, text)."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}, text
    rest = text[4:]
    end = rest.find("\n---\n")
    if end == -1:
        end = rest.find("\n---")
        if end == -1:
            return {}, text
    fm_text = rest[:end]
    body = rest[end + len("\n---\n") :] if rest[end:].startswith("\n---\n") else rest[end + len("\n---") :]
    fm: dict[str, str] = {}
    for line in fm_text.split("\n"):
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip().strip("'\"")
    return fm, body


def render_with_frontmatter(fm: dict[str, str], body: str) -> str:
    lines = ["---"]
    for key in sorted(fm.keys()):
        lines.append(f"{key}: {fm[key]}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body


# ---------------------------------------------------------------------------
# Proposal scan
# ---------------------------------------------------------------------------


def scan_proposals(consumer_root: Path) -> list[ProposalRef]:
    changes_dir = consumer_root / "openspec" / "changes"
    if not changes_dir.is_dir():
        return []
    results: list[ProposalRef] = []
    for child in sorted(changes_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name == "archive":
            continue
        proposal = child / "proposal.md"
        if not proposal.is_file():
            continue
        try:
            text = proposal.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, body = parse_frontmatter(text)
        results.append(
            ProposalRef(path=proposal, change_id=child.name, frontmatter=fm, body=body)
        )
    return results


def proposal_has_tracker(fm: dict[str, str]) -> bool:
    return bool(fm.get("tracker_id") or fm.get("tracker_issue"))


# ---------------------------------------------------------------------------
# Repo visibility
# ---------------------------------------------------------------------------


def _gh_available() -> bool:
    try:
        out = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True, timeout=10,
        )
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _gh_repo_visibility(consumer_root: Path) -> str | None:
    """Return ``PUBLIC`` / ``PRIVATE`` / ``INTERNAL`` or None on failure."""
    try:
        out = subprocess.run(
            ["gh", "repo", "view", "--json", "visibility"],
            capture_output=True, text=True, timeout=10, cwd=consumer_root,
        )
        if out.returncode != 0:
            return None
        data = json.loads(out.stdout.strip() or "{}")
        vis = data.get("visibility")
        return vis if isinstance(vis, str) else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None


def _gh_repo_nwo(consumer_root: Path) -> str | None:
    """Return ``owner/name`` string or None."""
    try:
        out = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner"],
            capture_output=True, text=True, timeout=10, cwd=consumer_root,
        )
        if out.returncode != 0:
            return None
        data = json.loads(out.stdout.strip() or "{}")
        nwo = data.get("nameWithOwner")
        return nwo if isinstance(nwo, str) else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None


def _consumer_name(consumer_root: Path) -> str:
    """Best-effort project name. AGENTS.md frontmatter → directory basename."""
    agents = consumer_root / "AGENTS.md"
    if agents.is_file():
        try:
            fm, _ = parse_frontmatter(agents.read_text(encoding="utf-8"))
            if fm.get("project"):
                return fm["project"]
        except OSError:
            pass
    return consumer_root.name


def _is_personal(consumer_root: Path) -> bool:
    agents = consumer_root / "AGENTS.md"
    if agents.is_file():
        try:
            fm, _ = parse_frontmatter(agents.read_text(encoding="utf-8"))
            return fm.get("personal", "").strip().lower() in ("true", "1", "yes")
        except OSError:
            return False
    return False


def _jira_project_for(consumer_name: str) -> str:
    if consumer_name in consumer-b_PROJECTS:
        return "consumer-b"
    if consumer_name in consumer-a_PROJECTS:
        return "consumer-a"
    return "consumer-a"


# ---------------------------------------------------------------------------
# Tracker surface selection
# ---------------------------------------------------------------------------


@dataclass
class SurfaceDecision:
    kind: str  # "jira" | "github" | "github-personal"
    jira_project: str | None = None
    gh_repo: str | None = None
    gh_project_number: str | None = None
    reason: str = ""


def decide_surface(consumer_root: Path) -> SurfaceDecision:
    """Pick the tracker surface based on registry + gh repo visibility."""
    consumer_name = _consumer_name(consumer_root)
    personal = _is_personal(consumer_root)

    gh_auth = _gh_available()
    visibility = _gh_repo_visibility(consumer_root) if gh_auth else None
    nwo = _gh_repo_nwo(consumer_root) if gh_auth else None

    if personal:
        # Personal repos → GH Issues in the same repo, no project board.
        return SurfaceDecision(
            kind="github-personal",
            gh_repo=nwo,
            reason="personal flag in AGENTS.md",
        )

    if visibility == "PUBLIC":
        gh_project_num = os.environ.get("AIPLAYBOOK_GH_PROJECT_NUMBER", "").strip() or None
        return SurfaceDecision(
            kind="github",
            gh_repo=nwo,
            gh_project_number=gh_project_num,
            reason="public repo",
        )

    # Default: private enterprise → Jira.
    return SurfaceDecision(
        kind="jira",
        jira_project=_jira_project_for(consumer_name),
        reason="private/unknown visibility; Jira default",
    )


# ---------------------------------------------------------------------------
# Jira REST client (urllib, stdlib-only)
# ---------------------------------------------------------------------------


@dataclass
class JiraCreds:
    url: str
    username: str
    api_token: str


def _load_jira_creds() -> JiraCreds | None:
    url = (os.environ.get("ATLASSIAN_URL") or "").strip()
    user = (os.environ.get("ATLASSIAN_USERNAME") or "").strip()
    token = (os.environ.get("ATLASSIAN_API_TOKEN") or "").strip()
    if not (url and user and token):
        return None
    return JiraCreds(url=url.rstrip("/"), username=user, api_token=token)


def create_jira_issue(
    *, creds: JiraCreds, project_key: str, summary: str, description: str,
    issue_type: str | None = None, labels: list[str] | None = None,
    timeout: float = 10.0,
) -> tuple[str | None, str]:
    """POST /rest/api/3/issue. Return (issue_key, reason). issue_key=None on failure."""
    issue_type = issue_type or os.environ.get(
        "AIPLAYBOOK_JIRA_DEFAULT_ISSUE_TYPE", DEFAULT_JIRA_ISSUE_TYPE
    )
    labels_final = list(labels or JIRA_LABELS)

    body = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}],
                    }
                ],
            },
            "issuetype": {"name": issue_type},
            "labels": labels_final,
        }
    }
    endpoint = f"{creds.url}/rest/api/3/issue"
    auth = base64.b64encode(
        f"{creds.username}:{creds.api_token}".encode("utf-8")
    ).decode("ascii")
    req = urlrequest.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ai-playbook/issue_sync",
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urlerror.HTTPError as exc:
        return None, f"http-{exc.code}"
    except urlerror.URLError as exc:
        return None, f"url:{exc.reason}"
    except TimeoutError:
        return None, "timeout"
    except OSError as exc:
        return None, f"os:{exc}"

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None, "malformed-json"
    key = parsed.get("key")
    if not isinstance(key, str):
        return None, "unexpected-shape"
    return key, "ok"


# ---------------------------------------------------------------------------
# GitHub CLI integration
# ---------------------------------------------------------------------------


def create_gh_issue(
    *, repo: str | None, title: str, body: str, labels: list[str] | None = None,
    project_number: str | None = None, cwd: Path | None = None,
) -> tuple[str | None, str]:
    """Run ``gh issue create``. Return (issue_number_or_url, reason)."""
    cmd = ["gh", "issue", "create", "--title", title, "--body", body]
    if repo:
        cmd += ["--repo", repo]
    for lbl in labels or ["openspec", "ai-playbook-managed"]:
        cmd += ["--label", lbl]

    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, cwd=cwd,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"subprocess:{exc.__class__.__name__}"
    if out.returncode != 0:
        return None, f"gh-create-rc-{out.returncode}"

    # gh prints the issue URL on stdout; extract the number.
    url = (out.stdout or "").strip().splitlines()[-1] if out.stdout.strip() else ""
    if not url:
        return None, "empty-gh-output"
    issue_number = url.rsplit("/", 1)[-1]

    if project_number:
        try:
            subprocess.run(
                ["gh", "project", "item-add", project_number,
                 "--owner", "Wizarck", "--url", url],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            # Don't fail the whole create if project-add fails; it's enrichment.
            pass

    return issue_number, "ok"


# ---------------------------------------------------------------------------
# Retry queue
# ---------------------------------------------------------------------------


def _queue_path(consumer_root: Path) -> Path:
    return consumer_root / ".ai-playbook" / "issue_sync_queue.jsonl"


def queue_entry(consumer_root: Path, *, change_id: str, reason: str, attempt: int = 1) -> None:
    path = _queue_path(consumer_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "change_id": change_id,
            "reason": reason,
            "attempt": attempt,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def read_queue(consumer_root: Path) -> list[dict]:
    path = _queue_path(consumer_root)
    if not path.is_file():
        return []
    entries: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def prune_queue(consumer_root: Path, *, now: datetime | None = None) -> list[dict]:
    """Remove entries older than QUEUE_TTL_DAYS. Return the dropped entries."""
    now = now or datetime.now(timezone.utc).astimezone()
    entries = read_queue(consumer_root)
    keep: list[dict] = []
    dropped: list[dict] = []
    cutoff = now - timedelta(days=QUEUE_TTL_DAYS)
    for e in entries:
        ts_raw = e.get("ts")
        try:
            ts = datetime.fromisoformat(ts_raw) if isinstance(ts_raw, str) else None
        except ValueError:
            ts = None
        if ts is None or ts >= cutoff:
            keep.append(e)
        else:
            dropped.append(e)
    path = _queue_path(consumer_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for e in keep:
                f.write(json.dumps(e) + "\n")
    except OSError:
        pass
    return dropped


# ---------------------------------------------------------------------------
# Proposal → tracker + write-back
# ---------------------------------------------------------------------------


def _embed_tracker(proposal: ProposalRef, *, key: str, field_name: str) -> None:
    proposal.frontmatter[field_name] = key
    try:
        proposal.path.write_text(
            render_with_frontmatter(proposal.frontmatter, proposal.body),
            encoding="utf-8",
        )
    except OSError as exc:
        # Don't lose the ticket; surface failure to caller.
        raise RuntimeError(f"cannot write proposal.md: {exc}") from exc


def _build_title(proposal: ProposalRef, consumer_name: str) -> str:
    slug = proposal.change_id
    return f"[{consumer_name}] {slug}"


def _build_description(proposal: ProposalRef, consumer_root: Path) -> str:
    rel = proposal.path.relative_to(consumer_root)
    return (
        f"Auto-created by ai-playbook issue_sync from OpenSpec change `{proposal.change_id}`.\n"
        f"Source: {rel.as_posix()}"
    )


# ---------------------------------------------------------------------------
# Sync one proposal
# ---------------------------------------------------------------------------


def _sync_one(
    *, proposal: ProposalRef, consumer_root: Path, surface: SurfaceDecision,
    dry_run: bool,
) -> tuple[bool, str, str]:
    """Return (ok, tracker_key, reason)."""
    consumer_name = _consumer_name(consumer_root)
    title = _build_title(proposal, consumer_name)
    description = _build_description(proposal, consumer_root)

    if dry_run:
        return True, "DRY-RUN", "dry-run"

    if surface.kind == "jira":
        creds = _load_jira_creds()
        if not creds or not surface.jira_project:
            return False, "", "jira-credentials-missing"
        key, reason = create_jira_issue(
            creds=creds, project_key=surface.jira_project,
            summary=title, description=description,
        )
        if not key:
            return False, "", f"jira:{reason}"
        try:
            _embed_tracker(proposal, key=key, field_name="tracker_id")
        except RuntimeError as exc:
            return False, key, f"writeback:{exc}"
        return True, key, "ok"

    # GH paths
    if not _gh_available():
        return False, "", "gh-unavailable"
    number, reason = create_gh_issue(
        repo=surface.gh_repo, title=title, body=description,
        project_number=surface.gh_project_number if surface.kind == "github" else None,
        cwd=consumer_root,
    )
    if not number:
        return False, "", f"gh:{reason}"
    try:
        _embed_tracker(proposal, key=number, field_name="tracker_issue")
    except RuntimeError as exc:
        return False, number, f"writeback:{exc}"
    return True, number, "ok"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def sync_all(
    *, consumer_root: Path, dry_run: bool = False,
) -> SyncOutcome:
    consumer_name = _consumer_name(consumer_root)
    notify_mod.notify(
        event="issue_sync.scan_start",
        severity="info",
        summary=f"scanning {consumer_name} for OpenSpec changes",
        attrs={"consumer_root": str(consumer_root)},
    )
    outcome = SyncOutcome()
    proposals = scan_proposals(consumer_root)

    if not proposals:
        notify_mod.notify(
            event="issue_sync.complete",
            severity="info",
            summary=f"{consumer_name}: no proposals found",
            attrs={"created": 0, "skipped": 0, "failed": 0},
        )
        return outcome

    surface = decide_surface(consumer_root)

    for proposal in proposals:
        if proposal_has_tracker(proposal.frontmatter):
            outcome.skipped += 1
            existing = (
                proposal.frontmatter.get("tracker_id")
                or proposal.frontmatter.get("tracker_issue")
                or ""
            )
            notify_mod.notify(
                event="issue_sync.skipped",
                severity="silent",
                summary=f"{proposal.change_id} already has tracker id {existing}",
                attrs={
                    "change_id": proposal.change_id,
                    "tracker_id": existing,
                    "project": consumer_name,
                },
            )
            continue

        ok, key, reason = _sync_one(
            proposal=proposal, consumer_root=consumer_root,
            surface=surface, dry_run=dry_run,
        )

        if ok:
            outcome.created += 1
            outcome.entries.append({
                "change_id": proposal.change_id,
                "tracker": key,
                "surface": surface.kind,
            })
            notify_mod.notify(
                event="issue_sync.created",
                severity="info",
                summary=f"Created {key} for {proposal.change_id}",
                attrs={
                    "change_id": proposal.change_id,
                    "tracker_id": key,
                    "project": consumer_name,
                    "surface": surface.kind,
                },
            )
        else:
            outcome.failed += 1
            queue_entry(consumer_root, change_id=proposal.change_id, reason=reason)
            notify_mod.notify(
                event="issue_sync.failed",
                severity="warn",
                summary=f"Failed to create tracker for {proposal.change_id}: {reason}",
                attrs={
                    "change_id": proposal.change_id,
                    "project": consumer_name,
                    "surface": surface.kind,
                    "reason": reason,
                },
            )

    dropped = prune_queue(consumer_root)
    for d in dropped:
        notify_mod.notify(
            event="issue_sync.queue_dropped",
            severity="error",
            summary=f"Dropping stale queue entry for {d.get('change_id')} after {QUEUE_TTL_DAYS}d",
            attrs={"change_id": d.get("change_id"), "reason": d.get("reason")},
        )

    notify_mod.notify(
        event="issue_sync.complete",
        severity="info",
        summary=(
            f"{consumer_name}: created={outcome.created} "
            f"skipped={outcome.skipped} failed={outcome.failed}"
        ),
        attrs={
            "created": outcome.created,
            "skipped": outcome.skipped,
            "failed": outcome.failed,
            "project": consumer_name,
            "surface": surface.kind,
        },
    )
    return outcome


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="issue_sync",
        description="Zero-touch sync of OpenSpec changes to Jira / GitHub Issues.",
    )
    p.add_argument("--consumer-root", type=Path, default=None, help="Consumer repo (default: cwd).")
    p.add_argument("--dry-run", action="store_true", help="Scan + print; do not create or write.")
    add_break_glass_flag(p)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    consumer_root = (args.consumer_root or Path.cwd()).expanduser().resolve()

    if not consumer_root.is_dir():
        emit_error(
            why=f"consumer root is not a directory: {consumer_root}",
            where=str(consumer_root),
            fix="run from a consumer repo or pass --consumer-root <path>.",
            override_invocation=None,
        )
        return 2

    if not (consumer_root / "openspec" / "changes").is_dir():
        # No openspec changes folder → honour break-glass for automation runners
        # that may fire on every repo.
        result = apply_break_glass(
            gate=GATE_NAME, script=SCRIPT_BASENAME,
            reason=args.force_reason, override_allowed=True,
            repo_root=consumer_root,
        )
        if result.applied:
            print(f"⚠️ OVERRIDE APPLIED: {result.reason}", file=sys.stderr)
            notify_mod.notify(
                event="issue_sync.scan_start",
                severity="warn",
                summary=f"no openspec/changes dir at {consumer_root}; override applied",
                attrs={"override_reason": result.reason},
            )
            return 0
        emit_error(
            why="no openspec/changes directory",
            where=f"{consumer_root}/openspec/changes",
            fix="run from a consumer repo that uses OpenSpec.",
            override_invocation=f'{SCRIPT_BASENAME} --force-with-reason="..."',
        )
        return 2

    try:
        outcome = sync_all(consumer_root=consumer_root, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001 — surface as warn notification, exit 1.
        notify_mod.notify(
            event="issue_sync.failed",
            severity="error",
            summary=f"issue_sync crashed: {exc.__class__.__name__}",
            detail=str(exc),
        )
        return 1

    print(
        f"✅ issue_sync: created={outcome.created} "
        f"skipped={outcome.skipped} failed={outcome.failed}",
        file=sys.stderr,
    )
    return 0


__all__ = [
    "ProposalRef",
    "SurfaceDecision",
    "SyncOutcome",
    "create_gh_issue",
    "create_jira_issue",
    "decide_surface",
    "main",
    "parse_frontmatter",
    "prune_queue",
    "queue_entry",
    "read_queue",
    "render_with_frontmatter",
    "scan_proposals",
    "sync_all",
]


if __name__ == "__main__":
    raise SystemExit(main())
