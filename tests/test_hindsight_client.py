"""Tests for scripts/_hindsight.py — shared HTTP client."""
from __future__ import annotations

import io
import json
from urllib import error as urlerror

import pytest

from scripts import _hindsight as hs

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _resp(body: bytes, status: int = 200):
    class _R:
        def __init__(self, b: bytes, s: int) -> None:
            self._b = b
            self.status = s

        def read(self) -> bytes:
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    return _R(body, status)


def _patch(monkeypatch: pytest.MonkeyPatch, fake) -> None:
    monkeypatch.setattr(hs.urlrequest, "urlopen", fake)


# ---------------------------------------------------------------------------
# Credentials resolution
# ---------------------------------------------------------------------------


def test_load_credentials_cf_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HINDSIGHT_URL", "https://h.example/")
    monkeypatch.setenv("CF_ACCESS_CLIENT_ID", "cid")
    monkeypatch.setenv("CF_ACCESS_CLIENT_SECRET", "csec")
    monkeypatch.delenv("HINDSIGHT_API_KEY", raising=False)
    creds = hs.load_credentials()
    assert creds.url == "https://h.example"
    assert creds.auth_method == "cf-access"
    h = creds.headers()
    assert h["CF-Access-Client-Id"] == "cid"
    assert h["CF-Access-Client-Secret"] == "csec"
    assert "Authorization" not in h


