"""Shared submodule-bump helpers used by both `bump_consumers.py` (manual,
local-only, reads ``~/.ai-playbook/projects.yaml``) and `propagate_bump.py`
(CI-side, reads ``consumers.yaml`` + clones via PAT).

This module factors out the things that BOTH flows need:

1. ``resolve_target_sha(submodule_path, tag)`` — the SHA the consumer's
   submodule pointer should be set to.
2. ``current_pin(submodule_path)`` — what the submodule currently points at,
   in human-readable form.
3. ``commit_bump(consumer_root, submodule_path, commit_message)`` — stage +
   commit the submodule pointer change in the parent repo.
4. ``bump_agents_md_pin(agents_md, source_repo, new_tag)`` — surgical
   line-level rewrite of ``inherits_from:`` and ``skills_sources:`` items in
   the frontmatter. Per v0.9.0 followup #1: ``propagate_bump.py`` previously
   only wrote the submodule pointer; ``AGENTS.md inherits_from`` was only
   rewritten by ``propagate_skills_bump.py``, which skipped consumers
   without ``skills_pins:`` (e.g. livekit), leaving stale frontmatter pins.
5. ``supersede_open_bump_prs(...)`` — close prior open bump PRs on the same
   logical change-stream. Now semver-aware (per v0.9.0 followup #2): only
   closes a PR if the new bump's version is ``>=`` than the open PR's.

The two CLIs differ in HOW they get the consumer checkout (local filesystem
vs ``git clone --recurse-submodules``) and HOW they push the result (local
commit vs branch + PR), but converge here for the "bump the pointer" core.

Stdlib-only.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SUBMODULE_PATH = ".ai-playbook"
COMMIT_TEMPLATE = "chore(playbook): bump .ai-playbook to {tag}"
BUMP_BRANCH_TEMPLATE = "chore/bump-playbook-{tag}"


class BumperError(RuntimeError):
    """Wraps a subprocess.CalledProcessError with a friendlier message."""


def _run(cmd: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd), check=check, capture_output=True, text=True, encoding="utf-8",
    )


def current_pin(submodule_path: Path) -> str | None:
    """Return ``vX.Y.Z`` if the submodule HEAD matches a tag, else short SHA, else None."""
    if not submodule_path.exists():
        return None
    try:
        r = _run(["git", "describe", "--tags", "--always"], cwd=submodule_path, check=False)
    except Exception:  # noqa: BLE001
        return None
    return r.stdout.strip() or None


def resolve_target_sha(submodule_path: Path, tag: str) -> str:
    """Resolve a tag (e.g. ``v0.3.0``) to a commit SHA inside the submodule.

    Fetches tags first to make sure the tag is known. Raises BumperError if
    the tag doesn't exist in the submodule's remote.
    """
    try:
        _run(["git", "fetch", "--tags", "--quiet", "origin"], cwd=submodule_path)
    except subprocess.CalledProcessError as exc:
        raise BumperError(f"could not fetch tags in {submodule_path}: {exc.stderr.strip()}") from exc
    try:
        r = _run(["git", "rev-parse", f"refs/tags/{tag}^{{commit}}"], cwd=submodule_path)
    except subprocess.CalledProcessError as exc:
        raise BumperError(f"tag {tag} not found in {submodule_path} remote") from exc
    return r.stdout.strip()


def checkout_tag(submodule_path: Path, tag: str) -> None:
    """Detached-checkout the tag inside the submodule."""
    try:
        _run(["git", "checkout", "--quiet", tag], cwd=submodule_path)
    except subprocess.CalledProcessError as exc:
        raise BumperError(f"could not checkout {tag} in {submodule_path}: {exc.stderr.strip()}") from exc


def commit_bump(
    consumer_root: Path,
    submodule_path_rel: str = DEFAULT_SUBMODULE_PATH,
    *,
    tag: str,
    author_name: str | None = None,
    author_email: str | None = None,
) -> None:
    """Stage the submodule pointer change and commit it. Raises if nothing to commit."""
    if author_name:
        _run(["git", "config", "user.name", author_name], cwd=consumer_root, check=False)
    if author_email:
        _run(["git", "config", "user.email", author_email], cwd=consumer_root, check=False)
    _run(["git", "add", submodule_path_rel], cwd=consumer_root)
    msg = COMMIT_TEMPLATE.format(tag=tag)
    try:
        _run(["git", "commit", "-m", msg], cwd=consumer_root)
    except subprocess.CalledProcessError as exc:
        raise BumperError(f"git commit failed in {consumer_root}: {exc.stderr.strip()}") from exc


_FRONTMATTER_REF_RE = re.compile(
    r"(?P<indent>\s*-\s*)(?P<ref>(?:github\.com/)?(?P<owner>[A-Za-z0-9._-]+)/"
    r"(?P<repo>[A-Za-z0-9._-]+)@(?P<tag>[A-Za-z0-9._+-]+))(?P<rest>\s*(?:#.*)?)?$"
)
_UPDATED_LINE_RE = re.compile(r"^\s*updated\s*:")
_UPDATED_VALUE_RE = re.compile(
    r"^(\s*updated\s*:\s*)(['\"]?)([^'\"#\n]+?)(['\"]?\s*(?:#.*)?)$"
)


def bump_agents_md_pin(
    agents_md: Path,
    source_repo: str,
    new_tag: str,
) -> tuple[bool, str]:
    """Rewrite frontmatter ``inherits_from:`` AND ``skills_sources:`` items.

    Surgical line-level edit (not a full YAML re-serialise) so we preserve
    comments, ordering, and quoting style in AGENTS.md. The file is small
    enough that a regex line-walk is reliable.

    Matches list items of the form ``- <owner>/<repo>@<tag>`` OR
    ``- github.com/<owner>/<repo>@<tag>`` (the prefix is optional). Both
    ``inherits_from:`` and ``skills_sources:`` use the same item shape, so
    a single regex covers both blocks.

    Per v0.9.0 followup #1 (livekit kept ``inherits_from`` stale at
    ``v0.9.0-rc2`` after the v0.9.0 cascade because ``propagate_bump.py``
    didn't touch frontmatter): this helper is shared between both
    propagation scripts. ``propagate_bump.py`` calls it for every consumer;
    ``propagate_skills_bump.py`` calls it for consumers with ``skills_pins:``.

    Args:
        agents_md: Path to ``AGENTS.md`` in the consumer's working tree.
        source_repo: short repo name to match (e.g. ``ai-playbook``). Items
            whose ``<repo>`` capture matches this string are rewritten.
        new_tag: the tag to set (e.g. ``v0.9.1``). Items already at this
            tag are left untouched.

    Returns:
        ``(changed, detail)`` where:

        * ``changed=True, detail="rewrote"`` if any line was updated.
        * ``changed=False, detail="up-to-date"`` if all matching items
          already pin ``new_tag``.
        * ``changed=False, detail="not-found"`` if no item references
          ``source_repo``.
        * ``changed=False, detail="agents-md-missing"`` if the file is
          missing.
        * ``changed=False, detail="no-frontmatter"`` if the file lacks a
          fenced YAML frontmatter block.
    """
    if not agents_md.is_file():
        return False, "agents-md-missing"
    text = agents_md.read_text(encoding="utf-8")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return False, "no-frontmatter"
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return False, "no-frontmatter"

    changed = False
    already_at_target = False
    updated_line_idx: int | None = None
    for i in range(1, end):
        ln = lines[i]
        if _UPDATED_LINE_RE.match(ln) and updated_line_idx is None:
            updated_line_idx = i
            continue
        m = _FRONTMATTER_REF_RE.match(ln)
        if not m:
            continue
        if m.group("repo") != source_repo:
            continue
        current_tag = m.group("tag")
        if current_tag == new_tag:
            already_at_target = True
            continue
        new_ref = re.sub(
            rf"@{re.escape(current_tag)}\b",
            f"@{new_tag}",
            m.group("ref"),
            count=1,
        )
        lines[i] = f"{m.group('indent')}{new_ref}{m.group('rest') or ''}"
        changed = True

    if changed and updated_line_idx is not None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        m_upd = _UPDATED_VALUE_RE.match(lines[updated_line_idx])
        if m_upd:
            lines[updated_line_idx] = (
                f"{m_upd.group(1)}{m_upd.group(2)}{today}{m_upd.group(4)}"
            )

    if changed:
        agents_md.write_text("\n".join(lines), encoding="utf-8", newline="\n")
        return True, "rewrote"
    if already_at_target:
        return False, "up-to-date"
    return False, "not-found"


_BUMP_BRANCH_VERSION_RE = re.compile(
    r"^chore/bump-(?:playbook|skills-[A-Za-z0-9._-]+)-(?P<tag>v[\w.+-]+)$"
)


def _parse_branch_version(branch: str) -> tuple[int, ...] | None:
    """Extract a comparable version key from a bump-branch name.

    Returns a tuple suitable for ``<`` / ``>=`` comparison. ``None`` if the
    branch doesn't follow the ``chore/bump-(playbook|skills-*)-vX.Y.Z[-rc.N]``
    pattern (caller treats unparseable branches as not-comparable and skips
    supersede on them).

    Stable comparison rules:

    * Stable releases (``v0.9.0``) sort ABOVE all rcs of the same series
      (``v0.9.0-rc3 < v0.9.0``).
    * RCs sort by their numeric suffix (``v0.9.0-rc2 < v0.9.0-rc3``).
    * Older series sort below newer (``v0.8.8 < v0.9.0-rc1 < v0.9.0``).

    Implementation:
        ``(major, minor, patch, stable_flag, rc_num)`` where
        ``stable_flag`` is ``1`` for stable releases and ``0`` for rcs.
        A stable release uses ``rc_num=0``; an rc uses ``rc_num=N``.
    """
    m = _BUMP_BRANCH_VERSION_RE.match(branch)
    if not m:
        return None
    tag = m.group("tag")
    body = tag[1:] if tag.startswith("v") else tag
    if "-rc" in body:
        core, rc_part = body.split("-rc", 1)
        try:
            rc_num = int(rc_part)
        except ValueError:
            return None
        stable_flag = 0
    elif "-" in body:
        return None
    else:
        core = body
        rc_num = 0
        stable_flag = 1

    parts = core.split(".")
    if len(parts) < 3:
        parts = parts + ["0"] * (3 - len(parts))
    try:
        major, minor, patch = (int(p) for p in parts[:3])
    except ValueError:
        return None
    return (major, minor, patch, stable_flag, rc_num)


def supersede_open_bump_prs(
    consumer_root: Path,
    branch_prefix: str,
    new_pr_number: int | None,
    *,
    new_branch: str | None = None,
    new_pr_url: str | None = None,
) -> list[str]:
    """Close open bump PRs SUPERSEDED by ``new_branch``/``new_pr_number``.

    Per release-management.md §3.4: each new ``chore/bump-*`` PR auto-
    closes prior open PRs on the same logical change-stream. Prevents
    the pile-up pattern observed during ai-playbook v0.8.0-rc1→rc6
    dogfooding (10 stacked, pairwise-conflicting bump PRs).

    Per v0.9.0 followup #2 (out-of-order tag pushes during the rc1+rc2
    cycle saw v0.8.7 PRs close newer v0.9.0-rc2 PRs simply because v0.8.7's
    workflow ran LAST): supersede is now SEMVER-AWARE. We only close an
    open PR when the new bump's parsed version is ``>=`` than the open
    PR's. ``new_branch`` is required for this comparison; if omitted we
    fall back to chronological "all-others-close" semantics for backwards
    compatibility (and log a warning to stderr).

    Returns list of closed PR numbers (as strings). Idempotent — safe to
    call even when no older PRs exist.

    Args:
        consumer_root: path to the consumer's working tree (cwd for `gh`).
        branch_prefix: e.g. "chore/bump-playbook-" or
                        "chore/bump-skills-ai-playbook-".
        new_pr_number: the PR just opened. PRs with this number are
                       excluded from the close list. If None (e.g. PR
                       creation failed or was skipped), all matching PRs
                       are considered for closure.
        new_branch: the head ref of the freshly-opened PR. Used to parse
                    the new bump's version for semver-aware comparison.
                    If None, supersede falls back to chronological mode.
        new_pr_url: optional, embedded in the supersede comment so the
                    closed PR points at its successor.
    """
    import json as _json
    import sys as _sys

    list_cmd = [
        "gh", "pr", "list",
        "--state", "open",
        "--json", "number,headRefName,url",
        "--limit", "100",
    ]
    try:
        r = _run(list_cmd, cwd=consumer_root)
    except subprocess.CalledProcessError as exc:
        raise BumperError(
            f"gh pr list failed in {consumer_root}: {exc.stderr.strip()}"
        ) from exc

    try:
        prs = _json.loads(r.stdout or "[]")
    except _json.JSONDecodeError as exc:
        raise BumperError(f"could not parse gh pr list output: {exc}") from exc

    candidates = [
        pr for pr in prs
        if pr.get("headRefName", "").startswith(branch_prefix)
        and pr.get("number") != new_pr_number
    ]
    if not candidates:
        return []

    new_version = _parse_branch_version(new_branch) if new_branch else None
    if new_branch is None:
        print(
            "[supersede] WARNING: called without new_branch — falling back "
            "to chronological mode. Pass new_branch for semver-aware "
            "behaviour (per v0.9.0 followup #2).",
            file=_sys.stderr,
        )
    elif new_version is None:
        print(
            f"[supersede] could not parse version from {new_branch!r}; "
            "falling back to chronological mode for this run.",
            file=_sys.stderr,
        )

    to_close: list[dict] = []
    for pr in candidates:
        if new_version is None:
            to_close.append(pr)
            continue
        open_version = _parse_branch_version(pr.get("headRefName", ""))
        if open_version is None:
            continue
        if new_version >= open_version:
            to_close.append(pr)

    if not to_close:
        return []

    successor_ref = (
        f" by #{new_pr_number}" if new_pr_number else ""
    ) + (f" ({new_pr_url})" if new_pr_url else "")
    comment = (
        f"Auto-closed: superseded{successor_ref}. "
        "Each new bump PR closes prior open PRs on the same logical "
        "change-stream per ai-playbook release-management.md §3.4."
    )

    closed: list[str] = []
    for pr in to_close:
        num = str(pr["number"])
        try:
            _run(
                ["gh", "pr", "close", num, "--comment", comment, "--delete-branch"],
                cwd=consumer_root,
                check=False,
            )
            closed.append(num)
        except subprocess.CalledProcessError:
            continue

    return closed


def bump_branch(tag: str) -> str:
    """Canonical branch name for a propagation PR."""
    return BUMP_BRANCH_TEMPLATE.format(tag=tag)


def commit_message(tag: str) -> str:
    return COMMIT_TEMPLATE.format(tag=tag)


__all__ = [
    "BUMP_BRANCH_TEMPLATE",
    "COMMIT_TEMPLATE",
    "DEFAULT_SUBMODULE_PATH",
    "BumperError",
    "bump_agents_md_pin",
    "bump_branch",
    "checkout_tag",
    "commit_bump",
    "commit_message",
    "current_pin",
    "resolve_target_sha",
    "supersede_open_bump_prs",
]
