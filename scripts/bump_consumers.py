"""Batch-bump the `.ai-playbook/` submodule pin across every registered consumer.

Reads `~/.ai-playbook/projects.yaml` (the per-dev registry written by
`scripts/discover_projects.py`) and for every project that has a
`.ai-playbook/` submodule:

    1. Fetches origin tags on the submodule.
    2. Checks out the target tag.
    3. Stages the submodule pointer bump + `.gitmodules` (if needed).
    4. Commits the bump with a canonical message.
    5. Optionally pushes and opens a PR via `gh`.

Usage
-----
    # Dry-run — show what would change per consumer:
    python -m scripts.bump_consumers --tag v0.2.1 --dry-run

    # Apply across every registered consumer, commit locally:
    python -m scripts.bump_consumers --tag v0.2.1

    # Apply + push + open PRs (requires `gh` authed, write access to each repo):
    python -m scripts.bump_consumers --tag v0.2.1 --push --open-pr

    # Restrict to specific projects:
    python -m scripts.bump_consumers --tag v0.2.1 --only consumer-c,consumer-d

Skips
-----
    - The playbook's own entry (has no `.ai-playbook/` submodule).
    - Projects without a `.ai-playbook/` directory.
    - Projects already pinned at or past the target tag (unless `--force`).

Break-glass
-----------
    - `--force-with-reason="..."` lets you skip the "same-or-newer tag" check
      (rare — typically you're moving forward).
    - Dirty working trees still block unless `--allow-dirty` + reason.

This script does NOT mutate the playbook itself. Run it from inside the
playbook checkout; it works against the sibling consumer repos named in the
registry.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

# Force UTF-8 stdio on Windows.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._break_glass import add_break_glass_flag, apply_break_glass  # noqa: E402
from scripts._bumper import (  # noqa: E402
    DEFAULT_SUBMODULE_PATH,
    bump_branch,
    commit_message,
)

DEFAULT_REGISTRY = Path.home() / ".ai-playbook" / "projects.yaml"
SUBMODULE_PATH = DEFAULT_SUBMODULE_PATH
# Re-export for back-compat with any external caller importing this name.
COMMIT_TEMPLATE = "chore(playbook): bump .ai-playbook to {tag}"


@dataclass
class Consumer:
    name: str
    path: Path
    current_pin: str | None  # human-readable (tag/SHA short) — None if unknown


@dataclass
class BumpResult:
    consumer: str
    status: str  # "bumped" | "skipped" | "up-to-date" | "error"
    detail: str


def _run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command, return the result. Captures stdout+stderr."""
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _load_registry(path: Path) -> dict:
    if not path.exists():
        print(
            f"❌ registry not found at {path}\n"
            f"   FIX: run `python -m scripts.discover_projects` to create it.\n"
            f"   OVERRIDE: none",
            file=sys.stderr,
        )
        sys.exit(1)
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _consumer_current_pin(project_path: Path) -> str | None:
    """Return a human-readable pin (`v0.1.0` or SHA) for the consumer's submodule."""
    sub = project_path / SUBMODULE_PATH
    if not sub.exists():
        return None
    try:
        r = _run(["git", "describe", "--tags", "--always"], cwd=sub, check=False)
        return r.stdout.strip() or None
    except Exception:
        return None


def _collect_consumers(registry: dict, only: list[str] | None) -> list[Consumer]:
    out: list[Consumer] = []
    for name, meta in (registry.get("projects") or {}).items():
        if only and name not in only:
            continue
        if name == "ai-playbook":
            continue  # playbook itself has no submodule
        path = Path(meta.get("path", ""))
        if not path.exists():
            out.append(Consumer(name=name, path=path, current_pin=None))
            continue
        if not (path / SUBMODULE_PATH).exists():
            out.append(Consumer(name=name, path=path, current_pin=None))
            continue
        out.append(Consumer(name=name, path=path, current_pin=_consumer_current_pin(path)))
    return out


def _is_dirty(project_path: Path) -> bool:
    r = _run(["git", "status", "--porcelain"], cwd=project_path, check=False)
    return bool(r.stdout.strip())


def _tag_exists(project_path: Path, tag: str) -> bool:
    sub = project_path / SUBMODULE_PATH
    r = _run(["git", "rev-parse", "--verify", f"refs/tags/{tag}"], cwd=sub, check=False)
    return r.returncode == 0


