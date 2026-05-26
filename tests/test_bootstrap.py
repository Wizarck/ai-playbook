"""Tests for scripts/bootstrap.py (T22e).

Mocks subprocess.run so tests never touch the real git / pre-commit / doctor /
discover_projects wiring. Template substitution, CLI parsing, owner-resolution
chain, personal flag injection, --dry-run safety, and break-glass fallback are
covered.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import bootstrap as bs

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeProc:
    """Mimics the subset of subprocess.CompletedProcess we care about."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _neuter_subprocess(monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]) -> None:
    """Replace subprocess.run with a recorder returning success."""
    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return _FakeProc(returncode=0)
    monkeypatch.setattr(bs.subprocess, "run", fake_run)


def _stub_prereqs(monkeypatch: pytest.MonkeyPatch) -> None:
    """git + pre-commit both found."""
    def fake_which(name):  # type: ignore[no-untyped-def]
        return f"/usr/bin/{name}"
    monkeypatch.setattr(bs.shutil, "which", fake_which)


def _clear_owner_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL", "EMAIL"):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Slug validation
# ---------------------------------------------------------------------------


def test_validate_slug_accepts_valid() -> None:
    bs.validate_slug("acme-shop")
    bs.validate_slug("A1")
    bs.validate_slug("repo_with_underscore")


def test_validate_slug_rejects_spaces() -> None:
    with pytest.raises(SystemExit) as exc:
        bs.validate_slug("Acme Shop")
    assert exc.value.code == 1


def test_validate_slug_rejects_leading_hyphen() -> None:
    with pytest.raises(SystemExit) as exc:
        bs.validate_slug("-bad")
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# Owner resolution chain: CLI > env > git > sentinel
# ---------------------------------------------------------------------------


def test_resolve_owner_cli_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "env@example.com")
    assert bs.resolve_owner("cli@example.com") == "cli@example.com"


def test_resolve_owner_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_owner_env(monkeypatch)
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "env@example.com")
    assert bs.resolve_owner(None) == "env@example.com"


def test_resolve_owner_git_config_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_owner_env(monkeypatch)

    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        assert cmd == ["git", "config", "user.email"]
        return _FakeProc(returncode=0, stdout="git@example.com\n")
    monkeypatch.setattr(bs.subprocess, "run", fake_run)
    assert bs.resolve_owner(None) == "git@example.com"


