"""Byte-equivalence test: hook helpers vs rule.py helpers.

Guards invariant INV-5 from docs/rules/apply-skill-enforcement.rule.md:
the L1 hook (`.claude/hooks/openspec-apply-enforce.py`) and the L3
rule.py validator (`scripts/rules/apply-skill-enforcement.rule.py`) MUST
agree on `_parse_write_paths` and `_path_matches`. The helpers are
deliberately duplicated to avoid `sys.path` injection from a PreToolUse
hook subprocess; this test is the gate that catches drift.

If you change either implementation, this test forces the other to
match (or forces a deliberate documented divergence).
"""
from __future__ import annotations

import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_TEMPLATE = (
    REPO_ROOT
    / "templates"
    / "new-project"
    / ".claude"
    / "hooks"
    / "openspec-apply-enforce.py.tmpl"
)
RULE_SCRIPT = REPO_ROOT / "scripts" / "rules" / "apply-skill-enforcement.rule.py"


def _load_module(name: str, path: Path) -> types.ModuleType:
    """Compile and exec the file in-memory.

    Avoids `importlib.SourceFileLoader` because that path writes a `.pyc`
    sibling under `__pycache__/` (e.g. `templates/.../hooks/__pycache__/`),
    which then poisons the bootstrap-template suite that scans `templates/`
    for UTF-8 text files. exec'ing into a fresh ModuleType keeps everything
    in RAM.
    """
    src = path.read_text(encoding="utf-8")
    code = compile(src, str(path), "exec")
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(code, module.__dict__)
    return module


_hook = _load_module("_hook_helpers", HOOK_TEMPLATE)
_rule = _load_module("_rule_helpers", RULE_SCRIPT)


# ---------------------------------------------------------------------------
# _parse_write_paths fixtures (tasks.md content → expected list[str])
# ---------------------------------------------------------------------------

_TASKS_FIXTURES: list[tuple[str, list[str]]] = [
    # 1. Minimal canonical case.
    (
        "# tasks — demo\n\n## Owns (write_paths)\n\n* `backend/foo.py`\n\n## Reads\n\n* nothing\n",
        ["backend/foo.py"],
    ),
    # 2. Multiple bullets.
    (
        "## Owns (write_paths)\n\n* `a/b.py`\n* `c/d.py`\n* `e/f.py`\n\n## Reads\n",
        ["a/b.py", "c/d.py", "e/f.py"],
    ),
    # 3. Mixed bullet styles (* and -).
    (
        "## Owns (write_paths)\n\n* `a.py`\n- `b.py`\n* `c.py`\n\n## Reads\n",
        ["a.py", "b.py", "c.py"],
    ),
    # 4. Glob entries.
    (
        "## Owns (write_paths)\n\n* `backend/services/*.py`\n* `frontend/**/*.tsx`\n\n## Reads\n",
        ["backend/services/*.py", "frontend/**/*.tsx"],
    ),
    # 5. Heading variants (case-insensitive).
    (
        "## OWNS (WRITE_PATHS)\n\n* `X.py`\n\n## Reads\n",
        ["X.py"],
    ),
    # 6. Section terminator: next ## heading stops collection.
    (
        "## Owns (write_paths)\n\n* `a.py`\n\n## Other section\n\n* `should_not_appear.py`\n",
        ["a.py"],
    ),
    # 7. No write_paths section at all.
    (
        "# tasks — demo\n\nFreeform notes here.\n",
        [],
    ),
    # 8. Empty section.
    (
        "## Owns (write_paths)\n\n## Reads\n\n* x\n",
        [],
    ),
    # 9. Surrounding whitespace tolerance.
    (
        "## Owns (write_paths)\n\n    * `padded.py`\n\n## Reads\n",
        ["padded.py"],
    ),
    # 10. Bullets without backticks should NOT match.
    (
        "## Owns (write_paths)\n\n* not_in_backticks.py\n* `backticked.py`\n\n## Reads\n",
        ["backticked.py"],
    ),
]


