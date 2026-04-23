"""Drift detection across the playbook, its consumers, and cross-references.

Populated in T17. Supersedes the v0.1.0 stub.

Checks (pick with ``--check``; ``all`` runs every check):

``inherits_from``
    Consumer ``AGENTS.md`` pins the playbook at a version more than one minor
    behind the playbook's own ``VERSION``. Reporting-only.

``auto-managed``
    Any markdown file under the playbook or a registered consumer carrying
    ``<!-- BEGIN auto-managed: <source> -->`` markers where the body is stale
    vs the current source (delegates to ``scripts.auto_managed``). ``--fix``
    rewrites stale sections in-place.

``xref``
    Relative links inside ``specs/*.md`` of the shape ``[text](target.md)``
    whose target does not exist on disk. Reporting-only.

``taxonomy``
    A term that lives in ``*.md`` under ``specs/`` or ``docs/``, appears in at
    least 3 distinct files, and is not defined in ``specs/taxonomy.md`` §1..§3.
    Reporting-only; noise-filtered by the 3-file threshold.

CLI
---
    python -m scripts.drift_check [--consumer-root PATH] [--registry PATH]
                                  [--check inherits|auto-managed|xref|taxonomy|all]
                                  [--fix] [--force-with-reason TEXT]
                                  [--playbook-root PATH]

Exit codes (per ``specs/error-message-standard.md``)
    0 clean OR override-applied
    1 drift detected
    2 setup failure (missing registry, unreadable playbook)
    3 reserved
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

# Force UTF-8 stdio — Windows default cp1252 cannot encode the sigils we emit.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

try:
    import yaml
except ImportError:
    print("❌ PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    raise SystemExit(2)

from scripts import auto_managed  # noqa: E402
from scripts._break_glass import add_break_glass_flag, apply_break_glass  # noqa: E402

SCRIPT_BASENAME = "drift_check.py"
GATE_NAME = "drift-check"

DEFAULT_REGISTRY_PATH = Path.home() / ".ai-playbook" / "projects.yaml"

INHERITS_PIN_RE = re.compile(
    r"github\.com/[^@\s]+@v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
)
MD_LINK_RE = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<target>[^)]+)\)")
BEGIN_MARKER_RE = re.compile(r"<!--\s*BEGIN auto-managed:")

CHECK_CHOICES = ("inherits", "auto-managed", "xref", "taxonomy", "all")

IGNORE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__",
    ".idea", ".vscode", "dist", "build", ".next", ".turbo",
    ".cache", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    "archive",
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class DriftFinding:
    """One drift hit. ``fix_hint`` is a canonical FIX string."""

    kind: str
    where: str
    why: str
    fix_hint: str


# ---------------------------------------------------------------------------
# Canonical error emission
# ---------------------------------------------------------------------------


def _emit_error(
    *, why: str, where: str, fix: str, override_invocation: str | None = None
) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    if override_invocation is None:
        print("   OVERRIDE: none", file=sys.stderr)
    else:
        print(f"   OVERRIDE: {override_invocation}", file=sys.stderr)


def _emit_warn(finding: DriftFinding) -> None:
    print(f"⚠️  [{finding.kind}] {finding.why} at {finding.where}", file=sys.stderr)
    print(f"   FIX: {finding.fix_hint}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Registry + playbook root
# ---------------------------------------------------------------------------


def _load_registry(path: Path) -> dict:
    if not path.exists():
        return {"schema": "ai-playbook/projects-registry/v1", "projects": {}}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {"schema": "ai-playbook/projects-registry/v1", "projects": {}}
    if not isinstance(data, dict):
        return {"schema": "ai-playbook/projects-registry/v1", "projects": {}}
    if not isinstance(data.get("projects"), dict):
        data["projects"] = {}
    return data


def _playbook_version(playbook_root: Path) -> tuple[int, int, int] | None:
    vfile = playbook_root / "VERSION"
    if not vfile.is_file():
        return None
    raw = vfile.read_text(encoding="utf-8").strip().lstrip("v")
    parts = raw.split(".")
    if len(parts) != 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Check 1 — inherits_from drift
# ---------------------------------------------------------------------------


def _extract_inherits_pins(agents_md_text: str) -> list[tuple[int, int, int]]:
    """Return every playbook semver pin found in the frontmatter's ``inherits_from`` list."""
    pins: list[tuple[int, int, int]] = []
    text = agents_md_text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return pins
    rest = text[4:]
    end = rest.find("\n---\n")
    if end == -1:
        end = rest.find("\n---")
        if end == -1:
            return pins
    fm_text = rest[:end]
    try:
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError:
        return pins
    if not isinstance(fm, dict):
        return pins
    raw_list = fm.get("inherits_from")
    if not isinstance(raw_list, list):
        return pins
    for item in raw_list:
        if not isinstance(item, str):
            continue
        m = INHERITS_PIN_RE.search(item)
        if m is None:
            continue
        pins.append((int(m["major"]), int(m["minor"]), int(m["patch"])))
    return pins