def test_resolve_owner_final_sentinel(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_owner_env(monkeypatch)

    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeProc(returncode=1, stdout="")
    monkeypatch.setattr(bs.subprocess, "run", fake_run)
    assert bs.resolve_owner(None) == "unknown@example.com"


# ---------------------------------------------------------------------------
# Target path resolution
# ---------------------------------------------------------------------------


def test_resolve_target_path_default_under_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    target = bs.resolve_target_path("alpha", None)
    assert target == (tmp_path / "alpha").resolve()


def test_resolve_target_path_explicit_override(tmp_path: Path) -> None:
    explicit = tmp_path / "custom"
    target = bs.resolve_target_path("alpha", explicit)
    assert target == explicit.resolve()


def test_resolve_target_path_file_collision(tmp_path: Path) -> None:
    collision = tmp_path / "collision"
    collision.write_text("not a dir\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        bs.resolve_target_path("alpha", collision)
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# Template substitution
# ---------------------------------------------------------------------------


def test_substitute_replaces_all_placeholders() -> None:
    text = (
        "project={{PROJECT_NAME}} owner={{OWNER_EMAIL}} today={{TODAY}} "
        "pin={{PLAYBOOK_PIN}}"
    )
    out = bs._substitute(
        text,
        project_name="alpha",
        owner="a@b.c",
        today_iso="2026-04-23",
        playbook_pin="v1.2.3",
    )
    assert out == "project=alpha owner=a@b.c today=2026-04-23 pin=v1.2.3"


def test_copy_templates_writes_expected_files(tmp_path: Path) -> None:
    playbook_root = bs.find_playbook_root()
    target = tmp_path / "alpha"
    target.mkdir()
    written = bs.copy_templates(
        playbook_root=playbook_root,
        target_dir=target,
        project_name="alpha",
        owner="a@b.c",
        playbook_pin="v1.2.3",
        dry_run=False,
    )
    agents = target / "AGENTS.md"
    assert agents in written
    content = agents.read_text(encoding="utf-8")
    assert "project: alpha" in content
    assert "owner: a@b.c" in content
    # inherits_from pin uses the substituted PLAYBOOK_PIN, not a hardcoded tag.
    assert "ai-playbook@v1.2.3" in content
    assert "{{PLAYBOOK_PIN}}" not in content
    # Unsubstituted placeholders remain for manual fill.
    assert "{{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}" in content


def test_copy_templates_missing_dir_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bogus_root = tmp_path / "not-a-playbook"
    bogus_root.mkdir()
    with pytest.raises(SystemExit) as exc:
        bs.copy_templates(
            playbook_root=bogus_root,
            target_dir=tmp_path,
            project_name="alpha",
            owner="a@b.c",
            playbook_pin="v1.2.3",
            dry_run=False,
        )
    assert exc.value.code == 1


def test_copy_templates_strips_tmpl_suffix(tmp_path: Path) -> None:
    playbook_root = bs.find_playbook_root()
    target = tmp_path / "proj"
    target.mkdir()
    bs.copy_templates(
        playbook_root=playbook_root,
        target_dir=target,
        project_name="proj",
        owner="a@b.c",
        playbook_pin="v1.2.3",
        dry_run=False,
    )
    # .tmpl files should land without the suffix.
    assert (target / "AGENTS.md").is_file()
    assert not (target / "AGENTS.md.tmpl").exists()


def test_copy_templates_dry_run_no_files(tmp_path: Path) -> None:
    playbook_root = bs.find_playbook_root()
    target = tmp_path / "alpha"
    target.mkdir()
    written = bs.copy_templates(
        playbook_root=playbook_root,
        target_dir=target,
        project_name="alpha",
        owner="a@b.c",
        playbook_pin="v1.2.3",
        dry_run=True,
    )
    assert written  # names listed
    assert not (target / "AGENTS.md").exists()


# ---------------------------------------------------------------------------
# Personal flag injection
# ---------------------------------------------------------------------------


def test_inject_personal_flag_adds_when_absent(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "---\nschema: agents-md/v1\nproject: p\n---\n\nbody\n",
        encoding="utf-8",
    )
    bs.inject_personal_flag(agents, dry_run=False)
    text = agents.read_text(encoding="utf-8")
    assert "personal: true" in text
    assert "body" in text


def test_inject_personal_flag_idempotent(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "---\nschema: agents-md/v1\npersonal: true\n---\n\nbody\n",
        encoding="utf-8",
    )
    bs.inject_personal_flag(agents, dry_run=False)
    text = agents.read_text(encoding="utf-8")
    assert text.count("personal: true") == 1


def test_inject_personal_flag_dry_run_is_noop(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "---\nschema: agents-md/v1\n---\nbody\n",
        encoding="utf-8",
    )
    before = agents.read_text(encoding="utf-8")
    bs.inject_personal_flag(agents, dry_run=True)
    assert agents.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# End-to-end CLI via main() with subprocess mocked
# ---------------------------------------------------------------------------


def test_main_happy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_prereqs(monkeypatch)
    calls: list[list[str]] = []
    _neuter_subprocess(monkeypatch, calls)
    monkeypatch.chdir(tmp_path)

    rc = bs.main(["alpha", "--owner", "a@b.c"])
    assert rc == 0
    target = (tmp_path / "alpha").resolve()
    assert (target / "AGENTS.md").is_file()
    assert "project: alpha" in (target / "AGENTS.md").read_text(encoding="utf-8")
    # git + pre-commit + doctor + discover all invoked.
    program_names = [c[0] for c in calls] + [c[2] if len(c) > 2 else "" for c in calls]
    assert any("git" in name for name in program_names)


def test_main_personal_flag_writes_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_prereqs(monkeypatch)
    _neuter_subprocess(monkeypatch, [])
    monkeypatch.chdir(tmp_path)

    rc = bs.main(["alpha", "--owner", "a@b.c", "--personal"])
    assert rc == 0
    text = ((tmp_path / "alpha") / "AGENTS.md").read_text(encoding="utf-8")
    assert "personal: true" in text


def test_main_dry_run_no_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_prereqs(monkeypatch)
    _neuter_subprocess(monkeypatch, [])
    monkeypatch.chdir(tmp_path)

    rc = bs.main(["alpha", "--owner", "a@b.c", "--dry-run"])
    assert rc == 0
    # Directory may be created via resolve_target_path, but AGENTS.md must not be.
    assert not ((tmp_path / "alpha") / "AGENTS.md").exists()


def test_main_invalid_slug_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        bs.main(["Acme Shop"])
    assert exc.value.code == 1


def test_main_git_missing_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # pre-commit found; git missing.
    def fake_which(name):  # type: ignore[no-untyped-def]
        return None if name == "git" else "/usr/bin/pre-commit"
    monkeypatch.setattr(bs.shutil, "which", fake_which)
    _neuter_subprocess(monkeypatch, [])
    monkeypatch.chdir(tmp_path)

    rc = bs.main(["alpha", "--owner", "a@b.c"])
    assert rc == 2


def test_main_submodule_failure_without_force_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_prereqs(monkeypatch)

    # Make the submodule add call fail; all other subprocess calls succeed.
    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        if "submodule" in cmd:
            return _FakeProc(returncode=128, stderr="unreachable")
        return _FakeProc(returncode=0)
    monkeypatch.setattr(bs.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)

    rc = bs.main(["alpha", "--owner", "a@b.c"])
    assert rc == 2


def test_main_playbook_path_without_force_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_prereqs(monkeypatch)
    _neuter_subprocess(monkeypatch, [])
    monkeypatch.chdir(tmp_path)

    local_copy = tmp_path / "local-playbook"
    local_copy.mkdir()
    rc = bs.main(["alpha", "--owner", "a@b.c", "--playbook-path", str(local_copy)])
    assert rc == 2


def test_main_playbook_path_with_force_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_prereqs(monkeypatch)
    _neuter_subprocess(monkeypatch, [])
    monkeypatch.chdir(tmp_path)

    local_copy = tmp_path / "local-playbook"
    # Provide minimal content so copytree has something real to copy.
    (local_copy / "specs").mkdir(parents=True)
    (local_copy / "specs" / "dummy.md").write_text("x\n", encoding="utf-8")

    rc = bs.main([
        "alpha", "--owner", "a@b.c",
        "--playbook-path", str(local_copy),
        "--force-with-reason", "bootstrapping alpha offline on plane wifi",
    ])
    assert rc == 0
    submodule = (tmp_path / "alpha" / ".ai-playbook")
    assert submodule.is_dir()
    assert (submodule / "specs" / "dummy.md").is_file()


def test_main_file_collision_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "alpha").write_text("not a dir\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        bs.main(["alpha", "--owner", "a@b.c"])
    assert exc.value.code == 1


def test_main_owner_resolution_via_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_prereqs(monkeypatch)
    _neuter_subprocess(monkeypatch, [])
    _clear_owner_env(monkeypatch)
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "env@example.com")
    monkeypatch.chdir(tmp_path)

    rc = bs.main(["alpha"])
    assert rc == 0
    text = ((tmp_path / "alpha") / "AGENTS.md").read_text(encoding="utf-8")
    assert "owner: env@example.com" in text


# ---------------------------------------------------------------------------
# Caveman default-on (step 4.6)
# ---------------------------------------------------------------------------


def _neuter_subprocess_with_classifier(
    monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]
) -> None:
    """Like _neuter_subprocess but classifies caveman invocations separately."""
    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return _FakeProc(returncode=0)
    monkeypatch.setattr(bs.subprocess, "run", fake_run)


