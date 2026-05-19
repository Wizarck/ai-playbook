"""Propagate a playbook tag bump to every consumer listed in `consumers.yaml`.

Automation-side twin of `bump_consumers.py`. Where `bump_consumers.py` reads
the per-dev `~/.ai-playbook/projects.yaml` (local paths on the dev's machine),
this script reads the committed org-level `consumers.yaml` and works against
GitHub via `gh` + a PAT — suitable for CI runners that don't have the
consumer repos cloned locally.

For each active consumer:

    1. Clone its repo into a temp dir using ``$GH_TOKEN``.
    2. Update the ``.ai-playbook/`` submodule pointer to the target tag.
    3. Push a branch ``chore/bump-playbook-<tag>``.
    4. Open a PR against the consumer's default branch.
    5. Emit a ``warn`` notification per PR via ``scripts/notify.py``.

Idempotent: if a PR already exists for ``chore/bump-playbook-<tag>`` on a
consumer, skip + log. Refuses to overwrite existing PRs.

Usage (CI)
----------
    python -m scripts.propagate_bump --tag v0.2.1 --consumers consumers.yaml --open-pr --notify

Env
---
    GH_TOKEN                       PAT with contents:write + pull-requests:write
                                   on every consumer repo.
    SMTP_*, AIPLAYBOOK_NOTIFICATIONS_TO  (optional) — if set, email fan-out.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Shared with bump_consumers.py — keeps the "what tag, what branch, what message"
# vocabulary in one place. See scripts/_bumper.py.
from scripts._bumper import (  # noqa: E402
    bump_agents_md_pin,
    bump_branch,
    commit_message,
    supersede_open_bump_prs,
)

# Branch prefix for the playbook-bump stream. Must match
# `_bumper.BUMP_BRANCH_TEMPLATE` (currently `chore/bump-playbook-{tag}`).
SUPERSEDE_PREFIX = "chore/bump-playbook-"

# Used to identify which AGENTS.md frontmatter items refer to the playbook
# itself. Per v0.9.0 followup #1, both `inherits_from:` and `skills_sources:`
# items pointing at this short repo name must be bumped in lockstep with the
# submodule pointer.
PLAYBOOK_REPO_NAME = "ai-playbook"

# Per specs/bootstrap-directive.md v1.2.0 (added 2026-05-05): every consumer's
# AGENTS.md §2 Dispatcher index MUST contain a row pointing to
# .ai-playbook/docs/development-flow.md. The migration runs as part of the
# v0.9.3+ bump PR (this is "Opción 1" from the consumer-side migration plan
# in development-flow.md §3.3). Idempotent — already-present link → no-op.
DEV_FLOW_CROSS_REF_ROW = (
    "| **How to make a change in this project (canonical entry point)** "
    "| [.ai-playbook/docs/development-flow.md]"
    "(.ai-playbook/docs/development-flow.md) |"
)
DEV_FLOW_LINK_LITERAL = "development-flow.md"


@dataclass
class PropagationResult:
    consumer: str
    status: str  # "pr-opened" | "up-to-date" | "pr-exists" | "skipped" | "error"
    detail: str
    pr_url: str | None = None


def _run(
    cmd: list[str],
    cwd: Path | None = None,
    check: bool = True,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run a subprocess, capturing stdout+stderr; raise on non-zero when check."""
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=merged_env,
    )


