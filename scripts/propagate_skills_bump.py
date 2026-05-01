"""Propagate a skills source repo tag bump to every consumer in `consumers.yaml`.

Sibling of `propagate_bump.py`. Where `propagate_bump.py` bumps the
`.ai-playbook/` submodule pointer for every active consumer, this script bumps
the **AGENTS.md frontmatter `skills_sources`** entry for every consumer that
has the matching `skills_pins.<source-repo>` key.

Triggered by tag pushes to ANY of the source repos listed in `consumers.yaml`'s
`skills_pins.*` keys (currently `ai-playbook` and `eligia-skills`); see
`.github/workflows/propagate-skills-bump.yml` for the wiring.

For each consumer that has `skills_pins.<source-repo>`:

    1. Clone the consumer repo into a temp dir using ``$GH_TOKEN``.
    2. Edit AGENTS.md frontmatter so the `<owner>/<source-repo>@<tag>` entry
       under `skills_sources` is updated to the new tag (idempotent: skip if
       already at target).
    3. Push a branch ``chore/bump-skills-<source-repo>-<tag>``.
    4. Open a PR against the consumer's default branch.
    5. Emit a ``warn`` notification per PR via ``scripts/notify.py``.

Idempotent: if a PR already exists for the same head_branch on a consumer,
skip + log. Refuses to overwrite existing PRs.

Usage (CI)
----------
    python -m scripts.propagate_skills_bump \
        --source-repo ai-playbook --tag v0.4.0 \
        --consumers consumers.yaml --open-pr --notify

Env
---
    GH_TOKEN                       PAT with contents:write + pull-requests:write
                                   on every consumer repo.
    SMTP_*, AIPLAYBOOK_NOTIFICATIONS_TO  (optional) — if set, email fan-out.

Exit codes
----------
    0  success (zero errors).
    1  one or more consumers errored; PRs that succeeded are still open.
"""
from __future__ import annotations

import argparse
import json
import os
import re
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

# Reuse the supersede helper. Per release-management.md §3.4, every new
# `chore/bump-*` PR auto-closes prior open PRs on the same logical change-
# stream. Identified by branch prefix (each source-repo has its own).
from scripts._bumper import supersede_open_bump_prs  # noqa: E402
from scripts._skills_materialiser import materialise_skills  # noqa: E402

SUPPORTED_SOURCES = ("ai-playbook", "eligia-skills")
BUMP_BRANCH_TEMPLATE = "chore/bump-skills-{source}-{tag}"
COMMIT_TEMPLATE = "chore(skills): bump {source} to {tag}"


def supersede_prefix(source_repo: str) -> str:
    """Branch prefix for the per-source supersede stream.

    Example: source_repo="ai-playbook" -> "chore/bump-skills-ai-playbook-".
    """
    return f"chore/bump-skills-{source_repo}-"


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class PropagationResult:
    consumer: str
    status: str  # "pr-opened" | "up-to-date" | "pr-exists" | "skipped" | "error"
    detail: str
    pr_url: str | None = None


# ---------------------------------------------------------------------------
# Subprocess helper (parity with propagate_bump.py)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Branch / commit naming
# ---------------------------------------------------------------------------


def bump_branch(source_repo: str, tag: str) -> str:
    return BUMP_BRANCH_TEMPLATE.format(source=source_repo, tag=tag)


def commit_message(source_repo: str, tag: str) -> str:
    return COMMIT_TEMPLATE.format(source=source_repo, tag=tag)


# ---------------------------------------------------------------------------
# consumers.yaml loading + filtering
# ---------------------------------------------------------------------------


