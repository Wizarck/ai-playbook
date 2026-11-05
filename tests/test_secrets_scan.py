"""Tests for scripts/secrets_scan.py (T10).

Mock `shutil.which` and `subprocess.run` so tests never require gitleaks or a
real git repo. Secrets in fixtures are obvious synthetic strings — NEVER paste
real credentials into tests.
"""
from __future__ import annotations

import codecs
import io
import random
import re
import subprocess
import time
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
     "cfg OPENAI='sk-proj-" + "a1B2" * 10 + "'"),
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
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"", stderr=b"")
    monkeypatch.setattr(subprocess, "run", fake_run)
    rc = main(["--staged"])
    assert rc == 0


def test_staged_mode_uses_git_diff_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, list[str]] = {}

    def fake_run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        recorded["cmd"] = cmd
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(secrets_scan, "_gitleaks_available", lambda: False)
    rc = main(["--staged"])
    assert rc == 0
    cmd = recorded["cmd"]
    assert cmd[0] == "git" and cmd[cmd.index("diff") + 1] == "--cached"
    assert "-z" in cmd


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


# ---------------------------------------------------------------------------
# Regression: catalogue gaps (S1-58). Secrets are constructed at runtime so the
# repo's own gitleaks hook never sees a literal credential in this file.
# ---------------------------------------------------------------------------

_PEM_HEAD = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
_PEM_TAIL = "-----END " + "OPENSSH PRIVATE KEY-----"


@pytest.mark.parametrize("kind,sample", [
    ("openai_api_key", "OPENAI=sk-" + "proj-" + "Ab1_cD2-" * 6),
    ("openai_api_key", "sk-" + "svcacct-" + "Zz9_" * 12),
    ("github_pat", "github_" + "pat_" + "11AB" * 6 + "_" + "xY9z" * 15),
    ("aws_access_key", "id=" + "ASIA" + "Q" * 16),
    ("private_key", _PEM_HEAD + "\n" + "b3BlbnNzaC1rZXk" * 4 + "\n" + _PEM_TAIL),
    ("aws_secret_access_key",
     "aws_secret_access_key=" + "wJalrXUtnFEMI/K7MDENG/bPxRfiCY" + "0123456789"),
    ("generic_env_secret", "CF_ACCESS_CLIENT_SECRET=" + "a1b2c3d4" * 8),
    ("generic_env_secret", "HINDSIGHT_API_KEY=hs_" + "Ab12Cd34Ef56Gh78Ij90"),
])
def test_new_formats_fire(kind: str, sample: str) -> None:
    assert kind in {m.kind for m in scan(sample)}, sample


@pytest.mark.parametrize("sample", [
    "sk-proj-short",                                  # too short
    "see github_pat_ docs",                           # prefix only
    "TOKEN = getTokenFromEnvironment()",              # call, not a literal
    "API_KEY=${{ secrets.OPENAI_API_KEY }}",          # CI interpolation
    "API_KEY=changeme_your_secret_here_please",       # placeholder
    "SOME_TOKEN=lowercaseonlyvalueislongenough",      # single class
    "-----BEGIN PUBLIC KEY-----",                     # public key
    "AKIAshort",
])
def test_new_formats_do_not_fire_on_lookalikes(sample: str) -> None:
    assert scan(sample) == [], sample


# ---------------------------------------------------------------------------
# Regression: false positives from the widened catalogue (SS-1). The gate has
# no override, so each of these blocked an Edit/Write outright.
# ---------------------------------------------------------------------------

_PROJ = "sk-" + "proj-"


@pytest.mark.parametrize("sample", [
    # kebab-case words ending in "sk" (the mixed-case body isolates the boundary)
    '<div class="helpdesk-admin-panel-component-wrapper">',
    "[access](#how-to-ask-admin-for-access-to-the-repository)",
    "task-proj-Management-Dashboard-Widget-For-Portal-2024",
    # .env.example placeholders
    "OPENAI_API_KEY=" + _PROJ + "your-openai-api-key-here",
    "OPENAI_API_KEY=" + _PROJ + "YOUR-OPENAI-PROJECT-KEY-GOES-HERE-1234567890",
    "OPENAI_API_KEY=" + _PROJ + "X" * 48,
    # an empty value must not take the next line as its value
    "ANTHROPIC_API_KEY=\nCLAUDE_MODEL=claude-sonnet-4-6",
    "TELEGRAM_BOT_TOKEN=\n\nTELEGRAM_CHAT_ID=Ab12Cd34Ef56Gh78Ij90Kl",
    "API_KEY=\r\nOTHER_VALUE=Ab12Cd34Ef56Gh78Ij90Kl",
    "API_KEY:\n  nested_value_Ab12Cd34Ef56Gh78",
    "aws_secret_access_key =\n" + "wJalrXUtnFEMI/K7MDENG/bPxRfiCY" + "0123456789",
])
def test_widened_catalogue_lookalikes_do_not_fire(sample: str) -> None:
    assert scan(sample) == [], sample