def _caveman_calls(calls: list[list[str]]) -> list[list[str]]:
    """Return the subset of recorded subprocess calls that target scripts.caveman."""
    out: list[list[str]] = []
    for c in calls:
        if any("scripts.caveman" in part for part in c):
            out.append(c)
    return out


def test_main_default_on_invokes_caveman(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bootstrap without --no-caveman MUST shell out to `python -m scripts.caveman on`."""
    _stub_prereqs(monkeypatch)
    calls: list[list[str]] = []
    _neuter_subprocess_with_classifier(monkeypatch, calls)
    monkeypatch.chdir(tmp_path)

    rc = bs.main(["alpha", "--owner", "a@b.c"])
    assert rc == 0

    cav_calls = _caveman_calls(calls)
    assert len(cav_calls) >= 1, f"expected a caveman invocation, got: {calls}"
    invoked = cav_calls[0]
    # Command shape: python -m scripts.caveman on --mode full --components <csv> --project <path>
    assert "on" in invoked
    assert "--mode" in invoked
    assert "full" in invoked
    assert "--components" in invoked
    csv = invoked[invoked.index("--components") + 1]
    for comp in bs.DEFAULT_CAVEMAN_COMPONENTS:
        assert comp in csv, f"component {comp!r} missing from --components {csv!r}"
    assert "--project" in invoked
    target = invoked[invoked.index("--project") + 1]
    assert Path(target).name == "alpha"


def test_main_no_caveman_skips_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--no-caveman MUST suppress the caveman activation subprocess call."""
    _stub_prereqs(monkeypatch)
    calls: list[list[str]] = []
    _neuter_subprocess_with_classifier(monkeypatch, calls)
    monkeypatch.chdir(tmp_path)

    rc = bs.main(["alpha", "--owner", "a@b.c", "--no-caveman"])
    assert rc == 0

    assert _caveman_calls(calls) == [], (
        f"--no-caveman must skip the caveman subprocess, but it was invoked: {calls}"
    )


def test_main_default_on_dry_run_is_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """--dry-run must NOT spawn the caveman subprocess; it only prints the intent."""
    _stub_prereqs(monkeypatch)
    calls: list[list[str]] = []
    _neuter_subprocess_with_classifier(monkeypatch, calls)
    monkeypatch.chdir(tmp_path)

    rc = bs.main(["alpha", "--owner", "a@b.c", "--dry-run"])
    assert rc == 0

    assert _caveman_calls(calls) == [], "dry-run must not invoke caveman"
    out = capsys.readouterr().out
    assert "Would activate caveman default-on" in out


def test_enable_caveman_default_warns_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A non-zero caveman exit MUST warn but not raise — bootstrap is best-effort here."""
    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeProc(returncode=1, stderr="❌ something went wrong\n")
    monkeypatch.setattr(bs.subprocess, "run", fake_run)

    target = tmp_path / "alpha"
    target.mkdir()
    bs.enable_caveman_default(target, dry_run=False)  # must not raise
    out = capsys.readouterr().out
    assert "caveman default-on failed" in out
    assert "something went wrong" in out


def test_enable_caveman_default_dry_run_message(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    target = tmp_path / "alpha"
    target.mkdir()
    bs.enable_caveman_default(target, dry_run=True)
    out = capsys.readouterr().out
    assert "Would activate caveman default-on" in out
    for comp in bs.DEFAULT_CAVEMAN_COMPONENTS:
        assert comp in out


# ---------------------------------------------------------------------------
# Post-bootstrap ai-playbook-check (validate-only drift report)
# ---------------------------------------------------------------------------


def _check_call(calls: list[list[str]]) -> list[str] | None:
    """Return the recorded ai_playbook_check invocation, or None."""
    for c in calls:
        if any("ai_playbook_check" in part for part in c):
            return c
    return None


def test_run_playbook_check_invokes_orchestrator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return _FakeProc(returncode=0)
    monkeypatch.setattr(bs.subprocess, "run", fake_run)

    target = tmp_path / "alpha"
    target.mkdir()
    bs.run_playbook_check(target, dry_run=False)

    cmd = _check_call(calls)
    assert cmd is not None
    assert "--check" in cmd, "must pass --check to suppress interactive apply"
    assert str(target) in cmd


def test_run_playbook_check_dry_run_no_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    calls: list[list[str]] = []
    _neuter_subprocess(monkeypatch, calls)

    target = tmp_path / "alpha"
    target.mkdir()
    bs.run_playbook_check(target, dry_run=True)

    assert _check_call(calls) is None
    out = capsys.readouterr().out
    assert "ai_playbook_check" in out
    assert "--check" in out


def test_run_playbook_check_drift_exit_does_not_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Exit 1 (drift detected) is the EXPECTED outcome — bootstrap must NOT warn."""
    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeProc(returncode=1)
    monkeypatch.setattr(bs.subprocess, "run", fake_run)

    target = tmp_path / "alpha"
    target.mkdir()
    bs.run_playbook_check(target, dry_run=False)
    out = capsys.readouterr().out
    assert "exited" not in out


def test_run_playbook_check_orchestrator_crash_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeProc(returncode=2)
    monkeypatch.setattr(bs.subprocess, "run", fake_run)

    target = tmp_path / "alpha"
    target.mkdir()
    bs.run_playbook_check(target, dry_run=False)
    out = capsys.readouterr().out
    assert "exited 2" in out


def test_no_check_flag_skips_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: --no-check must short-circuit run_playbook_check."""
    calls: list[list[str]] = []
    _neuter_subprocess(monkeypatch, calls)
    _stub_prereqs(monkeypatch)
    _clear_owner_env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    rc = bs.main(["alpha", "--owner", "a@b.c", "--dry-run", "--no-check"])
    assert rc == 0
    assert _check_call(calls) is None


def test_check_default_runs_in_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Default bootstrap (no --no-check) MUST surface the validate step in dry-run."""
    calls: list[list[str]] = []
    _neuter_subprocess(monkeypatch, calls)
    _stub_prereqs(monkeypatch)
    _clear_owner_env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    rc = bs.main(["alpha", "--owner", "a@b.c", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ai_playbook_check" in out
