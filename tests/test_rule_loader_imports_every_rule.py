"""Every shipped hardrule must actually import (D10 dispatcher).

THE DEFECT (fixed 2026-08-17). `_load_rule_module` built the module with
`module_from_spec` and ran `exec_module` WITHOUT registering it in
`sys.modules`. `@dataclass` resolves `cls.__module__` through `sys.modules` at
class-creation time, so any rule declaring a dataclass died with
`AttributeError: 'NoneType' object has no attribute '__dict__'` — a message that
names nothing useful.

The `except Exception: mod = None` then turned that into a `None`, and the
caller's `continue` made an unimportable rule indistinguishable from a rule that
simply has no hook for this event.

Measured cost: `jira-closure-evidence` declares a dataclass. It was
`status: enforced`, appeared in `--list`, was not disabled, and matched its
trigger — and had **never once run** since the day it shipped. Two later
explanations for why it was not firing (a matcher missing `transition`, then
absent Atlassian credentials) were both true and both downstream of this.

The first test is the one that matters: it is a census, so a NEW rule that fails
to import fails this file rather than going quietly missing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.hook_dispatcher import (  # noqa: E402
    _LOAD_ERRORS,
    _MODULE_CACHE,
    _load_rule_module,
    load_rules,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    _MODULE_CACHE.clear()
    _LOAD_ERRORS.clear()


def _rules_with_hardrules():
    return [r for r in load_rules() if r.hardrule_path]


def test_the_census_finds_hardrules():
    """Guard the guard: an empty list would make the next test vacuous."""
    rules = _rules_with_hardrules()
    assert len(rules) >= 10, (
        f"only {len(rules)} rules carry a hardrule — the loader is looking in "
        "the wrong place and the census below proves nothing"
    )


def test_every_shipped_hardrule_imports():
    """The census. A rule that cannot import is a silent coverage hole."""
    failed = {}
    for r in _rules_with_hardrules():
        if _load_rule_module(r.hardrule_path) is None:
            failed[r.slug] = _LOAD_ERRORS.get(str(r.hardrule_path), "unknown")
    assert not failed, (
        "these rules cannot be imported by the dispatcher, so they never run "
        f"no matter what their frontmatter says: {failed}"
    )


def test_a_dataclass_rule_imports(tmp_path):
    """The specific shape that broke, pinned directly.

    `from __future__ import annotations` is LOAD-BEARING here and was missing
    from the first draft of this test, which therefore passed with the fix
    reverted — a test claiming to pin a shape it could not reproduce, in the
    file about rules that silently do nothing.

    Measured: a plain `@dataclass` imports fine without the registration, and so
    does `@dataclass(slots=True)`. Only the deferred-annotations form fails,
    because that is what sends dataclasses to `sys.modules` to resolve the
    field types. Every rule in this repo starts with that import.
    """
    rule = tmp_path / "dataclass-thing.rule.py"
    rule.write_text(
        "from __future__ import annotations\n"
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class Thing:\n"
        "    x: int = 1\n"
        "def pretooluse(event):\n"
        "    return None\n",
        encoding="utf-8",
    )
    mod = _load_rule_module(rule)
    assert mod is not None, (
        "a rule declaring a dataclass still fails to import — the loader is "
        f"back to its old shape: {_LOAD_ERRORS.get(str(rule))}"
    )
    assert callable(mod.pretooluse)


def test_an_import_failure_is_recorded_not_swallowed(tmp_path):
    """NEGATIVE CONTROL, and the half that stops this recurring.

    A broken rule must still fail open — it must not wedge the hook path. But
    it must not vanish either: the reason is kept so a caller can say "this rule
    could not load" rather than treating it as absent by design.
    """
    broken = tmp_path / "broken.rule.py"
    broken.write_text("this is not python(\n", encoding="utf-8")
    assert _load_rule_module(broken) is None, "a broken rule must fail open"
    assert str(broken) in _LOAD_ERRORS, "the failure left no trace at all"
    assert "Error" in _LOAD_ERRORS[str(broken)]


def test_a_failed_import_leaves_no_half_built_module(tmp_path):
    """Registering before exec must not leak a broken module into sys.modules.

    A half-executed module left behind would be importable by name from
    anywhere else in the process, which is a worse failure than the one being
    fixed: it would appear to work.
    """
    broken = tmp_path / "half.rule.py"
    broken.write_text("import sys\nraise RuntimeError('boom')\n", encoding="utf-8")
    _load_rule_module(broken)
    leaked = [n for n in sys.modules if n.startswith("_rule_half_rule")]
    assert not leaked, f"a failed import left {leaked} in sys.modules"


def test_a_missing_file_is_not_an_error(tmp_path):
    """NEGATIVE CONTROL: absent is not broken."""
    assert _load_rule_module(tmp_path / "nope.rule.py") is None
    assert not _LOAD_ERRORS


def test_the_module_is_memoised(tmp_path):
    """Loading is per-process; the SLA is 50ms per tool call."""
    rule = tmp_path / "memo.rule.py"
    rule.write_text("def pretooluse(event):\n    return None\n", encoding="utf-8")
    assert _load_rule_module(rule) is _load_rule_module(rule)