@pytest.mark.parametrize("kind,sample", [
    ("openai_api_key", '{"apiKey": "' + _PROJ + "Ab1_cD2-" * 20 + '"}'),
    ("openai_api_key", 'client = OpenAI(api_key="' + _PROJ + "Ab1_cD2-" * 6 + '")'),
    ("openai_api_key", '"keys:\\n' + _PROJ + "Ab1_cD2-" * 6 + '"'),  # JSON-escaped line
    ("openai_api_key", "?key%3D" + _PROJ + "Ab1_cD2-" * 6),  # URL-encoded '='
    ("openai_api_key", "OPENAI_API_KEY=" + "sk-" + "A1b2C3d4" * 6),  # legacy format
    # a quoted value may still sit on the next line (YAML / wrapped JS)
    ("generic_env_secret", 'API_KEY:\n  "Ab12Cd34Ef56Gh78Ij90Kl"'),
    ("generic_env_secret", 'const STRIPE_SECRET_KEY =\n  "Ab12Cd34Ef56Gh78Ij90Kl";'),
    ("generic_env_secret", "DB_PASSWORD=Ab12Cd34Ef56Gh78Ij90Kl\r\nNEXT=1"),
    ("aws_secret_access_key",
     "aws_secret_access_key = " + "wJalrXUtnFEMI/K7MDENG/bPxRfiCY" + "0123456789\n"),
])
def test_widened_catalogue_still_fires_on_real_shapes(kind: str, sample: str) -> None:
    assert kind in {m.kind for m in scan(sample)}, sample


def test_private_key_sanitise_redacts_body() -> None:
    body = "b3BlbnNzaC1rZXktdjEAAAAA" * 3
    text = "before\n" + _PEM_HEAD + "\n" + body + "\n" + _PEM_TAIL + "\nafter"
    redacted, kinds = sanitise(text)
    assert kinds == ["private_key"]
    assert body not in redacted
    assert redacted.startswith("before\n") and redacted.endswith("\nafter")


# private_key needs key material (SS-1 c) and absorbs escaped / armored bodies
# so sanitise() redacts them (SS-4). The base64 lines are fake.
_PK_HEAD = "-----BEGIN " + "PRIVATE KEY-----"
_PK_TAIL = "-----END " + "PRIVATE KEY-----"
_PK_LINE = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDGb8IqRkE9Lkks"
_PK_LINE2 = "x9Kq2mZ7Lp4Wn8Rt" * 4
_BS_N = "\\" + "n"  # backslash + n, as inside a JSON / env string
_PGP_HEAD = "-----BEGIN PGP " + "PRIVATE KEY BLOCK-----"
_PGP_TAIL = "-----END PGP " + "PRIVATE KEY BLOCK-----"
_RSA_HEAD = "-----BEGIN RSA " + "PRIVATE KEY-----"
_RSA_TAIL = "-----END RSA " + "PRIVATE KEY-----"


@pytest.mark.parametrize("sample", [
    "it should contain TWO `" + _PK_HEAD + "`\nblocks.",
    "A key starts with " + _PK_HEAD + " and must never be committed.",
    'PEM_HEADER = "' + _PK_HEAD + '"\nPEM_FOOTER = "' + _PK_TAIL + '"',
    _PK_HEAD + "\nMIIE",
    _PK_HEAD + "\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC...\n" + _PK_TAIL,
    _PK_HEAD + "\n" + _PK_TAIL,
    _PK_HEAD + "\n" + "X" * 64 + "\n" + _PK_TAIL,
    _PK_HEAD + "\n<paste your private key here>\n" + _PK_TAIL,
    "regexes = ['''" + _PK_HEAD + "''', '''" + _RSA_HEAD + "''']",
    # joins and prefixes the key layouts below use, around no key material
    'HEADERS = ["' + _PK_HEAD + '", "' + _RSA_HEAD + '"]',
    'pem = "' + _PK_HEAD + _BS_N + '" + b64encode(der).decode() + "' + _BS_N + _PK_TAIL + '"',
    "# " + _PK_HEAD + "\n# (paste your key here)\n# " + _PK_TAIL,
    "> " + _PK_HEAD + "\n> ...\n> " + _PK_TAIL,
    "<pre>" + _PK_HEAD + "<br>&lt;your key&gt;<br>" + _PK_TAIL + "</pre>",
    'PEM_HEADER = "' + _PK_HEAD + '"  # first line of a PKCS8 file',
])
def test_private_key_header_without_key_material_does_not_fire(sample: str) -> None:
    assert scan(sample) == [], sample


