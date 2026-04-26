"""Tests for scripts/verdict_lint.py. Populated in T09."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import verdict_lint as vl

# ---------------------------------------------------------------------------
# Shape: artifact — happy paths
# ---------------------------------------------------------------------------


def test_approved_verdict_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "review.md"
    p.write_text("# QA report\n\nAll good.\n\n✅ APPROVED\n", encoding="utf-8")
    rc = vl.lint_artifact(p, audit=False)
    assert rc == 0
    assert "verdict shape valid" in capsys.readouterr().out


def test_clarification_verdict_passes(tmp_path: Path) -> None:
    p = tmp_path / "review.md"
    p.write_text(
        "# QA report\n\n## Question for human\nSomething?\n\n❓ CLARIFICATION NEEDED\n",
        encoding="utf-8",
    )
    assert vl.lint_artifact(p, audit=False) == 0


def test_issues_found_with_valid_severities(tmp_path: Path) -> None:
    body = (
        "# QA report\n\n"
        "- [S1] null pointer on empty cart\n"
        "  Location: a.ts:1\n"
        "- [S3] rename helper\n"
        "  Location: b.ts:2\n\n"
        "⚠️ ISSUES FOUND (iter 1)\n"
    )
    p = tmp_path / "review.md"
    p.write_text(body, encoding="utf-8")
    assert vl.lint_artifact(p, audit=False) == 0


# ---------------------------------------------------------------------------
# Shape: artifact — failures
# ---------------------------------------------------------------------------


def test_missing_verdict_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = tmp_path / "review.md"
    p.write_text("# QA report\n\nNo verdict at the bottom.\n", encoding="utf-8")
    rc = vl.lint_artifact(p, audit=False)
    assert rc == 1
    err = capsys.readouterr().err
    assert "missing verdict line" in err
    assert "FIX:" in err
    assert "OVERRIDE: none" in err


def test_multiple_verdicts_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = tmp_path / "review.md"
    p.write_text(
        "# QA\n\n✅ APPROVED\n\nActually wait.\n\n❓ CLARIFICATION NEEDED\n",
        encoding="utf-8",
    )
    rc = vl.lint_artifact(p, audit=False)
    assert rc == 1
    assert "expected exactly 1" in capsys.readouterr().err


def test_issues_without_severity_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = tmp_path / "review.md"
    p.write_text(
        "# QA\n\n- Something bad\n  Location: x:1\n\n⚠️ ISSUES FOUND (iter 1)\n",
        encoding="utf-8",
    )
    rc = vl.lint_artifact(p, audit=False)
    assert rc == 1
    assert "no `[Sx]` findings" in capsys.readouterr().err


def test_s0_rejected_without_audit(tmp_path: Path) -> None:
    p = tmp_path / "review.md"
    p.write_text(
        "- [S0] retro annotation\n  Loc: x\n\n⚠️ ISSUES FOUND (iter 1)\n",
        encoding="utf-8",
    )
    assert vl.lint_artifact(p, audit=False) == 1


def test_s0_allowed_with_audit(tmp_path: Path) -> None:
    p = tmp_path / "review.md"
    p.write_text(
        "- [S0] retro annotation\n  Loc: x\n\n⚠️ ISSUES FOUND (iter 1)\n",
        encoding="utf-8",
    )
    assert vl.lint_artifact(p, audit=True) == 0


def test_artifact_file_not_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = vl.lint_artifact(tmp_path / "missing.md", audit=False)
    assert rc == 1
    assert "artefact not found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Shape: error
# ---------------------------------------------------------------------------


def test_error_shape_valid() -> None:
    text = (
        "❌ foo broke at file.py:1\n"
        "   FIX: run the fix command.\n"
        "   OVERRIDE: none\n"
    )
    assert vl.lint_error_shape_text(text, "<stdin>") == 0


def test_error_shape_missing_fix(capsys: pytest.CaptureFixture[str]) -> None:
    text = "❌ foo broke at file.py:1\n   OVERRIDE: none\n"
    rc = vl.lint_error_shape_text(text, "<stdin>")
    assert rc == 1
    err = capsys.readouterr().err
    assert "FIX" in err


def test_error_shape_bad_override(capsys: pytest.CaptureFixture[str]) -> None:
    text = (
        "❌ foo broke at file.py:1\n"
        "   FIX: do the thing.\n"
        "   OVERRIDE: maybe\n"
    )
    rc = vl.lint_error_shape_text(text, "<stdin>")
    assert rc == 1
    assert "OVERRIDE" in capsys.readouterr().err


def test_error_shape_multiple_headers(capsys: pytest.CaptureFixture[str]) -> None:
    text = (
        "❌ first error at a:1\n   FIX: x\n   OVERRIDE: none\n"
        "❌ second error at b:2\n   FIX: y\n   OVERRIDE: none\n"
    )
    rc = vl.lint_error_shape_text(text, "<stdin>")
    assert rc == 1
    assert "exactly one" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Break-glass is refused (OVERRIDE: none)
# ---------------------------------------------------------------------------


def test_force_with_reason_refused(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        vl.main([
            "dummy.md",
            "--force-with-reason=legitimate-sounding reason longer than ten chars",
        ])
    assert excinfo.value.code == 3
    err = capsys.readouterr().err
    assert "OVERRIDE: none" in err


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def test_main_artifact_no_paths_fails(capsys: pytest.CaptureFixture[str]) -> None:
    rc = vl.main(["--shape", "artifact"])
    assert rc == 1
    assert "no artefact path" in capsys.readouterr().err


def test_main_script_cli_shape_warns_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = vl.main(["--shape", "script-cli"])
    assert rc == 0
    assert "placeholder" in capsys.readouterr().err


def test_main_artifact_end_to_end(tmp_path: Path) -> None:
    p = tmp_path / "review.md"
    p.write_text("# review\n\n✅ APPROVED\n", encoding="utf-8")
    rc = vl.main([str(p), "--shape", "artifact"])
    assert rc == 0
