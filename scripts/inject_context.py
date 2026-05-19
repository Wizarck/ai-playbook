"""Recall project context from Hindsight and inject it into the agent session.

Reads Hindsight credentials from environment variables (typically supplied via
`sops exec-env <secrets.env> -- python -m scripts.inject_context`):

    HINDSIGHT_URL                                — base URL of Hindsight deployment.
    CF_ACCESS_CLIENT_ID + CF_ACCESS_CLIENT_SECRET → CF Access service auth (preferred).
    HINDSIGHT_API_KEY                            → bearer fallback (legacy/direct).
    HINDSIGHT_BANK_ID                            — project bank (override AGENTS.md).

Calls ``POST /v1/default/banks/{bank_id}/memories/recall`` via HTTP through
the shared client at ``scripts._hindsight`` (stdlib-only; no MCP SDK dep —
this script runs in SessionStart hooks where the dep graph must stay tiny).

Writes results to ``<consumer>/.claude/injected-context.md``. Consumer's
``SessionStart`` hook (configured per-project) reads that file and surfaces it
in the CLI's startup context. Output is **sanitised** through
``scripts.secrets_scan.sanitise`` before write, so a poisoned recall cannot
leak credentials into the session.

CLI
---
    python -m scripts.inject_context [--query TEXT] [--bank-id ID] [--top-k N]
                                     [--consumer-root PATH] [--project NAME]
                                     [--output PATH] [--dry-run]
                                     [--force-with-reason TEXT]

Behaviour
---------
- `--query`: free text. Default: ``"<project> current work"`` where project is
  resolved from the consumer's ``AGENTS.md`` frontmatter.
- `--bank-id`: override resolved bank_id (useful for cross-project recall).
- `--top-k`: retrieval depth. Default 5 (matches ``memory-hierarchy.md`` §4).
- `--consumer-root`: consumer repo root. Default: cwd.
- `--output`: override output path. Default: ``<consumer>/.claude/injected-context.md``.
- `--dry-run`: prints what would be written to stdout without touching the file.

Exit codes
----------
    0  success (or override applied, or degraded-context path wrote empty file)
    1  user-actionable error (bad --query, unparseable Hindsight response)
    2  environment/setup error (missing credentials, unreachable host,
       consumer has no AGENTS.md)
    3  reserved (this script has no hard-block failure mode — secrets scan
       sanitises rather than blocks)

Degraded context
----------------
If Hindsight is unreachable (DNS / 5xx / timeout), the script writes an empty
``injected-context.md`` with a `DEGRADED_CONTEXT` banner per
``docs/concepts/degradation-modes.md`` and exits 0. The session proceeds; the agent is
aware memory is unavailable. Queued-retain logic lives in a companion script
(T14i lifecycle work) and is out of scope here.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Force UTF-8 stdio — banners contain ✅/⚠️ sigils.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


SCRIPT_BASENAME = "inject_context.py"
GATE_NAME = "hindsight-recall"
DEFAULT_TOP_K = 5
DEFAULT_TIMEOUT_SECS = 45.0  # cold recall ~30 s; hook envelope should be 60 s.


@dataclass
class RecallEntry:
    """One memory item returned by hindsight.recall."""

    score: float
    kind: str  # lesson | gotcha | decision | failure | unknown
    text: str
    when: str | None
    trace_id: str | None


@dataclass
class RecallResult:
    """Outcome of a single recall call."""

    ok: bool
    entries: list[RecallEntry]
    reason: str  # "ok" | "degraded" | "error:<short-cause>"


# ---------------------------------------------------------------------------
# Canonical error emission (subset — this script only needs a few)
# ---------------------------------------------------------------------------


def emit_error(
    *, why: str, where: str, fix: str, override_invocation: str | None
) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    if override_invocation is None:
        print("   OVERRIDE: none", file=sys.stderr)
    else:
        print(f"   OVERRIDE: {override_invocation}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Consumer AGENTS.md introspection — resolves default project / bank_id
# ---------------------------------------------------------------------------


def _resolve_project_from_agents_md(consumer_root: Path) -> tuple[str | None, str | None]:
    """Return ``(project_slug, bank_id)`` by parsing ``<consumer>/AGENTS.md``.

    Returns ``(None, None)`` if AGENTS.md is absent or unparseable. We don't
    import ``schema_validate`` so this script has a minimal dep graph.
    """
    agents = consumer_root / "AGENTS.md"
    if not agents.is_file():
        return None, None
    try:
        text = agents.read_text(encoding="utf-8")
    except OSError:
        return None, None
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return None, None
    rest = text[4:]
    end = rest.find("\n---\n")
    if end == -1:
        return None, None
    block = rest[:end]
    project: str | None = None
    bank_id: str | None = None
    for line in block.split("\n"):
        stripped = line.strip()
        if stripped.startswith("project:"):
            project = stripped.split(":", 1)[1].strip().strip("'\"") or None
        elif stripped.startswith("bank_id:"):
            bank_id = stripped.split(":", 1)[1].strip().strip("'\"") or None
    return project, bank_id


# ---------------------------------------------------------------------------
# Hindsight HTTP client — delegates to scripts._hindsight (shared with retain).
# ---------------------------------------------------------------------------

from scripts._hindsight import (  # noqa: E402
    HindsightAuthMissing,
    HindsightCreds,
    HindsightUrlMissing,
)
from scripts._hindsight import (  # noqa: E402
    load_credentials as _load_credentials_full,
)
from scripts._hindsight import (  # noqa: E402
    post_recall as _post_recall,
)


def _load_credentials() -> tuple[str | None, str | None]:
    """Compat shim — return ``(url, api_key)`` for legacy callers/tests.

    ``api_key`` here is "any auth method present" — present means there is
    EITHER a CF Access pair OR a bearer token. New code should use
    ``scripts._hindsight.load_credentials()`` directly.
    """
    try:
        creds = _load_credentials_full()
    except (HindsightUrlMissing, HindsightAuthMissing):
        return (
            (os.environ.get("HINDSIGHT_URL") or "").strip() or None,
            (os.environ.get("HINDSIGHT_API_KEY") or "").strip() or None,
        )
    placeholder = creds.api_key or (
        "<cf-access>" if creds.cf_client_id and creds.cf_client_secret else None
    )
    return creds.url, placeholder


def recall(
    *,
    url: str,
    api_key: str,
    bank_id: str,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    timeout: float = DEFAULT_TIMEOUT_SECS,
) -> RecallResult:
    """POST recall to Hindsight; normalise response into RecallResult.

    Resolves auth from env (CF Access preferred, bearer fallback). The
    ``api_key`` arg is honoured as a bearer fallback when env has nothing,
    which keeps test mocks working.
    """
    # Build creds: prefer env (CF Access), fall back to the api_key arg.
    cf_id = (os.environ.get("CF_ACCESS_CLIENT_ID") or "").strip() or None
    cf_secret = (os.environ.get("CF_ACCESS_CLIENT_SECRET") or "").strip() or None
    creds = HindsightCreds(
        url=url.rstrip("/"),
        cf_client_id=cf_id,
        cf_client_secret=cf_secret,
        api_key=(os.environ.get("HINDSIGHT_API_KEY") or api_key).strip() or None,
    )
    if creds.auth_method == "none":
        return RecallResult(ok=False, entries=[], reason="error:no-auth")

    # The Hindsight `max_tokens` parameter is the closest analogue of `top_k`
    # — recall returns "as many memories as fit". Map: top_k 5 ≈ 4096 tokens.
    max_tokens = max(512, int(top_k) * 800)
    http = _post_recall(creds, bank_id, query, max_tokens=max_tokens, timeout=timeout)
    if not http.ok:
        return RecallResult(ok=False, entries=[], reason=http.reason)

    parsed = http.body
    if isinstance(parsed, dict):
        items = parsed.get("results") or parsed.get("entries") or []
    elif isinstance(parsed, list):
        items = parsed
    else:
        return RecallResult(ok=False, entries=[], reason="error:unexpected-shape")

    entries: list[RecallEntry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entries.append(
            RecallEntry(
                score=float(item.get("score", 0.0) or 0.0),
                kind=str(item.get("type") or item.get("kind") or "unknown"),
                text=str(item.get("text") or item.get("content") or "").strip(),
                when=(
                    item.get("occurred_start")
                    or item.get("mentioned_at")
                    or item.get("when")
                    or item.get("ts")
                    or None
                ),
                trace_id=item.get("trace_id") or item.get("document_id") or None,
            )
        )
    return RecallResult(ok=True, entries=entries, reason="ok")


# ---------------------------------------------------------------------------
# Rendering + sanitisation
# ---------------------------------------------------------------------------


def _sanitise(text: str) -> tuple[str, list[str]]:
    """Best-effort sanitisation via ``scripts.secrets_scan.sanitise``.

    Returns ``(redacted_text, kinds_redacted)``. If the helper is unavailable
    (circular imports, startup race), we fall back to identity — Hindsight
    content has already been vetted server-side in production, so this is a
    defence-in-depth layer, not the sole gate.
    """
    try:
        from scripts.secrets_scan import sanitise

        return sanitise(text)
    except Exception:  # noqa: BLE001 — fail-open on tooling gap, not on content.
        return text, []


def render_injected_context(
    *,
    project: str,
    bank_id: str,
    query: str,
    result: RecallResult,
    sanitiser_active: bool,
    now: datetime | None = None,
) -> str:
    """Render the markdown body that will be written."""
    now = now or datetime.now(UTC).astimezone()
    ts = now.isoformat(timespec="seconds")
    lines: list[str] = []
    lines.append(f"# Injected context — {project}")
    lines.append("")
    lines.append(f"> Auto-generated by `scripts/inject_context.py` at {ts}.")
    lines.append(f"> Bank: `{bank_id}` — query: `{query}` — top_k: {len(result.entries)}")
    lines.append("")

    if not result.ok:
        banner = "⚠️ **DEGRADED_CONTEXT**" if result.reason.startswith("degraded") else "❌ **CONTEXT_ERROR**"
        lines.append(banner)
        lines.append("")
        lines.append(
            "Hindsight recall failed; the session proceeds without prior memory. "
            f"Reason: `{result.reason}`. See `docs/concepts/degradation-modes.md`."
        )
        lines.append("")
        return "\n".join(lines) + "\n"

    if not result.entries:
        lines.append("_No prior entries found for this query. Write lessons via `hindsight.retain` as they emerge._")
        lines.append("")
        return "\n".join(lines) + "\n"

    for i, entry in enumerate(result.entries, start=1):
        score_str = f"{entry.score:.3f}" if entry.score else "—"
        meta_bits = [f"kind=`{entry.kind}`", f"score={score_str}"]
        if entry.when:
            meta_bits.append(f"when=`{entry.when}`")
        if entry.trace_id:
            meta_bits.append(f"trace=`{entry.trace_id}`")
        lines.append(f"## {i}. ({' · '.join(meta_bits)})")
        lines.append("")
        lines.append(entry.text if entry.text else "_(empty entry)_")
        lines.append("")

    if sanitiser_active:
        lines.append("---")
        lines.append(
            "_Output filtered by `scripts.secrets_scan.sanitise` — any secret-like "
            "substrings are redacted with `[REDACTED:<kind>]`._"
        )
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _default_query(project: str | None) -> str:
    if project:
        return f"{project} current work"
    return "current work"


def _default_output(consumer_root: Path, override: Path | None) -> Path:
    if override is not None:
        return override
    return consumer_root / ".claude" / "injected-context.md"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="inject_context",
        description="Recall project context from Hindsight MCP and write to .claude/injected-context.md",
    )
    p.add_argument("--query", default=None, help="Free-text recall query (default: resolved from project).")
    p.add_argument("--bank-id", default=None,
                   help="Override Hindsight bank_id (default: project slug or HINDSIGHT_BANK_ID).")
    p.add_argument("--project", default=None,
                   help="Override project name (default: resolved from consumer AGENTS.md).")
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help=f"Recall depth (default {DEFAULT_TOP_K}).")
    p.add_argument("--consumer-root", type=Path, default=None, help="Consumer repo root (default: cwd).")
    p.add_argument("--output", type=Path, default=None,
                   help="Output path (default: <consumer>/.claude/injected-context.md).")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECS, help="HTTP timeout seconds.")
    p.add_argument("--dry-run", action="store_true", help="Print output to stdout instead of writing to disk.")
    # Break-glass — inject_context is safe to force (it only writes injected-context.md).
    p.add_argument("--force-with-reason", dest="force_reason", default=None,
                   help="Override auth/credential gate with audit trail (≥10 chars).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    consumer_root: Path = (args.consumer_root or Path.cwd()).expanduser().resolve()
    project_from_md, bank_from_md = _resolve_project_from_agents_md(consumer_root)
    project = args.project or project_from_md
    bank_id = args.bank_id or os.environ.get("HINDSIGHT_BANK_ID") or bank_from_md or project
    query = args.query or _default_query(project)
    output_path = _default_output(consumer_root, args.output)

    if not project:
        emit_error(
            why="cannot resolve project (no AGENTS.md, no --project)",
            where=str(consumer_root),
            fix="run from a consumer repo with AGENTS.md, or pass --project <slug>.",
            override_invocation=None,
        )
        return 2

    if not bank_id:
        emit_error(
            why="cannot resolve bank_id",
            where=f"{SCRIPT_BASENAME}:bank-resolve",
            fix="set HINDSIGHT_BANK_ID or pass --bank-id; alternatively, set `bank_id` "
                "in the AGENTS.md frontmatter.",
            override_invocation=None,
        )
        return 2

    url, api_key = _load_credentials()
    if not url or not api_key:
        # Honour break-glass: write a DEGRADED_CONTEXT banner and exit 0.
        if args.force_reason and len(args.force_reason.strip()) >= 10:
            print(f"⚠️ OVERRIDE APPLIED: {args.force_reason.strip()}", file=sys.stderr)
            result = RecallResult(
                ok=False, entries=[],
                reason="degraded:credentials-missing-override-applied",
            )
            body = render_injected_context(
                project=project, bank_id=bank_id, query=query,
                result=result, sanitiser_active=False,
            )
            if args.dry_run:
                sys.stdout.write(body)
            else:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(body, encoding="utf-8")
            return 0

        emit_error(
            why="Hindsight credentials missing",
            where="env:HINDSIGHT_URL/HINDSIGHT_API_KEY",
            fix="run under `sops exec-env <secrets.env>` or export the two vars; "
                "see docs/concepts/env-vars.md.",
            override_invocation=(
                f"{SCRIPT_BASENAME} --force-with-reason=\"<>=10 char reason\""
            ),
        )
        return 2

    result = recall(
        url=url,
        api_key=api_key,
        bank_id=bank_id,
        query=query,
        top_k=args.top_k,
        timeout=args.timeout,
    )

    # Opportunistic queue drain: a successful recall is proof Hindsight is reachable
    # right now, so flush any retains queued during a prior degraded session.
    if result.ok:
        try:
            from scripts.retain_memory import try_opportunistic_drain
            drained, _kept = try_opportunistic_drain(consumer_root, bank_id)
            if drained:
                print(
                    f"📤 SessionStart drain: replayed {drained} queued item(s) "
                    f"to bank `{bank_id}`.",
                    file=sys.stderr,
                )
        except Exception:  # noqa: BLE001 — never block SessionStart on drain failure.
            pass

    # Sanitise every entry's text in-place before rendering.
    sanitiser_active = False
    if result.ok:
        for entry in result.entries:
            if entry.text:
                redacted, kinds = _sanitise(entry.text)
                if kinds:
                    sanitiser_active = True
                    entry.text = redacted

    body = render_injected_context(
        project=project,
        bank_id=bank_id,
        query=query,
        result=result,
        sanitiser_active=sanitiser_active,
    )

    if args.dry_run:
        sys.stdout.write(body)
        return 0

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(body, encoding="utf-8")
    except OSError as exc:
        emit_error(
            why=f"cannot write injected-context.md: {exc}",
            where=str(output_path),
            fix="check directory permissions and disk space.",
            override_invocation=None,
        )
        return 2

    # Success — one-line stderr confirmation for humans; exit 0 for hooks.
    print(
        f"✅ injected-context.md written: {len(result.entries)} entries "
        f"from bank `{bank_id}` ({result.reason}).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
