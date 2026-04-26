"""End-to-end integration test for the Hindsight memory loop.

GATED — runs only when the env var ``AIPLAYBOOK_E2E=1`` is set AND a real
``HINDSIGHT_URL`` + auth pair are present. CI doesn't run these by default;
local development does (via `sops exec-env`):

    AIPLAYBOOK_E2E=1 sops exec-env consumer-d/secrets/secrets.env -- \\
        python -m pytest tests/integration/test_e2e_loop.py -v

What it verifies:
    1. retain_memory.py POSTs a sentinel item to a test bank.
    2. inject_context.py recalls something from that bank within timeout.
    3. The retained sentinel surfaces in the recall results within N retries
       (Hindsight's semantic indexing is async; we poll for it).

Cleanup is best-effort — Hindsight's REST surface allows DELETE per memory
but we just rely on the sentinel content being clearly testy ("e2e-test-…").
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

E2E_FLAG = os.environ.get("AIPLAYBOOK_E2E") == "1"
HINDSIGHT_URL = os.environ.get("HINDSIGHT_URL")
HAS_AUTH = (
    (os.environ.get("CF_ACCESS_CLIENT_ID") and os.environ.get("CF_ACCESS_CLIENT_SECRET"))
    or os.environ.get("HINDSIGHT_API_KEY")
)

pytestmark = pytest.mark.skipif(
    not (E2E_FLAG and HINDSIGHT_URL and HAS_AUTH),
    reason="set AIPLAYBOOK_E2E=1 + HINDSIGHT_URL + (CF_ACCESS_* or HINDSIGHT_API_KEY)",
)


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_BANK = "ai-playbook-e2e-test"
RECALL_RETRIES = 6   # Hindsight indexing is async; poll up to ~3 minutes.
RECALL_INTERVAL = 30


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(REPO_ROOT), check=True, capture_output=True, text=True,
        encoding="utf-8", **kwargs,
    )


def test_retain_then_recall_roundtrip() -> None:
    """Full loop: retain a sentinel → recall finds it within retries."""
    sentinel_id = str(uuid.uuid4())[:8]
    sentinel_content = (
        f"e2e-test-sentinel-{sentinel_id} — playbook integration test "
        f"verifying retain + recall round-trip on bank={TEST_BANK}"
    )

    # 1. Retain.
    retain = _run([
        sys.executable, "-m", "scripts.retain_memory",
        "--bank", TEST_BANK,
        "--kind", "fact",
        "--content", sentinel_content,
        "--why", f"e2e-test-{sentinel_id}",
        "--tag", "e2e-test",
        "--tag", sentinel_id,
    ])
    assert "retained" in retain.stdout, retain.stdout

    # 2. Poll recall until the sentinel surfaces (semantic indexing is async).
    from scripts._hindsight import load_credentials, post_recall

    creds = load_credentials()
    found = False
    last_results: list[dict] = []
    for attempt in range(1, RECALL_RETRIES + 1):
        time.sleep(RECALL_INTERVAL if attempt > 1 else 5)
        result = post_recall(creds, TEST_BANK, sentinel_content, max_tokens=2000)
        if not result.ok:
            continue
        results = (result.body or {}).get("results", []) if isinstance(result.body, dict) else []
        last_results = results
        if any(sentinel_id in (r.get("text") or "") for r in results):
            found = True
            break

    assert found, (
        f"sentinel {sentinel_id} not found in {len(last_results)} recall results "
        f"after {RECALL_RETRIES} retries; first text: "
        f"{(last_results[0] if last_results else {}).get('text', '<none>')[:120]}"
    )


def test_degraded_queue_on_no_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without auth, retain_memory queues to hindsight-queue.jsonl + exits 0."""
    monkeypatch.delenv("CF_ACCESS_CLIENT_ID", raising=False)
    monkeypatch.delenv("CF_ACCESS_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("HINDSIGHT_API_KEY", raising=False)
    monkeypatch.delenv("HINDSIGHT_URL", raising=False)

    proc = subprocess.run(
        [sys.executable, "-m", "scripts.retain_memory",
         "--bank", TEST_BANK, "--content", "queued-while-degraded"],
        cwd=str(tmp_path), capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    queue = tmp_path / ".ai-playbook" / "hindsight-queue.jsonl"
    assert queue.is_file()
    rec = json.loads(queue.read_text(encoding="utf-8").strip())
    assert "queued-while-degraded" in rec["item"]["content"]
