"""Tests for scripts/rules/gitignore-entries.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_gie_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "gitignore-entries.rule.py",
)
assert SPEC and SPEC.loader
_gie = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_gie)


REQUIRED = (
    ".ai-playbook/.ai-playbook-state/",
    "notifications.jsonl",
    "hindsight-queue.jsonl",
)


def _make_consumer(tmp_path: Path, *, with_agents: bool = True) -> Path:
    if with_agents:
        (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    return tmp_path


def _write_gitignore(root: Path, text: str) -> Path:
    p = root / ".gitignore"
    p.write_text(text, encoding="utf-8")
    return p


# --- validate ------------------------------------------------------------------

def test_validate_ok_when_all_entries_present(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    _write_gitignore(root, "node_modules/\n" + "\n".join(REQUIRED) + "\n")
    assert _gie.validate(root) == 0


def test_validate_drift_when_gitignore_missing(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    rc = _gie.validate(root)
    assert rc == 1
    assert ".gitignore missing" in capsys.readouterr().err


def test_validate_drift_when_one_entry_missing(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    # Drop one required entry.
    _write_gitignore(
        root,
        "node_modules/\n.ai-playbook/.ai-playbook-state/\nnotifications.jsonl\n",
    )
    rc = _gie.validate(root)
    assert rc == 1
    err = capsys.readouterr().err
    assert "hindsight-queue.jsonl" in err


def test_validate_drift_when_all_entries_missing(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    _write_gitignore(root, "node_modules/\n.venv/\n")
    rc = _gie.validate(root)
    assert rc == 1
    err = capsys.readouterr().err
    for e in REQUIRED:
        assert e in err


def test_validate_ignores_comment_lines(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    # Required entries inside a comment do NOT count as present.
    _write_gitignore(root, "# .ai-playbook/.ai-playbook-state/\n# notifications.jsonl\n")
    assert _gie.validate(root) == 1


def test_validate_fatal_when_no_consumer_root(tmp_path: Path, capsys) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    rc = _gie.validate(nested)
    assert rc == 2
    assert "no consumer root" in capsys.readouterr().err


def test_validate_skip_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_GITIGNORE_ENTRIES_SKIP", "1")
    assert _gie.validate(tmp_path) == 0


# --- apply ---------------------------------------------------------------------

def test_apply_appends_missing_entries_to_empty_gitignore(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    _write_gitignore(root, "")
    rc = _gie.apply(dry_run=False, cwd=root)
    assert rc == 0
    text = (root / ".gitignore").read_text(encoding="utf-8")
    for e in REQUIRED:
        assert e in text
    assert "ai-playbook managed entries" in text


def test_apply_creates_gitignore_when_missing(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    # No .gitignore at all.
    rc = _gie.apply(dry_run=False, cwd=root)
    assert rc == 0
    text = (root / ".gitignore").read_text(encoding="utf-8")
    for e in REQUIRED:
        assert e in text


def test_apply_preserves_existing_content_verbatim(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    existing = "node_modules/\n.venv/\n# custom comment\n"
    _write_gitignore(root, existing)
    rc = _gie.apply(dry_run=False, cwd=root)
    assert rc == 0
    text = (root / ".gitignore").read_text(encoding="utf-8")
    # Original content present, byte-for-byte, at the start.
    assert text.startswith(existing)
    for e in REQUIRED:
        assert e in text


def test_apply_partial_add_only_missing(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    existing = "node_modules/\n.ai-playbook/.ai-playbook-state/\n"
    _write_gitignore(root, existing)
    rc = _gie.apply(dry_run=False, cwd=root)
    assert rc == 0
    text = (root / ".gitignore").read_text(encoding="utf-8")
    # Only the two missing entries appended (not the already-present one).
    assert text.count(".ai-playbook/.ai-playbook-state/") == 1
    assert "notifications.jsonl" in text
    assert "hindsight-queue.jsonl" in text


def test_apply_dry_run_does_not_write(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    _write_gitignore(root, "node_modules/\n")
    rc = _gie.apply(dry_run=True, cwd=root)
    assert rc == 0
    # File unchanged.
    assert (root / ".gitignore").read_text(encoding="utf-8") == "node_modules/\n"


def test_apply_idempotent_when_all_present(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    # First apply writes the block.
    _gie.apply(dry_run=False, cwd=root)
    before = (root / ".gitignore").read_text(encoding="utf-8")
    # Second apply = no-op.
    rc = _gie.apply(dry_run=False, cwd=root)
    assert rc == 0
    after = (root / ".gitignore").read_text(encoding="utf-8")
    assert before == after


def test_apply_fatal_when_no_consumer_root(tmp_path: Path, capsys) -> None:
    nested = tmp_path / "deep" / "nested"
    nested.mkdir(parents=True)
    rc = _gie.apply(dry_run=False, cwd=nested)
    assert rc == 2
    assert "no consumer root" in capsys.readouterr().err
