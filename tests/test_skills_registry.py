"""Tests for scripts/skills_registry.py (T20).

Mocks urllib at the module level; no real HTTP to eligia-skills.palafitofood.com.
Covers env-var resolution, list/show happy paths, malformed response, timeout,
HTTP 5xx, unreachable, --force-with-reason degradation, --scope propagation,
--json output, and importable helpers.
"""
from __future__ import annotations

import io
import json
from urllib import error as urlerror

import pytest

from scripts import skills_registry as sr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


SAMPLE_PAYLOAD = {
    "skills": [
        {
            "name": "bmad-code-review",
            "description": "3-layer parallel code review",
            "source": "ai-playbook/.claude/skills/bmad-code-review/SKILL.md",
            "version": "1.0.0",
            "scope": "public",
        },
        {
            "name": "openspec-propose",
            "description": "Propose a new OpenSpec change",
            "source": "ai-playbook/.claude/skills/openspec-propose/SKILL.md",
            "version": "0.2.0",
            "scope": "public",
        },
    ],
    "fetched_at": "2026-04-23T12:00:00Z",
}


def _fake_response(body: bytes):
    """Context-manager-compatible fake urlopen response."""

    class _Resp:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def read(self) -> bytes:
            return self._data

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *a) -> None:
            return None

    return _Resp(body)


def _encoded(payload: object) -> bytes:
    return json.dumps(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# Env-var resolution
# ---------------------------------------------------------------------------


def test_load_credentials_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKILLS_REGISTRY_URL", "https://skills.example/")
    monkeypatch.setenv("SKILLS_REGISTRY_API_KEY", "tok")
    url, key = sr._load_credentials()
    assert url == "https://skills.example/"
    assert key == "tok"


def test_load_credentials_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SKILLS_REGISTRY_URL", raising=False)
    monkeypatch.delenv("SKILLS_REGISTRY_API_KEY", raising=False)
    url, key = sr._load_credentials()
    assert url is None
    assert key is None


# ---------------------------------------------------------------------------
# _fetch — HTTP normalisation
# ---------------------------------------------------------------------------


def test_fetch_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sr.urlrequest, "urlopen", lambda *a, **kw: _fake_response(_encoded(SAMPLE_PAYLOAD))
    )
    result = sr._fetch(
        url="https://skills.example", path="/api/v1/skills",
        api_key=None, query="", timeout=1.0,
    )
    assert result.ok is True
    assert result.reason == "ok"
    assert len(result.skills) == 2
    assert result.fetched_at == "2026-04-23T12:00:00Z"


def test_fetch_degraded_on_url_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*a, **kw):
        raise urlerror.URLError("unreachable")

    monkeypatch.setattr(sr.urlrequest, "urlopen", _boom)
    result = sr._fetch(
        url="https://skills.example", path="/api/v1/skills",
        api_key=None, query="", timeout=1.0,
    )
    assert result.ok is False
    assert result.reason.startswith("degraded:url")


def test_fetch_error_on_http_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*a, **kw):
        raise urlerror.HTTPError(
            "https://skills.example", 500, "err", {}, io.BytesIO(b""),
        )

    monkeypatch.setattr(sr.urlrequest, "urlopen", _boom)
    result = sr._fetch(
        url="https://skills.example", path="/api/v1/skills",
        api_key=None, query="", timeout=1.0,
    )
    assert result.ok is False
    assert result.reason == "error:http-500"


def test_fetch_error_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*a, **kw):
        raise TimeoutError("slow")

    monkeypatch.setattr(sr.urlrequest, "urlopen", _boom)
    result = sr._fetch(
        url="https://skills.example", path="/api/v1/skills",
        api_key=None, query="", timeout=0.1,
    )
    assert result.ok is False
    assert result.reason == "degraded:timeout"


def test_fetch_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sr.urlrequest, "urlopen", lambda *a, **kw: _fake_response(b"not-json")
    )
    result = sr._fetch(
        url="https://skills.example", path="/api/v1/skills",
        api_key=None, query="", timeout=1.0,
    )
    assert result.ok is False
    assert result.reason == "error:malformed-json"


def test_fetch_rejects_envelope_without_skills_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sr.urlrequest, "urlopen",
        lambda *a, **kw: _fake_response(_encoded({"other": []})),
    )
    result = sr._fetch(
        url="https://skills.example", path="/api/v1/skills",
        api_key=None, query="", timeout=1.0,
    )
    assert result.ok is False
    assert result.reason == "error:unexpected-shape"


def test_fetch_sends_bearer_when_api_key_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _capture(req, timeout):  # noqa: ANN001
        captured["headers"] = dict(req.header_items())
        captured["url"] = req.full_url
        return _fake_response(_encoded(SAMPLE_PAYLOAD))

    monkeypatch.setattr(sr.urlrequest, "urlopen", _capture)
    sr._fetch(
        url="https://skills.example", path="/api/v1/skills",
        api_key="secret-tok", query="scope=public", timeout=1.0,
    )
    # urllib normalises header names to title-case.
    header_names = {k.lower(): v for k, v in captured["headers"].items()}  # type: ignore[union-attr]
    assert header_names.get("authorization") == "Bearer secret-tok"
    assert "scope=public" in captured["url"]  # type: ignore[operator]


# ---------------------------------------------------------------------------
# Importable API
# ---------------------------------------------------------------------------


def test_list_skills_importable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sr.urlrequest, "urlopen", lambda *a, **kw: _fake_response(_encoded(SAMPLE_PAYLOAD))
    )
    entries = sr.list_skills(url="https://skills.example")
    assert len(entries) == 2
    assert entries[0]["name"] == "bmad-code-review"


def test_list_skills_raises_without_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SKILLS_REGISTRY_URL", raising=False)
    with pytest.raises(RuntimeError):
        sr.list_skills()


