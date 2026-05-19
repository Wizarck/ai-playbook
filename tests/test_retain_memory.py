"""Tests for scripts/retain_memory.py — write side of the Hindsight loop (renamed from retain_lesson in v0.3.0)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import _hindsight as hs
from scripts import retain_memory as rl

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


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, fake) -> None:
    monkeypatch.setattr(hs.urlrequest, "urlopen", fake)


def _wire_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HINDSIGHT_URL", "https://h.example/")
    monkeypatch.setenv("CF_ACCESS_CLIENT_ID", "cid")
    monkeypatch.setenv("CF_ACCESS_CLIENT_SECRET", "csec")
    monkeypatch.delenv("HINDSIGHT_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# RetainItem rendering
# ---------------------------------------------------------------------------


def test_retain_item_to_hindsight_minimal() -> None:
    item = rl.RetainItem(content="hello world", bank="consumer-d")
    out = item.to_hindsight()
    assert out["content"] == "hello world"
    # `kind` defaults to lesson, becomes context + tag
    assert out["context"] == "lesson"
    assert "lesson" in out["tags"]


def test_retain_item_to_hindsight_full() -> None:
    item = rl.RetainItem(
        content="rotated PAT to fine-grained scope",
        bank="consumer-d",
        kind="decision",
        project="ai-playbook",
        why="least-privilege",
        trace_id="trace-abc",
        tags=["security", "rotation"],
        ttl_days=180,
        timestamp="2026-04-24T14:00:00Z",
    )
    out = item.to_hindsight()
    assert "WHY: least-privilege" in out["content"]
    assert out["timestamp"] == "2026-04-24T14:00:00Z"
    assert out["context"] == "decision"
    assert out["tags"] == ["security", "rotation", "decision", "ai-playbook"]
    assert out["metadata"]["trace_id"] == "trace-abc"
    assert out["metadata"]["ttl_days"] == "180"
    assert out["metadata"]["project"] == "ai-playbook"
    assert out["metadata"]["kind"] == "decision"


# ---------------------------------------------------------------------------
# CLI happy path
# ---------------------------------------------------------------------------


def test_cli_single_item_retain_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _wire_creds(monkeypatch)
    monkeypatch.chdir(tmp_path)

    captured: dict[str, object] = {}

    def _cap(req, timeout):  # noqa: ANN001
        captured["body"] = req.data
        captured["url"] = req.full_url
        return _resp(b'{"success":true,"items_count":1,"usage":{"total_tokens":100}}')

    _patch_urlopen(monkeypatch, _cap)
    monkeypatch.setattr(
        "sys.argv",
        ["retain_memory", "--bank", "consumer-d", "--content", "Test lesson here",
         "--why", "Because reasons", "--kind", "decision", "--project", "ai-playbook"],
    )
    rc = rl.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "retained 1 item(s) to bank=consumer-d" in out
    assert "100" in out  # token usage echoed
    assert "/banks/consumer-d/memories" in captured["url"]


def test_cli_dry_run_does_not_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _wire_creds(monkeypatch)
    called = {"n": 0}

    def _spy(req, timeout):  # noqa: ANN001
        called["n"] += 1
        return _resp(b'{"items_count":1}')

    _patch_urlopen(monkeypatch, _spy)
    monkeypatch.setattr(
        "sys.argv",
        ["retain_memory", "--bank", "consumer-d", "--content", "x" * 50, "--dry-run"],
    )
    rc = rl.main()
    assert rc == 0
    assert called["n"] == 0
    body = capsys.readouterr().out
    parsed = json.loads(body)
    assert parsed["content"] == "x" * 50


def test_cli_bulk_jsonl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _wire_creds(monkeypatch)
    monkeypatch.chdir(tmp_path)
    bulk = tmp_path / "lessons.jsonl"
    bulk.write_text(
        json.dumps({"content": "first", "kind": "lesson", "project": "p"}) + "\n" +
        json.dumps({"content": "second", "kind": "gotcha", "tags": ["foo"]}) + "\n",
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def _cap(req, timeout):  # noqa: ANN001
        captured["body"] = req.data
        return _resp(b'{"success":true,"items_count":2,"usage":{"total_tokens":250}}')

    _patch_urlopen(monkeypatch, _cap)
    monkeypatch.setattr(
        "sys.argv",
        ["retain_memory", "--bank", "consumer-d", "--bulk", str(bulk)],
    )
    rc = rl.main()
    assert rc == 0
    sent = json.loads(captured["body"].decode("utf-8"))
    assert len(sent["items"]) == 2
    assert sent["items"][0]["content"] == "first"
    assert sent["items"][1]["content"] == "second"


# ---------------------------------------------------------------------------
# Degraded-mode queue
# ---------------------------------------------------------------------------


def test_cli_queues_on_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HINDSIGHT_URL", raising=False)  # forces HindsightUrlMissing
    monkeypatch.setattr(
        "sys.argv",
        ["retain_memory", "--bank", "consumer-d", "--content", "queued lesson"],
    )
    rc = rl.main()
    assert rc == 0
    err = capsys.readouterr().err
    assert "queued" in err
    queue = tmp_path / ".ai-playbook" / "hindsight-queue.jsonl"
    assert queue.is_file()
    rec = json.loads(queue.read_text(encoding="utf-8").strip())
    assert rec["item"]["content"] == "queued lesson"
    assert rec["bank"] == "consumer-d"


def test_replay_queue_drains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _wire_creds(monkeypatch)
    monkeypatch.chdir(tmp_path)
    queue = tmp_path / ".ai-playbook" / "hindsight-queue.jsonl"
    queue.parent.mkdir(parents=True)
    queue.write_text(
        json.dumps({"ts": "2026-04-24T00:00:00", "bank": "consumer-d",
                    "item": {"content": "queued"}}) + "\n" +
        json.dumps({"ts": "2026-04-24T00:01:00", "bank": "other-bank",
                    "item": {"content": "skip me"}}) + "\n",
        encoding="utf-8",
    )

    _patch_urlopen(monkeypatch, lambda req, timeout: _resp(b'{"items_count":1}'))
    monkeypatch.setattr(
        "sys.argv",
        ["retain_memory", "--bank", "consumer-d", "--replay-queue"],
    )
    rc = rl.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "replayed 1 item(s)" in out
    assert "1 remain queued" in out
    # The other-bank entry stays in the queue.
    remaining = queue.read_text(encoding="utf-8").strip()
    assert "other-bank" in remaining
    assert "queued" not in remaining  # the consumer-d entry was drained


# ---------------------------------------------------------------------------
# Opportunistic drain
# ---------------------------------------------------------------------------


def test_opportunistic_drain_no_queue(tmp_path: Path) -> None:
    """Missing or empty queue → noop, no exception."""
    sent, kept = rl.try_opportunistic_drain(tmp_path, "consumer-d")
    assert (sent, kept) == (0, 0)

    queue = tmp_path / ".ai-playbook" / "hindsight-queue.jsonl"
    queue.parent.mkdir(parents=True)
    queue.write_text("", encoding="utf-8")
    sent, kept = rl.try_opportunistic_drain(tmp_path, "consumer-d")
    assert (sent, kept) == (0, 0)


def test_post_success_drains_queued_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """After a successful POST /retain, queued items for the same bank are drained."""
    _wire_creds(monkeypatch)
    monkeypatch.chdir(tmp_path)
    queue = tmp_path / ".ai-playbook" / "hindsight-queue.jsonl"
    queue.parent.mkdir(parents=True)
    queue.write_text(
        json.dumps({"ts": "2026-04-24T00:00:00", "bank": "consumer-d",
                    "item": {"content": "previously queued"}}) + "\n",
        encoding="utf-8",
    )

    _patch_urlopen(monkeypatch, lambda req, timeout: _resp(
        b'{"success":true,"items_count":1,"usage":{"total_tokens":50}}'))
    monkeypatch.setattr(
        "sys.argv",
        ["retain_memory", "--bank", "consumer-d", "--content", "new lesson body"],
    )
    rc = rl.main()
    assert rc == 0

    captured = capsys.readouterr()
    assert "retained 1 item(s) to bank=consumer-d" in captured.out
    assert "opportunistically drained 1" in captured.err
    # Queue should now be empty.
    assert queue.read_text(encoding="utf-8") == ""


def test_opportunistic_drain_swallows_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If _drain_queue raises, try_opportunistic_drain returns (0, 0) silently."""
    queue = tmp_path / ".ai-playbook" / "hindsight-queue.jsonl"
    queue.parent.mkdir(parents=True)
    queue.write_text(
        json.dumps({"ts": "2026-04-24T00:00:00", "bank": "consumer-d",
                    "item": {"content": "queued"}}) + "\n",
        encoding="utf-8",
    )

    def _explode(*a, **kw):  # noqa: ANN001
        raise RuntimeError("boom")

    monkeypatch.setattr(rl, "_drain_queue", _explode)
    sent, kept = rl.try_opportunistic_drain(tmp_path, "consumer-d")
    assert (sent, kept) == (0, 0)
