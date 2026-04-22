"""Tests for scripts/block_manual_spec_edit.py. Populated in T09."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import block_manual_spec_edit as bmse


def _init_git(repo_root: Path, commit_msg: str | None = None) -> None:
    (repo_root / ".git").mkdir()
    if commit_msg is not None:
        (repo_root / ".git" / "COMMIT_EDITMSG").write_text(
            commit_msg, encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# Path matching
# ---------------------------------------------------------------------------


def test_is_protected_path_matches_openspec_specs() -> None:
    assert bmse.is_protected_path("openspec/specs/cart.md") is True
    assert bmse.is_protected_path("openspec/specs/sub/nested.md") is True
    assert bmse.is_protected_path("some/prefix/openspec/specs/foo.md") is True


def test_is_protected_path_ignores_unrelated() -> None:
    assert bmse.is_protected_path("openspec/changes/cart/proposal.md") is False
    assert bmse.is_protected_path("README.md") is False
    assert bmse.is_protected_path("specs/cart.md") is False
    assert bmse.is_protected_path("openspec/specs/not-md.txt") is False


def test_is_protected_path_normalises_backslashes() -> None:
    assert bmse.is_protected_path("openspec\\specs\\cart.md") is True


# ---------------------------------------------------------------------------
# main(): unprotected files pass
# ---------------------------------------------------------------------------


def test_main_no_protected_files_returns_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    rc = bmse.main(["README.md", "src/app.py"])
    assert rc == 0


def test_main_no_args_returns_0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert bmse.main([]) == 0


# ---------------------------------------------------------------------------
# main(): protected files
# ---------------------------------------------------------------------------


def test_main_protected_file_blocked_without_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _init_git(tmp_path, commit_msg="just a normal commit\n")
    monkeypatch.chdir(tmp_path)
    rc = bmse.main(["openspec/specs/cart.md"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "openspec/specs/cart.md" in err
    assert "FIX:" in err
    assert "OVERRIDE:" in err


def test_main_protected_file_allowed_with_archive_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git(
        tmp_path,
        commit_msg="docs: archive cart change\n\nopenspec-archive: acme-cart\n",
    )
    monkeypatch.chdir(tmp_path)
    rc = bmse.main(["openspec/specs/cart.md"])
    assert rc == 0


def test_main_env_commit_msg_file_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git(tmp_path, commit_msg="no marker here\n")
    external_msg = tmp_path / "external.msg"
    external_msg.write_text(
        "feat: archive\n\nopenspec-archive: acme-x\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PRE_COMMIT_COMMIT_MSG_FILE", str(external_msg))
    rc = bmse.main(["openspec/specs/cart.md"])
    assert rc == 0


def test_main_blocked_when_no_commit_msg_at_all(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # no .git, no env var
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PRE_COMMIT_COMMIT_MSG_FILE", raising=False)
    rc = bmse.main(["openspec/specs/cart.md"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "commit message unavailable" in err or "hand-edit" in err


# ---------------------------------------------------------------------------
# Break-glass
# ---------------------------------------------------------------------------


def test_main_break_glass_allows_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git(tmp_path, commit_msg="no marker\n")
    monkeypatch.chdir(tmp_path)
    rc = bmse.main(
        [
            "openspec/specs/cart.md",
            "--force-with-reason=intentionally patched archive marker for hot-fix",
        ]
    )
    assert rc == 0
    log = tmp_path / ".ai-playbook" / "overrides.log"
    assert log.exists()
    assert "openspec-specs-handedit" in log.read_text(encoding="utf-8")


def test_main_break_glass_short_reason_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git(tmp_path, commit_msg="no marker\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        bmse.main(
            [
                "openspec/specs/cart.md",
                "--force-with-reason=too-short",
            ]
        )
    assert excinfo.value.code == 1
