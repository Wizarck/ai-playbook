"""Tests for scripts/block_manual_spec_edit.py. Populated in T09."""
from __future__ import annotations

import sys
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
    msg = tmp_path / "msg.txt"
    msg.write_text("docs: archive cart change\n\nopenspec-archive: acme-cart\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PRE_COMMIT_COMMIT_MSG_FILE", str(msg))
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


# ---------------------------------------------------------------------------
# read_commit_message — CI mode (v0.9.1 followup #3)
#
# Surfaced by consumer-e PR #57 (slice 3 archive). The hook must detect
# the `openspec-archive:` marker when pre-commit runs in `--from-ref/--to-ref`
# mode (CI's PR mode), not just from `.git/COMMIT_EDITMSG` (local mode).
# ---------------------------------------------------------------------------


def _git(tmp_path: Path, *args: str) -> None:
    """Run a git subcommand inside tmp_path (real git, real repo)."""
    import subprocess as _sp

    _sp.run(
        ["git", *args],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
        text=True,
    )


def _bootstrap_repo(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "initial commit")


def _rev_parse(tmp_path: Path, rev: str = "HEAD") -> str:
    import subprocess as _sp

    return _sp.run(
        ["git", "rev-parse", rev],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_read_commit_message_reads_pre_commit_from_to_ref_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Followup #3: in CI mode, concat all commit messages between FROM..TO."""
    _bootstrap_repo(tmp_path)
    base_sha = _rev_parse(tmp_path)

    # Two commits in the range; the SECOND one carries the marker.
    (tmp_path / "x.md").write_text("x", encoding="utf-8")
    _git(tmp_path, "add", "x.md")
    _git(tmp_path, "commit", "-m", "fix: random non-archive change")
    (tmp_path / "y.md").write_text("y", encoding="utf-8")
    _git(tmp_path, "add", "y.md")
    _git(
        tmp_path,
        "commit",
        "-m",
        "chore(openspec): archive slice 3\n\nopenspec-archive: my-change\n",
    )

    head_sha = _rev_parse(tmp_path)

    monkeypatch.delenv("PRE_COMMIT_COMMIT_MSG_FILE", raising=False)
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", base_sha)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", head_sha)

    msg = bmse.read_commit_message(tmp_path)
    assert msg is not None
    assert "openspec-archive:" in msg
    assert "fix: random non-archive change" in msg


def test_read_commit_message_ci_mode_marker_in_first_of_two_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The marker can appear in ANY commit in the range — concat covers all."""
    _bootstrap_repo(tmp_path)
    base_sha = _rev_parse(tmp_path)

    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    _git(tmp_path, "add", "a.md")
    _git(
        tmp_path,
        "commit",
        "-m",
        "chore: archive\n\nopenspec-archive: my-change\n",
    )
    (tmp_path / "b.md").write_text("b", encoding="utf-8")
    _git(tmp_path, "add", "b.md")
    _git(tmp_path, "commit", "-m", "style: formatting cleanup")

    head_sha = _rev_parse(tmp_path)

    monkeypatch.delenv("PRE_COMMIT_COMMIT_MSG_FILE", raising=False)
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", base_sha)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", head_sha)

    msg = bmse.read_commit_message(tmp_path)
    assert msg is not None
    assert "openspec-archive:" in msg


def test_read_commit_message_local_stage_takes_precedence_over_ci_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If both env vars + COMMIT_MSG_FILE set, COMMIT_MSG_FILE wins (local stage)."""
    _bootstrap_repo(tmp_path)
    msg_file = tmp_path / "msg.txt"
    msg_file.write_text(
        "local-stage commit\nopenspec-archive: x\n", encoding="utf-8"
    )

    monkeypatch.setenv("PRE_COMMIT_COMMIT_MSG_FILE", str(msg_file))
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", "HEAD")
    monkeypatch.setenv("PRE_COMMIT_TO_REF", "HEAD")

    msg = bmse.read_commit_message(tmp_path)
    assert msg is not None
    assert "local-stage commit" in msg


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("PRE_COMMIT_COMMIT_MSG_FILE", "PRE_COMMIT_FROM_REF", "PRE_COMMIT_TO_REF"):
        monkeypatch.delenv(var, raising=False)


