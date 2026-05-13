"""Tests for `scripts/_llm.py` and `scripts/verify_llm_routing.py`.

Covers Phase 5 P5.4 OpenSpec change `add-litellm-enforcement`:

`_llm.call(...)` tests:
  - happy path: calls LiteLLM proxy, parses response, emits gen_ai.usage event
  - rejects unknown task_class with ValueError
  - raises LLMRoutingError on proxy unreachable
  - raises LLMRoutingError on malformed response
  - per-consumer override applied to metadata

`verify_llm_routing.scan(...)` tests:
  - flags `from anthropic import` outside excluded paths
  - flags `os.environ.get("ANTHROPIC_API_KEY")` outside the helper
  - excludes scripts/_llm.py, lib/telemetry/*_tracer.py, tests/, .git/
  - inline `# llm-routing-allow:` comment whitelists single occurrences
  - returns 0 findings on a clean tree

Run:
    python -m pytest tests/test_llm_helper.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from _llm import LLMRoutingError, call  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_events(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect events.jsonl writes to tmp_path."""
    events = tmp_path / "events.jsonl"
    monkeypatch.setenv("AIPLAYBOOK_EVENTS_FILE", str(events))
    monkeypatch.delenv("AIPLAYBOOK_CONSUMER", raising=False)
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
    monkeypatch.setenv("LITELLM_BASE_URL", "http://litellm.fake:4000")
    return events


class _MockHttpxClient:
    """Mock httpx.Client capturing POSTs to the LiteLLM proxy."""

    def __init__(
        self,
        captured: list[dict[str, Any]],
        *,
        response_body: dict[str, Any] | None = None,
        status_code: int = 200,
        raise_on_post: Exception | None = None,
    ) -> None:
        self._captured = captured
        self._response_body = response_body or {
            "choices": [{"message": {"content": "pong"}}],
            "model": "anthropic/claude-haiku-4-5",
            "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
        }
        self._status = status_code
        self._raise = raise_on_post

    def __enter__(self) -> _MockHttpxClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, *, json: dict[str, Any] | None = None,
             headers: dict[str, str] | None = None, **_kwargs):
        self._captured.append({"url": url, "json": json, "headers": headers})
        if self._raise is not None:
            raise self._raise

        body = self._response_body
        status = self._status

        class _MockResponse:
            def __init__(self) -> None:
                self.status_code = status

            def raise_for_status(self) -> None:
                if status >= 400:
                    raise httpx.HTTPStatusError(
                        "fake error",
                        request=httpx.Request("POST", "https://fake"),
                        response=httpx.Response(status),
                    )

            def json(self):  # noqa: ANN001 — match httpx signature
                return body

        return _MockResponse()


# ---------------------------------------------------------------------------
# _llm.call happy path
# ---------------------------------------------------------------------------

