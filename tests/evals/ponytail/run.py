"""3-arm eval harness for the ponytail skill.

Honest comparison: ponytail vs minimal (NOT vs baseline). Baseline is run for
context only — claiming ponytail saves N% vs baseline conflates it with the
generic "write minimal code" instruction, which is dishonest. The actual signal
is the delta between ponytail and ``Write only the code, as minimal as
possible.``.

Where caveman's harness measures OUTPUT TOKENS (prose compression), ponytail's
headline metric is CODE LINES (LOC inside fenced ``` blocks) — ponytail is about
the size of the deliverable, not the chattiness of the prose.

Arms
----
- ``baseline``  — no system prompt
- ``minimal``   — system prompt: ``Write only the code... as minimal as possible.``
- ``ponytail``  — system prompt: ``<minimal>\\n\\n<SKILL.md body>``

Output
------
A snapshot JSON at ``snapshots/results.json`` with shape::

    {
      "ran_at": "...",
      "model_actual": "...",
      "prompts": [
        {
          "prompt": "<text>",
          "arms": {
            "baseline": {"text": "...", "input_tokens": ..., "output_tokens": ..., "code_lines": ...},
            "minimal":  {...},
            "ponytail": {...}
          }
        }, ...
      ]
    }

Usage
-----
    python tests/evals/ponytail/run.py --dry-run        # show what would run, no API call
    python tests/evals/ponytail/run.py --emit-snapshot  # run all × all, write snapshot
    python tests/evals/ponytail/run.py --arm ponytail   # only run one arm

Requires
--------
- LiteLLM proxy reachable at ``$LITELLM_BASE_URL`` (default localhost:4000).
- The proxy must have a ``code_generation`` task class wired (edit
  ``_default_llm_call`` below if your proxy names it differently).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


HERE = Path(__file__).resolve().parent
PROMPTS_FILE = HERE / "prompts" / "en.txt"
SNAPSHOTS_DIR = HERE / "snapshots"

MINIMAL_PROMPT = "Write only the code that solves the task, as minimal as possible. No explanation."


def _playbook_root() -> Path:
    for c in (HERE, *HERE.parents):
        if (c / "specs").is_dir() and (c / "scripts").is_dir() and (c / "schemas").is_dir():
            return c
    raise FileNotFoundError("playbook root not found from tests/evals/ponytail/")


def _load_skill_body() -> str:
    root = _playbook_root()
    skill = (root / "skills" / "ponytail" / "SKILL.md").read_text(encoding="utf-8")
    # Strip the YAML frontmatter — the system prompt only needs the body.
    if skill.startswith("---"):
        end = skill.find("\n---", 3)
        if end != -1:
            skill = skill[end + 4 :].lstrip()
    return skill


def _load_prompts() -> list[str]:
    if not PROMPTS_FILE.is_file():
        raise FileNotFoundError(f"prompts file missing: {PROMPTS_FILE}")
    lines = PROMPTS_FILE.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def build_arms() -> dict[str, str | None]:
    skill_body = _load_skill_body()
    return {
        "baseline": None,
        "minimal": MINIMAL_PROMPT,
        "ponytail": f"{MINIMAL_PROMPT}\n\n{skill_body}",
    }


def count_code_lines(text: str) -> int:
    """Count non-blank lines of code in a model response.

    Lines inside fenced ``` blocks are the deliverable; count those. If the
    response has no fences (the model returned bare code), count all non-blank
    lines. The fence markers themselves are not counted.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    in_fence = False
    fenced: list[str] = []
    saw_fence = False
    for line in lines:
        if line.lstrip().startswith("```"):
            saw_fence = True
            in_fence = not in_fence
            continue
        if in_fence and line.strip():
            fenced.append(line)
    if saw_fence:
        return len(fenced)
    return sum(1 for line in lines if line.strip())


# ---------------------------------------------------------------------------
# LLM glue — same indirection as the caveman harness for testability
# ---------------------------------------------------------------------------


def _default_llm_call(prompt: str, system: str | None, max_tokens: int = 2048) -> dict:
    from scripts._llm import call as _llm_call

    resp = _llm_call(
        "code_generation",
        prompt,
        system=system,
        max_tokens=max_tokens,
        application="ponytail-evals",
    )
    return {
        "text": resp.text,
        "input_tokens": (resp.usage or {}).get("prompt_tokens"),
        "output_tokens": (resp.usage or {}).get("completion_tokens"),
        "model_actual": resp.model_actual,
    }


def run_suite(
    arms: dict[str, str | None],
    prompts: list[str],
    *,
    llm_call=_default_llm_call,
    arm_filter: str | None = None,
) -> dict:
    out: dict = {
        "ran_at": datetime.now(UTC).isoformat(),
        "model_actual": None,
        "prompts": [],
    }
    for p in prompts:
        per_arm: dict[str, dict] = {}
        for arm_name, system in arms.items():
            if arm_filter and arm_name != arm_filter:
                continue
            result = llm_call(p, system)
            per_arm[arm_name] = {
                "text": result["text"],
                "input_tokens": result.get("input_tokens"),
                "output_tokens": result.get("output_tokens"),
                "code_lines": count_code_lines(result["text"]),
            }
            if out["model_actual"] is None and result.get("model_actual"):
                out["model_actual"] = result["model_actual"]
        out["prompts"].append({"prompt": p, "arms": per_arm})
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ponytail_evals", description="3-arm ponytail skill evaluation.")
    p.add_argument("--dry-run", action="store_true", help="List arms × prompts; no API calls.")
    p.add_argument("--emit-snapshot", action="store_true", help="Write snapshots/results.json.")
    p.add_argument("--arm", choices=["baseline", "minimal", "ponytail"], default=None, help="Run only one arm.")
    p.add_argument("--snapshot-path", type=Path, default=None, help="Override snapshot output path.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        arms = build_arms()
        prompts = _load_prompts()
    except FileNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"Arms: {list(arms.keys())}")
        print(f"Prompts: {len(prompts)}")
        for i, p in enumerate(prompts, 1):
            print(f"  {i:2d}. {p[:80]}{'…' if len(p) > 80 else ''}")
        return 0

    try:
        snapshot = run_suite(arms, prompts, arm_filter=args.arm)
    except Exception as e:  # noqa: BLE001
        print(f"❌ eval run failed: {e}", file=sys.stderr)
        print(
            "   FIX: ensure LiteLLM proxy is up at $LITELLM_BASE_URL "
            "and the code_generation task_class is configured.",
            file=sys.stderr,
        )
        return 2

    if args.emit_snapshot:
        out_path = args.snapshot_path or (SNAPSHOTS_DIR / "results.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"✅ snapshot written: {out_path}")
    else:
        from tests.evals.ponytail.report import render_table  # local import keeps run.py importable from tests

        print(render_table(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
