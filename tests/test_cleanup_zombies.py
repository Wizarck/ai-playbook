"""Tests for scripts/rules/cleanup-zombies.rule.py.

Slice: add-cleanup-zombies-hook (v0.15.0).

Contracts:
- docs/rules/cleanup-zombies.rule.md (full contract)
- specs/zombies-manifest.yaml (manifest schema instance)
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "rules" / "cleanup-zombies.rule.py"
MANIFEST_PATH = REPO_ROOT / "specs" / "zombies-manifest.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_script(
    *args: str,
    manifest: Path | None = None,
    consumer_root: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT_PATH)]
    if manifest is not None:
        cmd += ["--manifest", str(manifest)]
    if consumer_root is not None:
        cmd += ["--consumer-root", str(consumer_root)]
    cmd += list(args)
    process_env = os.environ.copy()
    process_env["PYTHONIOENCODING"] = "utf-8"
    if env:
        process_env.update(env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        env=process_env,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _seed_consumer(tmp_path: Path) -> Path:
    """Create a fake consumer tree with `.ai-playbook/`."""
    consumer = tmp_path / "fake-consumer"
    (consumer / ".ai-playbook").mkdir(parents=True)
    # Make it a git repo so git ls-files etc. work
    subprocess.run(["git", "init", "--quiet"], cwd=str(consumer), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(consumer), check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(consumer), check=True)
    return consumer


def _write_manifest(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "manifest.yaml"
    data = {
        "version": 1,
        "manifest_version": "2026-05-19.1",
        "entries": entries,
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _base_entry(**overrides) -> dict:
    base = {
        "id": "test-entry",
        "tier": 1,
        "action": "delete",
        "safety": "check_gitmodules_first",
        "path": ".skills-sources",
        "introduced_in": "v0.4.0",
        "removed_in": "deprecation_only",
        "reason": "test",
        "evidence": "test",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Phase A — Manifest schema validation
# ---------------------------------------------------------------------------


def test_manifest_loads_with_required_top_level_keys(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path, [_base_entry()])
    result = _run_script("validate", manifest=manifest)
    assert result.returncode == 0, result.stderr


def test_entry_requires_id_path_tier_action_safety(tmp_path: Path) -> None:
    bad_entry = {"id": "x", "tier": 1}  # missing required fields
    manifest = _write_manifest(tmp_path, [bad_entry])
    result = _run_script("validate", manifest=manifest)
    assert result.returncode == 2
    assert "missing required keys" in result.stderr


def test_tier_must_be_1_2_or_3(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path, [_base_entry(tier=99)])
    result = _run_script("validate", manifest=manifest)
    assert result.returncode == 2
    assert "tier must be 1, 2, or 3" in result.stderr


def test_safety_must_be_known_name(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path, [_base_entry(safety="unknown_safety")])
    result = _run_script("validate", manifest=manifest)
    assert result.returncode == 2
    assert "unknown" in result.stderr


def test_tier2_entry_requires_rename_fields(tmp_path: Path) -> None:
    bad = _base_entry(tier=2, action="rename", safety="yaml_literal_rename")
    # Missing rename_from / rename_to / rename_in_files
    manifest = _write_manifest(tmp_path, [bad])
    result = _run_script("validate", manifest=manifest)
    assert result.returncode == 2
    assert "rename_from" in result.stderr


def test_rotate_entry_requires_rotation_days(tmp_path: Path) -> None:
    bad = _base_entry(action="rotate", safety="file_mtime_and_drained")
    manifest = _write_manifest(tmp_path, [bad])
    result = _run_script("validate", manifest=manifest)
    assert result.returncode == 2
    assert "rotation_days" in result.stderr


def test_manifest_version_must_match_pattern(tmp_path: Path) -> None:
    path = tmp_path / "m.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "manifest_version": "not-a-date",
                "entries": [_base_entry()],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    result = _run_script("validate", manifest=path)
    assert result.returncode == 2
    assert "manifest_version" in result.stderr


def test_shipped_manifest_validates() -> None:
    """The repo's own zombies-manifest.yaml must always validate."""
    result = _run_script("validate", manifest=MANIFEST_PATH)
    assert result.returncode == 0, result.stderr


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    entries = [_base_entry(), _base_entry()]  # same id
    manifest = _write_manifest(tmp_path, entries)
    result = _run_script("validate", manifest=manifest)
    assert result.returncode == 2
    assert "duplicate id" in result.stderr


