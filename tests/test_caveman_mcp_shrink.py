"""Tests for scripts.caveman.mcp_shrink — wrap/unwrap MCP server configs."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.caveman import mcp_shrink

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# wrap_entry / unwrap_entry (single-entry transforms)
# ---------------------------------------------------------------------------


def test_wrap_entry_stdio_basic() -> None:
    entry = {"command": "uv", "args": ["run", "hindsight-mcp"]}
    wrapped = mcp_shrink.wrap_entry(entry)
    assert wrapped["command"] == "npx"
    assert wrapped["args"] == ["-y", "caveman-shrink", "--", "uv", "run", "hindsight-mcp"]
    assert wrapped["_caveman_wrapped"] is True
    assert wrapped["_caveman_original"] == {"command": "uv", "args": ["run", "hindsight-mcp"]}


def test_wrap_entry_no_args() -> None:
    entry = {"command": "mcp-server"}
    wrapped = mcp_shrink.wrap_entry(entry)
    assert wrapped["args"] == ["-y", "caveman-shrink", "--", "mcp-server"]
    assert wrapped["_caveman_original"] == {"command": "mcp-server", "args": []}


def test_wrap_entry_idempotent() -> None:
    entry = {"command": "uv", "args": ["run"]}
    once = mcp_shrink.wrap_entry(entry)
    twice = mcp_shrink.wrap_entry(once)
    assert once == twice


def test_wrap_entry_rejects_http_entry() -> None:
    # HTTP entries have url, no command — must refuse.
    entry = {"url": "http://localhost:4000/mcp", "transport": "http"}
    with pytest.raises(ValueError, match="stdio entries"):
        mcp_shrink.wrap_entry(entry)


def test_wrap_entry_rejects_mixed_entry() -> None:
    # Entries with BOTH command and url are weird — don't touch.
    entry = {"command": "uv", "url": "http://x"}
    with pytest.raises(ValueError):
        mcp_shrink.wrap_entry(entry)


def test_unwrap_entry_restores_original() -> None:
    original = {"command": "uv", "args": ["run", "x"], "transport": "stdio"}
    wrapped = mcp_shrink.wrap_entry(original)
    unwrapped = mcp_shrink.unwrap_entry(wrapped)
    assert unwrapped["command"] == "uv"
    assert unwrapped["args"] == ["run", "x"]
    assert "_caveman_wrapped" not in unwrapped
    assert "_caveman_original" not in unwrapped
    # Other keys preserved
    assert unwrapped["transport"] == "stdio"


def test_unwrap_entry_unchanged_when_not_wrapped() -> None:
    entry = {"command": "uv", "args": ["run"]}
    out = mcp_shrink.unwrap_entry(entry)
    assert out == entry


def test_unwrap_entry_strips_markers_even_when_original_missing() -> None:
    entry = {
        "command": "npx",
        "args": ["caveman-shrink", "--"],
        "_caveman_wrapped": True,
        # Missing _caveman_original
    }
    out = mcp_shrink.unwrap_entry(entry)
    assert "_caveman_wrapped" not in out
    assert "_caveman_original" not in out


# ---------------------------------------------------------------------------
# shrink_file / restore_file (document-level)
# ---------------------------------------------------------------------------


def test_shrink_file_wraps_all_stdio_entries(tmp_path: Path) -> None:
    mcp = tmp_path / ".mcp.json"
    _write_json(mcp, {
        "mcpServers": {
            "hindsight": {"command": "uv", "args": ["run", "hs"]},
            "atlassian": {"url": "http://localhost:9000/sse", "transport": "sse"},
            "litellm": {"command": "litellm-mcp"},
        }
    })
    backup, count = mcp_shrink.shrink_file(tmp_path, mcp)
    assert count == 2  # hindsight + litellm, NOT atlassian (HTTP)
    assert backup is not None
    assert backup.is_file()

    doc = json.loads(mcp.read_text(encoding="utf-8"))
    assert doc["mcpServers"]["hindsight"]["_caveman_wrapped"] is True
    assert doc["mcpServers"]["litellm"]["_caveman_wrapped"] is True
    # HTTP entry untouched
    assert "_caveman_wrapped" not in doc["mcpServers"]["atlassian"]
    assert doc["mcpServers"]["atlassian"]["url"] == "http://localhost:9000/sse"


def test_shrink_file_returns_none_when_file_missing(tmp_path: Path) -> None:
    backup, count = mcp_shrink.shrink_file(tmp_path, tmp_path / "ghost.json")
    assert backup is None
    assert count == 0


def test_shrink_file_idempotent(tmp_path: Path) -> None:
    mcp = tmp_path / ".mcp.json"
    _write_json(mcp, {"mcpServers": {"a": {"command": "uv"}}})
    first_backup, first_count = mcp_shrink.shrink_file(tmp_path, mcp)
    assert first_count == 1
    # Run again — should be no-op (no new backup, no new wraps).
    second_backup, second_count = mcp_shrink.shrink_file(tmp_path, mcp)
    assert second_count == 0
    assert second_backup is None


def test_shrink_file_no_stdio_entries_is_noop(tmp_path: Path) -> None:
    mcp = tmp_path / ".mcp.json"
    _write_json(mcp, {
        "mcpServers": {
            "only-http": {"url": "http://x", "transport": "http"},
        }
    })
    backup, count = mcp_shrink.shrink_file(tmp_path, mcp)
    assert backup is None
    assert count == 0


def test_restore_file_unwraps_via_markers(tmp_path: Path) -> None:
    mcp = tmp_path / ".mcp.json"
    _write_json(mcp, {"mcpServers": {"a": {"command": "uv", "args": ["run"]}}})
    mcp_shrink.shrink_file(tmp_path, mcp)
    backup, count = mcp_shrink.restore_file(tmp_path, mcp)
    assert count == 1
    assert backup is not None

    doc = json.loads(mcp.read_text(encoding="utf-8"))
    assert doc["mcpServers"]["a"]["command"] == "uv"
    assert doc["mcpServers"]["a"]["args"] == ["run"]
    assert "_caveman_wrapped" not in doc["mcpServers"]["a"]


def test_restore_file_falls_back_to_backup_when_no_markers(tmp_path: Path) -> None:
    """If someone hand-edits the file and loses markers, restore from backup."""
    mcp = tmp_path / ".mcp.json"
    _write_json(mcp, {"mcpServers": {"a": {"command": "uv"}}})
    mcp_shrink.shrink_file(tmp_path, mcp)  # creates a backup of the un-wrapped state

    # Manually strip markers (simulate user editing)
    doc = json.loads(mcp.read_text(encoding="utf-8"))
    entry = doc["mcpServers"]["a"]
    entry.pop("_caveman_wrapped", None)
    entry.pop("_caveman_original", None)
    # Leave the wrapped command in place but markers stripped.
    _write_json(mcp, doc)

    backup, count = mcp_shrink.restore_file(tmp_path, mcp)
    assert backup is not None
    assert count == 1
    # File now matches the original (pre-shrink) state.
    restored = json.loads(mcp.read_text(encoding="utf-8"))
    assert restored["mcpServers"]["a"] == {"command": "uv"}


def test_restore_file_handles_missing_file_with_backup(tmp_path: Path) -> None:
    mcp = tmp_path / ".mcp.json"
    _write_json(mcp, {"mcpServers": {"a": {"command": "uv"}}})
    mcp_shrink.shrink_file(tmp_path, mcp)
    mcp.unlink()

    backup, count = mcp_shrink.restore_file(tmp_path, mcp)
    assert backup is not None
    assert count == 1
    assert mcp.is_file()


def test_restore_file_returns_none_when_nothing_to_do(tmp_path: Path) -> None:
    mcp = tmp_path / ".mcp.json"
    _write_json(mcp, {"mcpServers": {"a": {"command": "uv"}}})  # not wrapped
    backup, count = mcp_shrink.restore_file(tmp_path, mcp)
    assert backup is None
    assert count == 0


# ---------------------------------------------------------------------------
# shrink_project / restore_project
# ---------------------------------------------------------------------------


def test_shrink_project_handles_both_files(tmp_path: Path) -> None:
    _write_json(tmp_path / ".mcp.json", {"mcpServers": {"a": {"command": "uv"}}})
    _write_json(tmp_path / ".gemini" / "settings.json", {"mcpServers": {"b": {"command": "go"}}})

    result = mcp_shrink.shrink_project(tmp_path)
    assert result["claude"]["wrapped"] == 1
    assert result["gemini"]["wrapped"] == 1
    assert result["claude"]["backup"] is not None
    assert result["gemini"]["backup"] is not None


def test_shrink_project_handles_only_claude(tmp_path: Path) -> None:
    _write_json(tmp_path / ".mcp.json", {"mcpServers": {"a": {"command": "uv"}}})
    # No gemini settings.

    result = mcp_shrink.shrink_project(tmp_path)
    assert result["claude"]["wrapped"] == 1
    assert result["gemini"]["wrapped"] == 0
    assert result["gemini"]["backup"] is None


def test_shrink_then_restore_round_trip(tmp_path: Path) -> None:
    original_claude = {"mcpServers": {"a": {"command": "uv", "args": ["run"]}, "b": {"url": "http://x"}}}
    original_gemini = {"mcpServers": {"c": {"command": "go", "args": ["v"]}}}
    _write_json(tmp_path / ".mcp.json", original_claude)
    _write_json(tmp_path / ".gemini" / "settings.json", original_gemini)

    mcp_shrink.shrink_project(tmp_path)
    mcp_shrink.restore_project(tmp_path)

    assert json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8")) == original_claude
    assert json.loads((tmp_path / ".gemini" / "settings.json").read_text(encoding="utf-8")) == original_gemini
