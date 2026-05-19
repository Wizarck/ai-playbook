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

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "cleanup_zombies.py"
MANIFEST_PATH = REPO_ROOT / "specs" / "zombies-manifest.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_script(
    *args: str,
    manifest: Path | None = None,
    consumer_root: Path | None = None,
    env: dict[str, str] | None = None,
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
