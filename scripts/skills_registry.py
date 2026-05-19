"""Query the consumer-d-skills HTTP registry for the catalog of available skills.

Populated in T20. See ``docs/concepts/skills-registry.md`` for the full contract.

The registry is the authoritative discovery surface for project skills —
consumers stop copy-pasting ``SKILL.md`` under ``.claude/skills/`` and instead
query this script at bootstrap to learn what is available to their scope.

Reads credentials from the environment:

    SKILLS_REGISTRY_URL       — base URL (required).
    SKILLS_REGISTRY_API_KEY   — bearer token (optional; required for
                                ``scope=personal`` and non-``public`` scopes).

Calls ``GET <url>/api/v1/skills?scope=<slug>[&since=<iso>]`` and validates
the envelope ``{"skills": [...], "fetched_at": "..."}``.

CLI
---
    python -m scripts.skills_registry list [--scope SCOPE] [--since ISO]
                                           [--url URL] [--json]
                                           [--timeout SECS]
                                           [--force-with-reason TEXT]
    python -m scripts.skills_registry show <name> [--scope SCOPE]
                                                  [--url URL] [--json]
                                                  [--timeout SECS]

Exit codes
----------
    0  success (or ``--force-with-reason`` applied and degraded to empty list).
    1  malformed response, user-actionable error (missing <name>, etc).
    2  unreachable registry, missing credentials, other environment errors.
    3  reserved (no hard-block gate in this script).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path  # noqa: F401 — imported for parity with sibling scripts
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

# Force UTF-8 stdio — banners contain ✅/⚠️/❌ sigils.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


SCRIPT_BASENAME = "skills_registry.py"
DEFAULT_TIMEOUT_SECS = 10.0
DEFAULT_SCOPE = "public"
MIN_OVERRIDE_REASON_LEN = 10


# ---------------------------------------------------------------------------
# Canonical error emission (mirrors inject_context.py)
# ---------------------------------------------------------------------------


def emit_error(
    *, why: str, where: str, fix: str, override_invocation: str | None
) -> None:
    """Emit the canonical error shape (see docs/rules/error-message-standard.rule.md)."""
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    if override_invocation is None:
        print("   OVERRIDE: none", file=sys.stderr)
    else:
        print(f"   OVERRIDE: {override_invocation}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class RegistryResult:
    """Outcome of a single list call."""

    ok: bool
    skills: list[dict[str, Any]]
    fetched_at: str | None
    reason: str  # "ok" | "degraded:<cause>" | "error:<cause>"


# ---------------------------------------------------------------------------
# HTTP client (stdlib only — no new runtime deps)
# ---------------------------------------------------------------------------


def _load_credentials() -> tuple[str | None, str | None]:
    """Return ``(url, api_key)`` from env. Either may be None when unset."""
    url = (os.environ.get("SKILLS_REGISTRY_URL") or "").strip() or None
    api_key = (os.environ.get("SKILLS_REGISTRY_API_KEY") or "").strip() or None
    return url, api_key


def _build_query(scope: str | None, since: str | None) -> str:
    params: list[tuple[str, str]] = []
    if scope:
        params.append(("scope", scope))
    if since:
        params.append(("since", since))
    return urlparse.urlencode(params) if params else ""


def _fetch(
    *,
    url: str,
    path: str,
    api_key: str | None,
    query: str,
    timeout: float,
) -> RegistryResult:
    """HTTP GET, normalise response into a RegistryResult."""
    endpoint = url.rstrip("/") + path
    if query:
        endpoint = f"{endpoint}?{query}"

    headers = {
        "Accept": "application/json",
        "User-Agent": "ai-playbook/skills_registry",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urlrequest.Request(endpoint, method="GET", headers=headers)

    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urlerror.HTTPError as exc:
        return RegistryResult(
            ok=False, skills=[], fetched_at=None,
            reason=f"error:http-{exc.code}",
        )
    except urlerror.URLError as exc:
        return RegistryResult(
            ok=False, skills=[], fetched_at=None,
            reason=f"degraded:url:{exc.reason}",
        )
    except TimeoutError:
        return RegistryResult(
            ok=False, skills=[], fetched_at=None, reason="degraded:timeout",
        )
    except OSError as exc:
        return RegistryResult(
            ok=False, skills=[], fetched_at=None, reason=f"degraded:os:{exc}",
        )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return RegistryResult(
            ok=False, skills=[], fetched_at=None, reason="error:malformed-json",
        )

    # Envelope validation: { "skills": [...], "fetched_at": "..." }.
    if not isinstance(parsed, dict) or "skills" not in parsed:
        return RegistryResult(
            ok=False, skills=[], fetched_at=None,
            reason="error:unexpected-shape",
        )

    skills_raw = parsed.get("skills")
    if not isinstance(skills_raw, list):
        return RegistryResult(
            ok=False, skills=[], fetched_at=None,
            reason="error:skills-not-list",
        )

    skills: list[dict[str, Any]] = []
    for item in skills_raw:
        if isinstance(item, dict) and item.get("name"):
            skills.append(item)

    fetched_at = parsed.get("fetched_at")
    if fetched_at is not None and not isinstance(fetched_at, str):
        fetched_at = None

    return RegistryResult(
        ok=True, skills=skills, fetched_at=fetched_at, reason="ok",
    )


# ---------------------------------------------------------------------------
# Public importable API
# ---------------------------------------------------------------------------


def list_skills(
    *,
    scope: str | None = None,
    since: str | None = None,
    url: str | None = None,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECS,
) -> list[dict[str, Any]]:
    """Return the skills catalog for ``scope``.

    Raises ``RuntimeError`` on malformed or unreachable registry; callers
    that want degraded-mode behaviour should catch it or use the CLI with
    ``--force-with-reason``.
    """
    resolved_url = url or _load_credentials()[0]
    if not resolved_url:
        raise RuntimeError("SKILLS_REGISTRY_URL not set and no url= provided")

    resolved_key = api_key if api_key is not None else _load_credentials()[1]
    result = _fetch(
        url=resolved_url,
        path="/api/v1/skills",
        api_key=resolved_key,
        query=_build_query(scope, since),
        timeout=timeout,
    )
    if not result.ok:
        raise RuntimeError(f"skills registry error: {result.reason}")
    return result.skills


def skill_by_name(
    name: str,
    *,
    scope: str | None = None,
    url: str | None = None,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECS,
) -> dict[str, Any] | None:
    """Return the single skill entry matching ``name``, or None."""
    entries = list_skills(
        scope=scope, url=url, api_key=api_key, timeout=timeout,
    )
    for entry in entries:
        if entry.get("name") == name:
            return entry
    return None


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _format_table(skills: list[dict[str, Any]]) -> str:
    """Render a simple pipe-separated table for human readers."""
    if not skills:
        return "(no skills in scope)"
    header = "name | description | scope | source"
    sep = "-" * len(header)
    rows = [header, sep]
    for s in skills:
        rows.append(
            " | ".join(
                [
                    str(s.get("name", "")),
                    str(s.get("description", "")).replace("\n", " "),
                    str(s.get("scope", "")),
                    str(s.get("source", "")),
                ]
            )
        )
    return "\n".join(rows)


def _cmd_list(args: argparse.Namespace) -> int:
    url = (args.url or "").strip() or _load_credentials()[0]
    _, api_key = _load_credentials()
    scope = args.scope or DEFAULT_SCOPE

    if not url:
        # Honour break-glass: degrade to empty list.
        if args.force_reason and len(args.force_reason.strip()) >= MIN_OVERRIDE_REASON_LEN:
            print(
                f"⚠️ OVERRIDE APPLIED: {args.force_reason.strip()}", file=sys.stderr,
            )
            if args.json:
                sys.stdout.write(json.dumps([]) + "\n")
            else:
                sys.stdout.write(_format_table([]) + "\n")
            return 0
        emit_error(
            why="SKILLS_REGISTRY_URL not set",
            where="env:SKILLS_REGISTRY_URL",
            fix="export SKILLS_REGISTRY_URL=https://consumer-d-skills.consumer-bfood.com "
                "(or pass --url); see docs/concepts/env-vars.md.",
            override_invocation=(
                f"{SCRIPT_BASENAME} list --force-with-reason=\"<≥10 char reason>\""
            ),
        )
        return 2

    result = _fetch(
        url=url,
        path="/api/v1/skills",
        api_key=api_key,
        query=_build_query(scope, args.since),
        timeout=args.timeout,
    )

    if not result.ok:
        # Degraded path: force-with-reason → exit 0 with empty list.
        if result.reason.startswith("degraded:") and args.force_reason \
                and len(args.force_reason.strip()) >= MIN_OVERRIDE_REASON_LEN:
            print(
                f"⚠️ OVERRIDE APPLIED: {args.force_reason.strip()} "
                f"(reason={result.reason})",
                file=sys.stderr,
            )
            if args.json:
                sys.stdout.write(json.dumps([]) + "\n")
            else:
                sys.stdout.write(_format_table([]) + "\n")
            return 0

        if result.reason.startswith("degraded:"):
            emit_error(
                why=f"skills registry unreachable ({result.reason})",
                where=url,
                fix="verify the registry is up and SKILLS_REGISTRY_URL is correct; "
                    "retry or run with --force-with-reason to degrade.",
                override_invocation=(
                    f"{SCRIPT_BASENAME} list --force-with-reason=\"<≥10 char reason>\""
                ),
            )
            return 2

        # Malformed / unexpected shape / HTTP status.
        emit_error(
            why=f"skills registry response invalid ({result.reason})",
            where=url,
            fix="check registry logs; the client expects "
                "{\"skills\": [...], \"fetched_at\": \"...\"}.",
            override_invocation=None,
        )
        return 1

    if args.json:
        sys.stdout.write(json.dumps(result.skills) + "\n")
    else:
        sys.stdout.write(_format_table(result.skills) + "\n")
        if result.fetched_at:
            sys.stdout.write(f"\nfetched_at: {result.fetched_at}\n")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    url = (args.url or "").strip() or _load_credentials()[0]
    _, api_key = _load_credentials()
    scope = args.scope or DEFAULT_SCOPE

    if not url:
        emit_error(
            why="SKILLS_REGISTRY_URL not set",
            where="env:SKILLS_REGISTRY_URL",
            fix="export SKILLS_REGISTRY_URL (or pass --url); see docs/concepts/env-vars.md.",
            override_invocation=None,
        )
        return 2

    result = _fetch(
        url=url,
        path="/api/v1/skills",
        api_key=api_key,
        query=_build_query(scope, None),
        timeout=args.timeout,
    )

    if not result.ok:
        if result.reason.startswith("degraded:"):
            emit_error(
                why=f"skills registry unreachable ({result.reason})",
                where=url,
                fix="verify the registry is up; retry once network recovers.",
                override_invocation=None,
            )
            return 2
        emit_error(
            why=f"skills registry response invalid ({result.reason})",
            where=url,
            fix="check registry logs.",
            override_invocation=None,
        )
        return 1

    match = next((s for s in result.skills if s.get("name") == args.name), None)
    if match is None:
        emit_error(
            why=f"skill '{args.name}' not found in scope='{scope}'",
            where=url,
            fix=f"run `python -m scripts.skills_registry list --scope {scope}` "
                "to see available skills.",
            override_invocation=None,
        )
        return 1

    if args.json:
        sys.stdout.write(json.dumps(match, indent=2) + "\n")
    else:
        sys.stdout.write(f"name:        {match.get('name', '')}\n")
        sys.stdout.write(f"description: {match.get('description', '')}\n")
        sys.stdout.write(f"scope:       {match.get('scope', '')}\n")
        sys.stdout.write(f"version:     {match.get('version', '')}\n")
        sys.stdout.write(f"source:      {match.get('source', '')}\n")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="skills_registry",
        description="Query the consumer-d-skills HTTP registry (T20).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List all skills in a scope.")
    p_list.add_argument(
        "--scope", default=None,
        help=f"Scope filter (default '{DEFAULT_SCOPE}').",
    )
    p_list.add_argument("--since", default=None, help="ISO timestamp filter.")
    p_list.add_argument("--url", default=None, help="Override SKILLS_REGISTRY_URL.")
    p_list.add_argument("--json", action="store_true", help="Emit raw JSON array.")
    p_list.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_SECS,
        help=f"HTTP timeout seconds (default {DEFAULT_TIMEOUT_SECS}).",
    )
    p_list.add_argument(
        "--force-with-reason", dest="force_reason", default=None,
        help="Degrade to empty list when registry is unreachable / unset "
             "(≥10 char reason, audit-logged).",
    )
    p_list.set_defaults(func=_cmd_list)

    p_show = sub.add_parser("show", help="Show a single skill by name.")
    p_show.add_argument("name", help="Skill canonical name (kebab-case).")
    p_show.add_argument("--scope", default=None, help="Scope filter.")
    p_show.add_argument("--url", default=None, help="Override SKILLS_REGISTRY_URL.")
    p_show.add_argument("--json", action="store_true", help="Emit raw JSON entry.")
    p_show.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_SECS,
        help=f"HTTP timeout seconds (default {DEFAULT_TIMEOUT_SECS}).",
    )
    p_show.set_defaults(func=_cmd_show, force_reason=None)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
