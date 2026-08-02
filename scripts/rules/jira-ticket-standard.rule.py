#!/usr/bin/env python3
"""Hardrule for `docs/rules/jira-ticket-standard.rule.md`.

Two jobs, one contract (`specs/jira-ticket-standard.yaml`, read via `_ticket_kit`):

  * ``pretooluse`` — the PREVENTIVE half. Intercepts the Atlassian MCP
    create/edit calls and refuses a description that does not meet the standard.
    This is where the enforcement actually lands: the overwhelming majority of
    GPLO tickets are authored by an agent in session through that tool, not by
    the OpenSpec sync. A rule doc and a skill are advice that fades with context
    compaction; a PreToolUse hook re-fires on every single call with no memory of
    the last one, which is the only property that survives a long session.

  * ``check`` — the DETECTIVE half. Queries Jira and reports non-conformant
    tickets. It exists because prevention cannot be total: a claude.ai web
    session runs no local hooks, and `curl` with the sync credentials bypasses
    everything. Naming that residual honestly is the point — a gate whose
    coverage is overstated is worse than one whose limits are written down.

WHY ``triggers: ["PreToolUse"]`` AND NOT THE TOOL NAME

`hook_dispatcher._rule_matches` does exact membership, no globbing, and the MCP
tool's full name embeds the server alias (`mcp__claude_ai_Atlassian__…`), which
differs per client configuration. Listing a literal would silently stop matching
the day the alias changes — the worst failure mode available, because the gate
would keep reporting success. Firing on every PreToolUse and filtering here on a
regex costs one cheap string match per tool call and cannot go stale.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

if __name__ == "__main__":  # pragma: no cover - path bootstrap
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from scripts.rules import _ticket_kit as K
    from scripts.rules._hook_contract import HookVerdict, block
    from scripts.rules._rule_kit import emit_error
except ImportError:  # pragma: no cover - direct execution from the rules dir
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.rules import _ticket_kit as K
    from scripts.rules._hook_contract import HookVerdict, block
    from scripts.rules._rule_kit import emit_error

SLUG = "jira-ticket-standard"

# Matches the Atlassian MCP surface whatever the server is aliased to.
_MCP_CREATE_RE = re.compile(r"^mcp__.+__(createJiraIssue|editJiraIssue)$")

SKIP_ENV = "AIPLAYBOOK_JIRA_TICKET_SKIP"


# ---------------------------------------------------------------------------
# The preventive half
# ---------------------------------------------------------------------------


def _extract(tool_input: dict) -> tuple[object, str, list[str]]:
    """Pull (description, issue_type, labels) out of either MCP tool's payload.

    `createJiraIssue` is flat (`description`, `issueTypeName`, `additional_fields
    .labels`); `editJiraIssue` nests everything under `fields`. Both shapes are
    handled here rather than at two call sites.
    """
    fields = tool_input.get("fields") or {}
    description = tool_input.get("description", fields.get("description"))
    issue_type = (
        tool_input.get("issueTypeName")
        or (fields.get("issuetype") or {}).get("name")
        or ""
    )
    extra = tool_input.get("additional_fields") or {}
    labels = extra.get("labels") or fields.get("labels") or []
    return description, str(issue_type), [str(x) for x in labels]


def pretooluse(event: dict) -> HookVerdict | None:
    """Refuse an MCP Jira create/edit whose description misses the standard."""
    tool = str(event.get("tool_name") or "")
    if not _MCP_CREATE_RE.match(tool):
        return None
    if os.environ.get(SKIP_ENV):
        return None

    tool_input = event.get("tool_input") or {}
    description, issue_type, labels = _extract(tool_input)

    # An edit that does not touch the description has nothing to judge — the
    # body already in Jira is the `check` half's business, not this one's.
    if description is None:
        return None
    # A create with no issue type declared cannot be judged against a per-type
    # contract; the API will reject it anyway.
    if not issue_type:
        return None

    try:
        result = K.validate_description(description, issue_type, labels=labels)
    except K.ConfigError:
        # The contract could not be read. Fail OPEN: a broken spec must not
        # become an outage on every ticket anyone tries to file. `validate` in
        # CI is what catches a broken spec.
        return None

    if result.ok:
        return None
    return block(
        K.render_findings(result.findings)
        + f"\n\nOVERRIDE: {SKIP_ENV}=1 (déjalo escrito en el ticket si lo usas)."
    )


# ---------------------------------------------------------------------------
# The detective half
# ---------------------------------------------------------------------------


def _jira_search(creds, jql: str, timeout: float = 20.0) -> list[dict]:
    """Page through `/rest/api/3/search/jql`.

    NOT `/rest/api/3/search`: that endpoint was retired in 2025 and now answers
    410. The replacement paginates by opaque `nextPageToken` and does NOT return
    a total, so the loop ends when the token stops coming — never by comparing a
    running count against a total that no longer exists.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    out: list[dict] = []
    token: str | None = None
    auth = __import__("base64").b64encode(
        f"{creds.username}:{creds.api_token}".encode()
    ).decode()
    while True:
        params = {
            "jql": jql,
            "maxResults": "100",
            "fields": "summary,issuetype,description,status,labels,created",
        }
        if token:
            params["nextPageToken"] = token
        url = f"{creds.url}/rest/api/3/search/jql?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                retry = float(exc.headers.get("Retry-After", "5") or 5)
                import time
                time.sleep(min(retry, 30))
                continue
            raise K.ConfigError(f"Jira search failed: HTTP {exc.code}") from exc
        out.extend(payload.get("issues") or [])
        token = payload.get("nextPageToken")
        if not token:
            return out