def _load_consumers(path: Path, source_repo: str) -> list[dict]:
    """Return the active consumers that have a skills_pins.<source_repo> key."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not data or data.get("schema") != "ai-playbook/consumers/v1":
        raise SystemExit(f"❌ {path}: schema is not ai-playbook/consumers/v1")
    out = []
    for name, meta in (data.get("consumers") or {}).items():
        meta = meta or {}
        if meta.get("status") != "active":
            continue
        pins = meta.get("skills_pins") or {}
        if source_repo not in pins:
            continue
        out.append({"name": name, **meta})
    return out


# ---------------------------------------------------------------------------
# Git auth (parity with propagate_bump.py)
# ---------------------------------------------------------------------------


def _configure_git_credentials(token: str) -> None:
    """Install a global `url.<base>.insteadOf` rewrite so every github.com
    clone (including nested submodules) transparently uses the PAT."""
    _run(
        [
            "git", "config", "--global",
            f"url.https://{token}@github.com/.insteadOf",
            "https://github.com/",
        ],
    )
    _run(
        ["git", "config", "--global", "credential.helper", ""],
        check=False,
    )


def _clone_consumer(name: str, repo: str, workdir: Path) -> Path:
    url = f"https://github.com/{repo}.git"
    dest = workdir / name
    _run(["git", "clone", "--quiet", url, str(dest)])
    return dest


# ---------------------------------------------------------------------------
# AGENTS.md frontmatter editor
# ---------------------------------------------------------------------------


_AT_REF_RE = re.compile(
    r"(?P<prefix>(?:github\.com/)?[A-Za-z0-9._-]+/)(?P<repo>[A-Za-z0-9._-]+)@(?P<tag>[A-Za-z0-9._+-]+)"
)


def _edit_frontmatter_skills_source(
    agents_md: Path,
    source_repo: str,
    new_tag: str,
) -> tuple[bool, str]:
    """Rewrite the `skills_sources` line whose ref matches `source_repo`.

    Returns `(changed, detail)`. `changed=False, detail="up-to-date"` when the
    pin already matches `new_tag`. `changed=False, detail="not-found"` when the
    file has no entry for that source repo.

    Surgical line-level edit (not a full YAML re-serialise) so we preserve
    comments, ordering, and quoting style in AGENTS.md. The file is small
    enough that a regex line-walk is reliable.
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
        # Track `updated:` line index so we can refresh it when bumping.
        # Per gotcha (iguanatrader/docs/gotchas.md, surfaced 2026-05-01):
        # propagate_skills_bump previously rewrote skills_sources but not
        # `updated:`, leaving AGENTS.md frontmatter with stale dates after
        # automated bumps. Now we refresh in lockstep.
        if re.match(r"^\s*updated\s*:", ln) and updated_line_idx is None:
            updated_line_idx = i
            continue
        # Match a YAML list item like "  - Wizarck/ai-playbook@v0.3.0"
        # (also tolerates "github.com/" prefix).
        m = re.match(
            r"(?P<indent>\s*-\s*)(?P<ref>(?:github\.com/)?(?P<owner>[A-Za-z0-9._-]+)/"
            r"(?P<repo>[A-Za-z0-9._-]+)@(?P<tag>[A-Za-z0-9._+-]+))(?P<rest>\s*(?:#.*)?)?$",
            ln,
        )
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

    # If we rewrote a skills_sources line, also refresh `updated:` to today.
    if changed and updated_line_idx is not None:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Preserve key + indentation; replace value only. Tolerates quoted
        # values ("YYYY-MM-DD") and unquoted (YYYY-MM-DD).
        old_line = lines[updated_line_idx]
        m_upd = re.match(r"^(\s*updated\s*:\s*)(['\"]?)([^'\"#\n]+?)(['\"]?\s*(?:#.*)?)$", old_line)
        if m_upd:
            lines[updated_line_idx] = f"{m_upd.group(1)}{m_upd.group(2)}{today}{m_upd.group(4)}"

    if changed:
        agents_md.write_text("\n".join(lines), encoding="utf-8", newline="\n")
        return True, "rewrote"
    if already_at_target:
        return False, "up-to-date"
    return False, "not-found"


# ---------------------------------------------------------------------------
# PR existence check
# ---------------------------------------------------------------------------


