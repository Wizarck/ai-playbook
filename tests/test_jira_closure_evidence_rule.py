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
# The receipt
# ---------------------------------------------------------------------------
#
# WHY A RECEIPT. The obvious design - carry the closure comment inside the
# transition (update.comment[].add.body) - was built, tested against a real
# closure, and DOES NOT WORK. Jira accepts the ADF, returns success, moves the
# issue to Done, and silently drops the comment (hasScreen: false). Shipping it
# would have been worse than shipping nothing: the author complies, the API says
# yes, and the ticket lands in Done with no comment at all.
#
# addCommentToJiraIssue carries the body in its payload AND stores it. So the
# comment is judged where it is written, and the transition checks a qualifying
# comment was written.


@pytest.fixture(autouse=True)
def _isolated_receipts(tmp_path, monkeypatch):
    """Never touch the developer's real receipt directory from a test."""
    monkeypatch.setattr(RULE, "_receipt_dir", lambda: tmp_path)


def _comment_event(key: str, body: str) -> dict:
    return {
        "tool_name": "mcp__claude_ai_Atlassian__addCommentToJiraIssue",
        "tool_input": {"issueIdOrKey": key, "commentBody": body},
    }


def _transition_event(key: str, tid: str = "31") -> dict:
    return {
        "tool_name": "mcp__claude_ai_Atlassian__transitionJiraIssue",
        "tool_input": {"issueIdOrKey": key, "transition": {"id": tid}},
    }


GOOD = (
    "FIXED - verified against HEAD.\n"
    "1. the gate counts moved ids - adapters/shared_drive.py:354\n"
    "2. the verify test exists - test_shared_drive_adapter.py\n"
)
BLANK_HALF = (
    "FIXED\n"
    "1. the gate counts moved ids - adapters/shared_drive.py:354\n"
    "2. recursive source inventory\n"
)


