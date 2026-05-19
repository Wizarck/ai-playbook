"""Tests for scripts/inject_context.py (T12).

Never hits a real Hindsight endpoint — urllib is patched at the module level.
Tests cover credential resolution, AGENTS.md introspection, render shape,
sanitisation integration, degraded-context path, and break-glass.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from urllib import error as urlerror

import pytest

from scripts import _hindsight as hs
from scripts import inject_context as ic

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


AGENTS_MD = """\
---
schema: agents-md/v1
version: 1.0.0
inherits_from:
  - github.com/Wizarck/ai-playbook@v0.1.0
updated: 2026-04-23
project: {project}
owner: owner@example.com
capabilities_map: false
{extra}
---

# body
"""


def _write_consumer(tmp_path: Path, *, project: str = "acme-shop", bank: str | None = None) -> Path:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    extra = f"bank_id: {bank}" if bank else ""
    (consumer / "AGENTS.md").write_text(
        AGENTS_MD.format(project=project, extra=extra),
        encoding="utf-8",
    )
    return consumer


def _fake_response(body: bytes, status: int = 200):
    """Return a context-manager-compatible fake urlopen response."""
    class _Resp:
        def __init__(self, data: bytes, status: int) -> None:
            self._data = data
            self.status = status

        def read(self) -> bytes:
            return self._data

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *a) -> None:
            return None

    return _Resp(body, status)


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, fake) -> None:
    """Patch the urlopen used inside scripts._hindsight (where the real call lives now)."""
    monkeypatch.setattr(hs.urlrequest, "urlopen", fake)


# ---------------------------------------------------------------------------
# AGENTS.md introspection
# ---------------------------------------------------------------------------


def test_resolve_project_from_agents_md_reads_slug(tmp_path: Path) -> None:
    consumer = _write_consumer(tmp_path, project="acme-shop")
    project, bank = ic._resolve_project_from_agents_md(consumer)
    assert project == "acme-shop"
    assert bank is None


def test_resolve_project_from_agents_md_reads_bank_override(tmp_path: Path) -> None:
    consumer = _write_consumer(tmp_path, project="acme", bank="acme-private")
    project, bank = ic._resolve_project_from_agents_md(consumer)
    assert project == "acme"
    assert bank == "acme-private"


def test_resolve_project_missing_agents_md(tmp_path: Path) -> None:
    project, bank = ic._resolve_project_from_agents_md(tmp_path)
    assert project is None
    assert bank is None


# ---------------------------------------------------------------------------
# recall() — HTTP normalisation
# ---------------------------------------------------------------------------


def test_recall_parses_results_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real Hindsight returns ``{results: [{type, text, occurred_start, document_id, ...}]}``."""
    payload = json.dumps({
        "results": [
            {"type": "lesson", "text": "prefer X over Y", "occurred_start": "2026-03-01",
             "document_id": "doc-1"},
            {"type": "gotcha", "text": "port 3101 in prod", "document_id": "doc-2"},
        ]
    }).encode("utf-8")
    _patch_urlopen(monkeypatch, lambda *a, **kw: _fake_response(payload))

    result = ic.recall(url="https://h.example/", api_key="k", bank_id="acme", query="q", top_k=3)

    assert result.ok is True
    assert result.reason == "ok"
    assert len(result.entries) == 2
    assert result.entries[0].kind == "lesson"
    assert result.entries[0].when == "2026-03-01"
    assert result.entries[0].trace_id == "doc-1"


def test_recall_accepts_bare_list(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps([
        {"type": "decision", "content": "use DDD"}
    ]).encode("utf-8")
    _patch_urlopen(monkeypatch, lambda *a, **kw: _fake_response(payload))
    result = ic.recall(url="https://h.example/", api_key="k", bank_id="acme", query="q")
    assert result.ok
    assert result.entries[0].text == "use DDD"


def test_recall_degraded_on_urlerror(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*a, **kw):
        raise urlerror.URLError("unreachable")

    _patch_urlopen(monkeypatch, _boom)
    result = ic.recall(url="https://h.example/", api_key="k", bank_id="acme", query="q")
    assert result.ok is False
    assert result.reason.startswith("degraded:url")


def test_recall_error_on_http_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*a, **kw):
        raise urlerror.HTTPError("https://h.example/", 500, "err", {}, io.BytesIO(b""))

    _patch_urlopen(monkeypatch, _boom)
    result = ic.recall(url="https://h.example/", api_key="k", bank_id="acme", query="q")
    assert result.ok is False
    assert result.reason == "error:http-500"


