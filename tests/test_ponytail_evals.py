"""Tests for the ponytail 3-arm eval harness (no API calls)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# The harness lives under tests/evals/ponytail/ and its modules are named
# run.py / report.py — the same names the caveman harness uses. Load them under
# unique module names via importlib (no sys.path insert) so the two harnesses
# never collide in sys.modules regardless of pytest collection order.
HARNESS_DIR = Path(__file__).resolve().parents[1] / "tests" / "evals" / "ponytail"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HARNESS_DIR / filename)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


eval_run = _load("ponytail_eval_run", "run.py")
eval_report = _load("ponytail_eval_report", "report.py")

# ---------------------------------------------------------------------------
# Discovery + arm construction
# ---------------------------------------------------------------------------


def test_load_prompts_returns_nonempty_list() -> None:
    prompts = eval_run._load_prompts()
    assert len(prompts) >= 5
    assert all(not p.startswith("#") and p.strip() for p in prompts)


def test_build_arms_three_entries() -> None:
    arms = eval_run.build_arms()
    assert set(arms.keys()) == {"baseline", "minimal", "ponytail"}
    assert arms["baseline"] is None
    assert arms["minimal"] == eval_run.MINIMAL_PROMPT
    assert arms["ponytail"].startswith(eval_run.MINIMAL_PROMPT)
    # SKILL.md body is appended after the minimal-code prefix.
    assert "YAGNI" in arms["ponytail"]


# ---------------------------------------------------------------------------
# count_code_lines
# ---------------------------------------------------------------------------


def test_count_code_lines_counts_inside_fences() -> None:
    text = "Here you go:\n```python\nx = 1\n\ny = 2\n```\nDone."
    # Two non-blank code lines; prose and the blank line don't count.
    assert eval_run.count_code_lines(text) == 2


def test_count_code_lines_no_fence_counts_all_nonblank() -> None:
    text = "x = 1\ny = 2\n"
    assert eval_run.count_code_lines(text) == 2


# ---------------------------------------------------------------------------
# Dry run — no API
# ---------------------------------------------------------------------------


def test_dry_run_exits_clean(capsys: pytest.CaptureFixture[str]) -> None:
    rc = eval_run.main(["--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Arms: ['baseline', 'minimal', 'ponytail']" in out
    assert "Prompts:" in out


# ---------------------------------------------------------------------------
# Run suite with mock LLM
# ---------------------------------------------------------------------------


def _mock_call_factory(text_map: dict[str | None, str]):
    """Return a callable matching run.run_suite's llm_call signature."""

    def call(prompt: str, system: str | None, max_tokens: int = 2048) -> dict:
        key = None if system is None else system[:10]
        text = text_map.get(key, "```\nfallback = 1\n```")
        return {
            "text": text,
            "input_tokens": 50,
            "output_tokens": 100,
            "model_actual": "mock-model",
        }

    return call


def test_run_suite_records_per_arm_results() -> None:
    arms = {"baseline": None, "minimal": "Write only", "ponytail": "Write onlyMORE"}
    prompts = ["Sort numbers.", "Validate email."]
    mock = _mock_call_factory({
        None: "```\na\nb\nc\nd\n```",        # baseline: 4 LOC
        "Write only": "```\na\nb\n```",        # minimal: 2 LOC
    })
    snapshot = eval_run.run_suite(arms, prompts, llm_call=mock)

    assert snapshot["model_actual"] == "mock-model"
    assert len(snapshot["prompts"]) == 2
    first = snapshot["prompts"][0]
    assert first["prompt"] == "Sort numbers."
    assert set(first["arms"].keys()) == {"baseline", "minimal", "ponytail"}
    assert first["arms"]["baseline"]["code_lines"] == 4
    assert first["arms"]["minimal"]["code_lines"] == 2
    assert first["arms"]["baseline"]["output_tokens"] == 100


def test_run_suite_with_arm_filter_runs_only_one() -> None:
    arms = {"baseline": None, "minimal": "Write only", "ponytail": "Write onlyMORE"}
    prompts = ["Q1"]
    mock = _mock_call_factory({None: "```\na\n```"})
    snapshot = eval_run.run_suite(arms, prompts, llm_call=mock, arm_filter="baseline")
    arms_out = snapshot["prompts"][0]["arms"]
    assert "baseline" in arms_out
    assert "minimal" not in arms_out
    assert "ponytail" not in arms_out


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def test_render_table_emits_markdown_with_delta() -> None:
    snapshot = {
        "ran_at": "2026-06-16T00:00:00+00:00",
        "model_actual": "mock-model",
        "prompts": [
            {
                "prompt": "Validate an email address",
                "arms": {
                    "baseline": {"code_lines": 30},
                    "minimal": {"code_lines": 12},
                    "ponytail": {"code_lines": 3},
                },
            }
        ],
    }
    table = eval_report.render_table(snapshot)
    assert "| 1 |" in table
    assert "30" in table
    assert "12" in table
    # ponytail vs minimal delta: (12-3)/12 = 75.0%
    assert "75.0%" in table
    assert "ponytail vs minimal" in table.lower()


def test_render_table_handles_missing_data_gracefully() -> None:
    snapshot = {
        "ran_at": "2026-06-16T00:00:00+00:00",
        "model_actual": None,
        "prompts": [
            {"prompt": "Empty arms", "arms": {}},
        ],
    }
    table = eval_report.render_table(snapshot)
    assert "Empty arms" in table
    assert table.count("—") >= 3