@pytest.mark.parametrize("sample", [
    '    "' + _PK_HEAD + _BS_N + '"\n    "' + _PK_LINE + _BS_N + '"\n    "' + _PK_TAIL + '"',
    '{"private_key": "' + _PK_HEAD + _BS_N + _PK_LINE + _BS_N + _PK_TAIL + _BS_N + '"}',
    "key: |\n  " + _PK_HEAD + "\n  " + _PK_LINE + "\n  " + _PK_TAIL,
    _PK_HEAD + " " + _PK_LINE + " " + _PK_TAIL,
    '"' + _PK_HEAD + _BS_N + _PK_LINE[:30] + "\\/" + _PK_LINE[30:] + '"',  # PHP-escaped '/'
    _PGP_HEAD + "\nVersion: GnuPG v2\nComment: test key\n\nlQOYBF" + _PK_LINE2 + "\n" + _PGP_TAIL,
    _RSA_HEAD + "\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-128-CBC,9C2F0A1B\n\n" + _PK_LINE
    + "\n" + _RSA_TAIL,
])
def test_private_key_fires_on_key_material(sample: str) -> None:
    assert "private_key" in {m.kind for m in scan(sample)}, sample


@pytest.mark.parametrize("before,block,after", [
    ('{"private_key": "',
     _PK_HEAD + _BS_N + _PK_LINE + _BS_N + _PK_LINE2 + _BS_N + _PK_TAIL,
     _BS_N + '", "client_email": "svc@x.invalid"}'),
    ("key:\n",
     _PGP_HEAD + "\nComment: gpg\n\nlQOYBF" + _PK_LINE2 + "\n=Ab1C\n" + _PGP_TAIL,
     "\nnext line"),
    ("pem:\n",
     _RSA_HEAD + "\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-128-CBC,9C2F0A1B\n\n"
     + _PK_LINE + "\n" + _PK_LINE2 + "\n" + _RSA_TAIL,
     "\nend"),
    ('KEY = (\n    "',
     _PK_HEAD + _BS_N + '"\n    "' + _PK_LINE + _BS_N + '"\n    "' + _PK_LINE2 + _BS_N
     + '"\n    "' + _PK_TAIL,
     _BS_N + '"\n)'),
])
def test_private_key_sanitise_redacts_escaped_and_armored_bodies(
    before: str, block: str, after: str,
) -> None:
    redacted, kinds = sanitise(before + block + after)
    assert kinds == ["private_key"]
    assert redacted == before + "[REDACTED:private_key]" + after


# Regression: key lines joined by `+` / `.` / `,`, a backslash continuation, a
# `#` / `//` / `>` prefix or an encoded line break. The tip caught these by
# their BEGIN line alone; fe5024a's key-material rule missed them.
@pytest.mark.parametrize("before,block,after", [
    ('String k = "',
     _PK_HEAD + _BS_N + '" +\n    "' + _PK_LINE + _BS_N + '" +\n    "' + _PK_TAIL, '";'),
    ('k = "', _PK_HEAD + _BS_N + '"\n    + "' + _PK_LINE + _BS_N + '"\n    + "' + _PK_TAIL, '"'),
    ('$k = "', _PK_HEAD + _BS_N + '" .\n    "' + _PK_LINE + _BS_N + '" .\n    "' + _PK_TAIL, '";'),
    ('K = "\\n".join([\n    "', _PK_HEAD + '",\n    "' + _PK_LINE + '",\n    "' + _PK_TAIL,
     '",\n])'),
    ('K="', _PK_HEAD + "\\\n" + _PK_LINE + "\\\n" + _PK_TAIL, '"'),
    ("# ", _PK_HEAD + "\n# " + _PK_LINE + "\n# " + _PK_TAIL, "\nnext"),
    ("  // ", _PK_HEAD + "\n  // " + _PK_LINE + "\n  // " + _PK_TAIL, "\n}"),
    ("> ", _PK_HEAD + "\n> " + _PK_LINE + "\n> " + _PK_TAIL, "\n\ntext"),
    ('<add value="', _PK_HEAD + "&#10;" + _PK_LINE + "&#xD;&#xA;" + _PK_TAIL, '" />'),
    ('"', _PK_HEAD + "\\u000a" + _PK_LINE + "\\u000A" + _PK_TAIL, '"'),
    ("<p>", _PK_HEAD + "<br>" + _PK_LINE + "<br />" + _PK_TAIL, "</p>"),
], ids=["plus", "leading-plus", "php-dot", "list", "backslash-eol", "hash", "slashes",
        "quote", "xml-entity", "u000a", "br"])
