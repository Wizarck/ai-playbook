"""The branch-name gate must not demand something this repo forbids.

THE DEFECT (fixed 2026-08-16). The gate told authors to "create the proposal at
openspec/changes/<id>/ and commit it to this branch". This repository gitignores
`openspec/` on purpose — "the playbook does not commit its own proposals/tasks/
archive" (.gitignore, landed in #79) — so that remedy could never be followed.

Nobody was blocked, which is why it survived. The third remedy, "use a chore/*
branch", was the only one that worked, so every PR merged after #158 used
`chore/*` — including ones titled `feat(...)`: #163, #162, #161, #159, #157. The
prefix stopped meaning "this is maintenance" and came to mean "this is the only
prefix that passes", while the check reported green throughout.

These tests pin the shape of the fix rather than its wording, and the negative
controls are the important half: an exemption that swallows the whole gate would
satisfy every "must not block" assertion here while removing the enforcement the
file exists for.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "branch-name-validator.yml"


@pytest.fixture(scope="module")
def script() -> str:
    """The validate step's shell body."""
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = data["jobs"]["validate"]["steps"]
    step = next(s for s in steps if s.get("id") == "validate")
    return step["run"]


# ---------------------------------------------------------------------------
# The fix
# ---------------------------------------------------------------------------


def test_the_gate_exempts_a_change_id_whose_path_is_gitignored(script):
    """The requirement fires only where it can be satisfied."""
    assert "git check-ignore -q" in script, (
        "the gate no longer tests whether the proposal path is committable, so "
        "it can once again demand a file this repo forbids"
    )
    assert "exempt-openspec-ignored" in script


def test_the_ignore_test_targets_the_path_the_error_message_names(script):
    """The check and the advice must be about the SAME path.

    A `check-ignore` on some other path would be a gate that measures one thing
    and advises another — which is the original defect in a new costume.
    """
    assert 'git check-ignore -q "openspec/changes/$CHANGE_ID"' in script
    assert "openspec/changes/$CHANGE_ID/proposal.md" in script


def test_the_exemption_is_evaluated_after_the_directory_check(script):
    """Ordering is load-bearing.

    A consumer repo that DOES commit `openspec/` must still be judged by the
    directory itself. If the ignore-exemption ran first it would never matter,
    but if it ran before the `-d` test in a repo with a partially-ignored tree it
    would skip a check that was satisfiable.
    """
    dir_check = script.index('if [ -d "openspec/changes/$CHANGE_ID" ]')
    exemption = script.index("git check-ignore -q")
    assert dir_check < exemption


def test_the_repo_this_runs_in_actually_triggers_the_exemption():
    """The fix is worthless if its condition is false here.

    Measured against git rather than inferred from `.gitignore`, because the
    first draft of this fix DID infer — it asked "does the repo track anything
    under openspec/" and got "yes", since gitignoring a directory does not
    untrack what was committed before the ignore landed. That draft would have
    changed nothing at all.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", "openspec/changes/some-new-change"],
        cwd=ROOT, capture_output=True,
    )
    assert result.returncode == 0, (
        "openspec/changes/ is no longer gitignored here — if that is deliberate, "
        "this exemption is now dead code and the gate should enforce the "
        "directory again"
    )


# ---------------------------------------------------------------------------
# Negative controls — the exemption must not eat the gate
# ---------------------------------------------------------------------------


def test_the_branch_name_pattern_is_still_enforced(script):
    """The half that always applies, and the half worth keeping.

    Dropping the directory requirement is not the same as dropping the gate: a
    branch still has to be `<type>/<kebab-change-id>`.
    """
    assert "fail-branch-name" in script
    assert "^(feat|fix|chore|docs|refactor|test|release)/" in script


def test_a_committed_proposal_directory_still_satisfies_the_gate(script):
    """The original success path is untouched."""
    assert 'if [ -d "openspec/changes/$CHANGE_ID" ]' in script
    assert "verdict=ok" in script


def test_the_failing_verdict_still_exists(script):
    """There is still a way to fail.

    If this disappeared, every assertion above would pass while the gate had
    become unconditional success — the shape this whole module is about.
    """
    assert "verdict=fail-no-openspec" in script
    assert "exit 1" in script


@pytest.mark.parametrize("branch,should_match", [
    ("feat/closure-evidence", True),
    ("chore/release-cut", True),
    ("fix/some-thing", True),
    ("feat/Closure_Evidence", False),
    ("wip/whatever", False),
    ("no-slash", False),
])
def test_the_canonical_pattern_accepts_and_rejects_as_documented(script, branch, should_match):
    m = re.search(r"\^\((feat\|[a-z|]+)\)/\[a-z0-9\]\[a-z0-9-\]\*\$", script)
    assert m, "the canonical branch pattern is no longer in the script"
    pattern = re.compile(r"^(feat|fix|chore|docs|refactor|test|release)/[a-z0-9][a-z0-9-]*$")
    assert bool(pattern.match(branch)) is should_match
