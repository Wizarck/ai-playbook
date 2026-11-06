"""Consumer `pre-commit` / `commit-msg` git hooks hand the commit to pre-commit.

install-playbook-hooks.sh sets core.hooksPath=scripts/git-hooks, and
`pre-commit install` refuses to run while core.hooksPath is set, so in a
consumer with the playbook hooks wired the .pre-commit-config.yaml chain never
ran. The shims in templates/new-project/scripts/git-hooks/ replace the hooks
`pre-commit install` would write. Behavioural tests drive a real `git commit`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from scripts import bootstrap as bs

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_TEMPLATES = REPO_ROOT / "templates" / "new-project" / "scripts" / "git-hooks"
INSTALLER = REPO_ROOT / "templates" / "new-project" / "scripts" / "install-playbook-hooks.sh.tmpl"
SHIMS = ("pre-commit", "commit-msg")
GIT = shutil.which("git")

pytestmark = pytest.mark.skipif(GIT is None, reason="needs git")

FORBIDDEN_FILE = """\
repos:
  - repo: local
    hooks:
      - id: no-forbidden
        name: no forbidden file
        language: fail
        entry: forbidden file committed
        files: ^forbidden\\.txt$
"""

WIP_SUBJECT = FORBIDDEN_FILE + """\
      - id: no-wip
        name: no WIP subject
        language: pygrep
        entry: '^WIP'
        stages: [commit-msg]
"""

# A hook without `stages:` runs at every stage pre-commit is invoked for; this
# one only matches the message file, so it fails only if commit-msg runs.
MESSAGE_FILE_TRAP = """\
repos:
  - repo: local
    hooks:
      - id: trap
        name: stage-less hook on the message file
        language: fail
        entry: stage-less hook ran on the message
        files: COMMIT_EDITMSG$
