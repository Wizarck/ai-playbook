"""Tests for the dispatcher's in-process rule execution (Fase E foundation)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import hook_dispatcher as HD  # noqa: N812
from scripts import rules_toggle

SECRET = "AKIA" + "A" * 16  # AWS access-key-id shape recognised by secrets_scan
_SH = HD.REPO_ROOT / "scripts" / "rules" / "secrets-handling.rule.py"


def _event(secret: bool = True, tool: str = "Write") -> dict:
    content = f"AWS_KEY={SECRET}\n" if secret else "clean content\n"
    return {"tool_name": tool, "tool_input": {"file_path": "x.env", "content": content}}


def _rules():
    return HD.load_rules()


# --- secrets-handling pretooluse entrypoint -------------------------------


def test_secrets_pretooluse_blocks_secret() -> None:
    mod = HD._load_rule_module(_SH)
    v = mod.pretooluse(_event(secret=True))
    assert v.verdict == "block" and "secret" in v.message.lower()


def test_secrets_pretooluse_allows_clean() -> None:
    mod = HD._load_rule_module(_SH)
    assert mod.pretooluse(_event(secret=False)).verdict == "allow"


def test_secrets_pretooluse_none_for_non_edit_tool() -> None:
    mod = HD._load_rule_module(_SH)
    assert mod.pretooluse({"tool_name": "Read", "tool_input": {}}) is None


# --- run_rules aggregation ------------------------------------------------


def test_run_rules_blocks_on_secret(tmp_path: Path) -> None:
    blocked, messages, fired = HD.run_rules(_rules(), "PreToolUse", _event(True), consumer_root=tmp_path)
    assert blocked
    assert "secrets-handling" in fired
    assert any("secrets-handling" in m for m in messages)


def test_run_rules_allows_clean(tmp_path: Path) -> None:
    blocked, _m, _f = HD.run_rules(_rules(), "PreToolUse", _event(False), consumer_root=tmp_path)
    assert not blocked


def test_run_rules_respects_l1_toggle(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# x\n", encoding="utf-8")
    state = rules_toggle.default_state()
    state["applied_by"] = "test"
    state["rules"]["secrets-handling"] = {"enabled": True, "layers": {"L1": False}}
    rules_toggle.write_state(tmp_path, state)
    blocked, _m, fired = HD.run_rules(_rules(), "PreToolUse", _event(True), consumer_root=tmp_path)
    assert not blocked and "secrets-handling" not in fired


def test_run_rules_buggy_rule_fails_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rules = _rules()
    sh = next(r for r in rules if r.slug == "secrets-handling")
    mod = HD._load_rule_module(sh.hardrule_path)
    monkeypatch.setattr(mod, "pretooluse", lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
    blocked, messages, _f = HD.run_rules([sh], "PreToolUse", _event(True), consumer_root=tmp_path)
    assert not blocked  # a raising rule warns, never blocks
    assert any("errored" in m for m in messages)


# --- english-only-docs pretooluse -----------------------------------------

_EOD = HD.REPO_ROOT / "scripts" / "rules" / "english-only-docs.rule.py"
_ES = ("Este documento describe la configuración del módulo en español con muchas "
       "tildes: configuración, también, según, número, función, versión, sesión.")
_EN = "This document describes the module configuration in plain English prose."


def _doc_event(text: str, path: str = "docs/guide.md", tool: str = "Write") -> dict:
    return {"tool_name": tool, "tool_input": {"file_path": path, "content": text}}


def test_english_only_blocks_non_english_doc_write() -> None:
    mod = HD._load_rule_module(_EOD)
    assert mod.pretooluse(_doc_event(_ES)).verdict == "block"


def test_english_only_allows_english_doc_write() -> None:
    mod = HD._load_rule_module(_EOD)
    assert mod.pretooluse(_doc_event(_EN)).verdict == "allow"


def test_english_only_skips_partial_edit() -> None:
    mod = HD._load_rule_module(_EOD)
    assert mod.pretooluse(_doc_event(_ES, tool="Edit")) is None


def test_english_only_skips_non_docs_and_non_md() -> None:
    mod = HD._load_rule_module(_EOD)
    assert mod.pretooluse(_doc_event(_ES, path="README.md")) is None
    assert mod.pretooluse(_doc_event(_ES, path="docs/x.txt")) is None


def test_english_only_skips_when_skip_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_DOC_LANG_SKIP", "1")
    mod = HD._load_rule_module(_EOD)
    assert mod.pretooluse(_doc_event(_ES)) is None


# --- matching + capability helpers ----------------------------------------


def test_rule_matches_by_event_or_tool() -> None:
    sh = next(r for r in _rules() if r.slug == "secrets-handling")  # triggers [Edit, Write]
    assert HD._rule_matches(sh, "PreToolUse", "Write")
    assert not HD._rule_matches(sh, "PreToolUse", "Read")


def test_applies_gating() -> None:
    gem = next(r for r in _rules() if r.slug == "gemini-session-start")  # applies_to ["gemini"]
    assert HD._applies(gem, "gemini")
    assert not HD._applies(gem, "claude")


# --- CLI execution path ---------------------------------------------------


def test_cli_blocks_on_secret() -> None:
    assert HD.main(["PreToolUse", "--event-json", json.dumps(_event(True))]) == 2


def test_cli_allows_clean() -> None:
    assert HD.main(["PreToolUse", "--event-json", json.dumps(_event(False))]) == 0


def test_cli_match_only_does_not_block() -> None:
    # diagnostics mode never executes rules → never blocks
    assert HD.main(["PreToolUse", "--match-only", "--event-json", json.dumps(_event(True))]) == 0


# --- optional-dependency degradation (jsonschema absent) ------------------

_NO_JSONSCHEMA = """
import sys
sys.modules["jsonschema"] = None  # simulate an env without jsonschema
import scripts._ensure_deps as d
d._install = lambda dists: None  # no network install from a test
from scripts import hook_dispatcher as HD
sys.exit(HD.main(["PreToolUse", "--event-json", sys.argv[1]]))
"""


def _run_without_jsonschema(cwd: Path, event: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _NO_JSONSCHEMA, json.dumps(event)],
        cwd=cwd, capture_output=True, text=True, timeout=60,
        env={**os.environ, "PYTHONPATH": str(HD.REPO_ROOT), "CLAUDE_PROJECT_DIR": str(cwd)},
    )


def test_missing_jsonschema_does_not_brick_dispatcher(tmp_path: Path) -> None:
    """A missing optional dep must not turn every tool call into exit 2."""
    (tmp_path / "AGENTS.md").write_text("# x\n", encoding="utf-8")
    proc = _run_without_jsonschema(tmp_path, _event(secret=False))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1])["blocked"] is False


def test_toggle_honoured_without_jsonschema(tmp_path: Path) -> None:
    """The L1 toggle check is json-only; it still works when jsonschema is absent."""
    _disable_secrets(tmp_path)
    proc = _run_without_jsonschema(tmp_path, _event(secret=True))
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert "secrets-handling" not in out["fired"], proc.stderr


# --- consumer-root resolution ---------------------------------------------


def _disable_secrets(root: Path) -> None:
    (root / "AGENTS.md").write_text("# x\n", encoding="utf-8")
    (root / ".ai-playbook").mkdir(exist_ok=True)
    (root / ".ai-playbook" / "rules-toggle.json").write_text(
        json.dumps({"rules": {"secrets-handling": {"enabled": False}}}), encoding="utf-8"
    )


def _drifted_consumer(tmp_path: Path) -> tuple[Path, Path]:
    """Consumer with secrets-handling OFF, plus a cwd inside its playbook checkout."""
    consumer = tmp_path / "consumer"
    drift = consumer / ".ai-playbook" / "docs"
    drift.mkdir(parents=True)
    _disable_secrets(consumer)
    (consumer / ".ai-playbook" / "AGENTS.md").write_text("# playbook\n", encoding="utf-8")
    return consumer, drift


def test_root_prefers_claude_project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    consumer, drift = _drifted_consumer(tmp_path)
    monkeypatch.chdir(drift)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(consumer))
    blocked, _m, fired = HD.run_rules(_rules(), "PreToolUse", _event(True))
    assert not blocked and "secrets-handling" not in fired


def test_root_uses_event_cwd_and_skips_playbook_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _consumer, drift = _drifted_consumer(tmp_path)
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(sibling)  # process cwd drifted to an unrelated dir
    blocked, _m, fired = HD.run_rules(_rules(), "PreToolUse", {**_event(True), "cwd": str(drift)})
    assert not blocked and "secrets-handling" not in fired
