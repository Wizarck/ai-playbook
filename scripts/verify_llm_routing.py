"""verify_llm_routing.py — drift detector for direct-SDK LLM calls.

Per OpenSpec change `add-litellm-enforcement` (Phase 5 P5.4): every LLM call
in the codebase MUST go through `scripts/_llm.py` → LiteLLM proxy. This
script greps for direct-SDK usage that bypasses that helper.

Operating modes (D3.5):

- **warn-only** (default for v1): exits 0 even when violations are found;
  prints them to stderr so the developer notices but the build doesn't break.
- **error**: exits 2 when violations are found. Promote after 30 days of
  green builds — set `AIPLAYBOOK_LLM_ROUTING_STRICT=1` or pass `--strict`.

Detection rules:

| Pattern | Where it's banned | Where it's allowed |
|---|---|---|
| `from anthropic import` / `import anthropic` | anywhere outside the helper
  | `scripts/_llm.py`, `lib/telemetry/anthropic_tracer.py` |
| `from openai import` / `import openai` | anywhere outside the helper
  | `scripts/_llm.py` |
| `from google.generativeai import` / `import google.generativeai`
  | anywhere outside the helper | `scripts/_llm.py`, `lib/telemetry/gemini_tracer.py` |
| `os.environ.get("ANTHROPIC_API_KEY"` / `os.getenv("ANTHROPIC_API_KEY"`
  | anywhere outside helpers | `scripts/_llm.py` |

Excluded paths (built-in):

- `scripts/_llm.py` — the helper itself
- `lib/telemetry/*_tracer.py` — Langfuse/OTel tracers wrap the SDKs deliberately
- `tests/` — test fixtures may import SDK modules to construct mocks
- `.git/`, `__pycache__/`, `.venv/`, `node_modules/`, `_bmad-output/`

Run:

    python -m scripts.verify_llm_routing            # warn-only mode
    python -m scripts.verify_llm_routing --strict   # exit 2 on any finding
    python -m scripts.verify_llm_routing --json     # machine-readable output

Pre-commit hook config: see `.pre-commit-config.yaml` (added by Task 7 of the change).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Force UTF-8 stdio — Windows cp1252 cannot encode the ✓ sigil.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

# ---------------------------------------------------------------------------
# Detection rules
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    name: str          # short id for output
    pattern: re.Pattern[str]
    description: str   # human-readable explanation


_RULES: tuple[Rule, ...] = (
    Rule(
        name="anthropic-import",
        pattern=re.compile(r"^\s*(?:from\s+anthropic\s+import|import\s+anthropic\b)"),
        description="Direct anthropic SDK import — route via _llm.call(...) instead.",
    ),
    Rule(
        name="openai-import",
        pattern=re.compile(r"^\s*(?:from\s+openai\s+import|import\s+openai\b)"),
        description="Direct OpenAI SDK import — route via _llm.call(...) instead.",
    ),
    Rule(
        name="gemini-import",
        pattern=re.compile(r"^\s*(?:from\s+google\.generativeai\s+import|import\s+google\.generativeai\b)"),
        description="Direct Gemini SDK import — route via _llm.call(...) instead.",
    ),
    Rule(
        name="anthropic-key-env",
        pattern=re.compile(r"""os\.(?:environ\.get|getenv)\(\s*['"]ANTHROPIC_API_KEY['"]"""),
        description="Direct ANTHROPIC_API_KEY env read — _llm.py owns key resolution.",
    ),
)