def test_recall_error_on_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, lambda *a, **kw: _fake_response(b"not-json"))
    result = ic.recall(url="https://h.example/", api_key="k", bank_id="acme", query="q")
    assert result.ok is False
    assert result.reason == "error:malformed-json"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_render_empty_entries_shows_friendly_message() -> None:
    result = ic.RecallResult(ok=True, entries=[], reason="ok")
    body = ic.render_injected_context(
        project="acme", bank_id="acme", query="q", result=result, sanitiser_active=False,
    )
    assert "# Injected context — acme" in body
    assert "No prior entries found" in body


def test_render_includes_entries_and_metadata() -> None:
    result = ic.RecallResult(
        ok=True,
        entries=[
            ic.RecallEntry(score=0.9, kind="lesson", text="use DDD", when="2026-03-01", trace_id="t1"),
        ],
        reason="ok",
    )
    body = ic.render_injected_context(
        project="acme", bank_id="acme", query="q", result=result, sanitiser_active=True,
    )
    assert "kind=`lesson`" in body
    assert "use DDD" in body
    assert "trace=`t1`" in body
    assert "REDACTED" in body or "sanitise" in body  # sanitiser banner present


def test_render_degraded_writes_banner() -> None:
    result = ic.RecallResult(ok=False, entries=[], reason="degraded:timeout")
    body = ic.render_injected_context(
        project="acme", bank_id="acme", query="q", result=result, sanitiser_active=False,
    )
    assert "DEGRADED_CONTEXT" in body
    assert "degraded:timeout" in body


def test_render_error_writes_banner() -> None:
    result = ic.RecallResult(ok=False, entries=[], reason="error:http-500")
    body = ic.render_injected_context(
        project="acme", bank_id="acme", query="q", result=result, sanitiser_active=False,
    )
    assert "CONTEXT_ERROR" in body
    assert "error:http-500" in body


# ---------------------------------------------------------------------------
# Sanitisation integration — confirms secrets_scan.sanitise is wired in
# ---------------------------------------------------------------------------


def test_sanitise_helper_redacts_github_pat() -> None:
    text = "run with token ghp_" + "A" * 40
    redacted, kinds = ic._sanitise(text)
    assert "[REDACTED:github_pat]" in redacted
    assert "github_pat" in kinds


def test_sanitise_helper_passthrough_on_clean_text() -> None:
    text = "nothing secret here"
    redacted, kinds = ic._sanitise(text)
    assert redacted == text
    assert kinds == []


# ---------------------------------------------------------------------------
# main() — full CLI paths
# ---------------------------------------------------------------------------


