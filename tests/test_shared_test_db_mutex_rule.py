"""One test database, one run at a time.

The incident this guards is in the rule doc. What matters for these tests is the
shape of it: the second invocation is always SMALL — one file, ten seconds — and
it destroys a long run that is answering a real question, leaving behind a result
that still looks like an answer.

The negative controls carry most of the weight here. A mutex that blocks
everything would satisfy every "must block" case while making the tool unusable,
and a stale lock that never releases is the same outage with extra steps.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    name = "shared_test_db_mutex_rule"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / "rules" / "shared-test-db-mutex.rule.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


RULE = _load()


@pytest.fixture(autouse=True)
def _isolated_lock_dir(tmp_path, monkeypatch):
    """Never touch the developer's real lock directory from a test."""
    monkeypatch.setattr(RULE, "_lock_dir", lambda: tmp_path)
    monkeypatch.delenv(RULE.SKIP_ENV, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _event(command: str, session: str = "s1") -> dict:
    return {
        "tool_name": "Bash",
        "session_id": session,
        "tool_input": {"command": command},
    }


PYTEST = "python -m pytest backend/tests/ -q"


# ---------------------------------------------------------------------------
# What counts as a run that touches the database
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", [
    "python -m pytest backend/tests/",
    "pytest backend/tests/transfer -q",
    "cd /repo && python -m pytest backend/tests/blueprints",
    "python -m alembic upgrade head",
    "python scripts/bootstrap-test-db.py",
    "tox -e py313",
])
def test_database_touching_runs_are_matched(command):
    assert RULE.touches_test_db(command) is True


@pytest.mark.parametrize("command", [
    "python -m pytest --collect-only backend/tests/",
    "pytest --help",
    "pytest --fixtures",
    "git status",
    "ruff check backend/",
    "npm test",
])
def test_harmless_commands_are_not_matched(command):
    """NEGATIVE CONTROL for the matcher.

    `--collect-only` is the one people actually run beside a live suite, and
    blocking it would make the gate a nuisance for no protection: it opens no
    database.
    """
    assert RULE.touches_test_db(command) is False


def test_the_word_pytest_inside_a_longer_token_does_not_match():
    """`pytest-asyncio` in a pip install line is not a test run."""
    assert RULE.touches_test_db("pip install pytest-asyncio") is False


# ---------------------------------------------------------------------------
# The lock itself
# ---------------------------------------------------------------------------


def test_a_second_session_is_refused_while_the_first_holds_it():
    assert RULE.pretooluse(_event(PYTEST, session="s1")) is None
    verdict = RULE.pretooluse(_event(PYTEST, session="s2"))
    assert verdict is not None, "the second run was allowed to corrupt the first"
    assert "another test run holds this database" in verdict.message


def test_the_same_session_may_run_again():
    """NEGATIVE CONTROL.

    A session that already holds the lock is not competing with itself. Blocking
    here would mean one test command per session, which nobody would tolerate for
    a week before switching the hook off.
    """
    assert RULE.pretooluse(_event(PYTEST, session="s1")) is None
    assert RULE.pretooluse(_event(PYTEST, session="s1")) is None


def test_the_lock_is_released_when_the_run_returns():
    RULE.pretooluse(_event(PYTEST, session="s1"))
    RULE.posttooluse(_event(PYTEST, session="s1"))
    assert RULE.pretooluse(_event(PYTEST, session="s2")) is None


def test_another_session_cannot_release_our_lock():
    RULE.pretooluse(_event(PYTEST, session="s1"))
    RULE.posttooluse(_event(PYTEST, session="s2"))
    assert RULE.pretooluse(_event(PYTEST, session="s3")) is not None


def test_a_different_database_is_not_contended(tmp_path):
    """The resource is the DATABASE, not the checkout.

    Two projects with separate databases must be able to run at once, and it is
    the escape hatch the block message tells people to use.
    """
    a = "DATABASE_URL=postgresql://x/db_a python -m pytest backend/tests/"
    b = "DATABASE_URL=postgresql://x/db_b python -m pytest backend/tests/"
    assert RULE.pretooluse(_event(a, session="s1")) is None
    assert RULE.pretooluse(_event(b, session="s2")) is None


# ---------------------------------------------------------------------------
# Staleness — the half that stops the mutex becoming an outage
# ---------------------------------------------------------------------------


def test_an_old_lock_is_stale():
    old = {"pid": 1, "started": time.time() - RULE.STALE_AFTER_SECONDS - 1}
    assert RULE._is_stale(old) is True


def test_a_fresh_lock_from_a_live_process_is_not_stale():
    """NEGATIVE CONTROL: if this returned True the mutex would never hold."""
    import os
    fresh = {"pid": os.getpid(), "started": time.time()}
    assert RULE._is_stale(fresh) is False


def test_a_stale_lock_is_taken_over(tmp_path):
    path = tmp_path / f"{RULE._database_key(PYTEST)}.json"
    path.write_text(json.dumps({
        "session": "dead-session",
        "pid": 1,
        "started": time.time() - RULE.STALE_AFTER_SECONDS - 60,
        "command": "python -m pytest",
    }), encoding="utf-8")
    assert RULE.pretooluse(_event(PYTEST, session="s2")) is None


def test_a_corrupt_lock_file_does_not_block(tmp_path):
    """Fail open on garbage. A half-written lock must not wedge the repo."""
    (tmp_path / f"{RULE._database_key(PYTEST)}.json").write_text("{ not json",
                                                                encoding="utf-8")
    assert RULE.pretooluse(_event(PYTEST, session="s2")) is None


def test_the_skip_env_releases_the_gate(monkeypatch):
    RULE.pretooluse(_event(PYTEST, session="s1"))
    monkeypatch.setenv(RULE.SKIP_ENV, "1")
    assert RULE.pretooluse(_event(PYTEST, session="s2")) is None
