"""Detect CodeRabbit availability on a PR.

Per release-management.md §4.5.1: the worker AI MUST invoke this script
after `gh pr create` (or any push that updates a PR) to determine
whether CodeRabbit reviewed the diff or whether to apply Profile B
fallback (in-session self-review per `runbooks/coderabbit-fallback.md`).

CLI
---
    python -m scripts.check_coderabbit_status \\
        --pr 41 \\
        --repo Wizarck/iguanatrader \\
        --wait 300 \\
        [--poll-interval 30] \\
        [--json]

Behavior
--------
- Polls `gh pr view <PR> --repo <R> --json comments` every
  `--poll-interval` seconds for up to `--wait` seconds.
- Examines comments authored by the GitHub login `coderabbitai` (the
  CodeRabbit GH App).
- Classifies into one of four statuses:

    * **available**   — at least one CodeRabbit comment exists that is
                        NOT a rate-limit notice (i.e. CodeRabbit
                        actually reviewed the diff).
    * **rate-limited**— the most recent CodeRabbit comment matches the
                        canonical rate-limit body (substring
                        "Rate limit exceeded").
    * **silent**      — no CodeRabbit comments found within --wait
                        seconds.
    * **error**       — gh CLI failed or args invalid; the worker AI
                        should fall back to Profile B as if it were
                        ``rate-limited``.

JSON output schema (printed to stdout when --json or --pr is set)::

    {
      "status": "available|rate-limited|silent|error",
      "since_open_seconds": int,
      "last_comment_excerpt": "<first 200 chars of latest CodeRabbit comment, or null>",
      "comments_checked": int,
      "polled_at": "<ISO 8601 UTC>"
    }

Exit codes
----------
    0 — `available`
    1 — `rate-limited` or `silent` (Profile B fallback required)
    2 — setup error (gh unavailable, repo / PR not found, args invalid)
    3 — unrecoverable gh / network error after retries
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# Force UTF-8 stdio.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.bootstrap_gh_project import _emit, _gh_available  # noqa: E402

CODERABBIT_LOGIN = "coderabbitai"
RATE_LIMIT_MARKERS = (
    "Rate limit exceeded",
    "rate limited by coderabbit",
)


def _gh_pr_comments(pr: int, repo: str) -> list[dict[str, object]]:
    """Return the list of comments on the PR (via `gh pr view --json`)."""
    proc = subprocess.run(
        [
            "gh",
            "pr",
            "view",
            str(pr),
            "--repo",
            repo,
            "--json",
            "comments",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh pr view failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    payload = json.loads(proc.stdout)
    comments = payload.get("comments", [])
    if not isinstance(comments, list):
        return []
    return comments  # type: ignore[no-any-return]


def _gh_pr_meta(pr: int, repo: str) -> dict[str, object]:
    """Return PR open-time metadata (createdAt, headRefName)."""
    proc = subprocess.run(
        [
            "gh",
            "pr",
            "view",
            str(pr),
            "--repo",
            repo,
            "--json",
            "createdAt,headRefName,number",
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


def _is_rate_limit_body(body: str) -> bool:
    return any(marker in body for marker in RATE_LIMIT_MARKERS)


def _coderabbit_comments(comments: list[dict[str, object]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for c in comments:
        author = c.get("author") or {}
        if isinstance(author, dict) and author.get("login") == CODERABBIT_LOGIN:
            out.append(c)
    return out


def _classify(comments: list[dict[str, object]]) -> tuple[str, str | None]:
    """Return (status, last_comment_excerpt). status ∈ {available, rate-limited, silent}."""
    cr_comments = _coderabbit_comments(comments)
    if not cr_comments:
        return "silent", None

    # Pick the most recent — `gh` returns comments in chronological order, so
    # last entry is freshest.
    latest = cr_comments[-1]
    body = str(latest.get("body", ""))
    excerpt = body[:200]
    if _is_rate_limit_body(body):
        return "rate-limited", excerpt
    return "available", excerpt


def _seconds_since(iso: str) -> int:
    """Seconds elapsed between the given ISO-8601 timestamp and now (UTC)."""
    # `gh` returns "2026-05-01T03:30:00Z" — convert Z → +00:00 for fromisoformat.
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return -1
    now = datetime.now(UTC)
    return int((now - dt).total_seconds())


def run(
    *,
    pr: int,
    repo: str,
    wait_seconds: int,
    poll_interval: int,
    output_json: bool,
) -> int:
    if not _gh_available():
        print(
            "error: gh CLI not authenticated; run `gh auth login` first",
            file=sys.stderr,
        )
        if output_json:
            _emit_result(status="error", excerpt=None, since_open=-1, n_checked=0)
        return 2

    _emit(
        "check_coderabbit_status.start",
        pr=pr,
        repo=repo,
        wait_seconds=wait_seconds,
        poll_interval=poll_interval,
    )

    # PR meta first — fail fast if PR doesn't exist.
    try:
        meta = _gh_pr_meta(pr, repo)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if output_json:
            _emit_result(status="error", excerpt=None, since_open=-1, n_checked=0)
        return 2

    created_at = str(meta.get("createdAt", ""))

    deadline = time.monotonic() + max(wait_seconds, 0)
    last_status = "silent"
    last_excerpt: str | None = None
    n_checked = 0

    while True:
        try:
            comments = _gh_pr_comments(pr, repo)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            if output_json:
                _emit_result(
                    status="error",
                    excerpt=None,
                    since_open=_seconds_since(created_at) if created_at else -1,
                    n_checked=n_checked,
                )
            return 3

        n_checked = len(_coderabbit_comments(comments))
        status, excerpt = _classify(comments)
        last_status = status
        last_excerpt = excerpt

        if status == "available":
            break
        if status == "rate-limited":
            # No reason to keep polling — rate-limit notices don't disappear
            # within the wait window.
            break
        # status == "silent" — keep polling until deadline.
        if time.monotonic() >= deadline:
            break
        time.sleep(poll_interval)

    since_open = _seconds_since(created_at) if created_at else -1

    if output_json:
        _emit_result(
            status=last_status,
            excerpt=last_excerpt,
            since_open=since_open,
            n_checked=n_checked,
        )

    _emit(
        "check_coderabbit_status.complete",
        status=last_status,
        since_open_seconds=since_open,
        comments_checked=n_checked,
    )

    if last_status == "available":
        return 0
    return 1


def _emit_result(
    *, status: str, excerpt: str | None, since_open: int, n_checked: int
) -> None:
    payload = {
        "status": status,
        "since_open_seconds": since_open,
        "last_comment_excerpt": excerpt,
        "comments_checked": n_checked,
        "polled_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }
    print(json.dumps(payload, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Detect CodeRabbit availability on a PR. Returns exit 0 if "
            "CodeRabbit reviewed the diff, exit 1 if rate-limited or silent "
            "(worker AI must apply Profile B fallback per release-management.md "
            "§4.5)."
        )
    )
    p.add_argument("--pr", required=True, type=int, help="Pull request number")
    p.add_argument("--repo", required=True, metavar="owner/name")
    p.add_argument(
        "--wait",
        type=int,
        default=300,
        help="Maximum seconds to wait for CodeRabbit (default: 300)",
    )
    p.add_argument(
        "--poll-interval",
        type=int,
        default=30,
        help="Seconds between polls while waiting (default: 30)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON result on stdout (always emitted even without flag).",
    )
    args = p.parse_args(argv)

    if args.wait < 0:
        print("error: --wait must be >= 0", file=sys.stderr)
        return 2
    if args.poll_interval <= 0:
        print("error: --poll-interval must be > 0", file=sys.stderr)
        return 2

    try:
        return run(
            pr=args.pr,
            repo=args.repo,
            wait_seconds=args.wait,
            poll_interval=args.poll_interval,
            output_json=True,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        _emit("check_coderabbit_status.failed", reason=str(exc))
        return 3


if __name__ == "__main__":
    sys.exit(main())