def test_load_credentials_bearer_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HINDSIGHT_URL", "https://h.example/")
    monkeypatch.delenv("CF_ACCESS_CLIENT_ID", raising=False)
    monkeypatch.delenv("CF_ACCESS_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("HINDSIGHT_API_KEY", "sk-abc")
    creds = hs.load_credentials()
    assert creds.auth_method == "bearer"
    assert creds.headers()["Authorization"] == "Bearer sk-abc"


def test_load_credentials_missing_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HINDSIGHT_URL", raising=False)
    with pytest.raises(hs.HindsightUrlMissing):
        hs.load_credentials()


def test_load_credentials_missing_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HINDSIGHT_URL", "https://h.example/")
    monkeypatch.delenv("CF_ACCESS_CLIENT_ID", raising=False)
    monkeypatch.delenv("CF_ACCESS_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("HINDSIGHT_API_KEY", raising=False)
    with pytest.raises(hs.HindsightAuthMissing):
        hs.load_credentials()


def test_url_builders() -> None:
    creds = hs.HindsightCreds(url="https://h.example", api_key="k")
    assert hs.recall_url(creds, "acme-corp") == "https://h.example/v1/default/banks/acme-corp/memories/recall"
    assert hs.retain_url(creds, "acme-corp") == "https://h.example/v1/default/banks/acme-corp/memories"


# ---------------------------------------------------------------------------
# post_recall + post_retain HTTP behaviour
# ---------------------------------------------------------------------------


def test_post_recall_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _cap(req, timeout):  # noqa: ANN001
        captured["url"] = req.full_url
        captured["body"] = req.data
        captured["headers"] = dict(req.headers)
        return _resp(b'{"results":[{"text":"hi"}]}')

    _patch(monkeypatch, _cap)
    creds = hs.HindsightCreds(url="https://h.example", api_key="k")
    r = hs.post_recall(creds, "acme-corp", "test query", max_tokens=512)
    assert r.ok
    assert r.body == {"results": [{"text": "hi"}]}
    assert "memories/recall" in captured["url"]
    body = json.loads(captured["body"].decode("utf-8"))
    assert body == {"query": "test query", "max_tokens": 512}


def test_post_retain_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _cap(req, timeout):  # noqa: ANN001
        captured["url"] = req.full_url
        captured["body"] = req.data
        return _resp(b'{"success":true,"items_count":1}')

    _patch(monkeypatch, _cap)
    creds = hs.HindsightCreds(url="https://h.example", api_key="k")
    r = hs.post_retain(creds, "acme-corp", [{"content": "hello"}])
    assert r.ok
    assert r.body["items_count"] == 1
    assert captured["url"].endswith("/banks/acme-corp/memories")
    sent = json.loads(captured["body"].decode("utf-8"))
    assert sent == {"items": [{"content": "hello"}], "async": False}


def test_post_failure_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(req, timeout):  # noqa: ANN001
        raise urlerror.HTTPError("https://h.example", 500, "boom", {}, io.BytesIO(b"err-body"))

    _patch(monkeypatch, _boom)
    creds = hs.HindsightCreds(url="https://h.example", api_key="k")
    r = hs.post_recall(creds, "acme-corp", "q")
    assert not r.ok
    assert r.reason == "error:http-500"
    assert r.status == 500


def test_post_failure_url_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(req, timeout):  # noqa: ANN001
        raise urlerror.URLError("dns-failure")

    _patch(monkeypatch, _boom)
    creds = hs.HindsightCreds(url="https://h.example", api_key="k")
    r = hs.post_retain(creds, "acme-corp", [{"content": "x"}])
    assert not r.ok
    assert r.reason.startswith("degraded:url")


def test_post_failure_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(req, timeout):  # noqa: ANN001
        raise TimeoutError()

    _patch(monkeypatch, _boom)
    creds = hs.HindsightCreds(url="https://h.example", api_key="k")
    r = hs.post_recall(creds, "acme-corp", "q")
    assert not r.ok
    assert r.reason == "degraded:timeout"


def test_post_failure_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, lambda req, timeout: _resp(b"not-json"))
    creds = hs.HindsightCreds(url="https://h.example", api_key="k")
    r = hs.post_recall(creds, "acme-corp", "q")
    assert not r.ok
    assert r.reason == "error:malformed-json"


# ---------------------------------------------------------------------------
# OTel span emission — recall/retain open hindsight.* spans with bank+status
# ---------------------------------------------------------------------------


class _RecordingSpan:
    def __init__(self) -> None:
        self.attrs: dict[str, object] = {}

    def set_attribute(self, key: str, value: object) -> None:
        self.attrs[key] = value


def _install_recording_span(monkeypatch: pytest.MonkeyPatch) -> list:
    from contextlib import contextmanager

    import scripts.tracing.trace_emit as te
    captured: list = []

    @contextmanager
    def fake_span(name, attrs=None):
        rec = _RecordingSpan()
        captured.append((name, dict(attrs or {}), rec))
        yield rec

    monkeypatch.setattr(te, "span", fake_span)
    return captured


def test_post_recall_emits_span_with_entries_count(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, lambda req, timeout: _resp(b'{"results":[{"text":"a"},{"text":"b"}]}'))
    captured = _install_recording_span(monkeypatch)

    creds = hs.HindsightCreds(url="https://h.example", api_key="k")
    r = hs.post_recall(creds, "acme-corp", "q", max_tokens=2048)
    assert r.ok

    assert len(captured) == 1
    name, opening_attrs, rec = captured[0]
    assert name == "hindsight.recall"
    assert opening_attrs["ai_playbook.hindsight.bank_id"] == "acme-corp"
    assert opening_attrs["ai_playbook.hindsight.max_tokens"] == 2048
    assert opening_attrs["ai_playbook.hindsight.auth_method"] == "bearer"
    assert rec.attrs["ai_playbook.hindsight.ok"] is True
    assert rec.attrs["ai_playbook.hindsight.entries_count"] == 2
    assert rec.attrs["http.response.status_code"] == 200


def test_post_retain_emits_span_with_items_count(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, lambda req, timeout: _resp(b'{"ok":true}'))
    captured = _install_recording_span(monkeypatch)

    creds = hs.HindsightCreds(url="https://h.example", api_key="k")
    r = hs.post_retain(creds, "acme-corp", [{"content": "a"}, {"content": "b"}, {"content": "c"}])
    assert r.ok

    assert len(captured) == 1
    name, opening_attrs, rec = captured[0]
    assert name == "hindsight.retain"
    assert opening_attrs["ai_playbook.hindsight.items_count"] == 3
    assert opening_attrs["ai_playbook.hindsight.async"] is False
    assert rec.attrs["ai_playbook.hindsight.ok"] is True


def test_recall_span_records_failure_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(req, timeout):  # noqa: ANN001
        raise urlerror.HTTPError("https://h.example", 503, "down", {}, io.BytesIO(b""))

    _patch(monkeypatch, _boom)
    captured = _install_recording_span(monkeypatch)

    creds = hs.HindsightCreds(url="https://h.example", api_key="k")
    r = hs.post_recall(creds, "acme-corp", "q")
    assert not r.ok

    _, _, rec = captured[0]
    assert rec.attrs["ai_playbook.hindsight.ok"] is False
    assert rec.attrs["ai_playbook.hindsight.reason"] == "error:http-503"
    assert rec.attrs["http.response.status_code"] == 503
