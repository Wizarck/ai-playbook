"""Primitives shared by the manifest-driven hardrules.

Extracted from `capability-wiring.rule.py` when `repo-hygiene.rule.py` turned
out to need the same glob expansion, the same `{token}` interpolation, the same
`allow` semantics and the same break-glass parsing. The two rules ask different
questions — "is this capability wired?" vs "is this dependency used, is this
artifact stale?" — but they read their contracts the same way, so the reading
lives here once.

What is deliberately NOT here: each rule's `Finding` dataclass. Their fields and
their rendered lines differ, and collapsing them would buy a shared name at the
cost of a union type nobody can read. DRY applies to logic, not to coincidence.

Stdlib-only. These run at pre-commit inside consumer checkouts that ship only
the `.ai-playbook` submodule — no venv, no site-packages beyond pyyaml.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SEVERITIES = ("S1", "S2", "S3", "S4")

# S3/S4 print but never reach a non-zero exit. Calibrating on the CONSEQUENCE
# rather than the size of the fix is what keeps this list short enough to matter;
# see docs/rules/verdict-contract.rule.md §Severity levels.
BLOCKING = ("S1", "S2")

# Directories never worth walking. Two of them (`node_modules`, `.venv`) would
# otherwise dominate the walk time of every glob in every rule.
PRUNE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".next",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
}


class ConfigError(Exception):
    """Anything that makes a contract unevaluable. Always exit 2, never exit 1.

    The distinction is the point: exit 1 means "the repo has findings", exit 2
    means "the question could not be asked". Collapsing them would let a broken
    contract read as a clean repo — the failure mode these rules exist to stop.
    """


# ---------------------------------------------------------------------------
# Error shape — docs/rules/error-message-standard.rule.md
# ---------------------------------------------------------------------------


def emit_error(why: str, where: str, fix: str, override: str = "none") -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(f"   OVERRIDE: {override}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Glob expansion
# ---------------------------------------------------------------------------


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a POSIX-ish glob to a regex.

    Only `*`, `**` and `?` are metacharacters; everything else — crucially
    `(`, `)`, `[`, `]` — is escaped and matched literally. Python's own
    `Path.glob` treats `[seq]` as a character class, which would silently
    mangle real paths such as Next.js route groups (`app/(ops)/...`) or any
    path containing a bracket. `*` does not cross `/`; `**` does.
    """
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        char = pattern[i]
        if char == "*":
            if pattern.startswith("**", i):
                i += 2
                if pattern.startswith("/", i):
                    # `a/**/b` must also match `a/b` — the zero-directory case.
                    out.append("(?:.*/)?")
                    i += 1
                else:
                    out.append(".*")
            else:
                out.append("[^/]*")
                i += 1
        elif char == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(char))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def walk_root(pattern: str) -> str:
    """Longest literal directory prefix of `pattern`, so we never walk the repo."""
    positions = [p for p in (pattern.find("*"), pattern.find("?")) if p != -1]
    if not positions:
        return pattern
    head = pattern[: min(positions)]
    slash = head.rfind("/")
    return head[:slash] if slash != -1 else ""


def expand_glob(root: Path, pattern: str) -> list[str]:
    """Return root-relative POSIX paths matching `pattern`, sorted."""
    if "*" not in pattern and "?" not in pattern:
        # Literal path: no globbing at all. This is what keeps `(ops)` and any
        # bracketed directory working, and it is also the fast path.
        return [pattern] if (root / pattern).is_file() else []

    base = root / walk_root(pattern)
    if not base.is_dir():
        return []
    rx = glob_to_regex(pattern)
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        prefix = "" if rel_dir == "." else rel_dir + "/"
        for fname in filenames:
            rel = prefix + fname
            if rx.match(rel):
                found.append(rel)
    return sorted(found)


# ---------------------------------------------------------------------------
# `{token}` interpolation
# ---------------------------------------------------------------------------

# Only lowercase identifiers are candidate tokens, so regex quantifiers survive
# untouched: `{0,300}` and `{3}` are not matched here. That is why these engines
# never use `str.format` — a pattern is full of braces that mean quantifier.
TOKEN_RE = re.compile(r"\{([a-z_]+)\}")


def used_tokens(pattern: str) -> list[str]:
    return list(dict.fromkeys(TOKEN_RE.findall(pattern)))


def interpolate(pattern: str, bindings: dict[str, str]) -> str:
    """Substitute `{token}`s, `re.escape`ing every value first.

    Escaping is what makes a token incapable of injecting metacharacters: a path
    containing `.` or `(` can never alter the meaning of the surrounding regex.

    An unbound token raises rather than substituting empty. Substituting empty
    would widen the regex enormously and report a permanent, silent green.
    """
    def _sub(match: re.Match[str]) -> str:
        token = match.group(1)
        if token not in bindings:
            raise ConfigError(f"unknown or unbound interpolation token {{{token}}}")
        return re.escape(bindings[token])

    return TOKEN_RE.sub(_sub, pattern)


def compile_flags(spec: str) -> int:
    flags = re.NOFLAG
    for char in spec:
        if char == "i":
            flags |= re.IGNORECASE
        elif char == "m":
            flags |= re.MULTILINE
        elif char == "s":
            flags |= re.DOTALL
        else:
            # `x` is refused on purpose: verbose mode silently eats the spaces
            # that carry meaning inside a search pattern.
            raise ConfigError(f"unsupported regex flag {char!r} (allowed: i, m, s)")
    return flags


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


# ---------------------------------------------------------------------------
# `allow` semantics
# ---------------------------------------------------------------------------


def allow_matches(pattern: str, item_id: str) -> bool:
    """Exact match, or prefix match when the pattern ends in `*`.

    No other globbing: an exemption must not be able to quietly widen.
    """
    if pattern.endswith("*"):
        return item_id.startswith(pattern[:-1])
    return item_id == pattern


# ---------------------------------------------------------------------------
# Config discovery + git
# ---------------------------------------------------------------------------


def find_consumer_root(start: Path, marker: str) -> Path:
    """Nearest ancestor holding `.ai-playbook/` or the rule's own `marker` file."""
    start = start.resolve()
    for candidate in [start, *start.parents]:
        if (candidate / ".ai-playbook").is_dir() or (candidate / marker).is_file():
            return candidate
    return start


def resolve_config(explicit: str | None, marker: str) -> Path | None:
    if explicit:
        return Path(explicit)
    candidate = find_consumer_root(Path.cwd(), marker) / marker
    return candidate if candidate.is_file() else None


def changed_files(root: Path) -> set[str]:
    """Staged plus unstaged paths, root-relative POSIX."""
    out: set[str] = set()
    for args in (["diff", "--name-only", "--cached"], ["diff", "--name-only"]):
        try:
            proc = subprocess.run(
                ["git", *args], cwd=str(root), capture_output=True, text=True, check=False, timeout=30
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0:
            out.update(line.strip() for line in proc.stdout.splitlines() if line.strip())
    return out


def skip_directive(env_name: str) -> tuple[bool, set[str]]:
    """Parse `AIPLAYBOOK_*_SKIP` — `(skip_everything, {ids to skip})`.

    Per docs/rules/break-glass.rule.md the caller MUST log what it skipped.
    A silent break-glass is indistinguishable from a passing gate.
    """
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return False, set()
    if raw in ("1", "true", "TRUE", "yes"):
        return True, set()
    return False, {part.strip() for part in raw.split(",") if part.strip()}
