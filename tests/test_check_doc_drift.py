"""Tests for `scripts/check_doc_drift.py`.

Slice: doc-drift-enforcement (v0.16.0).

Strategy
--------
Each test seeds a temporary manifest (and optionally a temp repo root) under
`tmp_path`, invokes the script as a subprocess with `--manifest`, `--repo-root`,
and `--diff-files` overrides, and asserts exit code + stderr/stdout content per
the canonical WHY/FIX/OVERRIDE shape (per `docs/rules/error-message-standard.rule.md`).

Subprocess invocation (rather than direct import) matches the CI contract: the
script is executed as a CLI in GitHub Actions, so tests exercise the same path.

Contracts:
- docs/rules/doc-drift-enforcement.rule.md (full)
- specs/co-edit-pairs.yaml (canonical manifest schema)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_doc_drift.py"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_manifest(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _valid_manifest(extra_pairs: str = "") -> str:
    body = (
        'version: "1.0.0"\n'
        'manifest_version: "2026-05-19.1"\n'
        "pairs:\n"
        "  - id: pair-a\n"
        "    tier: 1\n"
        '    code: "scripts/foo.py"\n'
        '    doc: "specs/foo.md"\n'
        '    reason: "foo pair."\n'
        '    introduced_in: "v0.16.0"\n'
    )
    if extra_pairs:
        body += extra_pairs
    return body


def _run(
    *args: str,
    manifest: Path | None = None,
    repo_root: Path | None = None,
    diff_files: list[str] | None = None,
    pr_title: str | None = None,
    extra: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd: list[str] = [sys.executable, str(SCRIPT)]
    if manifest is not None:
        cmd += ["--manifest", str(manifest)]
    if repo_root is not None:
        cmd += ["--repo-root", str(repo_root)]
    cmd += list(args)
    if pr_title is not None:
        cmd += ["--pr-title", pr_title]
    if diff_files is not None:
        cmd += ["--diff-files", *diff_files]
    if extra:
        cmd += extra
    env = os.environ.copy()
    # Tests do not need to inherit parent's override env.
    env.pop("AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE", None)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
    )


# ---------------------------------------------------------------------------
# Schema validation (exit 2)
# ---------------------------------------------------------------------------


def test_validate_passes_on_canonical_manifest(tmp_path: Path) -> None:
    m = _write_manifest(tmp_path / "co-edit-pairs.yaml", _valid_manifest())
    proc = _run("validate", manifest=m, repo_root=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "manifest valid" in proc.stdout


def test_validate_fails_on_missing_top_level_key(tmp_path: Path) -> None:
    body = 'version: "1.0.0"\npairs: []\n'  # missing manifest_version
    m = _write_manifest(tmp_path / "m.yaml", body)
    proc = _run("validate", manifest=m, repo_root=tmp_path)
    assert proc.returncode == 2
    assert "manifest_version" in proc.stderr


def test_validate_fails_on_unsupported_schema_version(tmp_path: Path) -> None:
    body = (
        'version: "9.9.9"\n'
        'manifest_version: "2026-05-19.1"\n'
        'pairs:\n'
        '  - id: x\n    tier: 1\n    code: "a"\n    doc: "b"\n    reason: "r"\n    introduced_in: "v0.16.0"\n'
    )
    m = _write_manifest(tmp_path / "m.yaml", body)
    proc = _run("validate", manifest=m, repo_root=tmp_path)
    assert proc.returncode == 2
    assert "unsupported schema version" in proc.stderr


def test_validate_fails_on_bad_manifest_version_format(tmp_path: Path) -> None:
    body = (
        'version: "1.0.0"\n'
        'manifest_version: "v1.0"\n'  # wrong format
        'pairs:\n'
        '  - id: x\n    tier: 1\n    code: "a"\n    doc: "b"\n    reason: "r"\n    introduced_in: "v0.16.0"\n'
    )
    m = _write_manifest(tmp_path / "m.yaml", body)
    proc = _run("validate", manifest=m, repo_root=tmp_path)
    assert proc.returncode == 2
    assert "manifest_version" in proc.stderr


def test_validate_fails_on_missing_pair_field(tmp_path: Path) -> None:
    body = (
        'version: "1.0.0"\n'
        'manifest_version: "2026-05-19.1"\n'
        'pairs:\n'
        '  - id: x\n    tier: 1\n    code: "a"\n    reason: "r"\n    introduced_in: "v0.16.0"\n'
        # missing `doc:`
    )
    m = _write_manifest(tmp_path / "m.yaml", body)
    proc = _run("validate", manifest=m, repo_root=tmp_path)
    assert proc.returncode == 2
    assert "missing required field `doc`" in proc.stderr


def test_validate_fails_on_invalid_tier(tmp_path: Path) -> None:
    body = (
        'version: "1.0.0"\n'
        'manifest_version: "2026-05-19.1"\n'
        'pairs:\n'
        '  - id: xpair\n    tier: 5\n    code: "a"\n    doc: "b"\n    reason: "r"\n    introduced_in: "v0.16.0"\n'
    )
    m = _write_manifest(tmp_path / "m.yaml", body)
    proc = _run("validate", manifest=m, repo_root=tmp_path)
    assert proc.returncode == 2
    assert "tier" in proc.stderr.lower()


def test_validate_fails_on_bad_pair_id(tmp_path: Path) -> None:
    body = (
        'version: "1.0.0"\n'
        'manifest_version: "2026-05-19.1"\n'
        'pairs:\n'
        '  - id: "Bad_Id_Here"\n'
        '    tier: 1\n    code: "a"\n    doc: "b"\n'
        '    reason: "r"\n    introduced_in: "v0.16.0"\n'
    )
    m = _write_manifest(tmp_path / "m.yaml", body)
    proc = _run("validate", manifest=m, repo_root=tmp_path)
    assert proc.returncode == 2
    assert "does not match" in proc.stderr


def test_validate_fails_on_duplicate_pair_id(tmp_path: Path) -> None:
    body = (
        'version: "1.0.0"\n'
        'manifest_version: "2026-05-19.1"\n'
        'pairs:\n'
        '  - id: xpair\n    tier: 1\n    code: "a"\n    doc: "b"\n    reason: "r"\n    introduced_in: "v0.16.0"\n'
        '  - id: xpair\n    tier: 1\n    code: "c"\n    doc: "d"\n    reason: "r"\n    introduced_in: "v0.16.0"\n'
    )
    m = _write_manifest(tmp_path / "m.yaml", body)
    proc = _run("validate", manifest=m, repo_root=tmp_path)
    assert proc.returncode == 2
    assert "duplicate" in proc.stderr.lower()


def test_validate_fails_when_code_equals_doc(tmp_path: Path) -> None:
    body = (
        'version: "1.0.0"\n'
        'manifest_version: "2026-05-19.1"\n'
        'pairs:\n'
        '  - id: xpair\n    tier: 1\n    code: "same"\n    doc: "same"\n    reason: "r"\n    introduced_in: "v0.16.0"\n'
    )
    m = _write_manifest(tmp_path / "m.yaml", body)
    proc = _run("validate", manifest=m, repo_root=tmp_path)
    assert proc.returncode == 2
    assert "identical" in proc.stderr.lower()


def test_validate_fails_on_malformed_yaml(tmp_path: Path) -> None:
    body = "version: 1.0.0\npairs: [unclosed\n"
    m = _write_manifest(tmp_path / "m.yaml", body)
    proc = _run("validate", manifest=m, repo_root=tmp_path)
    assert proc.returncode == 2
    assert "parse error" in proc.stderr.lower() or "yaml" in proc.stderr.lower()


def test_validate_fails_when_manifest_missing(tmp_path: Path) -> None:
    m = tmp_path / "does-not-exist.yaml"
    proc = _run("validate", manifest=m, repo_root=tmp_path)
    assert proc.returncode == 2
    assert "manifest not found" in proc.stderr


# ---------------------------------------------------------------------------
# Drift detection (exit 0 / 1)
# ---------------------------------------------------------------------------


def test_check_no_changes_returns_zero(tmp_path: Path) -> None:
    m = _write_manifest(tmp_path / "m.yaml", _valid_manifest())
    proc = _run(manifest=m, repo_root=tmp_path, diff_files=[])
    assert proc.returncode == 0, proc.stderr
    assert "no files changed" in proc.stdout.lower()


def test_check_unknown_file_outside_any_pair_returns_zero(tmp_path: Path) -> None:
    m = _write_manifest(tmp_path / "m.yaml", _valid_manifest())
    proc = _run(manifest=m, repo_root=tmp_path, diff_files=["random/file.txt", "README.md"])
    assert proc.returncode == 0, proc.stderr


def test_check_code_touched_doc_not_returns_one(tmp_path: Path) -> None:
    m = _write_manifest(tmp_path / "m.yaml", _valid_manifest())
    proc = _run(manifest=m, repo_root=tmp_path, diff_files=["scripts/foo.py"])
    assert proc.returncode == 1
    assert "Doc-drift violation" in proc.stderr
    assert "pair-a" in proc.stderr
    assert "specs/foo.md" in proc.stderr


def test_check_doc_touched_code_not_returns_one(tmp_path: Path) -> None:
    m = _write_manifest(tmp_path / "m.yaml", _valid_manifest())
    proc = _run(manifest=m, repo_root=tmp_path, diff_files=["specs/foo.md"])
    assert proc.returncode == 1
    assert "pair-a" in proc.stderr
    assert "scripts/foo.py" in proc.stderr


def test_check_both_sides_touched_returns_zero(tmp_path: Path) -> None:
    m = _write_manifest(tmp_path / "m.yaml", _valid_manifest())
    proc = _run(manifest=m, repo_root=tmp_path, diff_files=["scripts/foo.py", "specs/foo.md"])
    assert proc.returncode == 0, proc.stderr


def test_check_glob_pattern_matches_multiple_files(tmp_path: Path) -> None:
    extra = (
        "  - id: globby\n"
        "    tier: 1\n"
        '    code: "scripts/rules/*.rule.py"\n'
        '    doc: "docs/rules/*.rule.md"\n'
        '    reason: "rule pattern."\n'
        '    introduced_in: "v0.16.0"\n'
    )
    m = _write_manifest(tmp_path / "m.yaml", _valid_manifest(extra))
    # Only code side touched (two files match the glob)
    proc = _run(
        manifest=m,
        repo_root=tmp_path,
        diff_files=["scripts/rules/alpha.rule.py", "scripts/rules/beta.rule.py"],
    )
    assert proc.returncode == 1
    assert "globby" in proc.stderr


def test_check_glob_pattern_clean_when_both_sides_touched(tmp_path: Path) -> None:
    extra = (
        "  - id: globby\n"
        "    tier: 1\n"
        '    code: "scripts/rules/*.rule.py"\n'
        '    doc: "docs/rules/*.rule.md"\n'
        '    reason: "rule pattern."\n'
        '    introduced_in: "v0.16.0"\n'
    )
    m = _write_manifest(tmp_path / "m.yaml", _valid_manifest(extra))
    proc = _run(
        manifest=m,
        repo_root=tmp_path,
        diff_files=["scripts/rules/alpha.rule.py", "docs/rules/alpha.rule.md"],
    )
    assert proc.returncode == 0, proc.stderr


def test_check_multi_pair_violation_lists_all(tmp_path: Path) -> None:
    extra = (
        "  - id: pair-b\n"
        "    tier: 1\n"
        '    code: "scripts/bar.py"\n'
        '    doc: "specs/bar.md"\n'
        '    reason: "bar pair."\n'
        '    introduced_in: "v0.16.0"\n'
    )
    m = _write_manifest(tmp_path / "m.yaml", _valid_manifest(extra))
    proc = _run(manifest=m, repo_root=tmp_path, diff_files=["scripts/foo.py", "scripts/bar.py"])
    assert proc.returncode == 1
    assert "pair-a" in proc.stderr
    assert "pair-b" in proc.stderr
    assert "2 pair(s)" in proc.stderr


def test_check_tier_2_pair_does_not_block(tmp_path: Path) -> None:
    """Tier 2 is reserved (soft / warn). v0.16.0 enforces ONLY Tier 1."""
    body = (
        'version: "1.0.0"\n'
        'manifest_version: "2026-05-19.1"\n'
        'pairs:\n'
        '  - id: soft\n'
        '    tier: 2\n    code: "scripts/soft.py"\n    doc: "specs/soft.md"\n'
        '    reason: "soft."\n    introduced_in: "v0.17.0"\n'
    )
    m = _write_manifest(tmp_path / "m.yaml", body)
    proc = _run(manifest=m, repo_root=tmp_path, diff_files=["scripts/soft.py"])
    assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# Escape hatch (exit 0 even on drift)
# ---------------------------------------------------------------------------


def test_escape_hatch_in_pr_title_bypasses_drift(tmp_path: Path) -> None:
    m = _write_manifest(tmp_path / "m.yaml", _valid_manifest())
    proc = _run(
        manifest=m,
        repo_root=tmp_path,
        diff_files=["scripts/foo.py"],
        pr_title="chore: rename var [no-doc-impact]",
    )
    assert proc.returncode == 0, proc.stderr
    assert "allowing" in proc.stderr.lower()


def test_escape_hatch_case_insensitive(tmp_path: Path) -> None:
    m = _write_manifest(tmp_path / "m.yaml", _valid_manifest())
    proc = _run(
        manifest=m,
        repo_root=tmp_path,
        diff_files=["scripts/foo.py"],
        pr_title="WIP [NO-DOC-IMPACT] lint cleanup",
    )
    assert proc.returncode == 0, proc.stderr


def test_escape_hatch_without_brackets_does_not_bypass(tmp_path: Path) -> None:
    """The exact bracketed token is required; bare phrase does not bypass."""
    m = _write_manifest(tmp_path / "m.yaml", _valid_manifest())
    proc = _run(
        manifest=m,
        repo_root=tmp_path,
        diff_files=["scripts/foo.py"],
        pr_title="chore: no doc impact lint cleanup",  # missing brackets
    )
    assert proc.returncode == 1, proc.stderr


def test_escape_hatch_empty_title_does_not_bypass(tmp_path: Path) -> None:
    m = _write_manifest(tmp_path / "m.yaml", _valid_manifest())
    proc = _run(
        manifest=m,
        repo_root=tmp_path,
        diff_files=["scripts/foo.py"],
        pr_title="",
    )
    assert proc.returncode == 1, proc.stderr


def test_escape_hatch_with_clean_diff_still_returns_zero(tmp_path: Path) -> None:
    """Escape hatch should not flip a clean diff into a failure."""
    m = _write_manifest(tmp_path / "m.yaml", _valid_manifest())
    proc = _run(
        manifest=m,
        repo_root=tmp_path,
        diff_files=["scripts/foo.py", "specs/foo.md"],
        pr_title="chore [no-doc-impact]",
    )
    assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# Real-manifest smoke (the actual specs/co-edit-pairs.yaml)
# ---------------------------------------------------------------------------


def test_real_manifest_validates() -> None:
    """The shipped `specs/co-edit-pairs.yaml` is schema-valid."""
    proc = _run("validate")
    assert proc.returncode == 0, proc.stderr


def test_real_manifest_synthetic_drift_probe() -> None:
    """Touching `scripts/rules/cleanup-zombies.rule.py` alone must fail against the real manifest."""
    proc = _run(diff_files=["scripts/rules/cleanup-zombies.rule.py"])
    assert proc.returncode == 1
    assert "cleanup-zombies" in proc.stderr


def test_real_manifest_escape_hatch_probe() -> None:
    """Same probe with escape hatch in PR title exits 0."""
    proc = _run(
        diff_files=["scripts/rules/cleanup-zombies.rule.py"],
        pr_title="release: bump [no-doc-impact]",
    )
    assert proc.returncode == 0