@pytest.fixture(autouse=True)
def _no_creds(monkeypatch):
    for var in ("ATLASSIAN_URL", "ATLASSIAN_USERNAME", "ATLASSIAN_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


def test_a_closure_comment_is_recorded(monkeypatch):
    assert RULE.pretooluse(_comment_event("PROJ-1", GOOD)) is None, (
        "commenting must never be blocked"
    )
    receipt = RULE.read_receipt("PROJ-1")
    assert receipt is not None and receipt["ok"] is True


def test_a_verdict_token_is_what_makes_it_a_closure(monkeypatch):
    """THE NO-OP GUARD.

    The verdict match is what decides whether anything is recorded at all. A
    draft of this shipped with literal backspace bytes instead of the `\\b`
    word-boundary escapes, so it matched nothing, wrote no receipt ever, and
    every transition sailed through - silently, with a full green suite.
    """
    assert RULE.pretooluse(_comment_event("PROJ-2", GOOD)) is None
    assert RULE.read_receipt("PROJ-2") is not None, (
        "no receipt written for an obvious closure - the verdict matcher is dead"
    )


def test_ordinary_discussion_is_not_recorded(monkeypatch):
    """NEGATIVE CONTROL: a comment with no verdict token is not a closure."""
    RULE.pretooluse(_comment_event("PROJ-3", "looks related to the other ticket"))
    assert RULE.read_receipt("PROJ-3") is None


def test_a_weak_closure_comment_is_recorded_as_failing(monkeypatch):
    RULE.pretooluse(_comment_event("PROJ-4", BLANK_HALF))
    receipt = RULE.read_receipt("PROJ-4")
    assert receipt is not None
    assert receipt["ok"] is False
    assert {f["id"] for f in receipt["failed"]} == {"C4"}


def test_commenting_never_blocks(monkeypatch):
    """NEGATIVE CONTROL, and the reason judgement is split from enforcement.

    Refusing a comment that merely says FIXED would be a false positive on the
    most common word in the verdict list - the fastest way to teach everyone
    the override.
    """
    assert RULE.pretooluse(_comment_event("PROJ-5", "FIXED, no evidence")) is None


# ---------------------------------------------------------------------------
# Enforcing
# ---------------------------------------------------------------------------


def test_a_transition_without_a_receipt_is_refused(monkeypatch):
    monkeypatch.setenv(RULE.DONE_TRANSITIONS_ENV, "31")
    verdict = RULE.pretooluse(_transition_event("PROJ-6"))
    assert verdict is not None
    assert "no closure comment" in verdict.message


def test_a_transition_with_a_good_receipt_passes(monkeypatch):
    """NEGATIVE CONTROL: the gate must be satisfiable with no credentials."""
    monkeypatch.setenv(RULE.DONE_TRANSITIONS_ENV, "31")
    RULE.pretooluse(_comment_event("PROJ-7", GOOD))
    assert RULE.pretooluse(_transition_event("PROJ-7")) is None


def test_a_transition_with_a_failing_receipt_is_refused(monkeypatch):
    monkeypatch.setenv(RULE.DONE_TRANSITIONS_ENV, "31")
    RULE.pretooluse(_comment_event("PROJ-8", BLANK_HALF))
    verdict = RULE.pretooluse(_transition_event("PROJ-8"))
    assert verdict is not None
    assert "[C4]" in verdict.message


def test_a_receipt_for_another_issue_does_not_authorise_this_one(monkeypatch):
    """The receipt is keyed on the issue, not on 'something was commented'."""
    monkeypatch.setenv(RULE.DONE_TRANSITIONS_ENV, "31")
    RULE.pretooluse(_comment_event("PROJ-9", GOOD))
    assert RULE.pretooluse(_transition_event("PROJ-10")) is not None


def test_an_expired_receipt_does_not_authorise(monkeypatch):
    """Evidence from last week cannot close today's ticket."""
    import time
    monkeypatch.setenv(RULE.DONE_TRANSITIONS_ENV, "31")
    RULE.pretooluse(_comment_event("PROJ-11", GOOD))
    assert RULE.read_receipt(
        "PROJ-11", now=time.time() + RULE.RECEIPT_TTL_SECONDS + 1,
    ) is None


def test_a_fresh_receipt_is_not_expired(monkeypatch):
    """NEGATIVE CONTROL: if the TTL were inverted nothing would ever pass."""
    RULE.pretooluse(_comment_event("PROJ-12", GOOD))
    assert RULE.read_receipt("PROJ-12") is not None


def test_an_undeclared_transition_is_ignored(monkeypatch):
    """NEGATIVE CONTROL: a move to In Progress is not a closure."""
    monkeypatch.setenv(RULE.DONE_TRANSITIONS_ENV, "31")
    assert RULE.pretooluse(_transition_event("PROJ-13", tid="21")) is None


def test_no_declared_transitions_means_the_rule_does_nothing(monkeypatch):
    """THE PORTABILITY GUARANTEE.

    A consumer who has not declared which transition means Done cannot be
    judged - ids are per-workflow. Silence is correct: the alternative is
    demanding a closure comment on every move to In Progress, which would be
    switched off within a day.
    """
    monkeypatch.delenv(RULE.DONE_TRANSITIONS_ENV, raising=False)
    assert RULE.pretooluse(_transition_event("PROJ-14")) is None
    assert RULE.declared_done_transitions() == set()


def test_declared_transitions_are_parsed(monkeypatch):
    monkeypatch.setenv(RULE.DONE_TRANSITIONS_ENV, "31, 41 ,")
    assert RULE.declared_done_transitions() == {"31", "41"}


def test_a_corrupt_receipt_does_not_crash(monkeypatch, tmp_path):
    """Fail open on garbage rather than a traceback inside a hook."""
    monkeypatch.setenv(RULE.DONE_TRANSITIONS_ENV, "31")
    RULE._receipt_path("PROJ-15").write_text("{ not json", encoding="utf-8")
    assert RULE.read_receipt("PROJ-15") is None


def test_the_skip_env_releases_the_gate(monkeypatch):
    monkeypatch.setenv(RULE.DONE_TRANSITIONS_ENV, "31")
    monkeypatch.setenv(SPEC.get("skip_env", "AIPLAYBOOK_JIRA_CLOSURE_SKIP"), "1")
    assert RULE.pretooluse(_transition_event("PROJ-16")) is None


def test_the_refusal_says_the_comment_cannot_ride_in_the_transition(monkeypatch):
    """The one thing a reader will try next, pre-empted.

    Faced with 'post the comment first', the obvious idea is to attach it to the
    transition. That silently loses the comment. The message says so.
    """
    monkeypatch.setenv(RULE.DONE_TRANSITIONS_ENV, "31")
    msg = RULE.pretooluse(_transition_event("PROJ-17")).message
    assert "cannot ride inside the transition" in msg


# ---------------------------------------------------------------------------
# C4 - no blank halves, judged with no ticket and no network
# ---------------------------------------------------------------------------


def test_an_enumerated_closure_with_a_blank_half_is_refused():
    assert "C4" in _failed("", BLANK_HALF)


def test_every_half_carrying_an_artefact_passes():
    """NEGATIVE CONTROL for C4."""
    assert "C4" not in _failed("", GOOD)


def test_the_blank_half_refusal_agrees_in_number():
    """The refusal is prose a person has to act on; make it read as prose.

    The plural was applied to the noun and not to the verb, so the COMMON case
    -- exactly one blank half -- shipped 'item 2 name no artefact'. Caught by
    reading the gate's own output during an end-to-end probe, not by any test:
    every assertion here checked clause ids, and none read the sentence.
    """
    def c4(comment: str) -> str:
        return next(c for c in RULE.evaluate("", comment, SPEC) if c.id == "C4").detail

    assert "item 2 names no artefact" in c4(BLANK_HALF)
    assert "items 1, 2 name no artefact" in c4("FIXED\n1. first thing\n2. second\n")


def test_evidence_on_the_following_line_still_counts():
    comment = (
        "FIXED\n"
        "1. the gate counts moved ids\n"
        "   see adapters/shared_drive.py:354\n"
        "2. the verify test exists\n"
        "   test_shared_drive_adapter.py\n"
    )
    assert "C4" not in _failed("", comment)


def test_prose_bullets_are_not_treated_as_claims():
    """NEGATIVE CONTROL: bullets carry context, not coverage claims."""
    comment = (
        "FIXED - adapters/shared_drive.py:354\n\n"
        "- point one was already resolved by GPLO-1511\n"
        "- point three is a design call for the transfer owner\n"
    )
    assert "C4" not in _failed("", comment)


def test_a_single_enumerated_item_is_not_judged_by_c4():
    """NEGATIVE CONTROL: counting to one adds nothing over C3."""
    assert "C4" not in _failed("", "FIXED\n1. done - app/x.py:1\n")
