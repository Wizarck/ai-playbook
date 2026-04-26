"""Shared submodule-bump helpers used by both `bump_consumers.py` (manual,
local-only, reads ``~/.ai-playbook/projects.yaml``) and `propagate_bump.py`
(CI-side, reads ``consumers.yaml`` + clones via PAT).

This module is intentionally small — it factors out the 3 things that BOTH
flows need:

1. ``resolve_target_sha(submodule_path, tag)`` — the SHA the consumer's
   submodule pointer should be set to.
2. ``current_pin(submodule_path)`` — what the submodule currently points at,
   in human-readable form.
3. ``commit_bump(consumer_root, submodule_path, commit_message)`` — stage +
   commit the submodule pointer change in the parent repo.

The two CLIs differ in HOW they get the consumer checkout (local filesystem
vs ``git clone --recurse-submodules``) and HOW they push the result (local
commit vs branch + PR), but converge here for the "bump the pointer" core.

Stdlib-only.
"""
from __future__ import annotations

import subprocess
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
        raise BumperError(f"could not fetch tags in {submodule_path}: {exc.stderr.strip()}")
    try:
        r = _run(["git", "rev-parse", f"refs/tags/{tag}^{{commit}}"], cwd=submodule_path)
    except subprocess.CalledProcessError:
        raise BumperError(f"tag {tag} not found in {submodule_path} remote")
    return r.stdout.strip()


def checkout_tag(submodule_path: Path, tag: str) -> None:
    """Detached-checkout the tag inside the submodule."""
    try:
        _run(["git", "checkout", "--quiet", tag], cwd=submodule_path)
    except subprocess.CalledProcessError as exc:
        raise BumperError(f"could not checkout {tag} in {submodule_path}: {exc.stderr.strip()}")


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
        raise BumperError(f"git commit failed in {consumer_root}: {exc.stderr.strip()}")


def bump_branch(tag: str) -> str:
    """Canonical branch name for a propagation PR."""
    return BUMP_BRANCH_TEMPLATE.format(tag=tag)


def commit_message(tag: str) -> str:
    return COMMIT_TEMPLATE.format(tag=tag)


__all__ = [
    "DEFAULT_SUBMODULE_PATH",
    "COMMIT_TEMPLATE",
    "BUMP_BRANCH_TEMPLATE",
    "BumperError",
    "bump_branch",
    "checkout_tag",
    "commit_bump",
    "commit_message",
    "current_pin",
    "resolve_target_sha",
]