def test_skill_by_name_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sr.urlrequest, "urlopen", lambda *a, **kw: _fake_response(_encoded(SAMPLE_PAYLOAD))
    )
    entry = sr.skill_by_name("openspec-propose", url="https://skills.example")
    assert entry is not None
    assert entry["version"] == "0.2.0"


def test_skill_by_name_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sr.urlrequest, "urlopen", lambda *a, **kw: _fake_response(_encoded(SAMPLE_PAYLOAD))
    )
    entry = sr.skill_by_name("does-not-exist", url="https://skills.example")
    assert entry is None


# ---------------------------------------------------------------------------
# CLI — list
# ---------------------------------------------------------------------------


def test_cli_list_happy_path_human_table(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SKILLS_REGISTRY_URL", "https://skills.example")
    monkeypatch.setattr(
        sr.urlrequest, "urlopen", lambda *a, **kw: _fake_response(_encoded(SAMPLE_PAYLOAD))
    )
    rc = sr.main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "bmad-code-review" in out
    assert "openspec-propose" in out
    assert "fetched_at" in out


def test_cli_list_json_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SKILLS_REGISTRY_URL", "https://skills.example")
    monkeypatch.setattr(
        sr.urlrequest, "urlopen", lambda *a, **kw: _fake_response(_encoded(SAMPLE_PAYLOAD))
    )
    rc = sr.main(["list", "--json"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert parsed[0]["name"] == "bmad-code-review"


def test_cli_list_empty_scope(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SKILLS_REGISTRY_URL", "https://skills.example")
    empty = {"skills": [], "fetched_at": "2026-04-23T12:00:00Z"}
    monkeypatch.setattr(
        sr.urlrequest, "urlopen", lambda *a, **kw: _fake_response(_encoded(empty))
    )
    rc = sr.main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "(no skills in scope)" in out


def test_cli_list_scope_param_in_query(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SKILLS_REGISTRY_URL", "https://skills.example")
    captured: dict[str, str] = {}

    def _capture(req, timeout):  # noqa: ANN001
        captured["url"] = req.full_url
        return _fake_response(_encoded(SAMPLE_PAYLOAD))

    monkeypatch.setattr(sr.urlrequest, "urlopen", _capture)
    rc = sr.main(["list", "--scope", "palafito-b2b"])
    assert rc == 0
    assert "scope=palafito-b2b" in captured["url"]


def test_cli_list_missing_url_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SKILLS_REGISTRY_URL", raising=False)
    monkeypatch.delenv("SKILLS_REGISTRY_API_KEY", raising=False)
    rc = sr.main(["list"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "SKILLS_REGISTRY_URL not set" in err


def test_cli_list_unreachable_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SKILLS_REGISTRY_URL", "https://skills.example")

    def _boom(*a, **kw):
        raise urlerror.URLError("unreachable")

    monkeypatch.setattr(sr.urlrequest, "urlopen", _boom)
    rc = sr.main(["list"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "skills registry unreachable" in err


def test_cli_list_force_with_reason_degrades_when_unreachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SKILLS_REGISTRY_URL", "https://skills.example")

    def _boom(*a, **kw):
        raise urlerror.URLError("unreachable")

    monkeypatch.setattr(sr.urlrequest, "urlopen", _boom)
    rc = sr.main([
        "list", "--json",
        "--force-with-reason", "bootstrapping before registry is deployed",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "OVERRIDE APPLIED" in captured.err
    assert json.loads(captured.out.strip()) == []


def test_cli_list_force_with_reason_degrades_when_url_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SKILLS_REGISTRY_URL", raising=False)
    monkeypatch.delenv("SKILLS_REGISTRY_API_KEY", raising=False)
    rc = sr.main([
        "list", "--json",
        "--force-with-reason", "offline dev environment, no SOPS yet",
    ])
    assert rc == 0
    assert json.loads(capsys.readouterr().out.strip()) == []


def test_cli_list_malformed_response_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SKILLS_REGISTRY_URL", "https://skills.example")
    monkeypatch.setattr(
        sr.urlrequest, "urlopen", lambda *a, **kw: _fake_response(b"not-json")
    )
    rc = sr.main(["list"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "skills registry response invalid" in err


def test_cli_list_http_500_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SKILLS_REGISTRY_URL", "https://skills.example")

    def _boom(*a, **kw):
        raise urlerror.HTTPError(
            "https://skills.example", 500, "err", {}, io.BytesIO(b""),
        )

    monkeypatch.setattr(sr.urlrequest, "urlopen", _boom)
    rc = sr.main(["list"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "error:http-500" in err


# ---------------------------------------------------------------------------
# CLI — show
# ---------------------------------------------------------------------------


def test_cli_show_found(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SKILLS_REGISTRY_URL", "https://skills.example")
    monkeypatch.setattr(
        sr.urlrequest, "urlopen", lambda *a, **kw: _fake_response(_encoded(SAMPLE_PAYLOAD))
    )
    rc = sr.main(["show", "bmad-code-review"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "bmad-code-review" in out
    assert "1.0.0" in out


def test_cli_show_not_found_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SKILLS_REGISTRY_URL", "https://skills.example")
    monkeypatch.setattr(
        sr.urlrequest, "urlopen", lambda *a, **kw: _fake_response(_encoded(SAMPLE_PAYLOAD))
    )
    rc = sr.main(["show", "does-not-exist"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "not found" in err


def test_cli_show_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SKILLS_REGISTRY_URL", "https://skills.example")
    monkeypatch.setattr(
        sr.urlrequest, "urlopen", lambda *a, **kw: _fake_response(_encoded(SAMPLE_PAYLOAD))
    )
    rc = sr.main(["show", "openspec-propose", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["name"] == "openspec-propose"