def check_inherits(
    registry: dict, playbook_root: Path
) -> list[DriftFinding]:
    """Warn when a consumer's pin is >1 minor behind the playbook VERSION."""
    version = _playbook_version(playbook_root)
    if version is None:
        return [
            DriftFinding(
                kind="inherits",
                why="playbook VERSION file missing or malformed",
                where=f"{(playbook_root / 'VERSION').as_posix()}",
                fix_hint="restore <playbook>/VERSION with a 'MAJOR.MINOR.PATCH' line.",
            )
        ]
    major_now, minor_now, _ = version
    findings: list[DriftFinding] = []
    for name, entry in registry.get("projects", {}).items():
        project_path = Path(str(entry.get("path", "")))
        agents_md = project_path / "AGENTS.md"
        if not agents_md.is_file():
            continue
        try:
            text = agents_md.read_text(encoding="utf-8")
        except OSError:
            continue
        pins = _extract_inherits_pins(text)
        if not pins:
            findings.append(
                DriftFinding(
                    kind="inherits",
                    why=f"consumer '{name}' has no github.com/*/ai-playbook@<semver> pin",
                    where=agents_md.as_posix(),
                    fix_hint="add 'inherits_from: [github.com/Wizarck/ai-playbook@v"
                    f"{major_now}.{minor_now}.0]' to the frontmatter.",
                )
            )
            continue
        # Compare the highest pin vs playbook current.
        best = max(pins)
        best_major, best_minor, _ = best
        if best_major < major_now or (
            best_major == major_now and minor_now - best_minor > 1
        ):
            findings.append(
                DriftFinding(
                    kind="inherits",
                    why=(
                        f"consumer '{name}' pinned at v{best[0]}.{best[1]}.{best[2]}; "
                        f"playbook is v{major_now}.{minor_now} (>1 minor behind)"
                    ),
                    where=agents_md.as_posix(),
                    fix_hint=(
                        f"bump inherits_from to github.com/Wizarck/ai-playbook@v"
                        f"{major_now}.{minor_now}.0 and re-run tests."
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Check 2 — auto-managed drift (delegates)
# ---------------------------------------------------------------------------


def _iter_markdown(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*.md"):
        if not p.is_file():
            continue
        if any(part in IGNORE_DIRS or part.startswith(".") for part in p.relative_to(root).parts[:-1]):
            continue
        out.append(p)
    return out


def _files_with_auto_markers(roots: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for md in _iter_markdown(root):
            if md in seen:
                continue
            try:
                head = md.read_text(encoding="utf-8")
            except OSError:
                continue
            if BEGIN_MARKER_RE.search(head) is None:
                continue
            seen.add(md)
            out.append(md)
    return out


def check_auto_managed(
    roots: list[Path], playbook_root: Path, *, fix: bool
) -> list[DriftFinding]:
    """Check (and optionally fix) auto-managed sections across ``roots``."""
    findings: list[DriftFinding] = []
    for md in _files_with_auto_markers(roots):
        try:
            if fix:
                diffs = auto_managed.apply_fix(md, playbook_root)
            else:
                diffs = auto_managed.regenerate(md, playbook_root)
        except ValueError as exc:
            findings.append(
                DriftFinding(
                    kind="auto-managed",
                    why=f"marker syntax error: {exc}",
                    where=md.as_posix(),
                    fix_hint="repair the BEGIN/END marker pairs and re-run.",
                )
            )
            continue
        except FileNotFoundError as exc:
            findings.append(
                DriftFinding(
                    kind="auto-managed",
                    why=f"source file missing: {exc}",
                    where=md.as_posix(),
                    fix_hint="verify playbook checkout + fix source_spec path in marker.",
                )
            )
            continue
        except LookupError as exc:
            findings.append(
                DriftFinding(
                    kind="auto-managed",
                    why=f"source anchor missing: {exc}",
                    where=md.as_posix(),
                    fix_hint="rename the source heading or update the source_spec anchor.",
                )
            )
            continue
        stale = [d for d in diffs if d.changed]
        for d in stale:
            verb = "rewrote" if fix else "stale"
            findings.append(
                DriftFinding(
                    kind="auto-managed",
                    why=f"{verb} section [{d.source}] lines {d.start_line}..{d.end_line}",
                    where=md.as_posix(),
                    fix_hint="run `python -m scripts.auto_managed <file> --fix`.",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Check 3 — xref drift
# ---------------------------------------------------------------------------


def check_xrefs(playbook_root: Path) -> list[DriftFinding]:
    """Relative markdown links inside ``specs/*.md`` pointing at missing files."""
    findings: list[DriftFinding] = []
    specs_dir = playbook_root / "specs"
    if not specs_dir.is_dir():
        return findings
    for md in sorted(specs_dir.glob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in MD_LINK_RE.finditer(text):
            target = m.group("target").strip()
            # Skip anchors, absolute URLs, and in-page refs.
            if target.startswith("#"):
                continue
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if target.startswith("/"):
                continue
            # Strip anchor suffix and optional title.
            target_path, _, _ = target.partition("#")
            target_path = target_path.strip()
            if not target_path:
                continue
            if not target_path.endswith(".md"):
                continue
            resolved = (md.parent / target_path).resolve()
            if resolved.is_file():
                continue
            findings.append(
                DriftFinding(
                    kind="xref",
                    why=f"broken link [{m.group('text')}]({target_path})",
                    where=md.as_posix(),
                    fix_hint=f"create {target_path} or update the link text/path.",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Check 4 — taxonomy term drift
# ---------------------------------------------------------------------------


_TAXONOMY_TERM_RE = re.compile(r"^\|\s*([A-Z][^|]+?)\s*\|", re.MULTILINE)
_WORD_CANDIDATE_RE = re.compile(r"(?<![A-Za-z])(?P<cap>[A-Z][A-Za-z]{2,})")

# Words that are common English nouns / project names and would flood the
# heuristic. Keep conservative; the 3-file threshold already filters noise.
_TAXONOMY_STOPWORDS = {
    "The", "This", "That", "These", "Those", "Here", "There",
    "When", "Where", "While", "What", "Which", "Who", "Why", "How",
    "From", "Into", "Onto", "Over", "Under", "With", "Without", "Within",
    "And", "Also", "Above", "Below", "After", "Before", "Between",
    "For", "Then", "Than", "Such", "Some", "Each", "Every", "Any",
    "TODO", "NOTE", "FIXME", "BEGIN", "END", "YAML", "JSON", "HTML",
    "API", "CLI", "CI", "URL", "UTC", "ISO", "UTF",
    "Arturo", "consumer-d", "Python", "Claude", "GitHub", "Git", "OpenSpec",
    "README", "AGENTS", "CLAUDE", "BRAIN", "LLM",
}


def _taxonomy_terms(playbook_root: Path) -> set[str]:
    """Extract the set of defined taxonomy terms from §1..§3 of ``specs/taxonomy.md``."""
    f = playbook_root / "specs" / "taxonomy.md"
    if not f.is_file():
        return set()
    text = f.read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = text.split("\n")
    # Restrict to §1..§3 window.
    start_idx = 0
    end_idx = len(lines)
    for i, line in enumerate(lines):
        if line.strip() == "## 1 Runtime entities":
            start_idx = i
        elif line.strip().startswith("## 4 "):
            end_idx = i
            break
    window = "\n".join(lines[start_idx:end_idx])

    terms: set[str] = set()
    for m in _TAXONOMY_TERM_RE.finditer(window):
        cell = m.group(1).strip()
        if not cell or cell.lower() in {"term", "---"}:
            continue
        # A defined term is the first column; tokenise the multi-word form.
        # We record both the whole phrase and each capitalised word.
        terms.add(cell)
        for word in cell.split():
            word = word.strip(",.()")
            if word and word[0].isupper():
                terms.add(word)
    return terms


def check_taxonomy(playbook_root: Path, *, min_files: int = 3) -> list[DriftFinding]:
    defined = _taxonomy_terms(playbook_root)
    if not defined:
        return []
    scan_roots = [playbook_root / "specs", playbook_root / "docs"]
    counts: dict[str, set[Path]] = defaultdict(set)
    for root in scan_roots:
        if not root.is_dir():
            continue
        for md in _iter_markdown(root):
            if md.name == "taxonomy.md":
                continue
            try:
                text = md.read_text(encoding="utf-8")
            except OSError:
                continue
            # Skip frontmatter + code fences to cut noise.
            body = _strip_non_prose(text)
            for m in _WORD_CANDIDATE_RE.finditer(body):
                word = m.group("cap")
                if word in _TAXONOMY_STOPWORDS:
                    continue
                if word in defined:
                    continue
                counts[word].add(md)

    findings: list[DriftFinding] = []
    for word, files in sorted(counts.items()):
        if len(files) < min_files:
            continue
        sample = ", ".join(sorted(f.as_posix() for f in list(files)[:3]))
        findings.append(
            DriftFinding(
                kind="taxonomy",
                why=f"undefined term '{word}' appears in {len(files)} files",
                where=sample,
                fix_hint=(
                    f"either add '{word}' to specs/taxonomy.md §1..§3 with a "
                    "definition or rename the usages to an already-defined term."
                ),
            )
        )
    return findings


def _strip_non_prose(text: str) -> str:
    text = text.replace("\r\n", "\n")
    # Strip YAML frontmatter.
    if text.startswith("---\n"):
        rest = text[4:]
        end = rest.find("\n---\n")
        if end != -1:
            text = rest[end + len("\n---\n"):]
    # Strip fenced code blocks.
    out_lines: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _run_checks(
    *,
    which: str,
    playbook_root: Path,
    registry: dict,
    extra_roots: list[Path],
    fix: bool,
) -> list[DriftFinding]:
    findings: list[DriftFinding] = []
    run_all = which == "all"

    if run_all or which == "inherits":
        findings.extend(check_inherits(registry, playbook_root))

    if run_all or which == "auto-managed":
        roots: list[Path] = [playbook_root]
        for entry in registry.get("projects", {}).values():
            p = Path(str(entry.get("path", "")))
            if p.is_dir():
                roots.append(p)
        roots.extend(r for r in extra_roots if r.is_dir())
        findings.extend(check_auto_managed(roots, playbook_root, fix=fix))

    if run_all or which == "xref":
        findings.extend(check_xrefs(playbook_root))

    if run_all or which == "taxonomy":
        findings.extend(check_taxonomy(playbook_root))

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="drift_check",
        description="Detect drift across the playbook + its consumers.",
    )
    parser.add_argument("--consumer-root", dest="consumer_roots", action="append",
                        type=Path, default=[],
                        help="Extra consumer repo root(s) to scan. "
                        "Repeatable. Registry entries are scanned automatically.")
    parser.add_argument("--registry", type=Path, default=None,
                        help="Registry YAML path "
                        "(default: ~/.ai-playbook/projects.yaml).")
    parser.add_argument("--check", choices=CHECK_CHOICES, default="all",
                        help="Which check to run (default: all).")
    parser.add_argument("--fix", action="store_true",
                        help="Rewrite stale auto-managed sections in-place "
                        "(other checks remain reporting-only).")
    parser.add_argument("--playbook-root", type=Path, default=None,
                        help="Explicit playbook root "
                        "(default: auto-detected from this script's location).")
    add_break_glass_flag(parser)
    args = parser.parse_args(argv)

    playbook_root = (
        args.playbook_root.expanduser().resolve()
        if args.playbook_root is not None
        else auto_managed.find_playbook_root()
    )
    if playbook_root is None or not (playbook_root / "specs").is_dir():
        _emit_error(
            why="ai-playbook root not found (no specs/ + scripts/ pair)",
            where=f"{SCRIPT_BASENAME}:playbook-root",
            fix="pass --playbook-root <path>, or run from inside an "
            "ai-playbook checkout.",
        )
        return 2

    registry_path = (
        args.registry.expanduser()
        if args.registry is not None
        else DEFAULT_REGISTRY_PATH
    )
    registry = _load_registry(registry_path)

    extra_roots = [p.expanduser().resolve() for p in (args.consumer_roots or [])]

    findings = _run_checks(
        which=args.check,
        playbook_root=playbook_root,
        registry=registry,
        extra_roots=extra_roots,
        fix=args.fix,
    )

    if not findings:
        print("✅ No drift detected.")
        return 0

    # When `--fix` applied, auto-managed rewrites are not a failure — they were
    # remediated. Filter those out of the failure set before escalating.
    if args.fix:
        remaining = [f for f in findings if f.kind != "auto-managed"]
        # Still surface what was rewritten for the audit trail.
        rewrote = len(findings) - len(remaining)
        if rewrote:
            print(f"✅ Rewrote {rewrote} auto-managed section(s).")
        if not remaining:
            return 0
        findings = remaining

    # Print findings as warnings (reporting) + one canonical error trailer.
    for f in findings:
        _emit_warn(f)

    result = apply_break_glass(
        gate=GATE_NAME,
        script=SCRIPT_BASENAME,
        reason=args.force_reason,
        override_allowed=True,
        repo_root=playbook_root,
    )
    if result.applied:
        print(f"⚠️ OVERRIDE APPLIED: {result.reason}")
        return 0

    _emit_error(
        why=f"{len(findings)} drift finding(s) across checks={args.check}",
        where=f"{SCRIPT_BASENAME}:report",
        fix="address each ⚠️ above; re-run `python -m scripts.drift_check "
        "--check all` after the fix.",
        override_invocation='python -m scripts.drift_check '
        '--force-with-reason="<why>"',
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
