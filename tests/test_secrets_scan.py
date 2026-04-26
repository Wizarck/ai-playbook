"""Tests for scripts/secrets_scan.py (T10).

Mock `shutil.which` and `subprocess.run` so tests never require gitleaks or a
real git repo. Secrets in fixtures are obvious synthetic strings — NEVER paste
real credentials into tests.
"""
from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest

from scripts import secrets_scan
from scripts.secrets_scan import main, sanitise, scan

# ---------------------------------------------------------------------------
# Importable API — `scan` fires per pattern
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind,sample", [
    ("anthropic_api_key",
     "token=sk-ant-api03-" + "A" * 80),
    ("openai_api_key",
     "cfg OPENAI='sk-proj-" + "a" * 40 + "'"),
    ("github_pat",
     "token ghp_" + "A" * 40),
    ("aws_access_key",
     "aws_id=AKIAIOSFODNN7EXAMPLE"),
    ("aws_secret_access_key",
     'aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"'),
    ("jwt",
     "auth: eyJhbGciOiJIUzI1NiJ9." + "a" * 30 + "." + "b" * 30),
    ("langfuse_public_key",
     "pk-lf-" + "0" * 30),
    ("langfuse_secret_key",
     "sk-lf-" + "0" * 30),
])
def test_each_pattern_fires_on_canonical_example(kind: str, sample: str) -> None:
    matches = scan(sample)
    kinds = {m.kind for m in matches}
    assert kind in kinds, f"expected {kind} to fire on: {sample!r}, got {kinds}"


def test_generic_env_secret_fires_on_mixed_class_rhs() -> None:
    text = 'API_SECRET_KEY="Abcdefghij0123456789ZZZ"'
    kinds = {m.kind for m in scan(text)}
    assert "generic_env_secret" in kinds


def test_generic_env_secret_ignores_placeholders() -> None:
    text = 'API_SECRET_KEY="changeme_your_secret_here"'
    # length passes, but lowercased includes "changeme" → filtered out
    kinds = {m.kind for m in scan(text)}
    assert "generic_env_secret" not in kinds


def test_clean_text_has_no_matches() -> None:
    clean = "The quick brown fox jumps over 123 lazy dogs."
    assert scan(clean) == []


def test_line_numbers_are_1_indexed_and_accurate() -> None:
    text = "first line\nsecond line with ghp_" + "A" * 40 + "\nthird line\n"
    matches = scan(text)
    assert len(matches) == 1
    assert matches[0].kind == "github_pat"
    assert matches[0].line_no == 2


# ---------------------------------------------------------------------------
# Sanitise API
# ---------------------------------------------------------------------------


def test_sanitise_redacts_all_kinds_and_returns_sorted_kinds() -> None:
    text = (
        "api = sk-ant-" + "A" * 80 +
        "\nalso AKIAIOSFODNN7EXAMPLE"
    )
    redacted, kinds = sanitise(text)
    assert "[REDACTED:anthropic_api_key]" in redacted
    assert "[REDACTED:aws_access_key]" in redacted
    assert "sk-ant-" not in redacted
    assert "AKIA" not in redacted
    assert kinds == ["anthropic_api_key", "aws_access_key"]


def test_sanitise_clean_text_is_passthrough() -> None:
    text = "nothing secret here\n"
    redacted, kinds = sanitise(text)
    assert redacted == text
    assert kinds == []


# ---------------------------------------------------------------------------
# CLI — --text mode
# ---------------------------------------------------------------------------


