#!/usr/bin/env python3
"""PreToolUse hook: block Edit/Write/MultiEdit/Bash on a slice's write_paths
unless the openspec-apply-change skill has signalled a `start` marker for
the current Claude session.

Shipped with ai-playbook v0.20.0 (Bash interception, telemetry v2, feature flag).

Contracts:
- docs/rules/apply-skill-enforcement.rule.md (rule definition + Bash extension)
- docs/rules/error-message-standard.rule.md (block message shape)
- docs/rules/break-glass.rule.md (AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE env)
- docs/concepts/telemetry-design.md (rule-event/v2 schema)

Feature flags:
- AIPLAYBOOK_BASH_INSPECTION (default "1"; set "0" to skip the Bash branch
  while keeping Edit/Write/MultiEdit gated — emergency rollback).
- AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE (>=10 chars; honored as break-glass for
  all gated tools per docs/rules/break-glass.rule.md).

Telemetry: emits one rule-event/v2 JSONL row per decision (allow/block/warn)
via scripts.telemetry.rule_event_logger.log_event. Fail-safe: telemetry
exceptions never affect the hook's decision.

Bash inspection policy: conservative high-confidence-or-pass. The heuristic
recognises explicit mutation patterns (>, >>, tee, sed -i, python -c open,
PowerShell Out-File/Set-Content, etc.). Ambiguous commands pass through with
a stderr warning. See `_extract_bash_targets` for the full pattern table.

Adoption notes
--------------
1. Copy this template to `.claude/hooks/openspec-apply-enforce.py` in the
   consumer project (project-local; not a global hook).
2. Register it in `.claude/settings.json` under
   `hooks.PreToolUse[*].matcher = "Edit|Write|MultiEdit|Bash"`.
3. Helper script `.ai-playbook/scripts/openspec_apply_marker.py` must be
   reachable from the project root (delivered via the `.ai-playbook` git
   submodule).

This file is plain Python (no template placeholders today; rendering is a
copy). If future placeholders are introduced, document them at the top of
this header.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


MARKER_HELPER_REL = Path(".ai-playbook/scripts/openspec_apply_marker.py")
GATED_TOOLS = {"Edit", "Write", "MultiEdit", "Bash"}
WRITE_PATHS_HEADING_RE = re.compile(r"^\s*##\s*owns\b.*write_paths", re.IGNORECASE)
NEXT_HEADING_RE = re.compile(r"^\s*##\s+")
BULLET_PATH_RE = re.compile(r"^\s*[*\-]\s+`([^`]+)`")

RULE_SLUG = "apply-skill-enforcement"

# Per-process memoization of write_paths parsing, keyed by (path, mtime_ns).
# PreToolUse hook processes are short-lived (one tool call each), but the
# cache is harmless and useful if the hook ever runs in a longer-lived shell.
_TASKS_CACHE: dict[tuple[str, int], list[str]] = {}

# Per-process memoization of the rules-toggle state file, keyed by mtime_ns.
# Value is the parsed dict (or None if absent/corrupt — treated as "all ON").
# Same lifecycle as _TASKS_CACHE.
_TOGGLE_CACHE: dict[int, dict] = {}


# ============================================================================
# Bash command inspection (POSIX + PowerShell heuristics).
#
# Each entry: (pattern_kind, compiled_regex). Patterns must use named group
# `path` to indicate the captured target. Evaluated in order; more specific
# patterns first.
#
# Conservative policy: regex matches must be unambiguous. If no pattern fires,
# the hook passes without blocking and emits a stderr warning for visibility.
# ============================================================================

# POSIX in-place editors (very high confidence: the path is the target).
_POSIX_SED_INPLACE = re.compile(
    r"""\bsed\b(?:\s+-[a-zA-Z]*i[a-zA-Z]*|\s+--in-place)\b
        (?:\s+(?:-[^\s'"]+|"[^"]*"|'[^']*'))*
        \s+(?:(?P<q1>')(?P<path1>[^']+)'|(?P<q2>")(?P<path2>[^"]+)"|(?P<path3>[^\s|&;()<>]+))
    """,
    re.VERBOSE,
)

_POSIX_AWK_INPLACE = re.compile(
    r"""\b(?:gawk|awk)\b\s+-i\s+inplace\b
        (?:\s+(?:-[^\s'"]+|"[^"]*"|'[^']*'))*
        \s+(?:(?P<q1>')(?P<path1>[^']+)'|(?P<q2>")(?P<path2>[^"]+)"|(?P<path3>[^\s|&;()<>]+))
    """,
    re.VERBOSE,
)

_POSIX_PERL_INPLACE = re.compile(
    r"""\bperl\b\s+-[a-zA-Z]*i[a-zA-Z]*\b
        (?:\s+(?:-[^\s'"]+|"[^"]*"|'[^']*'|-?[a-zA-Z]))*?
        \s+(?:(?P<q1>')(?P<path1>[^']+)'|(?P<q2>")(?P<path2>[^"]+)"|(?P<path3>[^\s|&;()<>]+))(?:\s|$)
    """,
    re.VERBOSE,
)

# python -c "...open('path', 'w'/'a')..." — must include write mode.
_PYTHON_OPEN_WRITE = re.compile(
    r"""(?:python3?|py)\s+-c\s+(?P<outer_q>['"])
        [^'"]*?(?:open|Path)\s*\(\s*
        (?P<inner_q>['"])(?P<path>[^'"]+)(?P=inner_q)
        \s*,\s*
        (?P<mode_q>['"])(?:w|a|wb|ab|w\+|a\+|x)(?P=mode_q)
    """,
    re.VERBOSE | re.DOTALL,
)

# python -c "...write_text('path', ...)..." or pathlib write_*.
_PYTHON_WRITE_TEXT = re.compile(
    r"""(?:python3?|py)\s+-c\s+(?P<outer_q>['"])
        [^'"]*?\.(?:write_text|write_bytes)\s*\(\s*
        (?P<inner_q>['"])(?P<path>[^'"]+)(?P=inner_q)
    """,
    re.VERBOSE | re.DOTALL,
)

# node -e "...writeFileSync('path', ...)..." / appendFileSync.
_NODE_WRITEFILE = re.compile(
    r"""\bnode\s+-e\s+(?P<outer_q>['"])
        [^'"]*?(?:writeFileSync|appendFileSync)\s*\(\s*
        (?P<inner_q>['"])(?P<path>[^'"]+)(?P=inner_q)
    """,
    re.VERBOSE | re.DOTALL,
)

# tee path / tee -a path. Only treats the target argument as a mutation.
_POSIX_TEE = re.compile(
    r"""\btee\b(?:\s+-[aA])?\s+
        (?:(?P<q1>')(?P<path1>[^']+)'|(?P<q2>")(?P<path2>[^"]+)"|(?P<path3>[^\s|&;()<>]+))
    """,
    re.VERBOSE,
)

# > path and >> path (POSIX redirects). Excludes `2>` stderr redirects via
# the lookbehind on the digit prefix being optional but skipping bare `2>`,
# `&>`, etc. — common safe redirections.
_POSIX_REDIRECT_WRITE = re.compile(
    r"""(?<![<>\d&])>(?!&)\s*
        (?:(?P<q1>')(?P<path1>[^']+)'|(?P<q2>")(?P<path2>[^"]+)"|(?P<path3>[^\s|&;()<>]+))
    """,
    re.VERBOSE,
)

_POSIX_REDIRECT_APPEND = re.compile(
    r""">>\s*
        (?:(?P<q1>')(?P<path1>[^']+)'|(?P<q2>")(?P<path2>[^"]+)"|(?P<path3>[^\s|&;()<>]+))
    """,
    re.VERBOSE,
)

# PowerShell: Out-File path / -FilePath path.
_PS_OUTFILE = re.compile(
    r"""\bOut-File\b
        (?:\s+-(?!FilePath\b|LiteralPath\b)[a-zA-Z]+(?:\s+\S+)?)*
        \s+(?:-FilePath\s+|-LiteralPath\s+)?
        (?:(?P<q1>')(?P<path1>[^']+)'|(?P<q2>")(?P<path2>[^"]+)"|(?P<path3>[^\s|&;()<>]+))
    """,
    re.VERBOSE,
)

_PS_SETCONTENT = re.compile(
    r"""\bSet-Content\b
        (?:\s+-(?!Path\b|LiteralPath\b)[a-zA-Z]+(?:\s+\S+)?)*
        \s+(?:-Path\s+|-LiteralPath\s+)?
        (?:(?P<q1>')(?P<path1>[^']+)'|(?P<q2>")(?P<path2>[^"]+)"|(?P<path3>[^\s|&;()<>]+))
    """,
    re.VERBOSE,
)

_PS_ADDCONTENT = re.compile(
    r"""\bAdd-Content\b
        (?:\s+-(?!Path\b|LiteralPath\b)[a-zA-Z]+(?:\s+\S+)?)*
        \s+(?:-Path\s+|-LiteralPath\s+)?
        (?:(?P<q1>')(?P<path1>[^']+)'|(?P<q2>")(?P<path2>[^"]+)"|(?P<path3>[^\s|&;()<>]+))
    """,
    re.VERBOSE,
)

# PowerShell New-Item -ItemType File path.
_PS_NEWITEM = re.compile(
    r"""\bNew-Item\b
        (?:\s+-(?!Path\b|LiteralPath\b)[a-zA-Z]+(?:\s+\S+)?)*
        \s+(?:-Path\s+|-LiteralPath\s+)?
        (?:(?P<q1>')(?P<path1>[^']+)'|(?P<q2>")(?P<path2>[^"]+)"|(?P<path3>[^\s|&;()<>]+))
        (?=.*?-ItemType\s+File)
    """,
    re.VERBOSE | re.DOTALL,
)

# Ordered list: more specific patterns first (in-place, interpreter writes,
# PowerShell, tee). Generic redirections last to give specific patterns
# priority on the same path token.
_BASH_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("sed-i", _POSIX_SED_INPLACE),
    ("awk-i-inplace", _POSIX_AWK_INPLACE),
    ("perl-i", _POSIX_PERL_INPLACE),
    ("python-c-open", _PYTHON_OPEN_WRITE),
    ("python-c-write-text", _PYTHON_WRITE_TEXT),
    ("node-e-writeFile", _NODE_WRITEFILE),
    ("powershell-outfile", _PS_OUTFILE),
    ("powershell-setcontent", _PS_SETCONTENT),
    ("powershell-addcontent", _PS_ADDCONTENT),
    ("powershell-newitem", _PS_NEWITEM),
    ("tee", _POSIX_TEE),
    ("redirect-append", _POSIX_REDIRECT_APPEND),
    ("redirect-write", _POSIX_REDIRECT_WRITE),
]


def _extract_bash_targets(command: str) -> list[tuple[str, str]]:
    """Return [(target_token, pattern_kind), ...] for high-confidence mutations.

    No-op heuristic: a target is a literal string that the command's surface
    syntax says will be written. Returns [] for commands without recognisable
    mutation patterns (git, builds, formatters, scripts wrapping syscall
    writes). Variables, subshells, and pipe expansions are intentionally not
    resolved (FN accepted; L3 catches them post-merge).
    """
    if not command:
        return []
    seen: set[tuple[str, str]] = set()
    results: list[tuple[str, str]] = []
    for kind, pattern in _BASH_PATTERNS:
        for match in pattern.finditer(command):
            groups = match.groupdict()
            path = groups.get("path") or groups.get("path1") or groups.get("path2") or groups.get("path3")
            if not path:
                continue
            path = path.strip()
            if not path or path.startswith(("-", "$", "&")) or path in ("/dev/null", "/dev/stdout", "/dev/stderr"):
                continue
            key = (path, kind)
            if key in seen:
                continue
            seen.add(key)
            results.append((path, kind))
    return results


# ============================================================================
# I/O helpers.
# ============================================================================


def _read_stdin_payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _project_root(cwd: Path) -> Path:
    current = cwd.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "openspec" / "changes").is_dir():
            return candidate
    return cwd.resolve()


def _project_relative(project: Path, file_path: str) -> str | None:
    if not file_path:
        return None
    try:
        target = Path(file_path)
        if not target.is_absolute():
            target = (project / target).resolve()
        else:
            target = target.resolve()
        return str(target.relative_to(project)).replace("\\", "/")
    except ValueError:
        return None


def _parse_write_paths(tasks_md: Path) -> list[str]:
    """Parse `## Owns (write_paths)` bullets, memoized by (path, mtime_ns)."""
    if not tasks_md.is_file():
        return []
    try:
        mtime_ns = tasks_md.stat().st_mtime_ns
    except OSError:
        return _parse_write_paths_uncached(tasks_md)
    cache_key = (str(tasks_md), mtime_ns)
    cached = _TASKS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    parsed = _parse_write_paths_uncached(tasks_md)
    _TASKS_CACHE[cache_key] = parsed
    return parsed


def _parse_write_paths_uncached(tasks_md: Path) -> list[str]:
    out: list[str] = []
    in_section = False
    try:
        text = tasks_md.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        if WRITE_PATHS_HEADING_RE.match(line):
            in_section = True
            continue
        if in_section and NEXT_HEADING_RE.match(line):
            break
        if in_section:
            m = BULLET_PATH_RE.match(line)
            if m:
                out.append(m.group(1).strip())
    return out


def _path_matches(target: str, write_path: str) -> bool:
    """Glob-aware match. target and write_path are both project-relative."""
    target = target.replace("\\", "/")
    write_path = write_path.replace("\\", "/")
    if write_path == target:
        return True
    if fnmatch.fnmatchcase(target, write_path):
        return True
    return write_path.endswith("/") and target.startswith(write_path)


def _is_rule_disabled(project: Path, slug: str, layer: str = "L1") -> bool:
    """Return True if `slug` is OFF at `layer` per .ai-playbook/rules-toggle.json.

    Mirrors scripts/rules_toggle.is_rule_disabled — duplicated here so the hook
    runs without sys.path injection (PreToolUse subprocess context). Drift is
    guarded by tests/test_apply_enforce_helpers_equivalence.py.

    File absent / corrupt → False (fail-safe: rule ON).
    """
    p = project / ".ai-playbook" / "rules-toggle.json"
    if not p.is_file():
        return False
    try:
        mtime_ns = p.stat().st_mtime_ns
    except OSError:
        return False
    cached = _TOGGLE_CACHE.get(mtime_ns)
    if cached is None:
        try:
            cached = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        _TOGGLE_CACHE[mtime_ns] = cached
    entry = (cached.get("rules") or {}).get(slug)
    if entry is None:
        return False
    if entry.get("enabled") is False:
        return True
    layers = entry.get("layers") or {}
    return layers.get(layer) is False


def _find_matching_changes(project: Path, target_rel: str) -> list[tuple[str, list[str]]]:
    """Return [(change_id, matched_write_paths), ...] for active changes."""
    matches: list[tuple[str, list[str]]] = []
    changes_root = project / "openspec" / "changes"
    if not changes_root.is_dir():
        return matches
    for child in sorted(changes_root.iterdir()):
        if not child.is_dir():
            continue
        tasks_md = child / "tasks.md"
        if not tasks_md.is_file():
            continue
        write_paths = _parse_write_paths(tasks_md)
        matched = [wp for wp in write_paths if _path_matches(target_rel, wp)]
        if matched:
            matches.append((child.name, matched))
    return matches


def _is_change_own_folder(target_rel: str) -> bool:
    """`openspec/changes/<id>/anything` is part of the change's own metadata."""
    return target_rel.startswith("openspec/changes/")


def _session_started(project: Path, change_id: str, session_id: str) -> bool:
    helper = project / MARKER_HELPER_REL
    if not helper.is_file():
        print(
            f"⚠ apply-enforce: marker helper not found at {helper}; allowing edit",
            file=sys.stderr,
        )
        return True
    env = os.environ.copy()
    env["CLAUDE_SESSION_ID"] = session_id
    result = subprocess.run(
        [sys.executable, str(helper), "session_started", "--change-id", change_id],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _record_override(
    project: Path,
    change_id: str,
    reason: str,
    file_path: str,
    session_id: str,
) -> None:
    helper = project / MARKER_HELPER_REL
    if not helper.is_file():
        return
    env = os.environ.copy()
    env["CLAUDE_SESSION_ID"] = session_id
    subprocess.run(
        [
            sys.executable,
            str(helper),
            "override",
            "--change-id",
            change_id,
            "--reason",
            reason,
            "--file-path",
            file_path,
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


# ============================================================================
# Telemetry emission (rule-event/v2 via scripts.telemetry.rule_event_logger).
#
# Fail-safe: any exception is swallowed so the hook's decision is never
# affected by telemetry plumbing.
# ============================================================================


def _emit_telemetry(
    project: Path,
    verdict: str,
    tool_name: str,
    extra: dict,
    latency_ms: float,
    session_id: str,
    escape_hatch: str | None = None,
) -> None:
    try:
        # Prefer the submodule-shipped logger; fall back to PYTHONPATH.
        marker_helper = project / MARKER_HELPER_REL
        playbook_root = marker_helper.parent.parent if marker_helper.is_file() else None
        if playbook_root and str(playbook_root) not in sys.path:
            sys.path.insert(0, str(playbook_root))
        from scripts.telemetry.rule_event_logger import log_event  # type: ignore[import-not-found]

        state_dir_env = os.environ.get("AI_PLAYBOOK_STATE_DIR")
        state_dir = Path(state_dir_env) if state_dir_env else (project / ".ai-playbook-state")
        log_event(
            slug=RULE_SLUG,
            llm=os.environ.get("AI_PLAYBOOK_LLM", "unknown"),
            verdict=verdict,
            latency_ms=latency_ms,
            trigger=f"PreToolUse:{tool_name}",
            session_id=session_id,
            self_check=False,
            escape_hatch=escape_hatch,
            extra=extra,
            state_dir=state_dir,
        )
    except Exception:
        # Never break the hook on telemetry plumbing issues.
        pass


# ============================================================================
# Error message emission (per docs/rules/error-message-standard.rule.md).
# ============================================================================


def _emit_block_edit(change_id: str, target_rel: str) -> int:
    """Block message for Edit/Write/MultiEdit (deterministic detection)."""
    print(f"❌ apply phase bypass detected at {target_rel}", file=sys.stderr)
    print(
        f"   The tool tried to edit a path in the write_paths of `{change_id}`",
        file=sys.stderr,
    )
    print("   but this session has no `start` record in", file=sys.stderr)
    print(f"   `openspec/changes/{change_id}/.apply_log.jsonl`.", file=sys.stderr)
    print(
        f"   FIX: invoke the skill `/openspec-apply-change {change_id}` first,",
        file=sys.stderr,
    )
    print(
        f"        or run `python .ai-playbook/scripts/openspec_apply_marker.py start --change-id {change_id}`.",
        file=sys.stderr,
    )
    print(
        '   OVERRIDE: export AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE="<≥10-char reason>"',
        file=sys.stderr,
    )
    print(
        "   See: docs/rules/apply-skill-enforcement.rule.md §3 (break-glass clause).",
        file=sys.stderr,
    )
    return 2


def _emit_block_bash(
    change_id: str,
    target_rel: str,
    command: str,
    pattern_kind: str,
    matched_pattern: str,
) -> int:
    """Block message for Bash (heuristic detection; documents kind + override)."""
    truncated = (command[:60] + "…") if len(command) > 60 else command
    print(
        "❌ apply phase bypass detected (Bash command writes to declared write_path)",
        file=sys.stderr,
    )
    print(f"   at command: {truncated}", file=sys.stderr)
    print(f"   target: {target_rel}", file=sys.stderr)
    print(
        f"   change: `{change_id}` (pattern: {pattern_kind} → `{matched_pattern}`)",
        file=sys.stderr,
    )
    print(
        f"   FIX: invoke `/openspec-apply-change {change_id}` first, then use Edit/Write.",
        file=sys.stderr,
    )
    print(
        f"        If the change MUST happen via terminal, run:",
        file=sys.stderr,
    )
    print(
        f"        `python .ai-playbook/scripts/openspec_apply_marker.py start --change-id {change_id}`.",
        file=sys.stderr,
    )
    print(
        '   OVERRIDE: export AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE="<≥10-char reason>"',
        file=sys.stderr,
    )
    print(
        "   ROLLBACK: export AIPLAYBOOK_BASH_INSPECTION=0 (disables Bash gate only;",
        file=sys.stderr,
    )
    print("             keeps Edit/Write/MultiEdit gated).", file=sys.stderr)
    print(
        "   See: docs/rules/apply-skill-enforcement.rule.md (Bash heuristics).",
        file=sys.stderr,
    )
    return 2


# ============================================================================
# Decision flow per tool kind.
# ============================================================================


def _decide_edit(
    project: Path,
    tool_name: str,
    file_path: str,
    session_id: str,
    override_reason: str,
    start: float,
) -> int:
    """Edit/Write/MultiEdit deterministic path: tool_input.file_path is the target."""
    if _is_rule_disabled(project, RULE_SLUG, layer="L1"):
        _emit_telemetry(
            project, "warn", tool_name,
            {"block_tool": tool_name, "block_class": "rule_disabled", "toggle_layer": "L1"},
            (time.monotonic() - start) * 1000.0, session_id,
        )
        return 0
    target_rel = _project_relative(project, file_path)
    base_extra = {"block_tool": tool_name}

    if target_rel is None:
        _emit_telemetry(
            project, "allow", tool_name,
            {**base_extra, "block_class": "outside_project"},
            (time.monotonic() - start) * 1000.0, session_id,
        )
        return 0
    if _is_change_own_folder(target_rel):
        _emit_telemetry(
            project, "allow", tool_name,
            {**base_extra, "block_class": "change_own_folder", "target_rel": target_rel},
            (time.monotonic() - start) * 1000.0, session_id,
        )
        return 0

    matches = _find_matching_changes(project, target_rel)
    if not matches:
        _emit_telemetry(
            project, "allow", tool_name,
            {**base_extra, "block_class": "none", "target_rel": target_rel},
            (time.monotonic() - start) * 1000.0, session_id,
        )
        return 0

    # Allow if any matching change has a session_started record.
    for change_id, _wps in matches:
        if _session_started(project, change_id, session_id):
            _emit_telemetry(
                project, "allow", tool_name,
                {
                    **base_extra,
                    "block_class": "none",
                    "target_rel": target_rel,
                    "change_id": change_id,
                    "marker_present": True,
                },
                (time.monotonic() - start) * 1000.0, session_id,
            )
            return 0

    blocking_change, matched_wps = matches[0]

    # Override path.
    if override_reason and len(override_reason) >= 10:
        for change_id, _wps in matches:
            _record_override(project, change_id, override_reason, target_rel, session_id)
        _emit_telemetry(
            project, "allow", tool_name,
            {
                **base_extra,
                "block_class": "apply_phase_bypass",
                "target_rel": target_rel,
                "change_id": blocking_change,
                "matched_pattern": matched_wps[0] if matched_wps else "",
                "marker_present": False,
                "override_reason": override_reason,
            },
            (time.monotonic() - start) * 1000.0, session_id,
            escape_hatch="AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE",
        )
        return 0

    # Block.
    _emit_telemetry(
        project, "block", tool_name,
        {
            **base_extra,
            "block_class": "apply_phase_bypass",
            "target_rel": target_rel,
            "change_id": blocking_change,
            "matched_pattern": matched_wps[0] if matched_wps else "",
            "marker_present": False,
        },
        (time.monotonic() - start) * 1000.0, session_id,
    )
    return _emit_block_edit(blocking_change, target_rel)


def _decide_bash(
    project: Path,
    command: str,
    session_id: str,
    override_reason: str,
    start: float,
) -> int:
    """Bash heuristic path: extract candidate targets from the command surface."""
    if _is_rule_disabled(project, RULE_SLUG, layer="L1"):
        _emit_telemetry(
            project, "warn", "Bash",
            {"block_tool": "Bash", "block_class": "rule_disabled", "toggle_layer": "L1"},
            (time.monotonic() - start) * 1000.0, session_id,
        )
        return 0
    bash_flag = os.environ.get("AIPLAYBOOK_BASH_INSPECTION", "1").strip()
    feature_flag = {"bash_inspection": bash_flag}
    base_extra = {"block_tool": "Bash", "feature_flag": feature_flag}

    if bash_flag == "0":
        # Rollback flag honoured.
        _emit_telemetry(
            project, "allow", "Bash",
            {**base_extra, "block_class": "flag_disabled"},
            (time.monotonic() - start) * 1000.0, session_id,
        )
        return 0

    candidates = _extract_bash_targets(command)
    if not candidates:
        # Ambiguous command → pass with stderr warning + telemetry warn.
        # Warn-level telemetry only if we'd have something useful to log
        # (the marker is fail-open; no false-positive penalty either way).
        _emit_telemetry(
            project, "allow", "Bash",
            {**base_extra, "block_class": "none"},
            (time.monotonic() - start) * 1000.0, session_id,
        )
        return 0

    # For each candidate, check write_paths intersection.
    for target_token, pattern_kind in candidates:
        target_rel = _project_relative(project, target_token)
        if target_rel is None or _is_change_own_folder(target_rel):
            continue
        matches = _find_matching_changes(project, target_rel)
        if not matches:
            continue
        # Found a write_path match. Decide allow vs block.
        for change_id, _wps in matches:
            if _session_started(project, change_id, session_id):
                # Marker present → allow.
                _emit_telemetry(
                    project, "allow", "Bash",
                    {
                        **base_extra,
                        "block_class": "none",
                        "target_rel": target_rel,
                        "change_id": change_id,
                        "bash_pattern_kind": pattern_kind,
                        "marker_present": True,
                    },
                    (time.monotonic() - start) * 1000.0, session_id,
                )
                return 0

        blocking_change, matched_wps = matches[0]

        # Override.
        if override_reason and len(override_reason) >= 10:
            for change_id, _wps in matches:
                _record_override(project, change_id, override_reason, target_rel, session_id)
            _emit_telemetry(
                project, "allow", "Bash",
                {
                    **base_extra,
                    "block_class": "apply_phase_bypass",
                    "target_rel": target_rel,
                    "change_id": blocking_change,
                    "matched_pattern": matched_wps[0] if matched_wps else "",
                    "bash_pattern_kind": pattern_kind,
                    "marker_present": False,
                    "override_reason": override_reason,
                },
                (time.monotonic() - start) * 1000.0, session_id,
                escape_hatch="AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE",
            )
            return 0

        # Block.
        _emit_telemetry(
            project, "block", "Bash",
            {
                **base_extra,
                "block_class": "apply_phase_bypass",
                "target_rel": target_rel,
                "change_id": blocking_change,
                "matched_pattern": matched_wps[0] if matched_wps else "",
                "bash_pattern_kind": pattern_kind,
                "marker_present": False,
            },
            (time.monotonic() - start) * 1000.0, session_id,
        )
        return _emit_block_bash(
            blocking_change,
            target_rel,
            command,
            pattern_kind,
            matched_wps[0] if matched_wps else "",
        )

    # No candidate matched any write_path → allow.
    _emit_telemetry(
        project, "allow", "Bash",
        {**base_extra, "block_class": "none"},
        (time.monotonic() - start) * 1000.0, session_id,
    )
    return 0


# ============================================================================
# Entry point.
# ============================================================================


def main() -> int:
    start = time.monotonic()
    payload = _read_stdin_payload()
    tool_name = payload.get("tool_name", "")
    if tool_name not in GATED_TOOLS:
        return 0

    tool_input = payload.get("tool_input") or {}
    session_id = payload.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or ""
    cwd = Path(payload.get("cwd") or os.getcwd())
    project = _project_root(cwd)
    override_reason = os.environ.get("AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE", "").strip()

    if tool_name == "Bash":
        command = tool_input.get("command") or ""
        return _decide_bash(project, command, session_id, override_reason, start)

    # Edit / Write / MultiEdit.
    file_path = tool_input.get("file_path") or ""
    return _decide_edit(project, tool_name, file_path, session_id, override_reason, start)


if __name__ == "__main__":
    sys.exit(main())