def test_private_key_joined_or_prefixed_lines_are_caught_and_redacted(
    before: str, block: str, after: str,
) -> None:
    redacted, kinds = sanitise(before + block + after)
    assert kinds == ["private_key"]
    assert redacted == before + "[REDACTED:private_key]" + after


# Regression: names that follow `_`, a letter or a digit, or run past the name
# bound, were caught by v0.24.1 and missed by a6cd276's lookbehind (SS-2).
_ENV_VAL = "Ab12Cd34Ef56Gh78Ij90Kl"


@pytest.mark.parametrize("sample", [
    f'_API_KEY = "{_ENV_VAL}"',
    f'self._API_TOKEN = "{_ENV_VAL}"',
    f'app_SECRET_KEY = "{_ENV_VAL}"',
    f'__SECRET_KEY = "{_ENV_VAL}"',
    f'MyApp_API_KEY = "{_ENV_VAL}"',
    f'2FA_SECRET = "{_ENV_VAL}"',
    "X" * 70 + f'_TOKEN = "{_ENV_VAL}"',
    f"_API_KEY={_ENV_VAL}",
])
def test_generic_env_secret_fires_on_any_name_prefix(sample: str) -> None:
    assert "generic_env_secret" in {m.kind for m in scan(sample)}, sample
    assert _ENV_VAL not in sanitise(sample)[0]


def test_generic_env_secret_is_linear_on_long_uppercase_line() -> None:
    line = "ABCDEF0123456789" * 6000  # ~96 KB, no assignment
    t0 = time.perf_counter()
    scan(line)
    assert time.perf_counter() - t0 < 2.0


# Regression: a value that runs into a non-terminator made every NAME= start
# inside it rescan the run: 'AKEY=' * 8000 + ')' took ~2.9 s (SS-3).
@pytest.mark.parametrize("text", [
    "AKEY=" * 40000 + ")",
    "ABKEY=" * 40000 + ":",
    "A_KEY=" * 40000 + "(",
    "X_TOKEN=a1B2" * 20000 + ".",
], ids=["paren", "colon", "call", "dot"])  # short ids: PYTEST_CURRENT_TEST is an env var
def test_generic_env_secret_is_linear_on_chained_assignments(text: str) -> None:
    t0 = time.perf_counter()
    scan(text)
    assert time.perf_counter() - t0 < 2.0


def _reference_env_hits(text: str) -> list[tuple[int, int]]:
    """generic_env_secret hits from plain finditer with the terminator in-regex."""
    head = dict(secrets_scan._PATTERNS)["generic_env_secret"]
    full = re.compile(head.pattern + r"""(?=[\s'"]|\Z)['"]?""")
    return [
        (m.start(), m.end()) for m in full.finditer(text)
        if secrets_scan._looks_like_secret(m.group("val"))
    ]


_ENV_TOKENS = [
    "API_KEY", "AKEY", "X_TOKEN", "PASS", "SECRET", "B" * 70, "A", "Ab1", "zZ9", "x1" * 12,
    "_", "=", ":", " ", "\t", "\n", '"', "'", "(", ".", "-", "/", "+", _ENV_VAL,
]