def test_cli_text_mode_blocks_with_exit_3(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--text", "token ghp_" + "A" * 40])
    assert rc == 3
    err = capsys.readouterr().err
    assert "Secret-like pattern matched" in err
    assert "github_pat" in err
    assert "OVERRIDE: none" in err


def test_cli_text_mode_clean_exits_0() -> None:
    rc = main(["--text", "nothing to see here"])
    assert rc == 0


def test_cli_error_output_never_contains_raw_secret(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Error block names the kind + line, NEVER the secret value."""
    raw = "sk-ant-api03-" + "B" * 80
    rc = main(["--text", raw])
    assert rc == 3
    err = capsys.readouterr().err
    # The secret value itself must NOT appear in stderr.
    assert raw not in err
    assert "B" * 80 not in err


# ---------------------------------------------------------------------------
# CLI — --sanitise-for hindsight
# ---------------------------------------------------------------------------


def test_sanitise_for_hindsight_exits_0_and_redacts_on_stdin(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw = "log line with ghp_" + "A" * 40 + "\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))
    rc = main(["--sanitise-for", "hindsight"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "[REDACTED:github_pat]" in captured.out
    assert "ghp_" not in captured.out
    # Stderr warning lists redacted kinds.
    assert "github_pat" in captured.err


def test_sanitise_for_hindsight_clean_text_passthrough(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("nothing secret here\n"))
    rc = main(["--sanitise-for", "hindsight"])
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out == "nothing secret here\n"


def test_sanitise_for_hindsight_rejects_other_inputs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(["--sanitise-for", "hindsight", "--text", "foo"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "mutually exclusive" in err


# ---------------------------------------------------------------------------
# CLI — --staged (mocks git)
# ---------------------------------------------------------------------------


def test_staged_mode_empty_exits_0(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    rc = main(["--staged"])
    assert rc == 0


def test_staged_mode_uses_git_diff_cached(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    clean_file = tmp_path / "clean.txt"
    clean_file.write_text("nothing secret", encoding="utf-8")

    recorded: dict[str, list[str]] = {}

    def fake_run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        recorded["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=str(clean_file) + "\n", stderr="",
        )
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(secrets_scan, "_gitleaks_available", lambda: False)
    rc = main(["--staged"])
    assert rc == 0
    assert recorded["cmd"][:4] == ["git", "diff", "--cached", "--name-only"]


def test_staged_mutually_exclusive_with_paths(
    capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    rc = main(["--staged", str(tmp_path / "f.txt")])
    assert rc == 2
    err = capsys.readouterr().err
    assert "mutually exclusive" in err


# ---------------------------------------------------------------------------
# CLI — --force-with-reason is NOT accepted (argparse rejects)
# ---------------------------------------------------------------------------


def test_force_with_reason_flag_is_not_registered() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--text", "x", "--force-with-reason", "long enough reason here"])
    # argparse uses exit 2 for unknown-arg errors; that's fine — the point is
    # the flag is NOT accepted.
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# CLI — path scanning + directory walking
# ---------------------------------------------------------------------------


def test_scan_file_finds_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    f = tmp_path / "config.env"
    f.write_text("GITHUB_TOKEN=ghp_" + "A" * 40 + "\n", encoding="utf-8")
    monkeypatch.setattr(secrets_scan, "_gitleaks_available", lambda: False)
    rc = main([str(f)])
    assert rc == 3
    err = capsys.readouterr().err
    assert "github_pat" in err
    assert f.as_posix() in err


def test_scan_directory_recurses_and_skips_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good = tmp_path / "src" / "safe.py"
    good.parent.mkdir(parents=True)
    good.write_text("x = 1\n", encoding="utf-8")

    # Secret inside an ignored dir should NOT fire.
    bad_ignored = tmp_path / "node_modules" / "leaky.js"
    bad_ignored.parent.mkdir(parents=True)
    bad_ignored.write_text("const k = 'ghp_" + "A" * 40 + "';", encoding="utf-8")

    monkeypatch.setattr(secrets_scan, "_gitleaks_available", lambda: False)
    rc = main([str(tmp_path)])
    assert rc == 0


def test_scan_skips_binary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_file = tmp_path / "blob.bin"
    # Null byte → classified as binary, not scanned.
    bin_file.write_bytes(b"\x00\x01 ghp_" + b"A" * 40 + b" \x00")
    monkeypatch.setattr(secrets_scan, "_gitleaks_available", lambda: False)
    rc = main([str(tmp_path)])
    assert rc == 0


# ---------------------------------------------------------------------------
# Gitleaks integration
# ---------------------------------------------------------------------------


def test_gitleaks_missing_emits_info_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "ok.txt").write_text("clean", encoding="utf-8")
    monkeypatch.setattr(secrets_scan, "_gitleaks_available", lambda: False)
    rc = main([str(tmp_path)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "gitleaks not found" in err.lower()


def test_gitleaks_present_exit1_surfaces_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "ok.txt").write_text("clean", encoding="utf-8")
    monkeypatch.setattr(secrets_scan, "_gitleaks_available", lambda: True)
    monkeypatch.setattr(
        secrets_scan, "_run_gitleaks_on",
        lambda paths: (1, "leaks found"),
    )
    rc = main([str(tmp_path)])
    # No regex matches in the file, gitleaks surfaces a warning but doesn't
    # block by itself (our regex pass is the blocker — see spec).
    assert rc == 0
    err = capsys.readouterr().err
    assert "gitleaks reported" in err


def test_no_inputs_prints_help_and_exits_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "No inputs" in err or "usage:" in err


def test_stdin_dash_mode_reads_and_exits_3_on_match(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("token ghp_" + "A" * 40))
    rc = main(["-"])
    assert rc == 3
    err = capsys.readouterr().err
    assert "github_pat" in err
