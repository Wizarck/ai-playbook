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
| `_llm.call(...)` / `_llm_call(...)` invoked without explicit `application=`
  | anywhere outside the helper and tests | `scripts/_llm.py`, `tests/` |

The application-tag check (`missing-application-kwarg`) requires AST parsing
because real-world `_llm.call(...)` invocations span multiple lines. It looks
at every call site, resolves the function name through file-local imports
(both `_llm.call(...)` and `from ._llm import call as _llm_call` aliases),
and emits a finding when no `application=` keyword is present. Callers may
rely on the `AIPLAYBOOK_APPLICATION` env var as a fallback — the static check
cannot see env state, so this is best-effort: in v1 it warns; the helper
itself enforces strict mode at runtime once the migration window closes.

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
import ast
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
    # Submodules — consumers vendor the playbook at `.ai-playbook/` and the
    # skills mirror at `.skills-sources/`. Their contents are upstream-owned;
    # consumers cannot fix findings inside them. The drift detector should
    # only surface drift in consumer-owned code.
    ".ai-playbook/",
    ".skills-sources/",
)


# Inline exclusion: a comment `# llm-routing-allow: <reason>` on the same line
# whitelists a single occurrence (e.g. one-off scripts that document intent).
_INLINE_ALLOW_RE = re.compile(r"#\s*llm-routing-allow:\s*\S")


# Name of the AST rule that flags `_llm.call(...)` without `application=`.
_APPLICATION_RULE_NAME = "missing-application-kwarg"


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
# AST-based scan: `_llm.call(...)` missing `application=` kwarg
# ---------------------------------------------------------------------------


def _collect_llm_bindings(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Return ``(call_aliases, module_aliases)`` bound in this file.

    - ``call_aliases``: names that resolve to ``scripts._llm.call`` (e.g.
      from ``from ._llm import call as _llm_call`` → ``{"_llm_call"}``).
    - ``module_aliases``: names that resolve to the ``_llm`` module itself
      (e.g. from ``from scripts import _llm`` → ``{"_llm"}``). Always
      includes the bare name ``"_llm"`` so ``_llm.call(...)`` without an
      explicit import in the file is still flagged.
    """
    call_aliases: set[str] = set()
    module_aliases: set[str] = {"_llm"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.endswith("_llm"):
                for alias in node.names:
                    if alias.name == "call":
                        call_aliases.add(alias.asname or "call")
            for alias in node.names:
                if alias.name == "_llm":
                    module_aliases.add(alias.asname or "_llm")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith("_llm"):
                    if alias.asname:
                        module_aliases.add(alias.asname)
                    elif "." not in alias.name:
                        module_aliases.add(alias.name)
    return call_aliases, module_aliases


def _is_llm_call(node: ast.Call, call_aliases: set[str], module_aliases: set[str]) -> bool:
    """True if ``node`` is a call to ``_llm.call`` (any binding) or to a known alias."""
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "call":
        cur: ast.AST = func.value
        while isinstance(cur, ast.Attribute):
            if cur.attr in module_aliases:
                return True
            cur = cur.value
        if isinstance(cur, ast.Name) and cur.id in module_aliases:
            return True
    return isinstance(func, ast.Name) and func.id in call_aliases


def _scan_file_ast(path: Path) -> list[Finding]:
    """Scan ``path`` for ``_llm.call(...)`` invocations missing ``application=``."""
    findings: list[Finding] = []
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return findings
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return findings

    call_aliases, module_aliases = _collect_llm_bindings(tree)
    source_lines = source.splitlines()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_llm_call(node, call_aliases, module_aliases):
            continue
        kwarg_names = {kw.arg for kw in node.keywords if kw.arg is not None}
        if "application" in kwarg_names:
            continue
        # `**kwargs` may carry application; we cannot know statically — skip.
        if any(kw.arg is None for kw in node.keywords):
            continue

        # Inline allow on any line spanned by this call expression.
        start = node.lineno
        end = getattr(node, "end_lineno", start) or start
        skipped = False
        for ln in range(start, end + 1):
            if 0 < ln <= len(source_lines) and _INLINE_ALLOW_RE.search(source_lines[ln - 1]):
                skipped = True
                break
        if skipped:
            continue

        line_text = source_lines[start - 1] if 0 < start <= len(source_lines) else ""
        findings.append(Finding(
            path=str(path),
            line_no=start,
            rule=_APPLICATION_RULE_NAME,
            line=line_text,
        ))
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
        out.extend(_scan_file_ast(f))
    out.sort(key=lambda f: (f.path, f.line_no, f.rule))
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
            direct_sdk = [f for f in findings if f.rule != _APPLICATION_RULE_NAME]
            missing_app = [f for f in findings if f.rule == _APPLICATION_RULE_NAME]
            if direct_sdk:
                print(
                    "\nDirect-SDK callers: migrate each to `from scripts._llm import call` "
                    "and use `call(task_class, prompt, ...)`. See docs/concepts/model-routing.md §1 "
                    "for the task-class taxonomy. Inline allow with `# llm-routing-allow: <reason>`.",
                    file=sys.stderr,
                )
            if missing_app:
                print(
                    "\nMissing-application: add an explicit `application=\"<canonical-name>\"` "
                    "kwarg to each `_llm.call(...)` flagged above. See docs/concepts/model-routing.md §5 "
                    "for the canonical application roster. Callers that set `AIPLAYBOOK_APPLICATION` "
                    "at runtime can also annotate the call with `# llm-routing-allow: env-fallback`.",
                    file=sys.stderr,
                )

    if findings and strict:
        return 2
    return 0


if __name__ == "__main__":
    from scripts.rules._telemetry import script_emit
    raise SystemExit(script_emit("verify-llm-routing", _main))