# ---------------------------------------------------------------------------
# Phase B — Safety checks (each tested via end-to-end run)
# ---------------------------------------------------------------------------


def test_check_gitmodules_first_passes_when_path_absent_from_gitmodules(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    (consumer / ".skills-sources").mkdir()
    # No .gitmodules → orphan
    manifest = _write_manifest(tmp_path, [_base_entry()])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0
    assert not (consumer / ".skills-sources").exists(), "orphan directory should be deleted"


def test_check_gitmodules_first_blocks_when_path_present(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    (consumer / ".skills-sources").mkdir()
    (consumer / ".gitmodules").write_text(
        '[submodule ".skills-sources"]\n  path = .skills-sources\n  url = https://example.com/x.git\n',
        encoding="utf-8",
    )
    manifest = _write_manifest(tmp_path, [_base_entry()])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0
    assert (consumer / ".skills-sources").exists(), "registered submodule path must not be deleted"


@pytest.mark.parametrize(
    "gitmodules",
    [
        '[submodule ".skills-sources/ai-playbook"]\n\tpath = .skills-sources/ai-playbook\n\turl = https://example.com/x.git\n',
        '[submodule "ai"]\n\tpath = ".skills-sources/ai-playbook"\n\turl = https://example.com/x.git\n',
    ],
    ids=["nested", "quoted"],
)
def test_check_gitmodules_first_blocks_when_a_submodule_is_nested_under_target(
    tmp_path: Path, gitmodules: str
) -> None:
    """`.skills-sources` holding registered `.skills-sources/<repo>` submodules
    was deleted with every checkout: the guard matched only an exact
    `path = .skills-sources` line."""
    consumer = _seed_consumer(tmp_path)
    nested = consumer / ".skills-sources" / "ai-playbook"
    nested.mkdir(parents=True)
    (nested / "README.md").write_text("x", encoding="utf-8")
    (consumer / ".gitmodules").write_text(gitmodules, encoding="utf-8")
    manifest = _write_manifest(tmp_path, [_base_entry()])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0, result.stderr
    assert (nested / "README.md").is_file(), "a registered nested submodule was deleted"


def test_check_gitmodules_first_ignores_a_sibling_with_the_same_prefix(tmp_path: Path) -> None:
    """NEGATIVE CONTROL: `.skills-sources-old` is not under `.skills-sources`."""
    consumer = _seed_consumer(tmp_path)
    (consumer / ".skills-sources").mkdir()
    (consumer / ".gitmodules").write_text(
        '[submodule "old"]\n\tpath = .skills-sources-old\n\turl = https://example.com/x.git\n',
        encoding="utf-8",
    )
    manifest = _write_manifest(tmp_path, [_base_entry()])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0, result.stderr
    assert not (consumer / ".skills-sources").exists()


def _upstream(tmp_path: Path) -> Path:
    """A local repo with one commit, to add as a submodule."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    for args in (["init", "--quiet"], ["config", "user.email", "t@example.com"],
                 ["config", "user.name", "T"], ["commit", "--allow-empty", "-q", "-m", "init"]):
        subprocess.run(["git", *args], cwd=str(upstream), check=True)
    return upstream


def _add_submodule(consumer: Path, upstream: Path, path: str, *extra: str) -> None:
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "submodule", "add", "--quiet", *extra,
         str(upstream), path],
        cwd=str(consumer), check=True, capture_output=True,
    )


def _tree(path: Path) -> list[str]:
    """Every path under `path`, so a partial rmtree cannot pass as `is_dir()`."""
    return sorted(p.relative_to(path).as_posix() for p in path.rglob("*"))


def test_shipped_manifest_keeps_nested_submodules_and_their_git_dirs(tmp_path: Path) -> None:
    """A consumer with real `.skills-sources/<repo>` submodules keeps both the
    checkout and `.git/modules/.skills-sources/<repo>` under the shipped
    manifest's `--apply` (both skills-sources Tier 1 entries)."""
    consumer = _seed_consumer(tmp_path)
    _add_submodule(consumer, _upstream(tmp_path), ".skills-sources/ai-playbook")
    sources, modules = consumer / ".skills-sources", consumer / ".git" / "modules" / ".skills-sources"
    before = (_tree(sources), _tree(modules))
    assert "ai-playbook/.git" in before[0] and "ai-playbook/HEAD" in before[1]
    result = _run_script("--apply", manifest=MANIFEST_PATH, consumer_root=consumer)
    assert result.returncode == 0, result.stderr
    assert (_tree(sources), _tree(modules)) == before, "a nested submodule or its git dir lost files"


def test_shipped_manifest_keeps_the_git_dir_of_a_gitlink_without_a_gitmodules_entry(tmp_path: Path) -> None:
    """The index still holds `.skills-sources/<repo>` after its .gitmodules section
    went: its git dir under `.git/modules/.skills-sources` is live."""
    consumer = _seed_consumer(tmp_path)
    _add_submodule(consumer, _upstream(tmp_path), ".skills-sources/eligia-skills")
    subprocess.run(["git", "commit", "-q", "-m", "add"], cwd=str(consumer), check=True)
    subprocess.run(["git", "config", "-f", ".gitmodules", "--remove-section",
                    "submodule..skills-sources/eligia-skills"], cwd=str(consumer), check=True)
    modules = consumer / ".git" / "modules" / ".skills-sources"
    before = _tree(modules)
    result = _run_script("--apply", manifest=MANIFEST_PATH, consumer_root=consumer)
    assert result.returncode == 0, result.stderr
    assert _tree(modules) == before, "git dir of a tracked gitlink lost files"
    assert (consumer / ".skills-sources" / "eligia-skills" / ".git").is_file()


@pytest.mark.parametrize("name", ["x", "hooks", "info", "logs", "refs", "objects", "lfs"])
def test_directory_orphan_keeps_a_git_dir_whose_checkout_points_back(tmp_path: Path, name: str) -> None:
    """Neither registered nor tracked, but a kept checkout's `.git` still points
    at the git dir: deleting it would orphan that checkout and its commits. A
    submodule named like a git-internal directory is a git dir like any other."""
    consumer = _seed_consumer(tmp_path)
    _add_submodule(consumer, _upstream(tmp_path), "vendor/x", "--name", f".skills-sources/{name}")
    subprocess.run(["git", "rm", "-q", "--cached", "vendor/x"], cwd=str(consumer), check=True)
    (consumer / ".gitmodules").unlink()
    modules = consumer / ".git" / "modules" / ".skills-sources"
    before = _tree(modules)
    assert f"{name}/HEAD" in before
    manifest = _write_manifest(tmp_path, [_base_entry(
        id="skills-sources-git-modules-orphan", safety="directory_orphan",
        path=".git/modules/.skills-sources",
    )])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0, result.stderr
    assert _tree(modules) == before, "a git dir with a live checkout lost files"


def test_check_gitmodules_first_keeps_a_gitlink_without_a_gitmodules_entry(tmp_path: Path) -> None:
    """A gitlink still in the index is live even after `.gitmodules` lost it."""
    consumer = _seed_consumer(tmp_path)
    _add_submodule(consumer, _upstream(tmp_path), ".skills-sources")
    (consumer / ".gitmodules").unlink()
    manifest = _write_manifest(tmp_path, [_base_entry()])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0, result.stderr
    assert (consumer / ".skills-sources" / ".git").exists(), "a tracked gitlink was deleted"


def test_check_gitmodules_first_keeps_an_untracked_checkout(tmp_path: Path) -> None:
    """A repository under the target that nothing registers or tracks may still
    hold uncommitted work."""
    consumer = _seed_consumer(tmp_path)
    kept = consumer / ".skills-sources" / "kept"
    kept.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet"], cwd=str(kept), check=True)
    (kept / "WIP.txt").write_text("uncommitted", encoding="utf-8")
    manifest = _write_manifest(tmp_path, [_base_entry()])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0, result.stderr
    assert (kept / "WIP.txt").is_file(), "an untracked checkout was deleted"


@pytest.mark.parametrize("kind", ["directory", "malformed"])
def test_an_unusable_gitmodules_fails_closed(tmp_path: Path, kind: str) -> None:
    """A .gitmodules that cannot be read or that git rejects proves nothing orphan."""
    consumer = _seed_consumer(tmp_path)
    (consumer / ".skills-sources").mkdir()
    git_dir = consumer / ".git" / "modules" / ".skills-sources"
    git_dir.mkdir(parents=True)
    gitmodules = consumer / ".gitmodules"
    if kind == "directory":
        gitmodules.mkdir()
    else:
        gitmodules.write_text('[Submodule "x"]\n\tPath = .skills-sources/x\nnot valid config\n', encoding="utf-8")
    manifest = _write_manifest(tmp_path, [
        _base_entry(),
        _base_entry(id="skills-sources-git-modules-orphan", safety="directory_orphan",
                    path=".git/modules/.skills-sources"),
    ])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0, result.stderr
    assert (consumer / ".skills-sources").is_dir() and git_dir.is_dir()


@pytest.mark.skipif(sys.platform not in ("win32", "darwin"), reason="case-insensitive filesystem only")
def test_check_gitmodules_first_matches_a_tracked_gitlink_case_insensitively(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    _add_submodule(consumer, _upstream(tmp_path), ".Skills-Sources/eligia-skills")
    (consumer / ".gitmodules").unlink()
    manifest = _write_manifest(tmp_path, [_base_entry()])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0, result.stderr
    assert (consumer / ".Skills-Sources" / "eligia-skills" / ".git").is_file()


_GIT_MODULES_ENTRY = dict(
    id="skills-sources-git-modules-orphan", safety="directory_orphan", path=".git/modules/.skills-sources",
)


def test_directory_orphan_keeps_a_git_dir_with_a_live_linked_worktree(tmp_path: Path) -> None:
    """After the intended deinit + rm, a linked worktree of the submodule (with
    an unpushed branch) still lives in its git dir's `worktrees/`."""
    consumer = _seed_consumer(tmp_path)
    _add_submodule(consumer, _upstream(tmp_path), ".skills-sources/x")
    subprocess.run(["git", "commit", "-q", "-m", "add"], cwd=str(consumer), check=True)
    subprocess.run(["git", "worktree", "add", "-q", "-b", "feature", str(tmp_path / "wt")],
                   cwd=str(consumer / ".skills-sources" / "x"), check=True)
    for args in (["submodule", "deinit", "-f", "-q", ".skills-sources/x"], ["rm", "-q", "-f", ".skills-sources/x"],
                 ["commit", "-q", "-m", "drop"]):
        subprocess.run(["git", *args], cwd=str(consumer), check=True)
    modules = consumer / ".git" / "modules" / ".skills-sources"
    before = _tree(modules)
    manifest = _write_manifest(tmp_path, [_base_entry(**_GIT_MODULES_ENTRY)])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0, result.stderr
    assert _tree(modules) == before, "the git dir of a live linked worktree lost files"


def test_directory_orphan_keeps_the_git_dir_of_a_deinited_tracked_gitlink(tmp_path: Path) -> None:
    """deinit removed the checkout and core.worktree, and the .gitmodules section
    is gone, but the index still holds the gitlink: the git dir stays."""
    consumer = _seed_consumer(tmp_path)
    _add_submodule(consumer, _upstream(tmp_path), ".skills-sources/x")
    subprocess.run(["git", "commit", "-q", "-m", "add"], cwd=str(consumer), check=True)
    subprocess.run(["git", "submodule", "deinit", "-f", "-q", ".skills-sources/x"], cwd=str(consumer), check=True)
    subprocess.run(["git", "config", "-f", ".gitmodules", "--remove-section", "submodule..skills-sources/x"],
                   cwd=str(consumer), check=True)
    modules = consumer / ".git" / "modules" / ".skills-sources"
    before = _tree(modules)
    manifest = _write_manifest(tmp_path, [_base_entry(**_GIT_MODULES_ENTRY)])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0, result.stderr
    assert _tree(modules) == before, "the git dir of a tracked gitlink lost files"


def test_directory_orphan_keeps_a_git_dir_declared_without_a_path(tmp_path: Path) -> None:
    """A .gitmodules section with a url but no path still declares the name."""
    consumer = _seed_consumer(tmp_path)
    git_dir = consumer / ".git" / "modules" / ".skills-sources"
    git_dir.mkdir(parents=True)
    (consumer / ".gitmodules").write_text(
        '[submodule ".skills-sources"]\n\turl = https://example.com/x.git\n', encoding="utf-8"
    )
    manifest = _write_manifest(tmp_path, [_base_entry(**_GIT_MODULES_ENTRY)])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0, result.stderr
    assert git_dir.is_dir()


def test_directory_orphan_keeps_a_directory_holding_a_repository(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    nested = consumer / "stray-dir" / "nested"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet"], cwd=str(nested), check=True)
    manifest = _write_manifest(tmp_path, [_base_entry(id="stray", safety="directory_orphan", path="stray-dir")])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0, result.stderr
    assert (nested / ".git").is_dir()


def test_shipped_manifest_fully_deletes_a_removed_submodules_leftovers(tmp_path: Path) -> None:
    """NEGATIVE CONTROL with a real git dir: after deinit + rm the leftovers go,
    read-only git objects included (Windows refused those mid-way)."""
    consumer = _seed_consumer(tmp_path)
    _add_submodule(consumer, _upstream(tmp_path), ".skills-sources/x")
    subprocess.run(["git", "commit", "-q", "-m", "add"], cwd=str(consumer), check=True)
    for args in (["submodule", "deinit", "-f", "-q", ".skills-sources/x"], ["rm", "-q", "-f", ".skills-sources/x"],
                 ["commit", "-q", "-m", "drop"]):
        subprocess.run(["git", *args], cwd=str(consumer), check=True)
    modules = consumer / ".git" / "modules" / ".skills-sources"
    assert "x/HEAD" in _tree(modules)
    result = _run_script("--apply", manifest=MANIFEST_PATH, consumer_root=consumer)
    assert result.returncode == 0, result.stderr
    assert not modules.exists(), result.stdout
    assert not (consumer / ".skills-sources").exists()


def _link_dir(src: Path, link: Path) -> None:
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(src), str(link))
    else:
        os.symlink(src, link, target_is_directory=True)


def test_link_loops_inside_a_target_do_not_hang_and_outside_data_survives(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    inner = consumer / ".skills-sources" / "a"
    inner.mkdir(parents=True)
    _link_dir(inner, inner / "l1")
    _link_dir(inner, inner / "l2")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    _link_dir(outside, inner / "out")
    manifest = _write_manifest(tmp_path, [_base_entry()])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer, timeout=60)
    assert result.returncode == 0, result.stderr
    assert (outside / "keep.txt").is_file(), "data behind a link was deleted"


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX permissions as non-root")
def test_an_unlistable_directory_fails_closed(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    locked = consumer / ".skills-sources" / "locked"
    locked.mkdir(parents=True)
    locked.chmod(0)
    try:
        manifest = _write_manifest(tmp_path, [_base_entry()])
        result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    finally:
        locked.chmod(0o700)
    assert result.returncode == 0, result.stderr
    assert locked.is_dir(), "a directory that could not be inspected was deleted"


@pytest.mark.skipif(sys.platform not in ("win32", "darwin"), reason="case-insensitive filesystem only")
def test_case_insensitive_matches_for_tracked_files_and_git_dirs(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    tracked = consumer / ".Skills-Sources" / "readme.txt"
    tracked.parent.mkdir()
    tracked.write_text("tracked", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(consumer), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=str(consumer), check=True)
    kept = consumer / "stray-dir"
    kept.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=str(kept), check=True)
    os.rename(kept / ".git", kept / ".tmp-git")
    os.rename(kept / ".tmp-git", kept / ".GIT")
    manifest = _write_manifest(tmp_path, [
        _base_entry(),
        _base_entry(id="stray", safety="directory_orphan", path="stray-dir"),
    ])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0, result.stderr
    assert tracked.is_file(), "a tracked mixed-case path was deleted"
    assert (kept / ".GIT").is_dir(), "a checkout with an upper-case .GIT was deleted"


def test_directory_orphan_skips_when_files_tracked(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    target_dir = consumer / "tracked-dir"
    target_dir.mkdir()
    (target_dir / "file.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "tracked-dir/file.txt"], cwd=str(consumer), check=True)
    subprocess.run(["git", "commit", "-m", "seed", "--quiet"], cwd=str(consumer), check=True)
    manifest = _write_manifest(
        tmp_path,
        [_base_entry(id="orphan-test", safety="directory_orphan", path="tracked-dir")],
    )
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0
    assert target_dir.exists(), "tracked dir must NOT be deleted"


def test_directory_orphan_keeps_git_dir_of_an_active_submodule(tmp_path: Path) -> None:
    """`.git/modules/<name>` is never git-tracked, so the ls-files probe always
    passed and `--apply` deleted the git dir of a REGISTERED submodule,
    losing its unpushed commits."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    for args in (["init", "--quiet"], ["config", "user.email", "t@example.com"],
                 ["config", "user.name", "T"], ["commit", "--allow-empty", "-q", "-m", "init"]):
        subprocess.run(["git", *args], cwd=str(upstream), check=True)
    consumer = _seed_consumer(tmp_path)
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "submodule", "add", "--quiet",
         str(upstream), ".skills-sources"],
        cwd=str(consumer), check=True, capture_output=True,
    )
    git_dir = consumer / ".git" / "modules" / ".skills-sources"
    before = _tree(git_dir)
    assert "HEAD" in before
    manifest = _write_manifest(tmp_path, [_base_entry(
        id="skills-sources-git-modules-orphan", safety="directory_orphan",
        path=".git/modules/.skills-sources",
    )])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0, result.stderr
    assert _tree(git_dir) == before, "git dir of a registered submodule lost files"


def test_directory_orphan_deletes_git_dir_of_a_removed_submodule(tmp_path: Path) -> None:
    """NEGATIVE CONTROL: once .gitmodules no longer registers it, it is an orphan."""
    consumer = _seed_consumer(tmp_path)
    git_dir = consumer / ".git" / "modules" / ".skills-sources"
    git_dir.mkdir(parents=True)
    manifest = _write_manifest(tmp_path, [_base_entry(
        id="skills-sources-git-modules-orphan", safety="directory_orphan",
        path=".git/modules/.skills-sources",
    )])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0, result.stderr
    assert not git_dir.exists()


def test_file_mtime_and_drained_passes_when_old_and_drained(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    queue = consumer / ".ai-playbook" / "hindsight-queue.jsonl"
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue.write_text('{"state": "drained", "id": "x"}\n{"state": "drained", "id": "y"}\n', encoding="utf-8")
    # Backdate the file 60 days
    old_ts = (dt.datetime.now() - dt.timedelta(days=60)).timestamp()
    os.utime(queue, (old_ts, old_ts))
    manifest = _write_manifest(
        tmp_path,
        [_base_entry(
            id="hq-rotation",
            action="rotate",
            safety="file_mtime_and_drained",
            path=".ai-playbook/hindsight-queue.jsonl",
            rotation_days=30,
        )],
    )
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0
    # File should still exist (truncated) but an archive sibling should be present
    archives = list(consumer.glob(".ai-playbook/hindsight-queue.*.jsonl.archive"))
    assert archives, f"expected rotation archive; got: {list(consumer.glob('.ai-playbook/*'))}"


def test_file_mtime_and_drained_blocks_when_record_not_drained(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    queue = consumer / ".ai-playbook" / "hindsight-queue.jsonl"
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue.write_text('{"state": "queued", "id": "x"}\n', encoding="utf-8")
    old_ts = (dt.datetime.now() - dt.timedelta(days=60)).timestamp()
    os.utime(queue, (old_ts, old_ts))
    manifest = _write_manifest(
        tmp_path,
        [_base_entry(
            id="hq-rotation",
            action="rotate",
            safety="file_mtime_and_drained",
            path=".ai-playbook/hindsight-queue.jsonl",
            rotation_days=30,
        )],
    )
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0
    assert queue.exists(), "queue with non-drained records must not be rotated"


def test_yaml_literal_rename_renames_scalar_values(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    target = consumer / "mcp-servers.yaml"
    target.write_text("consumers:\n  - consumer-c-legacy\n  - other\n", encoding="utf-8")
    manifest = _write_manifest(
        tmp_path,
        [_base_entry(
            id="rename-test",
            tier=2,
            action="rename",
            safety="yaml_literal_rename",
            path="**/*.yaml",
            rename_from="consumer-c-legacy",
            rename_to="consumer-c",
            rename_in_files=["mcp-servers.yaml"],
        )],
    )
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0
    text = target.read_text(encoding="utf-8")
    assert "consumer-c-legacy" not in text
    assert "consumer-c" in text


def test_yaml_literal_rename_skips_invalid_yaml(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    target = consumer / "broken.yaml"
    target.write_text("not: valid: yaml: here:\n  -  : indent\n", encoding="utf-8")
    manifest = _write_manifest(
        tmp_path,
        [_base_entry(
            id="rename-test",
            tier=2,
            action="rename",
            safety="yaml_literal_rename",
            path="**/*.yaml",
            rename_from="consumer-c-legacy",
            rename_to="consumer-c",
            rename_in_files=["broken.yaml"],
        )],
    )
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0
    # File should be untouched
    assert "not: valid: yaml: here:" in target.read_text(encoding="utf-8")


def test_report_only_never_modifies(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    agents_md = consumer / "AGENTS.md"
    agents_md.write_text("---\nskills_sources:\n  - one\n---\n", encoding="utf-8")
    manifest = _write_manifest(
        tmp_path,
        [_base_entry(
            id="report-test",
            tier=3,
            action="report",
            safety="report_only",
            path="AGENTS.md",
        )],
    )
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0
    # File untouched
    assert "skills_sources" in agents_md.read_text(encoding="utf-8")
    # But report file written with advisory
    report = consumer / ".ai-playbook" / "zombie-report.md"
    assert report.is_file()
    assert "report-test" in report.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Phase C — Decision flow + channels
# ---------------------------------------------------------------------------


def test_default_is_dry_run(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    (consumer / ".skills-sources").mkdir()
    manifest = _write_manifest(tmp_path, [_base_entry()])
    result = _run_script(manifest=manifest, consumer_root=consumer)  # no --apply
    assert result.returncode == 0
    assert (consumer / ".skills-sources").exists(), "dry-run must not delete"


def test_report_file_written_on_non_empty_run(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    (consumer / ".skills-sources").mkdir()
    manifest = _write_manifest(tmp_path, [_base_entry()])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0
    report = consumer / ".ai-playbook" / "zombie-report.md"
    assert report.is_file()
    text = report.read_text(encoding="utf-8")
    assert "Playbook zombie cleanup" in text
    assert "2026-05-19.1" in text  # manifest_version


def test_report_file_removed_on_empty_run(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    # Pre-populate a stale report file
    report = consumer / ".ai-playbook" / "zombie-report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("stale", encoding="utf-8")
    # Manifest entry whose target is absent → no zombies
    manifest = _write_manifest(tmp_path, [_base_entry(path=".nonexistent-zombie-path")])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0
    assert not report.exists(), "empty run must remove stale report file"


def test_stdout_summary_format(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    (consumer / ".skills-sources").mkdir()
    manifest = _write_manifest(tmp_path, [_base_entry()])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0
    assert "cleanup_zombies" in result.stdout
    assert "deleted" in result.stdout


def test_quiet_suppresses_stdout(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    (consumer / ".skills-sources").mkdir()
    manifest = _write_manifest(tmp_path, [_base_entry()])
    result = _run_script("--apply", "--quiet", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0
    assert result.stdout == "", f"--quiet should suppress stdout; got: {result.stdout!r}"


def test_injected_context_appended_when_file_exists(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    (consumer / ".skills-sources").mkdir()
    ic_path = consumer / ".claude" / "injected-context.md"
    ic_path.parent.mkdir(parents=True, exist_ok=True)
    ic_path.write_text("# existing context\n", encoding="utf-8")
    manifest = _write_manifest(tmp_path, [_base_entry()])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0
    text = ic_path.read_text(encoding="utf-8")
    assert "# existing context" in text  # preserved
    assert "playbook-cleanup found pending items" in text


def test_injected_context_skipped_when_file_missing(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    (consumer / ".skills-sources").mkdir()
    # No .claude/injected-context.md
    manifest = _write_manifest(tmp_path, [_base_entry()])
    result = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result.returncode == 0
    assert not (consumer / ".claude" / "injected-context.md").exists()


def test_injected_context_not_duplicated_on_re_run(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    (consumer / ".skills-sources").mkdir()
    ic_path = consumer / ".claude" / "injected-context.md"
    ic_path.parent.mkdir(parents=True, exist_ok=True)
    ic_path.write_text("# context\n", encoding="utf-8")
    manifest = _write_manifest(tmp_path, [_base_entry()])
    # First run with the zombie present
    _run_script("--apply", manifest=manifest, consumer_root=consumer)
    # Second run: re-create the zombie so the report fires again
    (consumer / ".skills-sources").mkdir()
    _run_script("--apply", manifest=manifest, consumer_root=consumer)
    text_after_second = ic_path.read_text(encoding="utf-8")
    # The marker should appear exactly once even after a re-run
    assert text_after_second.count("playbook-cleanup found pending items") == 1


# ---------------------------------------------------------------------------
# Phase D — Exit-code policy + break-glass
# ---------------------------------------------------------------------------


def test_break_glass_env_skips_everything(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    (consumer / ".skills-sources").mkdir()
    manifest = _write_manifest(tmp_path, [_base_entry()])
    result = _run_script(
        "--apply",
        manifest=manifest,
        consumer_root=consumer,
        env={"AIPLAYBOOK_CLEANUP_SKIP": "1"},
    )
    assert result.returncode == 0
    assert (consumer / ".skills-sources").exists(), "break-glass must skip cleanup"
    assert "skipped via AIPLAYBOOK_CLEANUP_SKIP" in result.stderr


def test_missing_manifest_exits_zero(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    result = _run_script(manifest=tmp_path / "does-not-exist.yaml", consumer_root=consumer)
    assert result.returncode == 0
    assert "manifest missing" in result.stderr


def test_no_consumer_root_exits_zero(tmp_path: Path) -> None:
    # Run from a tmp dir with no .ai-playbook/ ancestor.
    # Use an explicit non-existent consumer-root override.
    result = _run_script(
        manifest=MANIFEST_PATH,
        consumer_root=tmp_path / "not-a-consumer-without-ai-playbook",
    )
    # The override path's first parent with .ai-playbook may still resolve to playbook
    # itself when invoked from script dir, so we instead verify exit 0.
    assert result.returncode == 0


def test_validate_subcommand_exits_two_on_bad_manifest(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("version: 99\nentries: []\n", encoding="utf-8")
    result = _run_script("validate", manifest=path)
    assert result.returncode == 2


def test_version_subcommand_prints_manifest_version(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path, [_base_entry()])
    result = _run_script("version", manifest=manifest)
    assert result.returncode == 0
    assert "2026-05-19.1" in result.stdout


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_re_run_with_no_zombies_is_no_op(tmp_path: Path) -> None:
    consumer = _seed_consumer(tmp_path)
    (consumer / ".skills-sources").mkdir()
    manifest = _write_manifest(tmp_path, [_base_entry()])
    # First run cleans the zombie
    result1 = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result1.returncode == 0
    # Second run: nothing to do
    result2 = _run_script("--apply", manifest=manifest, consumer_root=consumer)
    assert result2.returncode == 0
    assert result2.stdout == "", "no-zombies run must be silent"
    assert not (consumer / ".ai-playbook" / "zombie-report.md").exists()
