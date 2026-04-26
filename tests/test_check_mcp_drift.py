"""Tests for scripts/check_mcp_drift.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import check_mcp_drift as cmd

# ---------------------------------------------------------------------------
# _load_yaml + schema detection
# ---------------------------------------------------------------------------


def _write(p: Path, content: str) -> None:
    p.write_text(content, encoding="utf-8")


def test_no_drift_when_one_file_absent(tmp_path: Path) -> None:
    """A consumer that ships only the v1 file (or only the legacy file) is fine."""
    only_v1 = tmp_path / "only-v1"
    only_v1.mkdir()
    _write(only_v1 / "mcp-servers.project.yaml", """\
schema: mcp-servers/v1
layer: project
servers:
  hindsight:
    transport: http
    endpoint: https://h.example/
""")
    findings, summary = cmd.detect_drift(only_v1)
    assert findings == []
    assert summary["legacy_present"] is False
    assert summary["project_present"] is True
    assert "single-file" in (summary["skipped_reason"] or "")


def test_no_drift_when_legacy_is_actually_v1(tmp_path: Path) -> None:
    """Both files declaring the v1 schema is structural drift itself — surfaced as skipped."""
    consumer = tmp_path / "both-v1"
    consumer.mkdir()
    body = """\
schema: mcp-servers/v1
layer: project
servers:
  hindsight: {transport: http, endpoint: https://h.example/}
"""
    _write(consumer / "mcp-servers.yaml", body)
    _write(consumer / "mcp-servers.project.yaml", body)

    findings, summary = cmd.detect_drift(consumer)
    assert findings == []
    assert summary["legacy_is_v1"] is True
    assert "both files declare" in (summary["skipped_reason"] or "")


def test_drift_detected_on_endpoint_mismatch(tmp_path: Path) -> None:
    consumer = tmp_path / "drift"
    consumer.mkdir()
    _write(consumer / "mcp-servers.yaml", """\
metadata: {version: 2}
servers:
  hindsight:
    transport: http
    url: https://OLD.example/path/
""")
    _write(consumer / "mcp-servers.project.yaml", """\
schema: mcp-servers/v1
layer: project
servers:
  hindsight:
    transport: http
    endpoint: https://NEW.example/
    auth: cf-access
    env:
      required: [HINDSIGHT_URL]
""")
    findings, summary = cmd.detect_drift(consumer)
    fields = {f.field for f in findings}
    assert "endpoint" in fields
    # `auth` and `env_required` are declared on only one side; should NOT flag.
    assert "auth" not in fields
    assert "env_required" not in fields


def test_drift_skipped_when_legacy_omits_field(tmp_path: Path) -> None:
    """If only one side declares a field, the other side has nothing to disagree with."""
    consumer = tmp_path / "asymmetric"
    consumer.mkdir()
    _write(consumer / "mcp-servers.yaml", """\
metadata: {version: 2}
servers:
  hindsight:
    transport: http
    url: https://h.example/
""")
    _write(consumer / "mcp-servers.project.yaml", """\
schema: mcp-servers/v1
layer: project
servers:
  hindsight:
    transport: http
    endpoint: https://h.example/
    auth: cf-access
    env:
      required: [HINDSIGHT_URL, CF_ACCESS_CLIENT_ID]
""")
    findings, _ = cmd.detect_drift(consumer)
    assert findings == []


def test_drift_skipped_when_server_only_in_v1(tmp_path: Path) -> None:
    """A v1 server not in the legacy file is "new", not drift."""
    consumer = tmp_path / "new-server"
    consumer.mkdir()
    _write(consumer / "mcp-servers.yaml", """\
metadata: {version: 2}
servers:
  hindsight:
    transport: http
    url: https://h.example/
""")
    _write(consumer / "mcp-servers.project.yaml", """\
schema: mcp-servers/v1
layer: project
servers:
  hindsight:
    transport: http
    endpoint: https://h.example/
  guardrails:
    transport: http
    endpoint: https://g.example/
""")
    findings, _ = cmd.detect_drift(consumer)
    assert findings == []


def test_drift_env_lists_compared_as_sets(tmp_path: Path) -> None:
    """Order in env lists doesn't matter; content does."""
    consumer = tmp_path / "env-order"
    consumer.mkdir()
    _write(consumer / "mcp-servers.yaml", """\
metadata: {version: 2}
servers:
  s:
    transport: http
    secrets_refs: [B, A]
""")
    _write(consumer / "mcp-servers.project.yaml", """\
schema: mcp-servers/v1
layer: project
servers:
  s:
    transport: http
    env: {required: [A, B]}
""")
    findings, _ = cmd.detect_drift(consumer)
    # Same set, different order = no drift.
    assert findings == []


# ---------------------------------------------------------------------------
# CLI exit codes
# ---------------------------------------------------------------------------


def test_cli_exits_zero_on_no_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    consumer = tmp_path / "clean"
    consumer.mkdir()
    body = """\
metadata: {version: 2}
servers:
  hindsight: {transport: http, url: https://h.example/}
"""
    _write(consumer / "mcp-servers.yaml", body)
    _write(consumer / "mcp-servers.project.yaml", """\
schema: mcp-servers/v1
layer: project
servers:
  hindsight: {transport: http, endpoint: https://h.example/}
""")
    rc = cmd.main(["--consumer-root", str(consumer)])
    assert rc == 0
    assert "no drift" in capsys.readouterr().out


def test_cli_exits_one_on_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    consumer = tmp_path / "dirty"
    consumer.mkdir()
    _write(consumer / "mcp-servers.yaml", """\
metadata: {version: 2}
servers:
  s: {transport: http, url: https://OLD/}
""")
    _write(consumer / "mcp-servers.project.yaml", """\
schema: mcp-servers/v1
layer: project
servers:
  s: {transport: http, endpoint: https://NEW/}
""")
    rc = cmd.main(["--consumer-root", str(consumer)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "❌" in err
    assert "endpoint" in err


def test_cli_json_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    import json as json_mod

    consumer = tmp_path / "json"
    consumer.mkdir()
    _write(consumer / "mcp-servers.yaml", """\
metadata: {version: 2}
servers:
  s: {transport: http, url: https://OLD/}
""")
    _write(consumer / "mcp-servers.project.yaml", """\
schema: mcp-servers/v1
layer: project
servers:
  s: {transport: http, endpoint: https://NEW/}
""")
    rc = cmd.main(["--consumer-root", str(consumer), "--json"])
    assert rc == 1
    payload = json_mod.loads(capsys.readouterr().out)
    assert payload["findings"]
    assert payload["findings"][0]["field"] == "endpoint"


def test_cli_break_glass_overrides_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    consumer = tmp_path / "override"
    consumer.mkdir()
    _write(consumer / "mcp-servers.yaml", """\
metadata: {version: 2}
servers:
  s: {transport: http, url: https://OLD/}
""")
    _write(consumer / "mcp-servers.project.yaml", """\
schema: mcp-servers/v1
layer: project
servers:
  s: {transport: http, endpoint: https://NEW/}
""")
    rc = cmd.main([
        "--consumer-root", str(consumer),
        "--force-with-reason", "intentional staging endpoint divergence",
    ])
    assert rc == 0
    err = capsys.readouterr().err
    assert "OVERRIDE APPLIED" in err