def _pr_exists(consumer_root: Path, head_branch: str) -> str | None:
    """Return PR URL if a PR already exists for head_branch, else None."""
    r = _run(
        ["gh", "pr", "list", "--head", head_branch, "--state", "open", "--json", "url"],
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


# ---------------------------------------------------------------------------
# Per-consumer propagation
# ---------------------------------------------------------------------------


def _propagate_one(
    consumer: dict,
    *,
    source_repo: str,
    tag: str,
    workdir: Path,
    open_pr: bool,
) -> PropagationResult:
    name = consumer["name"]
    repo = consumer["repo"]
    default_branch = consumer.get("default_branch", "master")
    head_branch = bump_branch(source_repo, tag)

    try:
        root = _clone_consumer(name, repo, workdir)
    except subprocess.CalledProcessError as e:
        return PropagationResult(name, "error", f"clone failed: {(e.stderr or '').strip()[:200]}")

    agents_md = root / "AGENTS.md"
    if not agents_md.is_file():
        return PropagationResult(name, "skipped", "AGENTS.md not present")

    # Idempotency check — has the PR already been opened?
    existing = _pr_exists(root, head_branch)
    if existing:
        return PropagationResult(name, "pr-exists", f"PR already open: {existing}", existing)

    changed, detail = _edit_frontmatter_skills_source(agents_md, source_repo, tag)
    if not changed:
        if detail == "up-to-date":
            return PropagationResult(name, "up-to-date", f"already at {tag}")
        if detail == "not-found":
            return PropagationResult(
                name,
                "skipped",
                f"AGENTS.md has no skills_sources entry for {source_repo}",
            )
        return PropagationResult(
            name, "skipped", f"AGENTS.md edit unsupported: {detail}",
        )

    # Advance submodule + tracked skills/ mirror to match the new tag.
    #
    # Without this, AGENTS.md frontmatter says the new tag but the
    # `.skills-sources/<source>/` submodule pointer + tracked `skills/`
    # mirror stay at the old tag. The propagation is half-baked: every
    # consumer would need a manual `bootstrap.py --refresh-skills` after
    # merging the bump PR. Surfaced 2026-05-01 in openTrattOS — AGENTS.md
    # said `Wizarck/ai-playbook@v0.8.6` but `.skills-sources/ai-playbook`
    # was still pinned to v0.7.1. Fix: run the materialiser now so the bot
    # ships the fully-propagated state in one PR.
    mat_result = materialise_skills(root, dry_run=False)
    if mat_result.errors:
        return PropagationResult(
            name,
            "error",
            f"skills materialiser failed: {'; '.join(mat_result.errors)[:200]}",
        )

    # Stage + commit. Includes:
    #   - AGENTS.md (frontmatter skills_sources tag bump)
    #   - .gitmodules (only if a brand-new submodule was added)
    #   - .skills-sources/<source>/ (submodule pointer advance)
    #   - skills/ (tracked materialised mirror diffs from upstream tag)
    # The .claude/skills/ + .gemini/skills/ mirrors are gitignored and
    # regenerate on the consumer's machine via SessionStart hooks.
    _run(["git", "config", "user.name", "ai-playbook-bot"], cwd=root)
    _run(
        ["git", "config", "user.email", "arturo6ramirez@gmail.com"],
        cwd=root,
    )
    _run(["git", "checkout", "-b", head_branch], cwd=root)
    _run(["git", "add", "AGENTS.md"], cwd=root)
    # `.gitmodules` may not exist (first-ever bump on a fresh consumer);
    # `.skills-sources` and `skills` may have no diff if the upstream tag
    # didn't change those paths. `check=False` covers all of these.
    _run(["git", "add", ".gitmodules"], cwd=root, check=False)
    _run(["git", "add", ".skills-sources"], cwd=root, check=False)
    _run(["git", "add", "skills"], cwd=root, check=False)
    msg = commit_message(source_repo, tag)
    _run(["git", "commit", "-m", msg], cwd=root)

    _run(["git", "push", "-u", "origin", head_branch], cwd=root)

    pr_url = None
    if open_pr:
        body = (
            f"Automated bump of `{source_repo}` skills source to **{tag}**.\n\n"
            f"Opened by `scripts/propagate_skills_bump.py` on tag push of "
            f"`{source_repo}` per RFC-0001. This commit ships the fully-"
            f"propagated state in one go:\n\n"
            f"- `AGENTS.md` frontmatter `skills_sources` entry updated to `{tag}`\n"
            f"- `.skills-sources/{source_repo}/` submodule pointer advanced to `{tag}`\n"
            f"- `skills/` tracked mirror regenerated from the new tag's contents\n\n"
            f"The per-LLM mirrors at `.claude/skills/` and `.gemini/skills/` "
            f"are gitignored and regenerate locally on each consumer machine "
            f"via the SessionStart hook — no post-merge action required.\n\n"
            f"See [{source_repo} CHANGELOG.md]"
            f"(https://github.com/Wizarck/{source_repo}/blob/{tag}/CHANGELOG.md) "
            f"for what this tag includes."
        )
        r = _run(
            [
                "gh", "pr", "create",
                "--title", msg,
                "--body", body,
                "--base", default_branch,
                "--head", head_branch,
            ],
            cwd=root,
            check=False,
        )
        if r.returncode == 0:
            pr_url = (r.stdout or "").strip().splitlines()[-1] if r.stdout else None
        else:
            return PropagationResult(
                name, "error", f"gh pr create failed: {(r.stderr or '').strip()[:200]}",
            )

        # Supersede prior open `chore/bump-skills-<source>-*` PRs in this
        # consumer (per release-management.md §3.4). Per-source prefix so
        # ai-playbook bumps don't accidentally close eligia-skills bumps.
        new_pr_number: int | None = None
        if pr_url:
            try:
                new_pr_number = int(pr_url.rsplit("/", 1)[-1])
            except ValueError:
                new_pr_number = None
        try:
            closed = supersede_open_bump_prs(
                root,
                supersede_prefix(source_repo),
                new_pr_number,
                new_pr_url=pr_url,
            )
            if closed:
                print(
                    f"  superseded {len(closed)} prior open PR(s): {', '.join(closed)}",
                    file=sys.stderr,
                )
        except Exception as exc:  # noqa: BLE001 — supersede is best-effort
            print(f"[propagate_skills_bump] supersede failed for {name}: {exc}", file=sys.stderr)

    return PropagationResult(
        name, "pr-opened", f"{source_repo} → {tag}", pr_url,
    )


# ---------------------------------------------------------------------------
# Notification (parity with propagate_bump.py)
# ---------------------------------------------------------------------------


def _notify(event: str, severity: str, summary: str, detail: str) -> None:
    """Fire-and-forget notification via scripts/notify.py (JSONL + SMTP)."""
    try:
        from scripts.notify import emit
        emit(event=event, severity=severity, summary=summary, detail=detail)
    except Exception as exc:  # noqa: BLE001 — notify must never block propagation
        print(f"[propagate_skills_bump] notify failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument(
        "--source-repo",
        required=True,
        choices=list(SUPPORTED_SOURCES),
        help="Source repo whose tag was pushed (drives consumers.yaml filter).",
    )
    p.add_argument("--tag", required=True, help="Semver tag pushed to the source repo.")
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
    args = p.parse_args(argv)

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print(
            "❌ GH_TOKEN / GITHUB_TOKEN is unset at propagate_skills_bump:env\n"
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
            f"   FIX: pass --consumers <path-to-consumers.yaml>.\n"
            f"   OVERRIDE: none",
            file=sys.stderr,
        )
        return 1

    _configure_git_credentials(token)

    consumers = _load_consumers(consumers_path, args.source_repo)
    print(
        f"Propagating skills bump {args.source_repo}@{args.tag} to "
        f"{len(consumers)} consumer(s) with a `skills_pins.{args.source_repo}` "
        f"entry.\n"
    )
    if not consumers:
        print(
            f"  (no consumers have skills_pins.{args.source_repo} yet — "
            f"this is expected pre-Phase-5)."
        )
        return 0

    results: list[PropagationResult] = []
    with tempfile.TemporaryDirectory(prefix="skills-bump-") as tmp:
        workdir = Path(tmp)
        for c in consumers:
            try:
                r = _propagate_one(
                    c,
                    source_repo=args.source_repo,
                    tag=args.tag,
                    workdir=workdir,
                    open_pr=args.open_pr,
                )
            except Exception as exc:  # noqa: BLE001
                r = PropagationResult(c["name"], "error", f"unexpected: {exc}")
            results.append(r)

            if args.notify:
                sev = "error" if r.status == "error" else "warn"
                _notify(
                    event=f"skills.propagate.{r.status.replace('-', '_')}",
                    severity=sev,
                    summary=f"{c['name']}: {r.status}",
                    detail=f"{r.detail}{f' {r.pr_url}' if r.pr_url else ''}",
                )

    col = max((len(r.consumer) for r in results), default=10) + 2
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
            event="skills.propagate.summary_errors",
            severity="error",
            summary=f"{args.source_repo}@{args.tag}: {errors}/{len(results)} consumers errored",
            detail="; ".join(
                f"{r.consumer}: {r.detail}" for r in results if r.status == "error"
            ),
        )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
