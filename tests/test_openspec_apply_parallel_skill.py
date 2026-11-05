"""The openspec-apply-parallel skill's shell steps must survive separate Bash calls.

Claude Code runs every Bash tool call in a fresh shell. The skill set
`PRE_RECOMBINE=$(git rev-parse HEAD)` in step 8 and read it in step 9's abort,
a later call (the abort also waits for the user's yes), so the abort became
`git reset --hard ""`. Step 4's `$BASE_SHA` had the same shape and an empty
value silently branched from HEAD.
"""
from __future__ import annotations

import re
from pathlib import Path

SKILL = (
    Path(__file__).resolve().parents[1] / "skills" / "openspec-apply-parallel" / "SKILL.md"
)
TEXT = SKILL.read_text(encoding="utf-8")
BLOCKS = re.findall(r"```bash\n(.*?)```", TEXT, re.S)
REF = "slice/<change-id>--pre-recombine"


def _section(start: str, end: str) -> str:
    return TEXT[TEXT.index(start): TEXT.index(end)]


def test_no_bash_block_reads_a_variable_it_did_not_set() -> None:
    assert BLOCKS, "no bash blocks found: the parser no longer matches the skill"
    for block in BLOCKS:
        assigned = set(re.findall(r"^\s*(?:export\s+)?([A-Za-z_]\w*)=", block, re.M))
        assigned |= set(re.findall(r"\bfor\s+([A-Za-z_]\w*)\s+in\b", block))
        used = set(re.findall(r"\$\{?([A-Za-z_]\w*)", block))
        assert used <= assigned, f"{sorted(used - assigned)} set in another block:\n{block}"


def test_the_abort_point_is_a_ref_recorded_before_cherry_picking() -> None:
    step8 = _section("### 8.", "### 9.")
    assert f"git branch -f {REF} HEAD" in step8
    assert step8.index(f"git branch -f {REF}") < step8.index("git cherry-pick")


def test_the_abort_resets_to_that_ref_and_cleanup_removes_it() -> None:
    assert f"git reset --hard {REF}" in _section("### 9.", "### 10.")
    assert f"git branch -D {REF}" in _section("### 11.", "## Anti-patterns")