def test_parse_write_paths_equivalence(tmp_path):
    """Both implementations must parse the same set of write_paths from each fixture."""
    for idx, (content, _expected) in enumerate(_TASKS_FIXTURES):
        tasks_md = tmp_path / f"tasks_{idx}.md"
        tasks_md.write_text(content, encoding="utf-8")
        # Hook version is mtime-cached; the rule version is not. Both should
        # return the same list of strings.
        hook_result = _hook._parse_write_paths(tasks_md)
        rule_result = _rule._parse_write_paths(tasks_md)
        assert hook_result == rule_result, (
            f"fixture #{idx} diverges: hook={hook_result!r} rule={rule_result!r}\n"
            f"content:\n{content}"
        )


def test_parse_write_paths_matches_expected(tmp_path):
    """Sanity: both implementations match the expected output."""
    for idx, (content, expected) in enumerate(_TASKS_FIXTURES):
        tasks_md = tmp_path / f"tasks_{idx}.md"
        tasks_md.write_text(content, encoding="utf-8")
        for name, mod in (("hook", _hook), ("rule", _rule)):
            actual = mod._parse_write_paths(tasks_md)
            assert actual == expected, (
                f"fixture #{idx} ({name}): expected {expected!r}, got {actual!r}"
            )


# ---------------------------------------------------------------------------
# _path_matches fixtures (target, write_path) → expected match
# ---------------------------------------------------------------------------

_PATH_FIXTURES: list[tuple[str, str, bool]] = [
    # Exact match.
    ("backend/foo.py", "backend/foo.py", True),
    ("backend/foo.py", "backend/bar.py", False),
    # Star glob (single segment).
    ("backend/services/auth.py", "backend/services/*.py", True),
    ("backend/handlers/auth.py", "backend/services/*.py", False),
    # Double-star glob (any depth).
    ("frontend/a/b/c/x.tsx", "frontend/**/*.tsx", True),
    ("frontend/a/b/c/x.css", "frontend/**/*.tsx", False),
    # Directory prefix (write_path ends with /).
    ("backend/x.py", "backend/", True),
    ("frontend/x.tsx", "backend/", False),
    # Windows-style slashes normalised to forward slashes.
    (r"backend\foo.py", "backend/foo.py", True),
    ("backend/foo.py", r"backend\foo.py", True),
    # Empty target.
    ("", "backend/foo.py", False),
    # Empty write_path.
    ("backend/foo.py", "", False),
]


def test_path_matches_equivalence():
    """Hook and rule.py must agree on every (target, write_path) pair."""
    for target, wp, _expected in _PATH_FIXTURES:
        hook_match = _hook._path_matches(target, wp)
        rule_match = _rule._path_matches(target, wp)
        assert hook_match == rule_match, (
            f"divergence on ({target!r}, {wp!r}): hook={hook_match} rule={rule_match}"
        )


def test_path_matches_matches_expected():
    """Sanity: both implementations match the expected boolean."""
    for target, wp, expected in _PATH_FIXTURES:
        for name, mod in (("hook", _hook), ("rule", _rule)):
            actual = mod._path_matches(target, wp)
            assert actual == expected, (
                f"({name}) ({target!r}, {wp!r}): expected {expected}, got {actual}"
            )


def test_regex_constants_byte_identical():
    """The three regex constants must be byte-identical between hook and rule."""
    assert _hook.WRITE_PATHS_HEADING_RE.pattern == _rule.WRITE_PATHS_HEADING_RE.pattern, (
        "WRITE_PATHS_HEADING_RE drifted"
    )
    assert _hook.NEXT_HEADING_RE.pattern == _rule.NEXT_HEADING_RE.pattern, (
        "NEXT_HEADING_RE drifted"
    )
    assert _hook.BULLET_PATH_RE.pattern == _rule.BULLET_PATH_RE.pattern, (
        "BULLET_PATH_RE drifted"
    )