def _stage_spec(repo: Path, text: str) -> None:
    spec = repo / "openspec" / "specs" / "auth" / "spec.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")


def test_read_commit_message_ignores_stale_editmsg_when_changes_are_staged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At the pre-commit stage COMMIT_EDITMSG is the PREVIOUS commit's message."""
    _bootstrap_repo(tmp_path)
    _stage_spec(tmp_path, "v1\n")
    _git(tmp_path, "commit", "-m", "openspec-archive: add-auth")
    _stage_spec(tmp_path, "v2 hand edit\n")
    _clear_env(monkeypatch)
    assert bmse.read_commit_message(tmp_path) is None


def test_read_commit_message_nothing_staged_uses_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI `--all-files` on a pushed commit: message and diff both come from HEAD."""
    _bootstrap_repo(tmp_path)
    _stage_spec(tmp_path, "v1\n")
    _git(tmp_path, "commit", "-m", "openspec-archive: add-auth")
    _clear_env(monkeypatch)
    msg = bmse.read_commit_message(tmp_path)
    assert msg is not None and "openspec-archive: add-auth" in msg


def test_commit_msg_stage_blocks_hand_edit_after_archive_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case A (was a bypass): hand edit committed right after an archive commit."""
    _bootstrap_repo(tmp_path)
    _stage_spec(tmp_path, "v1\n")
    _git(tmp_path, "commit", "-m", "openspec-archive: add-auth")
    _stage_spec(tmp_path, "v2 hand edit\n")
    msg = tmp_path / ".git" / "COMMIT_EDITMSG"
    msg.write_text("chore: tweak wording\n", encoding="utf-8")
    _clear_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert bmse.main(["--commit-msg-file", str(msg)]) == 1


def test_commit_msg_stage_allows_archive_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case B (was a false block): the archive commit itself, previous message 'init'."""
    _bootstrap_repo(tmp_path)
    _stage_spec(tmp_path, "v1\n")
    msg = tmp_path / ".git" / "COMMIT_EDITMSG"
    msg.write_text("openspec-archive: add-auth\n", encoding="utf-8")
    _clear_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert bmse.main(["--commit-msg-file", str(msg)]) == 0


def test_pre_commit_stage_defers_instead_of_reading_stale_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without --commit-msg-file and with staged changes there is no message to
    check yet: defer to the commit-msg stage rather than guess from the last one."""
    _bootstrap_repo(tmp_path)
    _stage_spec(tmp_path, "v1\n")
    (tmp_path / ".git" / "COMMIT_EDITMSG").write_text("init\n", encoding="utf-8")
    _clear_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert bmse.main(["openspec/specs/auth/spec.md"]) == 0
    assert "commit-msg stage" in capsys.readouterr().err


def test_commit_msg_stage_ignores_commits_without_spec_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap_repo(tmp_path)
    (tmp_path / "README.md").write_text("changed", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    msg = tmp_path / "m.txt"
    msg.write_text("docs: readme\n", encoding="utf-8")
    _clear_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert bmse.main(["--commit-msg-file", str(msg)]) == 0


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX hook shebang")
def test_real_commit_msg_hook_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real `git commit` with the guard installed as a commit-msg hook."""
    import subprocess as _sp

    playbook = Path(__file__).resolve().parent.parent
    _bootstrap_repo(tmp_path)
    hook = tmp_path / ".git" / "hooks" / "commit-msg"
    hook.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{playbook / "scripts" / "block_manual_spec_edit.py"}"'
        ' --commit-msg-file "$1"\n',
        encoding="utf-8",
    )
    hook.chmod(0o755)
    _clear_env(monkeypatch)

    def commit(msg: str) -> int:
        return _sp.run(["git", "commit", "-q", "-m", msg], cwd=tmp_path, capture_output=True).returncode

    _stage_spec(tmp_path, "v1\n")
    assert commit("openspec-archive: add-auth") == 0  # Case B
    _stage_spec(tmp_path, "v2 hand edit\n")
    assert commit("chore: tweak wording") != 0  # Case A
