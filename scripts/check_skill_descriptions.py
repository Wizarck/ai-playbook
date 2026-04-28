"""Soft-warn lint for SKILL.md descriptions per skills-distribution.md §1 (v0.7.0+).

The `description` frontmatter field of a SKILL.md must tell the LLM **when** to
invoke the skill ("CSO — command-style operations" pattern from
`obra/superpowers`), not summarise what the skill does internally.

Examples
--------

❌ Bad (summarises the workflow):
    description: Generates a PRD with 12 sections via guided elicitation

✅ Good (when-to-use):
    description: Use when the user wants to start a new module's discovery phase and write its product requirements

The first form invites the LLM to short-circuit reading the full skill — the
description sounds complete on its own. The second form gives the LLM a clear
trigger condition without spoiling the workflow.

Usage
-----

    python -m scripts.check_skill_descriptions [--root <path>] [--strict]

By default scans `templates/new-project/.claude/skills/` and `skills/` (when
present) for `SKILL.md` files. Reports problematic descriptions as warnings.

Heuristics
----------

A description is **suspicious** if it matches any of these patterns:

1. Starts with a verb like "Generates", "Creates", "Produces", "Outputs",
   "Runs", "Executes" — typical of summary phrasing.
2. Contains workflow-step counts like "12 sections", "5 steps", "3 phases".
3. Contains internal mechanism words: "via", "through", "by reading",
   "by parsing", "elicitation", "scaffolding".
4. Does NOT contain a when-clause indicator: "Use when", "Invoke when",
   "When the user wants", "When you need to".

The lint reports each match with the file path + the description + which
heuristic fired + a suggested rewrite skeleton. It does NOT modify files.

Exit codes
----------

    0 — no warnings (or `--strict=False` and only warnings)
    1 — at least one suspicious description (with `--strict`)
    2 — setup error (root not found, malformed frontmatter, etc.)
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

# Indicators that mark a description as "summarises the workflow" (suspicious).
SUMMARY_VERB_PATTERNS = (
    r"^(generates?|creates?|produces?|outputs?|runs?|executes?|computes?|builds?|writes?|drafts?|emits?)\b",
)

WORKFLOW_MECHANICS_PATTERNS = (
    r"\b\d+\s*(sections?|steps?|phases?|stages?|gates?|artefacts?|files?)\b",
    r"\bvia\b",
    r"\bthrough\b",
    r"\bby (reading|parsing|scaffolding|invoking|elicit\w*)\b",
    r"\belicit\w*\b",
    r"\bscaffold\w*\b",
)

# Indicators that mark a description as "tells the LLM when to invoke" (good).
WHEN_TO_USE_PATTERNS = (
    r"\b(use|invoke)\s+when\b",
    r"^when\s+(the\s+user|you)\b",
    r"\b(when\s+the\s+user|when\s+you)\s+(wants|need|require)\b",
)


@dataclass
class Finding:
    path: Path
    description: str
    reasons: list[str]


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    """Extract the YAML frontmatter from a SKILL.md (between two --- lines).

    Uses ``yaml.safe_load`` so multi-line forms (folded ``>`` and literal ``|``
    block scalars) are honoured. Coerces every value to ``str`` so callers can
    treat ``fields["description"]`` uniformly regardless of source style.
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end]
    try:
        loaded = yaml.safe_load(block)
    except yaml.YAMLError:
        return None
    if not isinstance(loaded, dict):
        return None
    fields: dict[str, str] = {}
    for key, value in loaded.items():
        if value is None:
            fields[str(key)] = ""
        else:
            # ``str(value)`` collapses folded-scalar newlines per YAML spec
            # already (yaml.safe_load resolves ``>`` into a single-line string).
            fields[str(key)] = str(value).strip()
    return fields


def _check_description(description: str) -> list[str]:
    """Return a list of reasons the description is suspicious. Empty list = clean."""
    reasons: list[str] = []
    desc_lower = description.lower()

    # Heuristic 1: starts with a summary verb
    for pat in SUMMARY_VERB_PATTERNS:
        if re.search(pat, desc_lower):
            reasons.append(f"starts with summary verb (pattern: {pat})")
            break

    # Heuristic 2-3: workflow mechanics words
    for pat in WORKFLOW_MECHANICS_PATTERNS:
        if re.search(pat, desc_lower):
            reasons.append(f"contains workflow-mechanics phrasing (pattern: {pat})")
            break

    # Heuristic 4: no when-to-use indicator
    has_when = any(re.search(pat, desc_lower) for pat in WHEN_TO_USE_PATTERNS)
    if not has_when:
        reasons.append("missing when-to-use indicator (e.g. 'Use when', 'When the user wants')")

    return reasons


def scan(root: Path) -> list[Finding]:
    """Walk `root` for SKILL.md files; return suspicious descriptions."""
    findings: list[Finding] = []
    if not root.is_dir():
        return findings

    for skill_md in sorted(root.rglob("SKILL.md")):
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        if not fm:
            continue
        description = fm.get("description", "").strip()
        if not description:
            findings.append(Finding(path=skill_md, description="", reasons=["missing description field"]))
            continue
        reasons = _check_description(description)
        if reasons:
            findings.append(Finding(path=skill_md, description=description, reasons=reasons))
    return findings


def render(findings: list[Finding], *, root: Path) -> str:
    """Render findings as a human-readable report."""
    if not findings:
        return f"✅ No issues — all descriptions under {root} look like CSO-style when-to-use.\n"
    lines: list[str] = [f"⚠️  Found {len(findings)} suspicious description(s) under {root}:\n"]
    for f in findings:
        rel = f.path.relative_to(root) if f.path.is_relative_to(root) else f.path
        lines.append(f"  {rel}")
        lines.append(f"    description: {f.description!r}")
        for r in f.reasons:
            lines.append(f"    • {r}")
        lines.append("    suggested rewrite skeleton:")
        lines.append('      "Use when the user <trigger condition> and needs to <intent>"')
        lines.append("")
    lines.append(
        "Reference: specs/skills-distribution.md §1 (Required SKILL.md sections, v0.7.0+)\n"
        "Pattern source: obra/superpowers (MIT)\n"
    )
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="check_skill_descriptions",
        description="Soft-warn lint for SKILL.md description fields (CSO when-to-use rule).",
    )
    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help=(
            "Root to scan for SKILL.md files. Default: scan both "
            "templates/new-project/.claude/skills/ and skills/ (whichever exist)."
        ),
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on any finding (CI mode). Default: warning-only (exit 0).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    here = Path(__file__).resolve().parents[1]

    if args.root:
        roots = [args.root.expanduser().resolve()]
    else:
        candidates = [
            here / "templates" / "new-project" / ".claude" / "skills",
            here / "skills",
        ]
        roots = [c for c in candidates if c.is_dir()]
        if not roots:
            print(
                f"❌ No skill directory found under {here}. "
                "Pass --root to override.",
                file=sys.stderr,
            )
            return 2

    total = 0
    for root in roots:
        findings = scan(root)
        print(render(findings, root=root), end="")
        total += len(findings)

    if args.strict and total > 0:
        return 1
    return 0


__all__ = [
    "Finding",
    "scan",
    "render",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