def _creds():
    from scripts.issue_sync import _load_jira_creds
    return _load_jira_creds()


def cmd_check(args: argparse.Namespace) -> int:
    creds = _creds()
    if creds is None:
        # Same graceful skip `issue_sync` already uses. A developer without Jira
        # credentials must not see a red gate for a question nobody asked them.
        print("jira-ticket-standard: no ATLASSIAN_* credentials — skipped.")
        return 0

    jql = args.jql or f"project = {args.project} AND statusCategory != Done"
    if args.since:
        jql += f' AND created >= "{args.since}"'
    jql += " ORDER BY created DESC"

    issues = _jira_search(creds, jql)
    spec = K.load_spec()

    conformant: list[str] = []
    failing: list[tuple[str, K.Result]] = []
    exempt: list[str] = []
    na_total = 0
    dialects: dict[str, int] = {}

    for issue in issues:
        key = issue.get("key", "?")
        f = issue.get("fields") or {}
        itype = ((f.get("issuetype") or {}).get("name")) or ""
        result = K.validate_description(
            f.get("description"), itype, labels=f.get("labels") or [], spec=spec
        )
        dialects[result.dialect] = dialects.get(result.dialect, 0) + 1
        na_total += len(result.na_sections)
        if result.exempt_reason:
            exempt.append(key)
        elif result.ok:
            conformant.append(key)
        else:
            failing.append((key, result))

    judged = len(conformant) + len(failing)
    pct = (100.0 * len(conformant) / judged) if judged else 100.0

    print(f"jira-ticket-standard: {len(issues)} issue(s) over {jql}")
    print(f"  conformant   {len(conformant)}")
    print(f"  failing      {len(failing)}")
    print(f"  exempt       {len(exempt)}  (issue_sync tracker stubs)")
    print(f"  conformance  {pct:.1f}%   ·  N/A sections used: {na_total}")
    # The split measures how much legacy the degenerate-ADF bug left behind:
    # tickets stored as one literal text blob predate the markdown→ADF fix.
    print("  storage      " + ", ".join(f"{k}={v}" for k, v in sorted(dialects.items())))

    if failing and args.verbose:
        print()
        for key, result in failing[: args.limit]:
            kinds = ", ".join(sorted({f.kind for f in result.findings}))
            print(f"  {key:<12} {kinds}")

    if args.max is None:
        return 0
    if len(failing) > args.max:
        emit_error(
            why=f"{len(failing)} non-conformant ticket(s), baseline is {args.max}",
            where=jql,
            fix="author tickets through `/jira-ticket`, or run "
                "`jira-ticket-standard.rule.py explain <KEY>` to see what is missing.",
            override=SKIP_ENV,
        )
        return 1
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    creds = _creds()
    if creds is None:
        print("jira-ticket-standard: no ATLASSIAN_* credentials — skipped.")
        return 0
    issues = _jira_search(creds, f"key = {args.key}")
    if not issues:
        raise K.ConfigError(f"{args.key} not found")
    f = issues[0].get("fields") or {}
    itype = ((f.get("issuetype") or {}).get("name")) or ""
    result = K.validate_description(
        f.get("description"), itype, labels=f.get("labels") or []
    )
    print(f"{args.key}  ({itype})  storage={result.dialect}")
    if result.exempt_reason:
        print(f"  EXEMPT — {result.exempt_reason}")
        return 0
    for section in result.matched_sections:
        mark = "N/A" if section in result.na_sections else "ok"
        print(f"  [{mark:>3}] {section}")
    if result.findings:
        print()
        print(K.render_findings(result.findings))
        return 1
    print("  conformant")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Parse the contract and prove the closed list is quoted consistently.

    Without this, "the enum lives in one place" is aspirational: nothing stops
    the template and the skill drifting from the spec within a week, and a
    reader who trusts the prose gets a type the validator rejects.
    """
    spec = K.load_spec()
    root = K.playbook_root()
    canon = [m["canonical"] for m in spec["metric_types"]]

    problems = 0
    for rel in ("templates/jira-ticket.md.tmpl", "skills/jira-ticket/SKILL.md"):
        path = root / rel
        if not path.exists():
            emit_error(why=f"{rel} is missing", where=str(path),
                             fix="the standard's human face must exist alongside the spec.")
            problems += 1
            continue
        text = path.read_text(encoding="utf-8")
        missing = [c for c in canon if c not in text]
        if missing:
            emit_error(
                why=f"{rel} does not quote metric type(s): {', '.join(missing)}",
                where=str(path),
                fix="quote the five canonical types verbatim, or change "
                    "specs/jira-ticket-standard.yaml if the list really changed.",
            )
            problems += 1

    for name, cfg in spec["issue_types"].items():
        for key in cfg["sections"]:
            if key not in spec["sections"]:
                emit_error(
                    why=f"issue type {name!r} requires unknown section {key!r}",
                    where="specs/jira-ticket-standard.yaml",
                    fix="add the section or fix the reference.",
                )
                problems += 1

    if problems:
        return 2
    print(f"jira-ticket-standard: contract OK — {len(canon)} metric types, "
          f"{len(spec['sections'])} sections, {len(spec['issue_types'])} issue types.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=SLUG)
    sub = parser.add_subparsers(dest="cmd", required=True)

    check = sub.add_parser("check", help="Report non-conformant tickets in Jira.")
    check.add_argument("--project", default="GPLO")
    check.add_argument("--jql", default=None, help="Override the whole query.")
    check.add_argument("--since", default=None,
                       help="Only tickets created on/after this date (YYYY-MM-DD). "
                            "This is the ratchet: it lets the gate bite for new "
                            "work without failing on a legacy backlog nobody is "
                            "rewriting.")
    check.add_argument("--max", type=int, default=None,
                       help="Committed baseline. Omit for report-only.")
    check.add_argument("--limit", type=int, default=25)
    check.add_argument("--verbose", action="store_true")
    check.set_defaults(func=cmd_check)

    explain = sub.add_parser("explain", help="Section-by-section for one ticket.")
    explain.add_argument("key")
    explain.set_defaults(func=cmd_explain)

    validate = sub.add_parser("validate", help="Parse the contract only.")
    validate.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except K.ConfigError as exc:
        emit_error(why=str(exc), where="specs/jira-ticket-standard.yaml",
                         fix="fix the contract or the credentials, then re-run.")
        return 2


if __name__ == "__main__":  # pragma: no cover
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit(SLUG, main))