def test_call_happy_path(isolated_events, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(httpx, "Client", lambda **kw: _MockHttpxClient(captured))

    resp = call("triage", "ping", max_tokens=10, consumer="JUDGE")

    assert resp.text == "pong"
    assert resp.task_class == "triage"
    assert resp.model_actual == "anthropic/claude-haiku-4-5"
    assert resp.fallback_depth == 0
    assert resp.consumer == "JUDGE"
    assert resp.usage == {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}

    # Captured request shape
    assert len(captured) == 1
    req = captured[0]
    assert req["url"] == "http://litellm.fake:4000/chat/completions"
    body = req["json"]
    assert body["model"] == "triage"   # router resolves this
    assert body["max_tokens"] == 10
    assert body["metadata"]["task_class"] == "triage"
    assert body["metadata"]["consumer"] == "JUDGE"
    assert body["messages"] == [{"role": "user", "content": "ping"}]


def test_call_with_system_prompt(isolated_events, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(httpx, "Client", lambda **kw: _MockHttpxClient(captured))

    call("daily_dev", "implement story X", system="You are an executor")

    msgs = captured[0]["json"]["messages"]
    assert msgs[0] == {"role": "system", "content": "You are an executor"}
    assert msgs[1] == {"role": "user", "content": "implement story X"}


def test_call_emits_gen_ai_usage_event(isolated_events, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(httpx, "Client", lambda **kw: _MockHttpxClient(captured))

    call("triage", "ping")

    # Read events file
    lines = isolated_events.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines if line.strip()]
    usage_events = [e for e in events if e["event"] == "gen_ai.usage"]
    assert len(usage_events) == 1
    e = usage_events[0]
    assert e["ai_playbook.task_class"] == "triage"
    assert e["gen_ai.response.model"] == "anthropic/claude-haiku-4-5"
    assert e["gen_ai.usage.prompt_tokens"] == 4
    assert e["gen_ai.usage.completion_tokens"] == 1


def test_call_resolves_consumer_from_env(isolated_events, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(httpx, "Client", lambda **kw: _MockHttpxClient(captured))
    monkeypatch.setenv("AIPLAYBOOK_CONSUMER", "advisor")  # lowercase → upper-cased

    call("triage", "ping")

    assert captured[0]["json"]["metadata"]["consumer"] == "ADVISOR"


def test_call_attaches_master_key_when_set(isolated_events, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(httpx, "Client", lambda **kw: _MockHttpxClient(captured))
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master-test")

    call("triage", "ping")

    assert captured[0]["headers"]["Authorization"] == "Bearer sk-master-test"


# ---------------------------------------------------------------------------
# _llm.call error paths
# ---------------------------------------------------------------------------

def test_call_rejects_unknown_task_class(isolated_events) -> None:
    with pytest.raises(ValueError, match="unknown task_class"):
        call("not_a_real_class", "ping")


def test_call_raises_routing_error_on_proxy_down(isolated_events, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: _MockHttpxClient(
            captured, raise_on_post=httpx.ConnectError("proxy refused"),
        ),
    )

    with pytest.raises(LLMRoutingError, match="LiteLLM proxy unreachable"):
        call("triage", "ping")

    # Failure event was emitted
    lines = isolated_events.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines if line.strip()]
    assert any(e["event"] == "gen_ai.request.failed" for e in events)


def test_call_raises_on_malformed_response(isolated_events, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: _MockHttpxClient(
            captured,
            response_body={"weird": "no choices field"},
        ),
    )

    with pytest.raises(LLMRoutingError, match="malformed"):
        call("triage", "ping")


# ---------------------------------------------------------------------------
# verify_llm_routing.scan
# ---------------------------------------------------------------------------

import verify_llm_routing  # noqa: E402


def test_scan_clean_tree_returns_no_findings(tmp_path: Path) -> None:
    (tmp_path / "good.py").write_text(
        "from scripts._llm import call\n"
        "resp = call('triage', 'ping', application='dashboard-backend')\n",
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    assert findings == []


def test_scan_flags_direct_anthropic_import(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text(
        "import anthropic\nclient = anthropic.Anthropic()\n",
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    assert len(findings) == 1
    assert findings[0].rule == "anthropic-import"
    assert findings[0].line_no == 1


def test_scan_flags_direct_anthropic_key_env(tmp_path: Path) -> None:
    (tmp_path / "leak.py").write_text(
        'import os\nkey = os.environ.get("ANTHROPIC_API_KEY")\n',
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    assert len(findings) == 1
    assert findings[0].rule == "anthropic-key-env"


def test_scan_flags_direct_openai_import(tmp_path: Path) -> None:
    (tmp_path / "openai_leak.py").write_text(
        "from openai import OpenAI\nc = OpenAI()\n",
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    assert len(findings) == 1
    assert findings[0].rule == "openai-import"


def test_scan_excludes_tests_dir_by_default(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "import anthropic  # mocked in fixtures\n",
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    assert findings == []


def test_scan_excludes_telemetry_tracers(tmp_path: Path) -> None:
    (tmp_path / "lib" / "telemetry").mkdir(parents=True)
    (tmp_path / "lib" / "telemetry" / "anthropic_tracer.py").write_text(
        "import anthropic\n",
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    assert findings == []


def test_scan_excludes_submodule_directories(tmp_path: Path) -> None:
    """Consumers vendor the playbook at .ai-playbook/ — drift in submodule code
    is upstream-owned and must not appear in the consumer's drift report.
    """
    for submodule in (".ai-playbook", ".skills-sources"):
        (tmp_path / submodule / "scripts").mkdir(parents=True)
        (tmp_path / submodule / "scripts" / "vendored.py").write_text(
            "import anthropic\nclient = anthropic.Anthropic()\n",
            encoding="utf-8",
        )
    # Consumer-owned code with the same shape MUST still be flagged.
    (tmp_path / "consumer.py").write_text(
        "import anthropic\n",
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    assert len(findings) == 1
    assert findings[0].path.endswith("consumer.py")


def test_scan_inline_allow_comment_whitelists_line(tmp_path: Path) -> None:
    (tmp_path / "annotated.py").write_text(
        "import anthropic  # llm-routing-allow: bootstrap script, runs once\n",
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    assert findings == []


def test_scan_returns_findings_sorted_by_path_then_line(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import anthropic\n", encoding="utf-8")
    (tmp_path / "b.py").write_text(
        "from openai import OpenAI\nfrom anthropic import Anthropic\n",
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    # a.py:1 first, then b.py:1, b.py:2
    assert len(findings) == 3
    assert findings[0].path.endswith("a.py")
    assert findings[1].path.endswith("b.py")
    assert findings[1].line_no == 1
    assert findings[2].path.endswith("b.py")
    assert findings[2].line_no == 2


# ---------------------------------------------------------------------------
# verify_llm_routing.scan — AST check: missing `application=` kwarg
# ---------------------------------------------------------------------------


def test_scan_flags_llm_call_missing_application(tmp_path: Path) -> None:
    (tmp_path / "caller.py").write_text(
        "from scripts import _llm\n"
        "resp = _llm.call('triage', 'ping', consumer='ADVISOR')\n",
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    assert len(findings) == 1
    assert findings[0].rule == "missing-application-kwarg"
    assert findings[0].line_no == 2
    assert findings[0].path.endswith("caller.py")


def test_scan_accepts_explicit_application_kwarg(tmp_path: Path) -> None:
    (tmp_path / "caller.py").write_text(
        "from scripts import _llm\n"
        "resp = _llm.call('triage', 'ping', application='dashboard-backend')\n",
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    assert findings == []


def test_scan_flags_multiline_call_missing_application(tmp_path: Path) -> None:
    (tmp_path / "caller.py").write_text(
        "from scripts import _llm\n"
        "resp = _llm.call(\n"
        "    'triage',\n"
        "    'ping',\n"
        "    consumer='ADVISOR',\n"
        "    max_tokens=256,\n"
        ")\n",
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    assert len(findings) == 1
    assert findings[0].rule == "missing-application-kwarg"
    # The finding points at the line where the Call starts.
    assert findings[0].line_no == 2


def test_scan_accepts_multiline_call_with_application(tmp_path: Path) -> None:
    (tmp_path / "caller.py").write_text(
        "from scripts import _llm\n"
        "resp = _llm.call(\n"
        "    'triage',\n"
        "    'ping',\n"
        "    consumer='ADVISOR',\n"
        "    application='lib-advisor',\n"
        ")\n",
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    assert findings == []


def test_scan_handles_aliased_call_import(tmp_path: Path) -> None:
    """Aliased import: `from ._llm import call as _llm_call` — alias is tracked."""
    (tmp_path / "caller.py").write_text(
        "from scripts._llm import call as _llm_call\n"
        "resp = _llm_call('safety_judge', 'text', consumer='INJECTION')\n",
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    assert len(findings) == 1
    assert findings[0].rule == "missing-application-kwarg"


def test_scan_inline_allow_whitelists_missing_application(tmp_path: Path) -> None:
    (tmp_path / "caller.py").write_text(
        "from scripts import _llm\n"
        "resp = _llm.call('triage', 'ping')  # llm-routing-allow: env-fallback\n",
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    assert findings == []


def test_scan_skips_call_with_kwargs_splat(tmp_path: Path) -> None:
    """If the call uses **kwargs we can't know statically whether application is present.

    Skip rather than emit a false positive.
    """
    (tmp_path / "caller.py").write_text(
        "from scripts import _llm\n"
        "extra = {'application': 'dashboard-backend'}\n"
        "resp = _llm.call('triage', 'ping', **extra)\n",
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    assert findings == []


def test_scan_excludes_llm_module_itself(tmp_path: Path) -> None:
    """`scripts/_llm.py` implements `call` — it must not be scanned."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "_llm.py").write_text(
        "def call(task_class, prompt):\n"
        "    return _llm_call_internal(task_class, prompt)\n"
        "def _llm_call_internal(a, b):\n"
        "    return None\n",
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    assert findings == []


def test_scan_handles_chained_attribute_call(tmp_path: Path) -> None:
    """`scripts._llm.call(...)` (fully qualified) is still flagged when application is missing."""
    (tmp_path / "caller.py").write_text(
        "import scripts._llm\n"
        "resp = scripts._llm.call('triage', 'ping')\n",
        encoding="utf-8",
    )
    findings = verify_llm_routing.scan(tmp_path)
    assert len(findings) == 1
    assert findings[0].rule == "missing-application-kwarg"
