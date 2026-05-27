"""Tests for ``scripts.caveman.policy`` — never-compress invariants."""
from __future__ import annotations

import pytest

from scripts.caveman import policy


# ---------------------------------------------------------------------------
# Marker block policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block_id", [
    "bootstrap-directive", "dispatcher-index", "capability-map", "mcp-sources",
])
def test_never_compress_block_ids_regardless_of_toggle(block_id: str) -> None:
    assert policy.is_block_compressible(block_id, user_global_enabled=True) is False
    assert policy.is_block_compressible(block_id, user_global_enabled=False) is False


def test_unrelated_block_id_follows_toggle() -> None:
    assert policy.is_block_compressible("some-other-block", user_global_enabled=True) is True
    assert policy.is_block_compressible("some-other-block", user_global_enabled=False) is False


# ---------------------------------------------------------------------------
# project_meta policy
# ---------------------------------------------------------------------------


def test_hard_rules_never_compress() -> None:
    assert policy.is_project_meta_key_compressible("hard_rules", user_global_enabled=True) is False
    assert policy.is_project_meta_key_compressible(
        "hard_rules", user_global_enabled=True, per_section_override=True,
    ) is False


@pytest.mark.parametrize("key", [
    "project_identity", "inherited_overrides", "gotchas", "active_work",
])
def test_compressible_keys_follow_toggle(key: str) -> None:
    assert policy.is_project_meta_key_compressible(key, user_global_enabled=True) is True
    assert policy.is_project_meta_key_compressible(key, user_global_enabled=False) is False


def test_per_section_override_takes_precedence_over_toggle() -> None:
    assert policy.is_project_meta_key_compressible(
        "project_identity", user_global_enabled=False, per_section_override=True,
    ) is True
    assert policy.is_project_meta_key_compressible(
        "project_identity", user_global_enabled=True, per_section_override=False,
    ) is False


def test_unknown_project_meta_key_is_safe_default_false() -> None:
    assert policy.is_project_meta_key_compressible(
        "unrecognised_key", user_global_enabled=True,
    ) is False


# ---------------------------------------------------------------------------
# MCP description policy
# ---------------------------------------------------------------------------


def test_mcp_default_off() -> None:
    assert policy.is_mcp_description_compressible(
        "any-server", user_global_enabled=True,
    ) is False


def test_mcp_per_server_override() -> None:
    assert policy.is_mcp_description_compressible(
        "any-server", user_global_enabled=False, per_server_override=True,
    ) is True
    assert policy.is_mcp_description_compressible(
        "any-server", user_global_enabled=True, per_server_override=False,
    ) is False


# ---------------------------------------------------------------------------
# describe_policy snapshot
# ---------------------------------------------------------------------------


def test_describe_policy_snapshot() -> None:
    snapshot = policy.describe_policy()
    assert "bootstrap-directive" in snapshot["never_compress_block_ids"]
    assert "hard_rules" in snapshot["never_compress_project_meta_keys"]
    assert "project_identity" in snapshot["compressible_project_meta_keys"]
