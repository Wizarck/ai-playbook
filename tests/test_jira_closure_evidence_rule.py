"""The closure gate must fire on the four real closures that prompted it.

Each case below is a REAL wrong closure from the geeplo campaign of
2026-08-15/16, reduced to the ticket text and the comment that was actually
posted. That is the point: a gate justified by an anecdote should be tested
against the anecdote, not against an invented example that was written to pass.

The negative controls matter at least as much. A rule that refuses everything
would satisfy every "must block" case here while making the board unusable, so
each clause has an arm proving it stays quiet on a good closure.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    """Load the hyphenated rule file as a module.

    Registered in ``sys.modules`` BEFORE ``exec_module``: the rule declares a
    ``@dataclass``, and dataclasses resolve ``cls.__module__`` through
    ``sys.modules`` at class-creation time. Without the registration that lookup
    returns ``None`` and the import dies with an ``AttributeError`` that says
    nothing about the real cause.
    """
    name = "jira_closure_evidence_rule"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / "rules" / "jira-closure-evidence.rule.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


RULE = _load()
SPEC = RULE.load_spec()


def _failed(description: str, comment: str) -> set[str]:
    return {c.id for c in RULE.evaluate(description, comment, SPEC) if not c.ok}


# ---------------------------------------------------------------------------
# The spec itself
# ---------------------------------------------------------------------------


def test_the_contract_parses_and_is_populated():
    """Guard the guard: an empty spec makes every assertion below vacuous."""
    assert SPEC.get("verdicts"), "no verdict tokens — C2 would never fire"
    assert SPEC.get("artefact_patterns"), "no artefact patterns — C3 never fires"
    assert RULE.cmd_validate(None) == 0


# ---------------------------------------------------------------------------
# C1-C3, the always-on clauses
# ---------------------------------------------------------------------------


def test_a_transition_with_no_comment_is_refused():
    assert "C1" in _failed("some ticket", "")


def test_a_comment_without_a_verdict_is_refused():
    assert "C2" in _failed("body", "Checked it, looks right. app/router.py:12")


def test_a_comment_without_an_artefact_is_refused():
    """'Verified' is a claim. The gate wants something a reader can open."""
    assert "C3" in _failed("body", "FIXED — verified against HEAD, all good.")


def test_a_minimal_but_honest_closure_passes():
    """NEGATIVE CONTROL for C1-C3.

    Without this, "refuse everything" satisfies all three tests above.
    """
    assert not _failed(
        "A ticket written as prose with no cited paths and no numbered list.",
        "**STALE** — already remediated by #485; adapters/shared_drive.py:158 "
        "stores the name today.",
    )


# ---------------------------------------------------------------------------
# C4 — path fidelity. The GPLO-1388 and GPLO-1497 clause.
# ---------------------------------------------------------------------------


GPLO_1388 = (
    "## Contexto / Problema\n\n"
    "`backend/app/blueprints/datashield/router.py:818` exposes the flagged "
    "employee list without an admin gate.\n"
)


def test_reading_the_directory_the_label_suggests_is_refused():
    """The exact GPLO-1388 mistake: `[DataScout]` in the title, `datashield/`
    in the body. The closure followed the label."""
    comment = (
        "CANNOT-REPRODUCE — read backend/app/blueprints/datascout/router.py "
        "and the gate is present."
    )
    assert "C5" in _failed(GPLO_1388, comment)


def test_opening_the_path_the_ticket_cites_passes():
    """NEGATIVE CONTROL for C6."""
    comment = (
        "FIXED — backend/app/blueprints/datashield/router.py:818 now takes "
        "require_internal_admin. test_a_plain_member_cannot_reach_the_flagged_list"
    )
    assert "C5" not in _failed(GPLO_1388, comment)


def test_a_loose_path_reference_still_counts():
    """Compared on the last two segments, so an honest closure that writes
    `datashield/router.py` is not failed on formatting."""
    assert "C5" not in _failed(GPLO_1388, "FIXED — datashield/router.py:818 gated.")


def test_c4_stays_quiet_when_the_ticket_cites_no_paths():
    """The clause fires only where the ticket makes the check unambiguous."""
    assert "C4" not in _failed(
        "The wizard collapses two users onto one destination.",
        "FIXED — see frontend/app/components/transfer/domainAutoMap.ts",
    )


# ---------------------------------------------------------------------------
# C5 — one artefact per enumerated requirement. The GPLO-1469 clause.
# ---------------------------------------------------------------------------


THREE_REQUIREMENTS = (
    "## Contexto / Problema\n\nSomething is wrong.\n\n"
    "## Repro\n\n1. open it\n2. look\n3. despair\n4. again\n\n"
    "## Esperado vs Actual\n\n"
    "1. the L2 sample must cover descendants\n"
    "2. the reparent gate must count what should have moved\n"
    "3. `test_shared_drive_adapter.py` must have a verify test\n"
)


def test_closing_three_requirements_on_one_artefact_is_refused():
    comment = "FIXED — the gate is in adapters/shared_drive.py:354."
    assert "C6" in _failed(THREE_REQUIREMENTS, comment)


def test_naming_one_artefact_per_requirement_passes():
    """NEGATIVE CONTROL for C6."""
    comment = (
        "**FIXED** — verified against HEAD.\n"
        "1. adapters/shared_drive.py:354 — descendants sampled\n"
        "2. adapters/_common.py:412 — gate counts the manifest\n"
        "3. tests/transfer/test_shared_drive_adapter.py — verify test added\n"
    )
    assert "C6" not in _failed(THREE_REQUIREMENTS, comment)


def test_repeating_one_path_does_not_satisfy_the_count():
    """Distinct artefacts, not mentions.

    Counting mentions would let a closure name its single file three times and
    call that three halves verified — which is the defect wearing the gate's
    uniform.
    """
    comment = (
        "FIXED\n1. adapters/shared_drive.py\n2. adapters/shared_drive.py\n"
        "3. adapters/shared_drive.py\n"
    )
    assert "C6" in _failed(THREE_REQUIREMENTS, comment)


def test_repro_steps_are_not_counted_as_requirements():
    """The Repro block above has FOUR numbered steps.

    Counting those would demand one artefact per reproduction step, which would
    make the clause absurd on exactly the tickets that are written best.
    """
    assert RULE._enumerated_requirements(THREE_REQUIREMENTS, SPEC) == 3


def test_c5_stays_quiet_on_a_single_requirement_ticket():
    body = (
        "## Esperado vs Actual\n\n1. it should not 500\n"
    )
    assert "C5" not in _failed(body, "FIXED — app/x.py:10")


# ---------------------------------------------------------------------------
# The transition targeting, and the exemptions
# ---------------------------------------------------------------------------


def test_only_transitions_into_done_are_judged():
    issue = {"transitions": [
        {"id": "11", "to": {"statusCategory": {"key": "new"}}},
        {"id": "31", "to": {"statusCategory": {"key": "done"}}},
    ]}
    assert RULE._targets_done(issue, "31", SPEC) is True
    assert RULE._targets_done(issue, "11", SPEC) is False


def test_an_unknown_transition_id_is_let_through():
    """Not our call: either the payload is wrong and Jira rejects it, or the
    list is stale. Blocking on our own ignorance is the wrong direction."""
    assert RULE._targets_done({"transitions": []}, "99", SPEC) is False


@pytest.mark.parametrize("tool,matches", [
    ("mcp__claude_ai_Atlassian__transitionJiraIssue", True),
    ("mcp__some_other_alias__transitionJiraIssue", True),
    ("mcp__claude_ai_Atlassian__editJiraIssue", False),
    ("Bash", False),
])
def test_the_tool_matcher_is_alias_agnostic(tool, matches):
    """The server alias is per-client. A literal would go stale silently."""
    assert bool(RULE._MCP_TRANSITION_RE.match(tool)) is matches


def test_a_non_transition_tool_is_ignored_entirely():
    assert RULE.pretooluse({"tool_name": "Bash", "tool_input": {}}) is None


# ---------------------------------------------------------------------------
# The bug this module found in its own rule
# ---------------------------------------------------------------------------


def test_paths_inside_backticks_are_seen():
    """The first draft stripped code spans before looking for paths.

    Tickets write paths in backticks nearly every time, so C3 and C4 were
    unfirable on the common case — a gate that cannot fail, inside the file
    whose entire subject is gates that cannot fail. Found by
    `test_reading_the_directory_the_label_suggests_is_refused` going green when
    it should have gone red, which is the only reason it was caught at all.
    """
    body = "See `backend/app/blueprints/datashield/router.py:818` for the route."
    assert RULE._cited_paths(body, SPEC) == {"datashield/router.py"}
    assert RULE._artefact_refs("FIXED — `app/x/y.py:3`", SPEC)


def test_a_fenced_block_in_the_comment_still_yields_artefacts():
    comment = "FIXED\n\n```\nbackend/app/router.py:12\n```\n"
    assert RULE._artefact_refs(comment, SPEC)


# ---------------------------------------------------------------------------
# C4 — no blank halves. Judged WITHOUT the ticket, so it survives having no
# credentials, which is the normal state for a consumer of a public playbook.
# ---------------------------------------------------------------------------
#
# This is the clause that replaces what the remote fetch used to buy. The old
# design needed an Atlassian API token to know how many requirements a ticket
# had, so every consumer would have had to mint one for a capability most of
# them will never use. C4 asks a question the payload can answer by itself: of
# the halves you SAY you closed, does each one carry evidence?


def test_an_enumerated_closure_with_a_blank_half_is_refused():
    """The GPLO-1469 shape, caught with no ticket and no network."""
    comment = (
        "FIXED\n"
        "1. the reparent gate counts moved ids - adapters/shared_drive.py:354\n"
        "2. the verify test exists - test_shared_drive_adapter.py\n"
        "3. recursive source inventory\n"
    )
    assert "C4" in _failed("", comment)


def test_every_half_carrying_an_artefact_passes():
    """NEGATIVE CONTROL for C4 - the honest three-part closure."""
    comment = (
        "FIXED\n"
        "1. gate counts moved ids - adapters/shared_drive.py:354\n"
        "2. verify test added - test_shared_drive_adapter.py\n"
        "3. docstring states the limit - adapters/shared_drive.py:290\n"
    )
    assert "C4" not in _failed("", comment)


def test_evidence_on_the_following_line_still_counts():
    """An item runs to the next marker, so multi-line items are not punished."""
    comment = (
        "FIXED\n"
        "1. the gate counts moved ids\n"
        "   see adapters/shared_drive.py:354\n"
        "2. the verify test exists\n"
        "   test_shared_drive_adapter.py\n"
    )
    assert "C4" not in _failed("", comment)


def test_prose_bullets_are_not_treated_as_claims():
    """NEGATIVE CONTROL: bullets carry context, not coverage claims.

    Demanding an artefact per bullet would fail the closures that explain
    themselves best, and a clause that is usually wrong gets skipped.
    """
    comment = (
        "FIXED - adapters/shared_drive.py:354\n"
        "\n"
        "- point one was already resolved by GPLO-1511\n"
        "- point three is a design call for the transfer owner\n"
    )
    assert "C4" not in _failed("", comment)


def test_a_single_enumerated_item_is_not_judged_by_c4():
    """NEGATIVE CONTROL: counting to one adds nothing over C3."""
    assert "C4" not in _failed("", "FIXED\n1. done - app/x.py:1\n")


def test_c4_needs_no_ticket_body_at_all():
    """The whole point of the rework, asserted directly.

    Every clause that fires here does so on an empty description. If this ever
    returns an empty set, payload-only mode has become a no-op - which is the
    failure the previous version shipped with.
    """
    fired = _failed("", "closed it")
    assert fired, "payload-only mode judges nothing - the gate is inert again"
    assert {"C2", "C3"} <= fired


# ---------------------------------------------------------------------------
# The comment must ride IN the transition
# ---------------------------------------------------------------------------


def test_the_comment_is_read_from_the_transition_payload():
    tool_input = {
        "issueIdOrKey": "PROJ-1",
        "transition": {"id": "31"},
        "update": {"comment": [{"add": {"body": "FIXED - app/x.py:1"}}]},
    }
    assert RULE.payload_comment(tool_input) == "FIXED - app/x.py:1"


def test_a_transition_with_no_comment_field_yields_nothing():
    assert RULE.payload_comment({"transition": {"id": "31"}}) == ""


@pytest.mark.parametrize("update", [
    {"comment": []},
    {"comment": [{}]},
    {"comment": [{"add": {}}]},
    {"comment": [{"add": {"body": "   "}}]},
    {"comment": "not-a-list"},
])
def test_malformed_comment_payloads_do_not_crash(update):
    """Fail open on shape, rather than a traceback inside a PreToolUse hook."""
    assert RULE.payload_comment({"update": update}) == ""


# ---------------------------------------------------------------------------
# The opt-in - a consumer joins by naming its own workflow, not by minting a
# token. This is what keeps the playbook tracker-agnostic.
# ---------------------------------------------------------------------------


def test_no_declared_transitions_means_the_rule_does_nothing(monkeypatch):
    """NEGATIVE CONTROL, and the portability guarantee.

    A consumer who has not declared which transition means Done cannot be judged
    - transition ids are per-workflow. Silence here is correct: the alternative
    is demanding a closure comment on every move to In Progress, which would be
    switched off within a day.
    """
    monkeypatch.delenv(RULE.DONE_TRANSITIONS_ENV, raising=False)
    assert RULE.declared_done_transitions() == set()


def test_declared_transitions_are_parsed(monkeypatch):
    monkeypatch.setenv(RULE.DONE_TRANSITIONS_ENV, "31, 41 ,")
    assert RULE.declared_done_transitions() == {"31", "41"}


def _no_creds(monkeypatch):
    for var in ("ATLASSIAN_URL", "ATLASSIAN_USERNAME", "ATLASSIAN_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def test_payload_only_mode_blocks_a_declared_done_transition(monkeypatch):
    """End-to-end with NO credentials: the gate must still bite."""
    monkeypatch.setenv(RULE.DONE_TRANSITIONS_ENV, "31")
    _no_creds(monkeypatch)

    verdict = RULE.pretooluse({
        "tool_name": "mcp__claude_ai_Atlassian__transitionJiraIssue",
        "tool_input": {"issueIdOrKey": "PROJ-1", "transition": {"id": "31"},
                       "update": {"comment": [{"add": {"body": "done"}}]}},
    })
    assert verdict is not None, (
        "no credentials and the gate went quiet - this is exactly the defect "
        "v0.22.16 documented, reintroduced"
    )
    assert "payload alone" in verdict.message


def test_payload_only_mode_ignores_an_undeclared_transition(monkeypatch):
    """NEGATIVE CONTROL: a move to In Progress is not a closure."""
    monkeypatch.setenv(RULE.DONE_TRANSITIONS_ENV, "31")
    _no_creds(monkeypatch)
    assert RULE.pretooluse({
        "tool_name": "mcp__claude_ai_Atlassian__transitionJiraIssue",
        "tool_input": {"issueIdOrKey": "PROJ-1", "transition": {"id": "11"}},
    }) is None


def test_a_good_closure_passes_in_payload_only_mode(monkeypatch):
    """NEGATIVE CONTROL: the gate must be satisfiable without credentials."""
    monkeypatch.setenv(RULE.DONE_TRANSITIONS_ENV, "31")
    _no_creds(monkeypatch)
    body = (
        "FIXED - verified against HEAD.\n"
        "1. the gate counts moved ids - adapters/shared_drive.py:354\n"
        "2. the verify test exists - test_shared_drive_adapter.py\n"
    )
    assert RULE.pretooluse({
        "tool_name": "mcp__claude_ai_Atlassian__transitionJiraIssue",
        "tool_input": {"issueIdOrKey": "PROJ-1", "transition": {"id": "31"},
                       "update": {"comment": [{"add": {"body": body}}]}},
    }) is None


# ---------------------------------------------------------------------------
# The block message must say which mode judged it
# ---------------------------------------------------------------------------


def test_the_message_admits_when_the_ticket_was_not_read():
    clauses = RULE.evaluate("", "closed it", SPEC)
    msg = RULE.render(clauses, SPEC, remote=False)
    assert "not read" in msg
    assert "C1-C4" in msg


def test_the_message_says_so_when_the_ticket_was_read():
    """NEGATIVE CONTROL for the mode notice.

    If both modes printed the same thing, a reader would assume path fidelity
    had been checked when it had not - overstated coverage, which is the
    campaign-long defect this whole rule is about.
    """
    clauses = RULE.evaluate("some ticket", "closed it", SPEC)
    msg = RULE.render(clauses, SPEC, remote=True)
    assert "C1-C6" in msg
    assert "not read" not in msg
