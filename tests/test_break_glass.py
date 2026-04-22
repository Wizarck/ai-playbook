"""Tests for scripts/_break_glass.py. Populated in T09."""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from scripts import _break_glass as bg


def test_add_break_glass_flag_registers_on_parser() -> None:
    parser = argparse.ArgumentParser()
    bg.add_break_glass_flag(parser)
    ns = parser.parse_args(["--force-with-reason", "abc"])
    assert ns.force_reason == "abc"


def test_add_break_glass_flag_default_none() -> None:
    parser = argparse.ArgumentParser()
    bg.add_break_glass_flag(parser)
    ns = parser.parse_args([])
    assert ns.force_reason is None


def test_apply_break_glass_no_reason_no_override(tmp_path: Path) -> None:
    result = bg.apply_break_glass(
        gate="g", script="s.py", reason=None, override_allowed=True, repo_root=tmp_path
    )
    assert result.applied is False
    assert result.reason == ""


def test_apply_break_glass_reason_too_short_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        bg.apply_break_glass(
            gate="g",
            script="s.py",
            reason="short",
            override_allowed=True,
            repo_root=tmp_path,
        )
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert f">= {bg.MIN_REASON_LEN}" in err
    assert "FIX:" in err


def test_apply_break_glass_whitespace_only_reason_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        bg.apply_break_glass(
            gate="g",
            script="s.py",
            reason="          ",  # 10 spaces — stripped = 0 chars
            override_allowed=True,
            repo_root=tmp_path,
        )


def test_apply_break_glass_valid_reason_logs_and_returns_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "tester@example.com")
    result = bg.apply_break_glass(
        gate="my-gate",
        script="my_script.py",
        reason="this is a valid reason with enough length",
        override_allowed=True,
        repo_root=tmp_path,
    )
    assert result.applied is True
    assert result.reason == "this is a valid reason with enough length"
    log = tmp_path / ".ai-playbook" / "overrides.log"
    assert log.exists()
    contents = log.read_text(encoding="utf-8")
    assert "tester@example.com" in contents
    assert "my_script.py" in contents
    assert "my-gate" in contents
    assert '"this is a valid reason with enough length"' in contents


def test_apply_break_glass_override_refused_exits_3(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        bg.apply_break_glass(
            gate="g",
            script="s.py",
            reason="legitimate reason ten plus chars",
            override_allowed=False,
            repo_root=tmp_path,
        )
    assert excinfo.value.code == 3
    err = capsys.readouterr().err
    assert "OVERRIDE: none" in err


def test_apply_break_glass_override_refused_but_no_reason_returns_false(
    tmp_path: Path,
) -> None:
    result = bg.apply_break_glass(
        gate="g", script="s.py", reason=None, override_allowed=False, repo_root=tmp_path
    )
    assert result.applied is False


def test_apply_break_glass_explicit_git_user_email(tmp_path: Path) -> None:
    bg.apply_break_glass(
        gate="g",
        script="s.py",
        reason="valid reason passing the min length check",
        override_allowed=True,
        repo_root=tmp_path,
        git_user_email="explicit@example.com",
    )
    log = tmp_path / ".ai-playbook" / "overrides.log"
    assert "explicit@example.com" in log.read_text(encoding="utf-8")


def test_apply_break_glass_appends_not_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "a@b.com")
    for i in range(3):
        bg.apply_break_glass(
            gate=f"gate{i}",
            script="s.py",
            reason=f"reason number {i} long enough",
            override_allowed=True,
            repo_root=tmp_path,
        )
    log = tmp_path / ".ai-playbook" / "overrides.log"
    lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 3


def test_min_reason_len_is_10() -> None:
    assert bg.MIN_REASON_LEN == 10