def test_main_missing_agents_md_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    # No AGENTS.md in tmp_path; no --project.
    rc = ic.main(["--consumer-root", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "cannot resolve project" in err


def test_main_missing_credentials_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("HINDSIGHT_URL", raising=False)
    monkeypatch.delenv("HINDSIGHT_API_KEY", raising=False)
    consumer = _write_consumer(tmp_path)
    rc = ic.main(["--consumer-root", str(consumer)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "Hindsight credentials missing" in err


def test_main_credentials_missing_with_force_writes_degraded_banner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("HINDSIGHT_URL", raising=False)
    monkeypatch.delenv("HINDSIGHT_API_KEY", raising=False)
    consumer = _write_consumer(tmp_path)
    rc = ic.main([
        "--consumer-root", str(consumer),
        "--force-with-reason", "bootstrapping before SOPS env is wired in",
    ])
    assert rc == 0
    out_path = consumer / ".claude" / "injected-context.md"
    assert out_path.is_file()
    body = out_path.read_text(encoding="utf-8")
    assert "DEGRADED_CONTEXT" in body


def test_main_happy_path_writes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HINDSIGHT_URL", "https://h.example/")
    monkeypatch.setenv("HINDSIGHT_API_KEY", "test-key")
    consumer = _write_consumer(tmp_path, project="acme")

    payload = json.dumps({
        "entries": [{"score": 0.8, "kind": "lesson", "text": "be careful with X"}]
    }).encode("utf-8")
    _patch_urlopen(monkeypatch, lambda *a, **kw: _fake_response(payload))

    rc = ic.main(["--consumer-root", str(consumer), "--top-k", "3"])
    assert rc == 0
    body = (consumer / ".claude" / "injected-context.md").read_text(encoding="utf-8")
    assert "acme" in body
    assert "be careful with X" in body


def test_main_dry_run_does_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HINDSIGHT_URL", "https://h.example/")
    monkeypatch.setenv("HINDSIGHT_API_KEY", "test-key")
    consumer = _write_consumer(tmp_path, project="acme")

    payload = json.dumps([{"score": 0.5, "kind": "gotcha", "text": "port 3101"}]).encode("utf-8")
    _patch_urlopen(monkeypatch, lambda *a, **kw: _fake_response(payload))

    rc = ic.main(["--consumer-root", str(consumer), "--dry-run"])
    assert rc == 0
    assert not (consumer / ".claude" / "injected-context.md").exists()
    out = capsys.readouterr().out
    assert "port 3101" in out


def test_main_degraded_hindsight_still_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HINDSIGHT_URL", "https://h.example/")
    monkeypatch.setenv("HINDSIGHT_API_KEY", "test-key")
    consumer = _write_consumer(tmp_path, project="acme")

    def _boom(*a, **kw):
        raise urlerror.URLError("unreachable")

    _patch_urlopen(monkeypatch, _boom)
    rc = ic.main(["--consumer-root", str(consumer)])
    assert rc == 0
    body = (consumer / ".claude" / "injected-context.md").read_text(encoding="utf-8")
    assert "DEGRADED_CONTEXT" in body


def test_main_successful_recall_drains_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """SessionStart hook: successful recall opportunistically drains the queue."""
    monkeypatch.setenv("HINDSIGHT_URL", "https://h.example/")
    monkeypatch.setenv("HINDSIGHT_API_KEY", "test-key")
    consumer = _write_consumer(tmp_path, project="acme")

    # Seed the queue with an item targeting the same bank (project slug = bank_id).
    queue = consumer / ".ai-playbook" / "hindsight-queue.jsonl"
    queue.parent.mkdir(parents=True)
    queue.write_text(
        json.dumps({"ts": "2026-04-24T00:00:00", "bank": "acme",
                    "item": {"content": "previously queued lesson"}}) + "\n",
        encoding="utf-8",
    )

    # urlopen handles BOTH POST /recall (returns entries) AND POST /retain (success).
    def _route(req, timeout):  # noqa: ANN001
        url = req.full_url
        if url.endswith("/recall"):
            return _fake_response(json.dumps(
                {"results": [{"type": "lesson", "text": "recalled"}]}
            ).encode("utf-8"))
        return _fake_response(b'{"success":true,"items_count":1}')

    _patch_urlopen(monkeypatch, _route)
    rc = ic.main(["--consumer-root", str(consumer)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "SessionStart drain: replayed 1 queued item(s)" in err
    # Queue is now empty.
    assert queue.read_text(encoding="utf-8") == ""


def test_main_degraded_recall_does_not_drain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """If recall fails, opportunistic drain does NOT fire — queue is preserved."""
    monkeypatch.setenv("HINDSIGHT_URL", "https://h.example/")
    monkeypatch.setenv("HINDSIGHT_API_KEY", "test-key")
    consumer = _write_consumer(tmp_path, project="acme")

    queue = consumer / ".ai-playbook" / "hindsight-queue.jsonl"
    queue.parent.mkdir(parents=True)
    original = (json.dumps({"ts": "2026-04-24T00:00:00", "bank": "acme",
                            "item": {"content": "untouched"}}) + "\n")
    queue.write_text(original, encoding="utf-8")

    def _boom(*a, **kw):
        raise urlerror.URLError("unreachable")

    _patch_urlopen(monkeypatch, _boom)
    rc = ic.main(["--consumer-root", str(consumer)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "SessionStart drain" not in err
    # Queue is preserved bit-for-bit.
    assert queue.read_text(encoding="utf-8") == original


def test_main_bank_id_override_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HINDSIGHT_URL", "https://h.example/")
    monkeypatch.setenv("HINDSIGHT_API_KEY", "k")
    consumer = _write_consumer(tmp_path, project="acme")

    captured: dict[str, object] = {}

    def _capture(req, timeout):  # noqa: ANN001
        captured["body"] = req.data
        captured["url"] = req.full_url
        return _fake_response(b'{"results":[]}')

    _patch_urlopen(monkeypatch, _capture)
    rc = ic.main(["--consumer-root", str(consumer), "--bank-id", "acme-personal"])
    assert rc == 0
    # Per the real Hindsight API the bank_id rides in the URL path, not the body.
    assert "/v1/default/banks/acme-personal/memories/recall" in captured["url"]
    sent = json.loads(captured["body"].decode("utf-8"))
    assert "query" in sent  # body still carries the recall query
    assert sent.get("max_tokens", 0) > 0
