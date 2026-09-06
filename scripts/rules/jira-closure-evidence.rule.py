#!/usr/bin/env python3
"""Hardrule for `docs/rules/jira-closure-evidence.rule.md`.

The twin of `jira-ticket-standard.rule.py`. That rule gates what a ticket must
CONTAIN when filed; this one gates what must be SHOWN when it is closed.
Contract in `specs/jira-closure-standard.yaml`.

WHY A HOOK AND NOT A NORM, stated as evidence rather than preference.

A norm with this exact content already existed — an agent memory written after
two wrong closures, saying "'verified' has to name WHICH HALF; follow the paths
a ticket cites, not its label". It was loaded in context. Two more wrong
closures followed in the next session (four total, 2026-08-15/16). Every one of
them had a confident comment attached. What none had was a mechanical reason to
be complete.

That is the whole argument for this file: the failure mode is not ignorance, it
is confidence under load, and confidence is exactly what a PreToolUse hook does
not have. It re-fires on every transition with no memory of the last one.

WHY IT MATCHES ON `PreToolUse` AND NOT A TOOL NAME

Same reason the ticket-standard rule gives: `hook_dispatcher._rule_matches`
does exact membership with no globbing, and the Atlassian MCP tool name embeds a
per-client server alias (`mcp__claude_ai_Atlassian__…`). A literal would stop
matching the day the alias changes, and the gate would keep reporting success —
the worst available failure. One regex per tool call cannot go stale.

WHAT THIS RULE CANNOT SEE, written down rather than glossed:

  * a transition made from the Jira web UI, or by `curl` with the sync token
  * a comment posted AFTER the transition — the gate reads what exists at the
    moment of closing, which is deliberate: evidence that arrives later did not
    inform the decision
  * whether the evidence is TRUE. It checks that a reader was given something to
    open, not that opening it agrees. No static gate can do the second, and
    claiming otherwise would make this file the next thing that reports green
    while nothing happens.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __name__ == "__main__":  # pragma: no cover - path bootstrap
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from scripts.rules import _ticket_kit as K
    from scripts.rules._hook_contract import HookVerdict, block
except ImportError:  # pragma: no cover - direct execution from the rules dir
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.rules import _ticket_kit as K
    from scripts.rules._hook_contract import HookVerdict, block

SLUG = "jira-closure-evidence"
SPEC_RELATIVE = "specs/jira-closure-standard.yaml"

_MCP_TRANSITION_RE = re.compile(r"^mcp__.+__transitionJiraIssue$")
_MCP_COMMENT_RE = re.compile(r"^mcp__.+__addCommentToJiraIssue$")

#: Consumer-declared transition ids that mean "Done", comma-separated.
#:
#: THE OPT-IN, and what keeps a tracker-agnostic playbook agnostic. Transition
#: ids are per-workflow, so the playbook cannot know them. The first version of
#: this rule solved that by fetching the live transition list, which cost every
#: consumer an Atlassian API token for a capability most will never use.
#:
#: Declaring "31 means Done" is not a secret. It is cheap, static, per-repo
#: config verifiable by eye, and a consumer who never sets it is never affected.
#: Where credentials DO exist the live status category still wins.
DONE_TRANSITIONS_ENV = "AIPLAYBOOK_CLOSURE_DONE_TRANSITIONS"

#: How long a closure receipt authorises a transition.
#:
#: Long enough for a real workflow (write the comment, check CI, close), short
#: enough that evidence from last week cannot authorise today's closure. The
#: receipt is proof that a QUALIFYING comment was posted, not a standing pass.
RECEIPT_TTL_SECONDS = 60 * 60

_SPEC_CACHE: dict[str, Any] = {}


def load_spec(path: Path | None = None) -> dict[str, Any]:
    """Read the closure contract, cached per process."""
    target = path or (K.playbook_root() / SPEC_RELATIVE)
    key = str(target)
    if key not in _SPEC_CACHE:
        if not target.exists():
            raise K.ConfigError(f"closure standard not found: {target}")
        import yaml
        _SPEC_CACHE[key] = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return _SPEC_CACHE[key]


# ---------------------------------------------------------------------------
# The six clauses (C1-C4 judge the comment alone; C5-C6 need the ticket)
# ---------------------------------------------------------------------------


@dataclass
class Clause:
    id: str
    ok: bool
    detail: str


def _artefact_refs(text: str, spec: dict[str, Any]) -> set[str]:
    """Every openable thing the comment points at.

    A set rather than a count, because the same path repeated three times in one
    comment is one artefact examined, not three. That distinction is the whole
    point of C5 — a closure that names its single file over and over must not
    satisfy a requirement to name three different ones.

    CODE SPANS ARE NOT STRIPPED, unlike the ticket standard's metric check. That
    difference is load-bearing and was found by this module's own test: tickets
    and closures write paths in backticks nearly every time
    (``` `backend/app/x/router.py:818` ```), so stripping code here deleted
    exactly the evidence C3 and C4 exist to find. The first draft did strip, and
    both clauses were silently unfirable on the common case — a gate that cannot
    fail, in the file whose whole subject is gates that cannot fail.
    """
    found: set[str] = set()
    for pattern in (spec.get("artefact_patterns") or {}).values():
        for m in re.finditer(str(pattern), text):
            found.add(m.group(0).strip())
    return found


def _cited_paths(text: str, spec: dict[str, Any]) -> set[str]:
    """File paths the TICKET BODY names, normalised to bare filename + parent.

    Compared loosely on purpose. A ticket writes
    ``backend/app/blueprints/datashield/router.py:818`` and a closure comment
    may reasonably write ``datashield/router.py`` or just ``router.py:818``.
    Demanding a byte-identical string would fail the honest closure and pass
    nothing extra, so the comparison is on the last two path segments.

    Code spans are kept, for the reason given in :func:`_artefact_refs`.
    """
    pattern = str((spec.get("artefact_patterns") or {}).get("path") or "")
    if not pattern:
        return set()
    out: set[str] = set()
    for m in re.finditer(pattern, text):
        raw = m.group(0).split(":")[0]
        parts = [p for p in raw.split("/") if p]
        if parts:
            out.add("/".join(parts[-2:]) if len(parts) >= 2 else parts[-1])
    return out


def enumerated_items(text: str) -> list[str]:
    """Ordered-list items in a closure comment, each with its full body.

    ORDERED LISTS ONLY. Bullets carry prose — context, caveats, links — and
    demanding an artefact on every bullet would fail the closures that are
    written best, which is how a clause earns a reputation for being wrong and
    starts getting skipped. A numbered list in a closure is a claim about
    coverage: "these are the things I closed."

    An item runs from its own marker to the next, so evidence on the following
    line still counts as carried.
    """
    lines = (text or "").splitlines()
    starts = [i for i, line in enumerate(lines) if re.match(r"^\s*\d+[.)]\s+\S", line)]
    return [
        "\n".join(lines[s:(starts[n + 1] if n + 1 < len(starts) else len(lines))])
        for n, s in enumerate(starts)
    ]


# ---------------------------------------------------------------------------
# The receipt
# ---------------------------------------------------------------------------
#
# WHY A RECEIPT AND NOT THE TRANSITION PAYLOAD. The obvious design — carry the
# closure comment inside the transition (`update.comment[].add.body`) — was
# built, tested against a real closure, and DOES NOT WORK: Jira accepts the ADF,
# returns success, moves the issue to Done, and silently drops the comment
# (`hasScreen: false` on the transition). Shipping it would have been worse than
# shipping nothing, because the author would comply and the ticket would land in
# Done with no comment at all.
#
# `addCommentToJiraIssue` carries the body in its payload AND stores it. So the
# comment is judged where it is written, and the transition checks that a
# qualifying comment was written. No credentials, no network, and it validates
# text that demonstrably exists.


def _receipt_dir() -> Path:
    root = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
    if os.name == "nt":  # pragma: no cover - platform branch
        root = os.environ.get("TEMP") or os.environ.get("TMP") or root
    d = Path(root) / "ai-playbook-closure-receipts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _receipt_path(key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(key))[:64]
    return _receipt_dir() / f"{safe}.json"


def write_receipt(key: str, clauses: list[Clause]) -> None:
    """Record what the closure comment for `key` did and did not satisfy."""
    import time
    payload = {
        "key": key,
        "at": time.time(),
        "ok": all(c.ok for c in clauses),
        "failed": [{"id": c.id, "detail": c.detail} for c in clauses if not c.ok],
    }
    try:
        _receipt_path(key).write_text(json.dumps(payload), encoding="utf-8")
    except OSError:  # pragma: no cover - a read-only tmp is not worth blocking on
        pass


def read_receipt(key: str, *, now: float | None = None) -> dict[str, Any] | None:
    """The live receipt for `key`, or None if absent, unreadable or expired."""
    import time
    now = time.time() if now is None else now
    try:
        data = json.loads(_receipt_path(key).read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if now - float(data.get("at") or 0) > RECEIPT_TTL_SECONDS:
        return None
    return data


def _enumerated_requirements(description: str, spec: dict[str, Any]) -> int:
    """How many requirements the ticket states as an ordered list.

    Counted only inside the sections named by the contract, because an ordered
    list under "Repro" is a set of STEPS, not a set of requirements, and counting
    those would demand one artefact per reproduction step. That mistake would
    make the clause absurd on exactly the tickets that are written best.
    """
    cfg = spec.get("requirement_coverage") or {}
    if not cfg.get("enabled"):
        return 0
    try:
        norm = (K.load_spec().get("normalization") or {})
        sections = K.split_sections(description, norm)
    except Exception:  # pragma: no cover - defensive; fail open upstream
        return 0

    wanted = {
        K.normalize_heading(str(s), norm) for s in (cfg.get("count_sections") or [])
    }
    total = 0
    for heading, body in sections.items():
        if K.normalize_heading(heading, norm) not in wanted:
            continue
        total += len(re.findall(r"^\s*\d+[.)]\s+\S", K.strip_code(body), re.MULTILINE))
    return total


def evaluate(description: str, comment: str, spec: dict[str, Any]) -> list[Clause]:
    """Judge one closure. Pure — no network, no Jira types, so it is testable."""
    clauses: list[Clause] = []
    text = comment or ""

    # C1 — a closure comment exists at all.
    clauses.append(Clause(
        "C1", bool(text.strip()),
        "no closure comment on the issue: a transition to Done with no written "
        "reason leaves the next reader nothing to check",
    ))
    if not text.strip():
        return clauses

    # C2 — it says what kind of closure this is.
    verdicts = [str(v) for v in (spec.get("verdicts") or [])]
    hit = next(
        (v for v in verdicts
         if re.search(rf"\b{re.escape(v)}\b", text, re.IGNORECASE)),
        None,
    )
    clauses.append(Clause(
        "C2", hit is not None,
        f"no verdict token. Use one of: {', '.join(verdicts)}. "
        f"'STALE' and 'FIXED' carry different follow-up obligations and a "
        f"closure that says neither cannot be read later",
    ))

    # C3 — it points at something openable.
    refs = _artefact_refs(text, spec)
    clauses.append(Clause(
        "C3", bool(refs),
        "no artefact reference. Name a path, a test, a commit or a PR — "
        "'verified' on its own is a claim, not evidence",
    ))

    # C4 — no blank halves. Judged against the comment ITSELF, so it needs
    # neither the ticket nor a credential, and it is what catches the error the
    # whole rule was built for: GPLO-1469 was closed after checking 1 of 3.
    # Writing three numbered halves and leaving two without evidence is a blank
    # someone has to fill deliberately, where before it was simply forgotten.
    rc = spec.get("requirement_coverage") or {}
    items = enumerated_items(text)
    if len(items) >= int(rc.get("minimum_items", 2)):
        blank = [n for n, item in enumerate(items, 1) if not _artefact_refs(item, spec)]
        one = len(blank) == 1
        clauses.append(Clause(
            "C4", not blank,
            f"the closure enumerates {len(items)} items but "
            f"{'item' if one else 'items'} {', '.join(str(b) for b in blank)} "
            f"{'names' if one else 'name'} no artefact. Every half you "
            f"claim to have closed needs its own openable thing",
        ))

    # C5 — path fidelity: did you look where the ticket pointed? REMOTE ONLY.
    pf = spec.get("path_fidelity") or {}
    if pf.get("enabled") and description:
        cited = _cited_paths(description, spec)
        if cited:
            in_comment = _cited_paths(text, spec)
            overlap = cited & in_comment
            need = int(pf.get("minimum_overlap", 1))
            clauses.append(Clause(
                "C5", len(overlap) >= need,
                "the closure references none of the paths the ticket cites "
                f"({', '.join(sorted(cited)[:4])}). Follow the paths a ticket "
                f"names, not its label — GPLO-1388 was closed by reading the "
                f"directory its product tag suggested while its first line "
                f"named a different file",
            ))

    # C6 — one artefact per requirement the TICKET enumerates. REMOTE ONLY, and
    # the strictly stronger form of C4: C4 asks whether the halves you listed
    # carry evidence, C6 asks whether you listed them all. Only the ticket knows
    # the second, which is the one thing a credential actually buys.
    n = _enumerated_requirements(description or "", spec)
    if n >= int(rc.get("minimum_items", 2)):
        clauses.append(Clause(
            "C6", len(refs) >= n,
            f"the ticket enumerates {n} requirements but the closure names "
            f"{len(refs)} distinct artefact(s). 'Verified' has to say WHICH "
            f"HALF — GPLO-1469 was closed after checking 1 requirement of 3",
        ))

    return clauses


def render(clauses: list[Clause], spec: dict[str, Any]) -> str:
    failed = [c for c in clauses if not c.ok]
    lines = [
        "jira-closure-evidence: this ticket may not be closed yet.",
        "",
    ]
    lines += [f"  [{c.id}] {c.detail}" for c in failed]
    lines += [
        "",
        "A closure comment that satisfies this looks like:",
        "",
        "    **FIXED** — verified against HEAD.",
        "    1. <requirement> — backend/app/x/router.py:818, gated. test_a_plain_member_cannot_reach()",
        "    2. <requirement> — frontend/app/y.tsx:141, state filter added. MigrationJobDetail.test.tsx",
        "",
        f"OVERRIDE: {spec.get('skip_env', 'AIPLAYBOOK_JIRA_CLOSURE_SKIP')}=1, "
        f"or label the issue "
        f"'{(spec.get('exempt_labels') or ['closure-evidence-exempt'])[0]}'.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The preventive half
# ---------------------------------------------------------------------------


def _issue_key(tool_input: dict) -> str:
    return str(tool_input.get("issueIdOrKey") or "").strip()


def _fetch(creds, key: str, timeout: float = 15.0) -> dict[str, Any]:
    """One call for everything: description, comments, and the transition list.

    `expand=transitions` is what makes the status-category check possible without
    hardcoding transition ids — those are per-workflow, and a hardcoded id is a
    gate that silently stops matching the day someone edits the workflow.
    """
    import base64
    import urllib.parse
    import urllib.request

    auth = base64.b64encode(
        f"{creds.username}:{creds.api_token}".encode()
    ).decode()
    params = urllib.parse.urlencode({
        "fields": "description,comment,issuetype,labels",
        "expand": "transitions",
    })
    req = urllib.request.Request(
        f"{creds.url}/rest/api/3/issue/{urllib.parse.quote(key)}?{params}",
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _targets_done(issue: dict[str, Any], transition_id: str, spec: dict[str, Any]) -> bool:
    want = str((spec.get("fires_on") or {}).get("status_category") or "done").lower()
    for t in issue.get("transitions") or []:
        if str(t.get("id")) == str(transition_id):
            cat = (((t.get("to") or {}).get("statusCategory")) or {}).get("key")
            return str(cat or "").lower() == want
    # Transition id not in the list: either the payload is wrong (Jira will
    # reject it) or the list is stale. Not our call to make — let it through.
    return False


def _latest_comment(issue: dict[str, Any]) -> str:
    comments = ((issue.get("fields") or {}).get("comment") or {}).get("comments") or []
    if not comments:
        return ""
    body = comments[-1].get("body")
    if isinstance(body, str):
        return body
    text, _ = K.adf_to_markdownish(body)
    return text


def _description_text(issue: dict[str, Any]) -> str:
    desc = (issue.get("fields") or {}).get("description")
    if isinstance(desc, str):
        return desc
    if not desc:
        return ""
    text, _ = K.adf_to_markdownish(desc)
    return text


def declared_done_transitions() -> set[str]:
    """Transition ids the consumer has declared as meaning Done.

    Empty when unset, and empty means this rule cannot tell a closure from any
    other transition — so it does nothing. That is the opt-in: a consumer joins
    by naming its own workflow, not by provisioning a token.
    """
    raw = os.environ.get(DONE_TRANSITIONS_ENV, "")
    return {p.strip() for p in raw.split(",") if p.strip()}


def _on_comment(event: dict, spec: dict[str, Any]) -> None:
    """Judge a closure comment where it is WRITTEN, and record the verdict.

    Never blocks. A comment saying "this was FIXED in the other ticket" is
    ordinary discussion, and refusing it would be a false positive on the most
    common word in the verdict list — the fastest way to teach everyone the
    override. The judgement is stored; the transition is where it is enforced.
    """
    tool_input = event.get("tool_input") or {}
    key = _issue_key(tool_input)
    body = str(tool_input.get("commentBody") or "")
    if not key or not body.strip():
        return
    verdicts = [str(v) for v in (spec.get("verdicts") or [])]
    # The same word-boundary match C2 uses. A looser test here would record
    # receipts that C2 then refuses, and two halves of one rule disagreeing
    # is worse than either being wrong alone.
    if not any(
        re.search(rf"\b{re.escape(v)}\b", body, re.IGNORECASE) for v in verdicts
    ):
        return  # not a closure comment; nothing to record
    write_receipt(key, evaluate("", body, spec))


def pretooluse(event: dict) -> HookVerdict | None:
    """Two acts: record the closure comment, then gate the transition."""
    tool = str(event.get("tool_name") or "")
    is_comment = bool(_MCP_COMMENT_RE.match(tool))
    is_transition = bool(_MCP_TRANSITION_RE.match(tool))
    if not (is_comment or is_transition):
        return None

    try:
        spec = load_spec()
    except Exception:
        return None  # fail open: a broken spec must not block every transition

    if os.environ.get(str(spec.get("skip_env") or "")):
        return None

    if is_comment:
        _on_comment(event, spec)
        return None

    tool_input = event.get("tool_input") or {}
    key = _issue_key(tool_input)
    transition_id = str((tool_input.get("transition") or {}).get("id") or "")
    if not key or not transition_id:
        return None

    # The remote fetch is an ENHANCEMENT. It used to be the only path, which
    # made a tracker-agnostic playbook depend on one tracker's API token — and
    # where those credentials did not exist the rule failed open on every
    # transition while advertising `enforced`.
    issue: dict[str, Any] | None = None
    try:
        from scripts.issue_sync import _load_jira_creds
        creds = _load_jira_creds()
        if creds is not None:
            issue = _fetch(creds, key)
    except Exception:
        issue = None

    if issue is not None:
        if not _targets_done(issue, transition_id, spec):
            return None
        fields = issue.get("fields") or {}
        itype = str(((fields.get("issuetype") or {}).get("name")) or "")
        if itype in set(spec.get("issue_types_exempt") or []):
            return None
        labels = {str(x) for x in (fields.get("labels") or [])}
        if labels & set(spec.get("exempt_labels") or []):
            return None
        clauses = evaluate(_description_text(issue), _latest_comment(issue), spec)
        if all(c.ok for c in clauses):
            return None
        return block(render(clauses, spec, remote=True))

    # Payload-only. We cannot ask what transition 31 means, so the consumer must
    # have said. Unset = this rule is not for you.
    if transition_id not in declared_done_transitions():
        return None

    receipt = read_receipt(key)
    if receipt is None:
        return block(render_missing_receipt(key, spec))
    if receipt.get("ok"):
        return None
    return block(render_bad_receipt(key, receipt, spec))


def _override_line(spec: dict[str, Any]) -> str:
    return (
        f"OVERRIDE: {spec.get('skip_env', 'AIPLAYBOOK_JIRA_CLOSURE_SKIP')}=1, or "
        f"label the issue "
        f"'{(spec.get('exempt_labels') or ['closure-evidence-exempt'])[0]}'."
    )


def render_missing_receipt(key: str, spec: dict[str, Any]) -> str:
    return "\n".join([
        f"jira-closure-evidence: {key} has no closure comment to close on.",
        "",
        f"  Post the closure comment FIRST (addCommentToJiraIssue), then",
        f"  transition. Nothing qualifying was written for {key} in the last "
        f"{RECEIPT_TTL_SECONDS // 60} minutes.",
        "",
        "  A comment counts once it carries a verdict token and evidence:",
        "",
        "    **FIXED** — verified against HEAD.",
        "    1. <requirement> — backend/app/x/router.py:818. test_a_plain_member_cannot_reach()",
        "    2. <requirement> — frontend/app/y.tsx:141. MigrationJobDetail.test.tsx",
        "",
        "  NB the comment cannot ride inside the transition itself: Jira accepts",
        "  `update.comment` on a screenless transition and silently drops it.",
        "",
        _override_line(spec),
    ])


def render_bad_receipt(key: str, receipt: dict[str, Any], spec: dict[str, Any]) -> str:
    lines = [
        f"jira-closure-evidence: the closure comment on {key} is not enough yet.",
        "",
    ]
    lines += [f"  [{f.get('id')}] {f.get('detail')}" for f in receipt.get("failed") or []]
    lines += [
        "",
        "  Judged from the comment alone — the ticket body was not read, so path",
        "  fidelity and requirement count were NOT checked.",
        "",
        "  Post a corrected closure comment, then transition.",
        "",
        _override_line(spec),
    ]
    return "\n".join(lines)


def cmd_validate(_args: argparse.Namespace) -> int:
    spec = load_spec()
    missing = [k for k in ("verdicts", "artefact_patterns", "fires_on")
               if not spec.get(k)]
    if missing:
        print(f"{SLUG}: spec is missing {missing}")
        return 1
    for name, pattern in (spec.get("artefact_patterns") or {}).items():
        try:
            re.compile(str(pattern))
        except re.error as exc:
            print(f"{SLUG}: artefact_patterns.{name} is not a regex: {exc}")
            return 1
    print(f"{SLUG}: spec OK ({len(spec.get('verdicts') or [])} verdicts).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=SLUG)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate").set_defaults(func=cmd_validate)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    from scripts.rules._telemetry import cli_emit

    raise SystemExit(cli_emit(SLUG, main))