def test_generic_env_secret_linear_scan_matches_plain_finditer() -> None:
    cases = [
        # a NAME that ends where an unterminated value ends must still be found
        "A_KEY=" + "x1" * 15 + 'API_KEY: "' + _ENV_VAL + '"',
        "A_KEY=" + "x1" * 500 + 'API_KEY: "' + _ENV_VAL + '"',
        "A_KEY=" + "x1" * 30 + "B" * 100 + '_KEY: "' + _ENV_VAL + '"',
    ]
    rng = random.Random(20261105)
    cases += ["".join(rng.choices(_ENV_TOKENS, k=40)) for _ in range(2000)]
    hits = 0
    for text in cases:
        got = [(m.start, m.end) for m in scan(text, kinds=["generic_env_secret"])]
        assert got == _reference_env_hits(text), text
        hits += bool(got)
    assert hits > 100  # the token mix must actually exercise matches


# ---------------------------------------------------------------------------
# Regression: sanitise() overlapping spans (S1-59)
# ---------------------------------------------------------------------------


def test_sanitise_overlapping_matches_keeps_trailing_text() -> None:
    pat = "ghp_" + "A1b2" * 10
    text = f'GITHUB_TOKEN="{pat}" then run the deploy script in staging'
    redacted, kinds = sanitise(text)
    assert redacted.endswith(" then run the deploy script in staging")
    assert "A1b2" not in redacted
    assert set(kinds) == {"generic_env_secret", "github_pat"}


def test_sanitise_nested_match_leaks_no_tail() -> None:
    text = 'API_TOKEN="AKIA' + "ABCDEFGHIJKLMNOP" + 'secretTail99" ok'
    redacted, _ = sanitise(text)
    assert redacted == "[REDACTED:generic_env_secret] ok"


# ---------------------------------------------------------------------------
# Regression: UTF-8 char split at the binary-sniff boundary (S1-60)
# ---------------------------------------------------------------------------


def test_multibyte_char_at_sample_boundary_is_still_scanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = tmp_path / "notes.md"
    f.write_bytes(b"a" * 2047 + "—".encode() + b" ghp_" + b"A" * 40 + b"\n")
    monkeypatch.setattr(secrets_scan, "_gitleaks_available", lambda: False)
    assert main([str(f)]) == 3


# ---------------------------------------------------------------------------
# Regression: UTF-16/32 (with BOM) and legacy 8-bit text were skipped as
# binary, so they were never scanned (SS-5)
# ---------------------------------------------------------------------------

_PAT_LINE = "GITHUB_TOKEN=ghp_" + "A" * 40 + "\n"
_NON_UTF8_TEXT = {
    # Windows PowerShell 5.1 `>` / Out-File
    "utf16le-bom": codecs.BOM_UTF16_LE + ("# notas\r\n" + _PAT_LINE).encode("utf-16-le"),
    "utf16be-bom": codecs.BOM_UTF16_BE + _PAT_LINE.encode("utf-16-be"),
    "utf32le-bom": codecs.BOM_UTF32_LE + _PAT_LINE.encode("utf-32-le"),
    # Windows PowerShell 5.1 Set-Content
    "cp1252": ("contraseña = segura\n" + _PAT_LINE).encode("cp1252"),
}


@pytest.mark.parametrize("data", _NON_UTF8_TEXT.values(), ids=_NON_UTF8_TEXT.keys())
def test_non_utf8_text_file_is_scanned(
    data: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = tmp_path / "notes.env"
    f.write_bytes(data)
    monkeypatch.setattr(secrets_scan, "_gitleaks_available", lambda: False)
    assert main([str(f)]) == 3


def test_control_bytes_without_nul_are_still_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = tmp_path / "blob.dat"
    f.write_bytes(b"\x01\x02\xff ghp_" + b"A" * 40 + b"\x03")
    monkeypatch.setattr(secrets_scan, "_gitleaks_available", lambda: False)
    assert main([str(f)]) == 0


# ---------------------------------------------------------------------------
# Regression: --staged scans the index, not the worktree (S1-61)
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd, check=True, capture_output=True,
    )


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _git(tmp_path, "init", "-q")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(secrets_scan, "_gitleaks_available", lambda: False)
    return tmp_path


def test_staged_scans_index_content_not_worktree(repo: Path) -> None:
    f = repo / "app.cfg"
    f.write_text("token ghp_" + "A" * 40 + "\n", encoding="utf-8")
    _git(repo, "add", "app.cfg")
    f.write_text("clean now\n", encoding="utf-8")  # unstaged edit hides it
    assert main(["--staged"]) == 3