def _bump_one(
    consumer: Consumer,
    tag: str,
    dry_run: bool,
    allow_dirty: bool,
    force: bool,
    push: bool,
    open_pr: bool,
) -> BumpResult:
    if consumer.current_pin is None:
        return BumpResult(consumer.name, "skipped", "no .ai-playbook submodule")

    if not consumer.path.exists():
        return BumpResult(consumer.name, "skipped", f"path not present: {consumer.path}")

    if _is_dirty(consumer.path) and not allow_dirty:
        return BumpResult(
            consumer.name, "skipped", "dirty working tree (use --allow-dirty + reason)"
        )

    sub = consumer.path / SUBMODULE_PATH

    # Fetch tags on the submodule.
    _run(["git", "fetch", "--tags", "--quiet", "origin"], cwd=sub)

    if not _tag_exists(consumer.path, tag):
        return BumpResult(consumer.name, "error", f"tag {tag} not in submodule remote")

    # Resolve target SHA to compare with current.
    target_sha = _run(["git", "rev-parse", f"{tag}^{{commit}}"], cwd=sub).stdout.strip()
    current_sha = _run(["git", "rev-parse", "HEAD"], cwd=sub).stdout.strip()
    if target_sha == current_sha and not force:
        return BumpResult(consumer.name, "up-to-date", f"already at {tag}")

    if dry_run:
        return BumpResult(
            consumer.name,
            "would-bump",
            f"{consumer.current_pin} → {tag} ({target_sha[:8]})",
        )

    # Checkout the tag (detached HEAD is expected in submodules).
    _run(["git", "checkout", "--quiet", tag], cwd=sub)

    # Stage + commit in the parent.
    _run(["git", "add", SUBMODULE_PATH], cwd=consumer.path)
    commit_msg = commit_message(tag)
    _run(["git", "commit", "-m", commit_msg], cwd=consumer.path)

    if push:
        # Push current branch to its upstream.
        branch = _run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=consumer.path
        ).stdout.strip()
        push_branch = bump_branch(tag)
        _run(["git", "checkout", "-b", push_branch], cwd=consumer.path)
        _run(["git", "push", "-u", "origin", push_branch], cwd=consumer.path)

        if open_pr:
            body = (
                f"Automated bump of `.ai-playbook/` submodule to `{tag}`.\n\n"
                f"Generated by `scripts/bump_consumers.py`.\n\n"
                f"Previous pin: `{consumer.current_pin}`\n"
                f"New pin: `{tag}` ({target_sha[:8]})"
            )
            _run(
                [
                    "gh",
                    "pr",
                    "create",
                    "--title",
                    commit_msg,
                    "--body",
                    body,
                    "--base",
                    branch,
                    "--head",
                    push_branch,
                ],
                cwd=consumer.path,
            )

    return BumpResult(
        consumer.name, "bumped", f"{consumer.current_pin} → {tag} ({target_sha[:8]})"
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--tag", required=True, help="Target semver tag to pin (e.g. v0.2.1).")
    p.add_argument(
        "--registry",
        default=str(DEFAULT_REGISTRY),
        help=f"Registry path (default: {DEFAULT_REGISTRY}).",
    )
    p.add_argument(
        "--only",
        default="",
        help="Comma-separated subset of project names to bump (default: all).",
    )
    p.add_argument("--dry-run", action="store_true", help="Report plan, mutate nothing.")
    p.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Proceed even if a consumer has uncommitted changes (break-glass required).",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Bump even if consumer is already at the target tag (break-glass required).",
    )
    p.add_argument("--push", action="store_true", help="Push the bump branch to origin.")
    p.add_argument(
        "--open-pr",
        action="store_true",
        help="Open a PR via `gh pr create` (implies --push).",
    )
    add_break_glass_flag(p)
    args = p.parse_args()

    if (args.allow_dirty or args.force) and not args.force_reason:
        print(
            "❌ --allow-dirty and --force require --force-with-reason\n"
            "   FIX: supply a reason (≥10 chars) explaining the override.\n"
            "   OVERRIDE: --force-with-reason=\"<text>\"",
            file=sys.stderr,
        )
        return 1

    if args.force_reason:
        apply_break_glass(
            gate="bump_consumers.override",
            script="bump_consumers.py",
            reason=args.force_reason,
            override_allowed=True,
            repo_root=Path(__file__).resolve().parent.parent,
        )

    if args.open_pr:
        args.push = True

    registry = _load_registry(Path(args.registry))
    only = [s.strip() for s in args.only.split(",") if s.strip()] or None
    consumers = _collect_consumers(registry, only)

    if not consumers:
        print("No consumers found in registry (after --only filter).", file=sys.stderr)
        return 2

    print(f"Bumping {len(consumers)} consumer(s) to {args.tag}:\n")
    results: list[BumpResult] = []
    for c in consumers:
        try:
            results.append(
                _bump_one(
                    c,
                    args.tag,
                    args.dry_run,
                    args.allow_dirty,
                    args.force,
                    args.push,
                    args.open_pr,
                )
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip().splitlines()[-1:] or [""]
            results.append(BumpResult(c.name, "error", stderr[0]))

    col = max(len(r.consumer) for r in results) + 2
    for r in results:
        icon = {
            "bumped": "✅",
            "would-bump": "➡️",
            "up-to-date": "✓ ",
            "skipped": "— ",
            "error": "❌",
        }.get(r.status, "? ")
        print(f"  {icon} {r.consumer:<{col}} {r.status:<11} {r.detail}")

    errors = sum(1 for r in results if r.status == "error")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