"""

OPT_IN = "default_install_hook_types: [pre-commit, commit-msg]\n"


def _shell_dir() -> Path | None:
    """Directory of the shell git runs hooks with (usr/bin on Git for Windows)."""
    out = subprocess.run([GIT, "var", "GIT_SHELL_PATH"], capture_output=True, encoding="utf-8", errors="replace")
    if out.returncode == 0 and out.stdout.strip():
        return Path(out.stdout.strip()).parent
    sh = shutil.which("sh")
    return Path(sh).parent if sh else None


def _env(tmp_path: Path, path: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "PRE_COMMIT")) and k != "SKIP"}
    global_config = tmp_path / "gitconfig"
    global_config.touch()
    env.update(
        PATH=path,
        GIT_CONFIG_GLOBAL=str(global_config),
        GIT_CONFIG_NOSYSTEM="1",
        PRE_COMMIT_HOME=str(tmp_path / "pre-commit-home"),
    )
    return env


def _run(cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=120
    )


def _git(repo: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return _run([GIT, *args], repo, env)


def _init(repo: Path, env: dict[str, str]) -> None:
    repo.mkdir()
    for args in (
        ("init", "-q", "--initial-branch=main"),
        ("config", "user.email", "t@example.com"),
        ("config", "user.name", "T"),
    ):
        assert _git(repo, env, *args).returncode == 0


def _consumer(tmp_path: Path, env: dict[str, str], config: str | None) -> Path:
    repo = tmp_path / "consumer"
    _init(repo, env)
    hooks = repo / "scripts" / "git-hooks"
    hooks.mkdir(parents=True)
    for name in SHIMS:
        shutil.copyfile(HOOK_TEMPLATES / f"{name}.tmpl", hooks / name)
        (hooks / name).chmod(0o755)
    assert _git(repo, env, "config", "core.hooksPath", "scripts/git-hooks").returncode == 0
    if config is not None:
        (repo / ".pre-commit-config.yaml").write_text(config, encoding="utf-8", newline="\n")
    return repo


def _commit(repo: Path, env: dict[str, str], name: str, message: str) -> subprocess.CompletedProcess:
    (repo / name).write_text("x\n", encoding="utf-8")
    assert _git(repo, env, "add", "-A").returncode == 0
    return _git(repo, env, "commit", "-q", "-m", message)


def _stubbed_path(tmp_path: Path, *dirs: Path) -> str:
    """A PATH whose `python` / `python3` cannot import pre_commit, then `dirs`,
    then only what git and the hook shell need."""
    stub = tmp_path / "stub"
    stub.mkdir()
    for name in ("python", "python3"):
        (stub / name).write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="\n")
        (stub / name).chmod(0o755)
    grep = shutil.which("grep")
    system = (_shell_dir(), Path(GIT).parent, Path(grep).parent if grep else None)
    return os.pathsep.join(dict.fromkeys(str(d) for d in (stub, *dirs, *system) if d))


def _pre_commit_executable() -> str | None:
    """`pre-commit` as pipx or pip installs it: on PATH or in a scripts dir."""
    dirs = (
        os.environ.get("PATH", ""),
        sysconfig.get_path("scripts"),
        sysconfig.get_path("scripts", sysconfig.get_preferred_scheme("user")),
    )
    return next((exe for d in dirs if (exe := shutil.which("pre-commit", path=d))), None)


@pytest.fixture
def framework_path() -> str:
    """A PATH whose `python` is this interpreter, which imports pre_commit."""
    pytest.importorskip("pre_commit")
    py_dir = os.path.dirname(sys.executable)
    if not (shutil.which("python", path=py_dir) or shutil.which("python3", path=py_dir)):
        pytest.skip("no `python` / `python3` beside sys.executable for the shims to find")
    return py_dir + os.pathsep + os.environ.get("PATH", "")


def test_shims_run_both_stages_through_pre_commit(tmp_path: Path, framework_path: str) -> None:
    env = _env(tmp_path, framework_path)
    repo = _consumer(tmp_path, env, WIP_SUBJECT)

    ok = _commit(repo, env, "ok.txt", "feat: ok")
    assert ok.returncode == 0, ok.stdout + ok.stderr

    wip = _commit(repo, env, "next.txt", "WIP: not yet")
    assert wip.returncode != 0
    assert "no WIP subject" in wip.stdout + wip.stderr

    bad = _commit(repo, env, "forbidden.txt", "feat: bad")
    assert bad.returncode != 0
    assert "forbidden file committed" in bad.stdout + bad.stderr


def test_commit_msg_shim_runs_only_when_the_config_names_the_stage(
    tmp_path: Path, framework_path: str
) -> None:
    env = _env(tmp_path, framework_path)
    repo = _consumer(tmp_path, env, MESSAGE_FILE_TRAP)
    # As after a plain `pre-commit install`: no commit-msg stage, hook runs once.
    quiet = _commit(repo, env, "a.txt", "feat: a")
    assert quiet.returncode == 0, quiet.stdout + quiet.stderr

    (repo / ".pre-commit-config.yaml").write_text(OPT_IN + MESSAGE_FILE_TRAP, encoding="utf-8", newline="\n")
    trapped = _commit(repo, env, "b.txt", "feat: b")
    assert trapped.returncode != 0
    assert "stage-less hook ran on the message" in trapped.stdout + trapped.stderr


def test_shims_fall_back_to_a_pre_commit_executable(tmp_path: Path) -> None:
    """pipx puts `pre-commit` on PATH where no `python` can import it."""
    exe = _pre_commit_executable()
    if exe is None:
        pytest.skip("no pre-commit executable")
    env = _env(tmp_path, _stubbed_path(tmp_path, Path(exe).parent))
    repo = _consumer(tmp_path, env, WIP_SUBJECT)

    wip = _commit(repo, env, "next.txt", "WIP: not yet")
    assert wip.returncode != 0
    assert "no WIP subject" in wip.stdout + wip.stderr

    bad = _commit(repo, env, "forbidden.txt", "feat: bad")
    assert bad.returncode != 0
    assert "forbidden file committed" in bad.stdout + bad.stderr


def test_shims_warn_and_let_the_commit_through_without_pre_commit(tmp_path: Path) -> None:
    path = _stubbed_path(tmp_path)
    if shutil.which("pre-commit", path=path):
        pytest.skip("a pre-commit executable sits next to git/sh; cannot hide it")
    env = _env(tmp_path, path)
    repo = _consumer(tmp_path, env, None)

    silent = _commit(repo, env, "a.txt", "feat: a")
    assert silent.returncode == 0, silent.stderr
    assert "warn:" not in silent.stderr

    (repo / ".pre-commit-config.yaml").write_text(OPT_IN + FORBIDDEN_FILE, encoding="utf-8", newline="\n")
    unchecked = _commit(repo, env, "forbidden.txt", "feat: b")
    assert unchecked.returncode == 0, unchecked.stderr
    for hook in SHIMS:
        assert unchecked.stderr.count(f"warn: {hook} hook skipped: pre-commit not found") == 1, unchecked.stderr


def test_installer_adds_missing_shims_and_keeps_existing_hooks(tmp_path: Path) -> None:
    shell_dir = _shell_dir()
    bash = shutil.which("bash", path=str(shell_dir)) if shell_dir else None
    if bash is None:
        pytest.skip("needs the bash git runs hooks with")
    env = _env(tmp_path, str(shell_dir) + os.pathsep + os.environ.get("PATH", ""))
    repo = tmp_path / "consumer"
    _init(repo, env)
    playbook_hooks = repo / ".ai-playbook" / "templates" / "new-project" / "scripts" / "git-hooks"
    playbook_hooks.mkdir(parents=True)
    for name in SHIMS:
        shutil.copyfile(HOOK_TEMPLATES / f"{name}.tmpl", playbook_hooks / f"{name}.tmpl")
    custom = repo / "scripts" / "git-hooks" / "commit-msg"
    custom.parent.mkdir(parents=True)
    custom.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
    shutil.copyfile(INSTALLER, repo / "scripts" / "install-playbook-hooks.sh")
    install = [bash, "scripts/install-playbook-hooks.sh"]

    first = _run(install, repo, env)
    assert first.returncode == 0, first.stderr
    assert _git(repo, env, "config", "--get", "core.hooksPath").stdout.strip() == "scripts/git-hooks"
    shim = repo / "scripts" / "git-hooks" / "pre-commit"
    assert shim.read_bytes() == (HOOK_TEMPLATES / "pre-commit.tmpl").read_bytes()
    if os.name == "posix":
        assert os.access(shim, os.X_OK)
    assert custom.read_text(encoding="utf-8") == "#!/bin/sh\nexit 0\n"
    assert "scripts/git-hooks/commit-msg is not the playbook shim" in first.stderr
    assert "replace 'pre-commit install'" in first.stdout

    again = _run(install, repo, env)
    assert again.returncode == 0, again.stderr
    assert "scripts/git-hooks/pre-commit runs pre-commit" in again.stdout
    assert shim.read_bytes() == (HOOK_TEMPLATES / "pre-commit.tmpl").read_bytes()


def test_fresh_bootstrap_ships_the_shims_verbatim(tmp_path: Path) -> None:
    bs.copy_templates(
        playbook_root=REPO_ROOT,
        target_dir=tmp_path,
        project_name="alpha",
        owner="a@b.c",
        playbook_pin="v0.0.0",
        dry_run=False,
    )
    for name in SHIMS:
        landed = tmp_path / "scripts" / "git-hooks" / name
        assert landed.read_bytes() == (HOOK_TEMPLATES / f"{name}.tmpl").read_bytes()