@pytest.mark.parametrize("data", _NON_UTF8_TEXT.values(), ids=_NON_UTF8_TEXT.keys())
def test_staged_non_utf8_text_is_scanned(repo: Path, data: bytes) -> None:
    (repo / "notes.env").write_bytes(data)
    _git(repo, "add", "notes.env")
    assert main(["--staged"]) == 3


def test_staged_non_ascii_path_is_scanned(repo: Path) -> None:
    (repo / "café.env").write_text("ghp_" + "A" * 40 + "\n", encoding="utf-8")
    _git(repo, "add", "café.env")
    assert main(["--staged"]) == 3


def test_staged_from_subdirectory_is_scanned(
    repo: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sub = repo / "sub"
    sub.mkdir()
    (sub / "k.txt").write_text("ghp_" + "A" * 40 + "\n", encoding="utf-8")
    _git(repo, "add", "sub/k.txt")
    monkeypatch.chdir(sub)
    assert main(["--staged"]) == 3


def test_staged_outside_repo_is_setup_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert main(["--staged"]) == 2


# ---------------------------------------------------------------------------
# Regression: --staged leftovers (SS-6)
# ---------------------------------------------------------------------------


def _hash_blob(repo: Path, data: bytes) -> str:
    return subprocess.run(
        ["git", "hash-object", "-w", "--stdin"], cwd=repo, input=data,
        capture_output=True, check=True,
    ).stdout.decode().strip()


def test_staged_skips_submodule_pointers(repo: Path) -> None:
    # A submodule bump stages only a gitlink; its checkout (with the
    # playbook's own example keys) must not be walked or scanned.
    pointer = subprocess.run(
        ["git", "write-tree"], cwd=repo, capture_output=True, check=True,
    ).stdout.decode().strip()
    sub = repo / "vendor" / "lib"
    sub.mkdir(parents=True)
    (sub / "leak.py").write_text("token ghp_" + "A" * 40 + "\n", encoding="utf-8")
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{pointer},vendor/lib")
    assert main(["--staged"]) == 0
    (repo / "app.cfg").write_text("ghp_" + "A" * 40 + "\n", encoding="utf-8")
    _git(repo, "add", "app.cfg")
    assert main(["--staged"]) == 3


def test_staged_type_change_is_scanned(repo: Path) -> None:
    # A symlink replaced by a regular file is status T, not M.
    link = _hash_blob(repo, b"target.txt")
    _git(repo, "update-index", "--add", "--cacheinfo", f"120000,{link},cfg")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m", "link")
    secret = _hash_blob(repo, ("ghp_" + "A" * 40 + "\n").encode())
    _git(repo, "update-index", "--cacheinfo", f"100644,{secret},cfg")
    assert main(["--staged"]) == 3


def test_staged_ignores_diff_relative_setting(
    repo: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(repo, "config", "diff.relative", "true")  # temp repo's own config
    (repo / "top.env").write_text("ghp_" + "A" * 40 + "\n", encoding="utf-8")
    _git(repo, "add", "top.env")
    sub = repo / "sub"
    sub.mkdir()
    monkeypatch.chdir(sub)
    assert main(["--staged"]) == 3


def test_staged_reads_every_blob_through_one_cat_file(
    repo: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for i in range(5):
        (repo / f"f{i}.txt").write_text(f"line {i}\n", encoding="utf-8")
    (repo / "blob.bin").write_bytes(b"\x00\x01" * 4096)
    (repo / "k.env").write_text("ghp_" + "A" * 40 + "\n", encoding="utf-8")
    _git(repo, "add", ".")
    spawned: list[list[str]] = []
    real_popen = subprocess.Popen

    class SpyPopen(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            spawned.append(list(cmd))
            super().__init__(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", SpyPopen)
    assert main(["--staged"]) == 3
    assert sum("cat-file" in cmd for cmd in spawned) == 1


# ---------------------------------------------------------------------------
# Regression: gitleaks invocation failure is surfaced, not silent (finding 4)
# ---------------------------------------------------------------------------


def test_gitleaks_invocation_failure_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "ok.txt").write_text("clean", encoding="utf-8")
    monkeypatch.setattr(secrets_scan, "_gitleaks_available", lambda: True)

    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise OSError("exec format error")
    monkeypatch.setattr(subprocess, "run", boom)
    rc = main([str(tmp_path)])
    assert rc == 0  # gitleaks is advisory; the regex pass is the gate
    assert "gitleaks invocation failed" in capsys.readouterr().err
