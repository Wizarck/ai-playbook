"""Post a structured self-review checklist on a PR when CodeRabbit + L1 didn't run.

Per release-management.md §4.5.2 (introduced in v0.9.0): when a PR opens
and CodeRabbit doesn't review within 5 minutes (rate-limited or silent)
AND the PR body's §4.5 section is empty/stubbed, this script posts a
diff-aware fallback checklist as a PR comment + marks the status check
``ai-self-review-required`` as failing. The check is informational
(not in branch-protection required-checks by default).

If the §4.5 section is **already populated** (the worker AI ran L1
in-session per `runbooks/coderabbit-fallback.md`), this script exits
quietly without posting — L2 is a silent safety net for the case where
L1 didn't run.

CLI
---
    python -m scripts.post_self_review_checklist \\
        --pr 41 \\
        --repo Wizarck/consumer-e \\
        [--head-sha <sha>] \\
        [--dry-run]

Exit codes
----------
    0 — quiet success: §4.5 already populated, OR checklist posted, OR
        coderabbit available (no need for L2).
    2 — setup error (gh unavailable, PR / repo not found, args invalid).
    3 — unrecoverable gh / network error.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# Force UTF-8 stdio.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.bootstrap_gh_project import _emit, _gh_available  # noqa: E402

# Markers L2 regex-checks in the PR body §4.5 section. All three required
# (case-sensitive substring), and the body content following the marker
# must be non-stub (not "TODO", not "<placeholder>", non-empty).
SCHEMA_MARKERS: tuple[str, ...] = (
    "Profile:",
    "Reviewer:",
    "Self-review findings:",
)
STUB_INDICATORS: tuple[str, ...] = (
    "TODO",
    "<placeholder>",
    "<finding>",
    "<reason>",
    "<one-sentence",
)
STATUS_CHECK_NAME = "ai-self-review-required"


def _gh_pr_body(pr: int, repo: str) -> str:
    proc = subprocess.run(
        ["gh", "pr", "view", str(pr), "--repo", repo, "--json", "body"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh pr view --json body failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    payload = json.loads(proc.stdout)
    body = payload.get("body", "")
    return str(body) if body else ""


def _gh_pr_diff(pr: int, repo: str) -> str:
    proc = subprocess.run(
        ["gh", "pr", "diff", str(pr), "--repo", repo],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh pr diff failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


def _gh_pr_meta(pr: int, repo: str) -> dict[str, object]:
    proc = subprocess.run(
        [
            "gh",
            "pr",
            "view",
            str(pr),
            "--repo",
            repo,
            "--json",
            "headRefOid,number,title",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh pr view failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    return json.loads(proc.stdout)  # type: ignore[no-any-return]


def is_section_45_populated(body: str) -> bool:
    """Return True iff the PR body's §4.5 section satisfies the schema.

    All three SCHEMA_MARKERS must be present in some form. The match is
    permissive enough to handle:

    * Markdown bold (``**Profile**:``).
    * Parenthetical annotation between marker word and colon
      (``**Self-review findings** (this branch):``).
    * Findings list starting on the next non-blank line (markdown lists
      where the marker line has only the colon).

    The line's content after the colon (or the next non-blank line) must
    be non-empty and must not contain a STUB_INDICATOR (``TODO``,
    ``<placeholder>``, etc.).
    """
    if not body:
        return False
    # Normalise markdown bold so `**Profile**:` matches `Profile:`. The
    # `**` characters carry no semantic load for the marker check.
    normalised = body.replace("**", "")
    for marker in SCHEMA_MARKERS:
        marker_word = marker.rstrip(":").strip()
        # Permissive: marker word, optional whitespace, optional
        # parenthetical annotation, optional whitespace, mandatory colon.
        pattern = re.compile(rf"{re.escape(marker_word)}\s*(?:\([^)]*\))?\s*:")
        m = pattern.search(normalised)
        if m is None:
            return False
        # Examine the rest of the line to filter stub content.
        remainder_start = m.end()
        eol = normalised.find("\n", remainder_start)
        line_remainder = (
            normalised[remainder_start:eol]
            if eol != -1
            else normalised[remainder_start:]
        )
        stripped = line_remainder.strip()
        if not stripped:
            # Allow content on the next non-blank line — handles markdown
            # lists where findings start beneath the marker line. But the
            # next non-blank line must NOT itself be another marker line
            # (e.g. `Reviewer:` followed by blank then `Self-review
            # findings: 1` — the Reviewer field is genuinely empty).
            tail = normalised[remainder_start:]
            for next_line in tail.split("\n")[1:]:
                if next_line.strip():
                    candidate_stripped = next_line.strip()
                    is_other_marker = any(
                        candidate_stripped.startswith(other.rstrip(":").strip())
                        for other in SCHEMA_MARKERS
                        if other.rstrip(":").strip() != marker_word
                    )
                    if is_other_marker:
                        return False
                    stripped = candidate_stripped
                    line_remainder = next_line
                    break
            if not stripped:
                return False
        if any(stub in line_remainder for stub in STUB_INDICATORS):
            return False
    return True


def analyse_diff(diff: str) -> dict[str, list[str]]:
    """Extract diff signals for the checklist.

    Returns a dict with categorized lines (functions / classes / async /
    error sites / new imports / new files). Non-exhaustive — designed to
    surface high-signal changes only.
    """
    files_changed: list[str] = []
    new_funcs: list[str] = []
    new_classes: list[str] = []
    new_async: list[str] = []
    new_raises: list[str] = []
    new_imports: list[str] = []

    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            files_changed.append(line[len("+++ b/") :])
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        added = line[1:].lstrip()
        if added.startswith("def "):
            name_match = re.match(r"def\s+([A-Za-z_][\w]*)", added)
            if name_match:
                new_funcs.append(name_match.group(1))
        elif added.startswith("async def "):
            name_match = re.match(r"async\s+def\s+([A-Za-z_][\w]*)", added)
            if name_match:
                new_async.append(name_match.group(1))
        elif added.startswith("class "):
            name_match = re.match(r"class\s+([A-Za-z_][\w]*)", added)
            if name_match:
                new_classes.append(name_match.group(1))
        elif added.startswith("raise "):
            new_raises.append(added.rstrip())
        elif added.startswith(("import ", "from ")):
            new_imports.append(added.rstrip())

    return {
        "files_changed": sorted(set(files_changed)),
        "new_functions": sorted(set(new_funcs)),
        "new_classes": sorted(set(new_classes)),
        "new_async": sorted(set(new_async)),
        "new_raises": sorted(set(new_raises))[:20],  # cap noise
        "new_imports": sorted(set(new_imports))[:30],
    }


def render_checklist(
    *, pr: int, repo: str, signals: dict[str, list[str]], reason: str
) -> str:
    """Render the markdown checklist body."""
    lines: list[str] = []
    lines.append("## Self-review checklist (CodeRabbit unavailable)")
    lines.append("")
    lines.append(
        f"_Posted by L2 of the v0.9.0 fallback contract because "
        f"`scripts/check_coderabbit_status.py` returned `{reason}` AND "
        f"the PR body's §4.5 section is empty / stubbed._"
    )
    lines.append("")
    lines.append(
        "The worker AI (or human reviewer) MUST address each category "
        "below + populate the **AI-reviewer signoff** section in the PR "
        "body per [`runbooks/coderabbit-fallback.md`](../runbooks/coderabbit-fallback.md). "
        "When §4.5 is populated, the `ai-self-review-required` status "
        "check turns ✅ on the next workflow run."
    )
    lines.append("")
    lines.append("### Diff signals")
    lines.append("")
    if signals["files_changed"]:
        lines.append(f"- **Files changed**: {len(signals['files_changed'])}")
    if signals["new_classes"]:
        lines.append(f"- **New classes**: `{', '.join(signals['new_classes'][:10])}`")
    if signals["new_functions"]:
        lines.append(
            f"- **New functions**: `{', '.join(signals['new_functions'][:10])}`"
            + (
                f" (+{len(signals['new_functions']) - 10} more)"
                if len(signals["new_functions"]) > 10
                else ""
            )
        )
    if signals["new_async"]:
        lines.append(
            f"- **New async functions**: `{', '.join(signals['new_async'][:10])}`"
            + (
                f" (+{len(signals['new_async']) - 10} more)"
                if len(signals["new_async"]) > 10
                else ""
            )
        )
    if signals["new_raises"]:
        lines.append(f"- **New raise sites**: {len(signals['new_raises'])}")
    if signals["new_imports"]:
        lines.append(f"- **New imports**: {len(signals['new_imports'])}")
    lines.append("")
    lines.append("### Categories to review")
    lines.append("")
    lines.append(
        "Per [`runbooks/coderabbit-fallback.md`](../runbooks/coderabbit-fallback.md) §2, "
        "address every category — note `n/a` for those that don't apply. "
        "**Empty checks suggest the AI didn't actually look.**"
    )
    lines.append("")
    lines.append(
        "- [ ] **Type safety** — new `# type: ignore` justified? "
        "`Any` masking concrete types? mypy --strict clean?"
    )
    lines.append(
        "- [ ] **Async + concurrency** — new async exceptions handled? "
        "`asyncio.create_task` cancellation handled? worker tasks logging failures?"
    )
    lines.append(
        "- [ ] **Error handling** — error paths include remediation hints? "
        "broad `except` justified? appropriate `IguanaError` subclass?"
    )
    lines.append(
        "- [ ] **Security** — input validation? regex anchored? "
        "no logging of secrets? new deps without known CVEs?"
    )
    lines.append(
        "- [ ] **Edge cases** — empty inputs / max-size / concurrent / "
        "time / numeric — all handled?"
    )
    lines.append(
        "- [ ] **Public API + docs** — new symbols in `__all__`? "
        "docstrings present? coverage ≥80%?"
    )
    lines.append(
        "- [ ] **Spec / runbook compliance** — boundary checks pass? "
        "scripts follow canonical layout? conventional commits?"
    )
    lines.append("")
    lines.append("### How to make this check turn ✅")
    lines.append("")
    lines.append(
        "Edit the PR body so the **AI-reviewer signoff** section contains all three "
        "markers from `release-management.md` §4.5.3:"
    )
    lines.append("")
    lines.append("```")
    lines.append("Profile: A | B")
    lines.append("Reviewer: <CodeRabbit | claude-code-action | self-review>")
    lines.append(
        "Self-review findings: <list of findings, or 'none' for trivial diffs>"
    )
    lines.append("```")
    lines.append("")
    lines.append(
        "Once committed, the next push will re-run this workflow + the status check turns ✅."
    )
    return "\n".join(lines)


def _gh_pr_comment(pr: int, repo: str, body: str, *, dry_run: bool) -> None:
    if dry_run:
        print(f"→ would post comment on PR {pr} ({len(body)} chars)")
        return
    proc = subprocess.run(
        ["gh", "pr", "comment", str(pr), "--repo", repo, "--body", body],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh pr comment failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )


def _set_status_check(
    *,
    repo: str,
    sha: str,
    state: str,
    description: str,
    dry_run: bool,
) -> None:
    """Set the ai-self-review-required check via the Checks API.

    state: "success" or "failure" (also "pending" / "neutral" valid).
    """
    if dry_run:
        print(f"→ would set status check {STATUS_CHECK_NAME!r}={state!r} on {sha}")
        return
    proc = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{repo}/check-runs",
            "--method",
            "POST",
            "-f",
            f"name={STATUS_CHECK_NAME}",
            "-f",
            f"head_sha={sha}",
            "-f",
            "status=completed",
            "-f",
            f"conclusion={state}",
            "-f",
            f"output[title]={STATUS_CHECK_NAME}",
            "-f",
            f"output[summary]={description}",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        # Non-fatal: the check API may fail if the workflow lacks
        # write permission. Log and continue — the comment still posted.
        print(
            f"warn: status check creation failed: {proc.stderr.strip()}",
            file=sys.stderr,
        )


def run(
    *,
    pr: int,
    repo: str,
    head_sha: str | None,
    dry_run: bool,
) -> int:
    if not _gh_available():
        print(
            "error: gh CLI not authenticated; run `gh auth login` first",
            file=sys.stderr,
        )
        return 2

    _emit("post_self_review_checklist.start", pr=pr, repo=repo, dry_run=dry_run)

    try:
        body = _gh_pr_body(pr, repo)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if is_section_45_populated(body):
        # L1 already ran in-session. Mark the check ✅ and exit silently.
        if head_sha:
            _set_status_check(
                repo=repo,
                sha=head_sha,
                state="success",
                description="§4.5 PR-body section populated; L1 in-session self-review applied.",
                dry_run=dry_run,
            )
        print("§4.5 already populated; no checklist posted.")
        _emit("post_self_review_checklist.complete", action="skipped_section_populated")
        return 0

    try:
        diff = _gh_pr_diff(pr, repo)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    signals = analyse_diff(diff)

    # Determine reason — caller may have passed it via env, but easiest is
    # to assume it's "rate-limited or silent" since this script only fires
    # when L1 already returned exit 1.
    reason = "rate-limited or silent"
    body_md = render_checklist(pr=pr, repo=repo, signals=signals, reason=reason)

    try:
        _gh_pr_comment(pr, repo, body_md, dry_run=dry_run)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    if head_sha:
        _set_status_check(
            repo=repo,
            sha=head_sha,
            state="failure",
            description=(
                "§4.5 PR-body section is empty or stubbed; "
                "self-review checklist posted as a PR comment."
            ),
            dry_run=dry_run,
        )

    _emit(
        "post_self_review_checklist.complete",
        action="posted_checklist",
        files_changed=len(signals["files_changed"]),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Post a structured self-review checklist on a PR when CodeRabbit + L1 "
            "did not run. Skips silently if the PR body's §4.5 section is already "
            "populated. Per release-management.md §4.5.2."
        )
    )
    p.add_argument("--pr", required=True, type=int, help="Pull request number")
    p.add_argument("--repo", required=True, metavar="owner/name")
    p.add_argument(
        "--head-sha",
        default=None,
        help="Head SHA to attach the status check to (optional)",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    try:
        return run(
            pr=args.pr,
            repo=args.repo,
            head_sha=args.head_sha,
            dry_run=args.dry_run,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        _emit("post_self_review_checklist.failed", reason=str(exc))
        return 3


if __name__ == "__main__":
    sys.exit(main())