def _load_consumers(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not data or data.get("schema") != "ai-playbook/consumers/v1":
        raise SystemExit(f"❌ {path}: schema is not ai-playbook/consumers/v1")
    out = []
    for name, meta in (data.get("consumers") or {}).items():
        if (meta or {}).get("status") != "active":
            continue
        out.append({"name": name, **(meta or {})})
    return out


def _configure_git_credentials(token: str) -> None:
    """Install a global `url.<base>.insteadOf` rewrite so every github.com
    clone (including nested submodules) transparently uses the PAT.

    Called once per run; overwrites any existing rewrite for github.com.
    """
    _run(
        [
            "git",
            "config",
            "--global",
            f"url.https://{token}@github.com/.insteadOf",
            "https://github.com/",
        ],
    )
    # Also disable any credential helper so git doesn't try to prompt on miss.
    _run(
        ["git", "config", "--global", "credential.helper", ""],
        check=False,
    )


def _clone_consumer(name: str, repo: str, token: str, workdir: Path) -> Path:
    """Clone the consumer (and its submodules). Relies on the `insteadOf`
    rewrite from `_configure_git_credentials` to authenticate transparently."""
    url = f"https://github.com/{repo}.git"
    dest = workdir / name
    _run(["git", "clone", "--quiet", "--recurse-submodules", url, str(dest)])
    return dest


def ensure_dev_flow_cross_ref(agents_md_path: Path) -> tuple[bool, str]:
    """Insert the development-flow.md cross-ref row in AGENTS.md §2 if absent.

    Per specs/bootstrap-directive.md v1.2.0. Idempotent — if the literal
    "development-flow.md" already appears anywhere in the body, return
    (False, "already-present") without modifying the file.

    Returns (changed, detail). `detail` is a one-line human-readable
    description for the PR body / propagation log.
    """
    if not agents_md_path.is_file():
        return False, "AGENTS.md absent"

    text = agents_md_path.read_text(encoding="utf-8")

    # Idempotent short-circuit.
    if DEV_FLOW_LINK_LITERAL in text:
        return False, "already-present"

    lines = text.splitlines(keepends=False)
    inserted = False
    out: list[str] = []

    # Find the §2 Dispatcher index section + its table separator row.
    # Pattern: a heading line containing "Dispatcher index" (any header level)
    # followed eventually by a table whose 2nd row is `|---|---|...|`. We
    # insert the new row IMMEDIATELY AFTER the separator (= as the first
    # data row of the table).
    in_section = False
    for line in lines:
        out.append(line)
        if not in_section:
            # Section detection — accept "## 2 Dispatcher index", "## 2.
            # Dispatcher index", "## Dispatcher index", "### Dispatcher index"
            # etc., case-insensitive.
            if line.lstrip().startswith("#") and "dispatcher index" in line.lower():
                in_section = True
            continue

        if inserted:
            continue

        # Inside §2 — look for the table separator (`|---|---|...|`).
        stripped = line.strip()
        if (
            stripped.startswith("|")
            and stripped.endswith("|")
            and set(stripped.replace("|", "").replace("-", "").replace(":", "").strip()) <= {" "}
            and "-" in stripped
        ):
            out.append(DEV_FLOW_CROSS_REF_ROW)
            inserted = True
            continue

        # Bail out if we hit the next heading without finding a table —
        # consumer's §2 is non-canonical; do not insert blindly.
        if line.lstrip().startswith("#") and "dispatcher index" not in line.lower():
            break

    if not inserted:
        return False, (
            "§2 Dispatcher index has no table separator (`|---|---|`); "
            "manual insert needed"
        )

    new_text = "\n".join(out)
    if text.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"
    agents_md_path.write_text(new_text, encoding="utf-8")
    return True, "inserted as first row of §2 Dispatcher index"


def _update_submodule_to_tag(consumer_root: Path, submodule_path: str, tag: str) -> str:
    """Check out the tag inside the submodule. Returns target SHA."""
    sub = consumer_root / submodule_path
    _run(["git", "fetch", "--tags", "--quiet", "origin"], cwd=sub)
    sha = _run(
        ["git", "rev-parse", f"refs/tags/{tag}^{{commit}}"], cwd=sub
    ).stdout.strip()
    _run(["git", "checkout", "--quiet", tag], cwd=sub)
    return sha


def _pr_exists(consumer_root: Path, head_branch: str) -> str | None:
    """Return PR URL if a PR already exists for head_branch, else None."""
    r = _run(
        [
            "gh",
            "pr",
            "list",
            "--head",
            head_branch,
            "--state",
            "open",
            "--json",
            "url",
        ],
        cwd=consumer_root,
        check=False,
    )
    if r.returncode != 0:
        return None
    try:
        items = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return items[0]["url"] if items else None


def _propagate_one(
    consumer: dict,
    tag: str,
    token: str,
    workdir: Path,
    open_pr: bool,
) -> PropagationResult:
    name = consumer["name"]
    repo = consumer["repo"]
    default_branch = consumer.get("default_branch", "master")
    submodule_path = consumer.get("submodule_path", ".ai-playbook")
    head_branch = bump_branch(tag)

    try:
        root = _clone_consumer(name, repo, token, workdir)
    except subprocess.CalledProcessError as e:
        return PropagationResult(name, "error", f"clone failed: {(e.stderr or '').strip()[:200]}")

    sub = root / submodule_path
    if not sub.exists():
        return PropagationResult(
            name, "skipped", f"{submodule_path}/ not present in repo"
        )

    # Idempotency check — has the PR already been opened?
    existing = _pr_exists(root, head_branch)
    if existing:
        return PropagationResult(name, "pr-exists", f"PR already open: {existing}", existing)

    try:
        target_sha = _update_submodule_to_tag(root, submodule_path, tag)
    except subprocess.CalledProcessError as e:
        return PropagationResult(
            name, "error", f"submodule checkout failed: {(e.stderr or '').strip()[:200]}"
        )

    current_parent_sha = _run(
        ["git", "rev-parse", f"HEAD:{submodule_path}"], cwd=root
    ).stdout.strip()

    # Per v0.9.0 followup #1: bump AGENTS.md frontmatter pins in the same
    # commit so consumers without `skills_pins:` (e.g. livekit) don't drift
    # to a stale `inherits_from:` value. The helper is a no-op when AGENTS.md
    # is missing or already at-target. Both `inherits_from:` items (with the
    # `github.com/` prefix) and `skills_sources:` items (without) match.
    agents_md_changed, agents_md_detail = bump_agents_md_pin(
        root / "AGENTS.md", PLAYBOOK_REPO_NAME, tag
    )

    # Per specs/bootstrap-directive.md v1.2.0: ensure consumer's AGENTS.md
    # §2 Dispatcher index has a row pointing to docs/development-flow.md.
    # Migration "Opción 1" — runs in the same commit as the version bump so
    # the cross-ref lands across all consumers in one rollout pass.
    # Idempotent (no-op if already present).
    cross_ref_changed, cross_ref_detail = ensure_dev_flow_cross_ref(
        root / "AGENTS.md"
    )

    if (
        current_parent_sha == target_sha
        and not agents_md_changed
        and not cross_ref_changed
    ):
        return PropagationResult(name, "up-to-date", f"already at {tag}")

    # Stage + commit.
    _run(["git", "config", "user.name", "ai-playbook-bot"], cwd=root)
    _run(
        ["git", "config", "user.email", "23051550+Wizarck@users.noreply.github.com"],
        cwd=root,
    )
    _run(["git", "checkout", "-b", head_branch], cwd=root)
    if current_parent_sha != target_sha:
        _run(["git", "add", submodule_path], cwd=root)
    if agents_md_changed or cross_ref_changed:
        _run(["git", "add", "AGENTS.md"], cwd=root)
    commit_msg = commit_message(tag)
    _run(["git", "commit", "-m", commit_msg], cwd=root)

    _run(["git", "push", "-u", "origin", head_branch], cwd=root)

    pr_url = None
    if open_pr:
        cross_ref_line = (
            f"\n- AGENTS.md §2 Dispatcher index: {cross_ref_detail}"
            if cross_ref_changed
            else ""
        )
        body = (
            f"Automated bump of `.ai-playbook/` submodule to **{tag}**.\n\n"
            f"Opened by `scripts/propagate_bump.py` on tag push.\n\n"
            f"- Previous submodule commit: `{current_parent_sha[:8]}`\n"
            f"- New submodule commit: `{target_sha[:8]}` (tag `{tag}`)"
            f"{cross_ref_line}\n\n"
            f"Review the submodule diff at `.ai-playbook/` and merge when ready.\n\n"
            f"See [ai-playbook CHANGELOG.md]"
            f"(https://github.com/Wizarck/ai-playbook/blob/{tag}/CHANGELOG.md) "
            f"for what this tag includes."
        )
        r = _run(
            [
                "gh",
                "pr",
                "create",
                "--title",
                commit_msg,
                "--body",
                body,
                "--base",
                default_branch,
                "--head",
                head_branch,
            ],
            cwd=root,
            check=False,
        )
        if r.returncode == 0:
            pr_url = (r.stdout or "").strip().splitlines()[-1] if r.stdout else None
        else:
            return PropagationResult(
                name, "error", f"gh pr create failed: {(r.stderr or '').strip()[:200]}"
            )

        # Supersede any prior open `chore/bump-playbook-*` PRs in this
        # consumer (per release-management.md §3.4). Best-effort: any
        # individual close failure is silently swallowed and the new PR
        # still wins. Extracted to _bumper.supersede_open_bump_prs so
        # propagate_skills_bump.py can share the logic.
        new_pr_number: int | None = None
        if pr_url:
            try:
                new_pr_number = int(pr_url.rsplit("/", 1)[-1])
            except ValueError:
                new_pr_number = None
        try:
            closed = supersede_open_bump_prs(
                root,
                SUPERSEDE_PREFIX,
                new_pr_number,
                new_branch=head_branch,
                new_pr_url=pr_url,
            )
            if closed:
                print(
                    f"  superseded {len(closed)} prior open PR(s): {', '.join(closed)}",
                    file=sys.stderr,
                )
        except Exception as exc:  # noqa: BLE001 — supersede is best-effort
            print(f"[propagate_bump] supersede failed for {name}: {exc}", file=sys.stderr)

    return PropagationResult(
        name, "pr-opened", f"{current_parent_sha[:8]} → {target_sha[:8]} ({tag})", pr_url
    )


def _notify(event: str, severity: str, summary: str, detail: str) -> None:
    """Fire-and-forget notification via scripts/notify.py (JSONL + SMTP)."""
    try:
        from scripts.notify import notify

        notify(event=event, severity=severity, summary=summary, detail=detail)
    except Exception as exc:  # noqa: BLE001 — notify must never block propagation
        print(f"[propagate_bump] notify failed: {exc}", file=sys.stderr)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--tag", required=True, help="Semver tag pushed to ai-playbook.")
    p.add_argument(
        "--consumers",
        default="consumers.yaml",
        help="Path to the committed consumers.yaml registry.",
    )
    p.add_argument("--open-pr", action="store_true", help="Open a PR per bump.")
    p.add_argument(
        "--notify",
        action="store_true",
        help="Emit notifications via scripts/notify.py.",
    )
    args = p.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print(
            "❌ GH_TOKEN / GITHUB_TOKEN is unset at propagate_bump:env\n"
            "   FIX: set a PAT with contents:write + pull-requests:write on every "
            "consumer repo listed in consumers.yaml.\n"
            "   OVERRIDE: none",
            file=sys.stderr,
        )
        return 1

    consumers_path = Path(args.consumers).resolve()
    if not consumers_path.exists():
        print(
            f"❌ consumers registry not found at {consumers_path}\n"
            f"   FIX: cp consumers.yaml.example consumers.yaml  (then fill in real data).\n"
            f"   consumers.yaml is gitignored — your real consumer inventory never\n"
            f"   enters the repo. consumers.yaml.example is the schema template.",
            file=sys.stderr,
        )
        return 1

    _configure_git_credentials(token)

    consumers = _load_consumers(consumers_path)
    print(f"Propagating {args.tag} to {len(consumers)} active consumer(s).\n")

    results: list[PropagationResult] = []
    with tempfile.TemporaryDirectory(prefix="playbook-bump-") as tmp:
        workdir = Path(tmp)
        for c in consumers:
            try:
                r = _propagate_one(c, args.tag, token, workdir, args.open_pr)
            except Exception as exc:  # noqa: BLE001
                r = PropagationResult(c["name"], "error", f"unexpected: {exc}")
            results.append(r)

            if args.notify:
                sev = "error" if r.status == "error" else "warn"
                _notify(
                    event=f"playbook.propagate.{r.status.replace('-', '_')}",
                    severity=sev,
                    summary=f"{c['name']}: {r.status}",
                    detail=f"{r.detail}{f' {r.pr_url}' if r.pr_url else ''}",
                )

    col = max(len(r.consumer) for r in results) + 2
    print()
    for r in results:
        icon = {
            "pr-opened": "✅",
            "up-to-date": "✓ ",
            "pr-exists": "➡️",
            "skipped": "— ",
            "error": "❌",
        }.get(r.status, "? ")
        print(f"  {icon} {r.consumer:<{col}} {r.status:<11} {r.detail}")
        if r.pr_url:
            print(f"     {r.pr_url}")

    errors = sum(1 for r in results if r.status == "error")
    if errors and args.notify:
        _notify(
            event="playbook.propagate.summary_errors",
            severity="error",
            summary=f"{args.tag}: {errors}/{len(results)} consumers errored",
            detail="; ".join(f"{r.consumer}: {r.detail}" for r in results if r.status == "error"),
        )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
