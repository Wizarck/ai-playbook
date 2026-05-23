"""3-arm eval harness for the caveman skill.

Honest comparison: caveman vs terse (NOT vs baseline). Baseline is run
for context only — claiming caveman saves N% vs baseline conflates it
with generic terseness, which is dishonest. The actual signal is the
delta between caveman and ``Answer concisely.``.

Arms
----
- ``baseline``  — no system prompt
- ``terse``     — system prompt: ``Answer concisely.``
- ``caveman``   — system prompt: ``Answer concisely.\\n\\n<SKILL.md body>``

Output
------
A snapshot JSON at ``snapshots/results.json`` with shape::

    {
      "ran_at": "2026-05-23T12:00:00+00:00",
      "model_actual": "...",
      "prompts": [
        {
          "prompt": "<text>",
          "arms": {
            "baseline":  {"text": "...", "input_tokens": ..., "output_tokens": ...},
            "terse":     {"text": "...", "input_tokens": ..., "output_tokens": ...},
            "caveman":   {"text": "...", "input_tokens": ..., "output_tokens": ...}
          }
        },
        ...
      ]
    }

Usage
-----
    python tests/evals/caveman/run.py --dry-run       # show what would run, no API call
    python tests/evals/caveman/run.py --emit-snapshot # run all × all, write snapshot
    python tests/evals/caveman/run.py --arm caveman   # only run one arm

Requires
--------
- LiteLLM proxy reachable at ``$LITELLM_BASE_URL`` (default localhost:4000).
- The proxy must have a ``doc_writing_edit`` task class wired.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


HERE = Path(__file__).resolve().parent
PROMPTS_FILE = HERE / "prompts" / "en.txt"
SNAPSHOTS_DIR = HERE / "snapshots"


def _playbook_root() -> Path:
    for c in (HERE, *HERE.parents):
        if (c / "specs").is_dir() and (c / "scripts").is_dir() and (c / "schemas").is_dir():
            return c
    raise FileNotFoundError("playbook root not found from tests/evals/caveman/")


def _load_skill_body() -> str:
    root = _playbook_root()
    skill = (root / "skills" / "caveman" / "SKILL.md").read_text(encoding="utf-8")
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
        "terse": "Answer concisely.",
        "caveman": f"Answer concisely.\n\n{skill_body}",
    }


# ---------------------------------------------------------------------------
# LLM glue — same indirection as scripts/caveman/compress.py for testability
# ---------------------------------------------------------------------------


def _default_llm_call(prompt: str, system: str | None, max_tokens: int = 2048) -> dict:
    from scripts._llm import call as _llm_call

    resp = _llm_call(
        "doc_writing_edit",
        prompt,
        system=system,
        max_tokens=max_tokens,
        application="caveman-evals",
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
        "ran_at": datetime.now(timezone.utc).isoformat(),
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
            }
            if out["model_actual"] is None and result.get("model_actual"):
                out["model_actual"] = result["model_actual"]
        out["prompts"].append({"prompt": p, "arms": per_arm})
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="caveman_evals", description="3-arm caveman skill evaluation.")
    p.add_argument("--dry-run", action="store_true", help="List arms × prompts; no API calls.")
    p.add_argument("--emit-snapshot", action="store_true", help="Write snapshots/results.json.")
    p.add_argument("--arm", choices=["baseline", "terse", "caveman"], default=None, help="Run only one arm.")
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
        print(f"   FIX: ensure LiteLLM proxy is up at $LITELLM_BASE_URL and the doc_writing_edit task_class is configured.", file=sys.stderr)
        return 2

    if args.emit_snapshot:
        out_path = args.snapshot_path or (SNAPSHOTS_DIR / "results.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"✅ snapshot written: {out_path}")
    else:
        # Print summary table to stdout.
        from tests.evals.caveman.report import render_table  # local import to keep run.py importable from tests

        print(render_table(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