# Built-in exclusion list — paths that LEGITIMATELY import SDKs.
_BUILTIN_EXCLUSIONS: tuple[str, ...] = (
    # The helper itself uses no SDKs (only httpx) but we exclude its dir for safety.
    "scripts/_llm.py",
    # Telemetry tracers wrap the SDKs — that's their job.
    "lib/telemetry/anthropic_tracer.py",
    "lib/telemetry/gemini_tracer.py",
    "lib/telemetry/litellm_callbacks.py",
    # Test fixtures may import SDKs to mock them.
    "tests/",
    # Build / cache / vendored.
    ".git/",
    "__pycache__/",
    ".venv/",
    "venv/",
    "node_modules/",
    "_bmad-output/",
    # Documentation that quotes SDK code in fenced blocks.
    "docs/",
    "rfcs/",
    # The drift detector itself names the rules — false positive on its own source.
    "scripts/verify_llm_routing.py",
)


# Inline exclusion: a comment `# llm-routing-allow: <reason>` on the same line
# whitelists a single occurrence (e.g. one-off scripts that document intent).
_INLINE_ALLOW_RE = re.compile(r"#\s*llm-routing-allow:\s*\S")


# ---------------------------------------------------------------------------
# Walking
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    path: str
    line_no: int
    rule: str
    line: str

    def render(self) -> str:
        return f"{self.path}:{self.line_no}  [{self.rule}]  {self.line.strip()}"


def _is_excluded(path: Path, repo_root: Path, exclusions: tuple[str, ...]) -> bool:
    rel = path.relative_to(repo_root).as_posix()
    return any(rel.startswith(p) for p in exclusions)


def _walk_repo(repo_root: Path, exclusions: tuple[str, ...]) -> list[Path]:
    """Yield every .py file under repo_root that is not excluded."""
    files: list[Path] = []
    for p in repo_root.rglob("*.py"):
        if _is_excluded(p, repo_root, exclusions):
            continue
        files.append(p)
    return files


def _scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return findings
    for line_no, line in enumerate(text.splitlines(), start=1):
        if _INLINE_ALLOW_RE.search(line):
            continue
        for rule in _RULES:
            if rule.pattern.search(line):
                findings.append(Finding(
                    path=str(path),
                    line_no=line_no,
                    rule=rule.name,
                    line=line,
                ))
                break  # one finding per line is enough
    return findings


# ---------------------------------------------------------------------------
# Public API (also used by tests)
# ---------------------------------------------------------------------------


def scan(repo_root: Path | str, *, exclusions: tuple[str, ...] | None = None) -> list[Finding]:
    """Scan the tree at ``repo_root`` and return all findings."""
    root = Path(repo_root).resolve()
    excl = exclusions if exclusions is not None else _BUILTIN_EXCLUSIONS
    out: list[Finding] = []
    for f in _walk_repo(root, excl):
        out.extend(_scan_file(f))
    out.sort(key=lambda f: (f.path, f.line_no))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main() -> int:
    parser = argparse.ArgumentParser(description="LLM-routing drift detector (Change C P5.4)")
    parser.add_argument("--root", default=".", help="repo root (default: cwd)")
    parser.add_argument("--strict", action="store_true",
                        help="exit 2 on any finding (default: warn-only)")
    parser.add_argument("--json", dest="json_out", action="store_true",
                        help="machine-readable JSON output")
    args = parser.parse_args()

    strict = args.strict or os.environ.get("AIPLAYBOOK_LLM_ROUTING_STRICT", "").strip() == "1"
    findings = scan(args.root)

    if args.json_out:
        print(json.dumps(
            {"findings": [f.__dict__ for f in findings], "strict": strict},
            ensure_ascii=False, indent=2,
        ))
    else:
        if not findings:
            print("verify_llm_routing: 0 findings — all LLM calls route via _llm.py ✓")
        else:
            print(f"verify_llm_routing: {len(findings)} finding(s):", file=sys.stderr)
            for f in findings:
                print(f"  {f.render()}", file=sys.stderr)
            print(
                "\nMigrate each call to `from scripts._llm import call` and use "
                "`call(task_class, prompt, ...)`. See specs/model-routing.md §1 for "
                "the task-class taxonomy. Inline allow with `# llm-routing-allow: <reason>`.",
                file=sys.stderr,
            )

    if findings and strict:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
