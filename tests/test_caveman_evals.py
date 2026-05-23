"""Tests for the caveman 3-arm eval harness (no API calls)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


# The harness lives under tests/evals/caveman/. Add it to sys.path so we
# can import its modules directly without a package shim.
HARNESS_DIR = Path(__file__).resolve().parents[1] / "tests" / "evals" / "caveman"
sys.path.insert(0, str(HARNESS_DIR))

import run as eval_run  # noqa: E402
import report as eval_report  # noqa: E402


# ---------------------------------------------------------------------------
# Discovery + arm construction
# ---------------------------------------------------------------------------


def test_load_prompts_returns_nonempty_list() -> None:
    prompts = eval_run._load_prompts()
    assert len(prompts) >= 5
    # No comment lines or blank lines should sneak through.
    assert all(not p.startswith("#") and p.strip() for p in prompts)


def test_build_arms_three_entries() -> None:
    arms = eval_run.build_arms()
    assert set(arms.keys()) == {"baseline", "terse", "caveman"}
    assert arms["baseline"] is None
    assert arms["terse"] == "Answer concisely."
    assert arms["caveman"].startswith("Answer concisely.")
    # SKILL.md body is appended after the terse prefix.
    assert "Drop articles" in arms["caveman"]


# ---------------------------------------------------------------------------
# Dry run — no API
# ---------------------------------------------------------------------------


def test_dry_run_exits_clean(capsys: pytest.CaptureFixture[str]) -> None:
    rc = eval_run.main(["--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Arms: ['baseline', 'terse', 'caveman']" in out
    assert "Prompts:" in out


# ---------------------------------------------------------------------------
# Run suite with mock LLM
# ---------------------------------------------------------------------------


def _mock_call_factory(token_map: dict[str | None, int]):
    """Return a callable matching the run.run_suite llm_call signature."""

    def call(prompt: str, system: str | None, max_tokens: int = 2048) -> dict:
        # token count derived from system prompt to make tests deterministic.
        out_tokens = token_map.get(system if system is None else system[:10], 100)
        return {
            "text": f"mock response for sys={system!r}",
            "input_tokens": 50,
            "output_tokens": out_tokens,
            "model_actual": "mock-model",
        }

    return call


def test_run_suite_records_per_arm_results() -> None:
    arms = {"baseline": None, "terse": "Answer con", "caveman": "Answer concise+more"}
    prompts = ["Explain X.", "Refactor Y."]
    mock = _mock_call_factory({None: 200, "Answer con": 150, "Answer con"[:10]: 150})
    snapshot = eval_run.run_suite(arms, prompts, llm_call=mock)

    assert snapshot["model_actual"] == "mock-model"
    assert len(snapshot["prompts"]) == 2
    first = snapshot["prompts"][0]
    assert first["prompt"] == "Explain X."
    assert set(first["arms"].keys()) == {"baseline", "terse", "caveman"}
    assert first["arms"]["baseline"]["output_tokens"] == 200
    assert first["arms"]["terse"]["output_tokens"] == 150


def test_run_suite_with_arm_filter_runs_only_one() -> None:
    arms = {"baseline": None, "terse": "Answer con", "caveman": "Answer concise+more"}
    prompts = ["Q1"]
    mock = _mock_call_factory({None: 200})
    snapshot = eval_run.run_suite(arms, prompts, llm_call=mock, arm_filter="baseline")
    arms_out = snapshot["prompts"][0]["arms"]
    assert "baseline" in arms_out
    assert "terse" not in arms_out
    assert "caveman" not in arms_out


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def test_render_table_emits_markdown_with_delta() -> None:
    snapshot = {
        "ran_at": "2026-05-23T00:00:00+00:00",
        "model_actual": "mock-model",
        "prompts": [
            {
                "prompt": "Explain React re-render",
                "arms": {
                    "baseline": {"output_tokens": 1180},
                    "terse": {"output_tokens": 400},
                    "caveman": {"output_tokens": 159},
                },
            }
        ],
    }
    table = eval_report.render_table(snapshot)
    assert "| 1 |" in table
    assert "1180" in table
    assert "400" in table
    assert "159" in table
    # caveman vs terse delta: (400-159)/400 = 60.25%
    assert "60.2%" in table or "60.3%" in table
    # Honest-delta disclaimer
    assert "caveman vs terse" in table.lower()


def test_render_table_handles_missing_data_gracefully() -> None:
    snapshot = {
        "ran_at": "2026-05-23T00:00:00+00:00",
        "model_actual": None,
        "prompts": [
            {"prompt": "Empty arms", "arms": {}},
        ],
    }
    table = eval_report.render_table(snapshot)
    assert "Empty arms" in table
    # All numeric columns become em-dash for missing data
    assert table.count("—") >= 3
