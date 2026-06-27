"""Ponytail discipline stats — count ``ponytail:`` shortcut markers in a tree.

Rung-1 measurement instrument for the telemetry dashboard's ponytail panel.
Where ``scripts/caveman/stats.py`` measures *output tokens saved*, this measures
a different signal: *deliberate simplifications taken* — the ``ponytail:``
comments that ``skills/ponytail-debt`` harvests into its debt ledger. One matched
line is one simplification, mirroring that skill's
``grep -rnE '(#|//) ?ponytail:'`` contract so the dashboard count and the
``/ponytail-debt`` ledger agree.

Honest by construction: this counts what is actually written in the tree, not an
LLM self-report. It is a *count of cuts taken*, not a dollar figure — see
``docs/concepts/ponytail-mode.md#discipline-methodology``.

Usage::

    python -m scripts.ponytail.stats [--root PATH] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Mirror skills/ponytail-debt's harvest regex so the dashboard count and the
# ledger agree. A comment prefix keeps prose that merely mentions the convention
# out of the count.
MARKER_RE = re.compile(r"(?:#|//) ?ponytail:")

# Directories never worth scanning (VCS, deps, build output, telemetry state).
# `.ai-playbook` / `.skills-sources` are the vendored playbook checkout in a
# consumer repo — skipping them keeps the count the *consumer's own* markers,
# not the playbook's (same segments the ponytail-reinforce hook skips).
SKIP_DIRS = frozenset(
    {
        ".git",
        ".ai-playbook",
        ".skills-sources",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "dist",
        "build",
        "site",
        ".ai-playbook-state",
        ".test",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)


@dataclass
class PonytailStats:
    markers: int = 0
    files_scanned: int = 0


def count_markers(root: Path) -> PonytailStats:
    """Walk ``root`` counting lines that carry a ``ponytail:`` comment marker.

    Binary / non-utf-8 files are skipped (best-effort, like grep on text). One
    matched line counts once, matching the ``/ponytail-debt`` ledger semantics.
    """
    stats = PonytailStats()
    # ponytail: full-tree walk on every dashboard build; add an mtime cache or
    # scope to the diff if this gets slow on large repos.
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            stats.files_scanned += 1
            for line in text.splitlines():
                if MARKER_RE.search(line):
                    stats.markers += 1
    return stats


def markers_added_since(root: Path, since_iso: str) -> int | None:
    """Count `ponytail:` markers ADDED to git history at-or-after ``since_iso``.

    A *flow* metric (cuts taken this window) complementing ``count_markers``'s
    *stock* (cuts currently in the tree). Counts ``+`` lines matching the marker
    regex across patches in the window — submodule-internal markers are excluded
    for free (the parent repo tracks submodules as pointers, not file lines).

    Returns ``None`` (not 0) when git is unavailable / ``root`` is not a repo /
    the call times out, so the caller can omit the field rather than fake a zero.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "log", "--since", since_iso,
             "--no-merges", "-p", "--format=%n", "--", "."],
            capture_output=True, text=True, timeout=8, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    count = 0
    for line in proc.stdout.splitlines():
        # Added content lines start with a single '+'; '+++' is a file header.
        if line.startswith("+") and not line.startswith("+++") and MARKER_RE.search(line):
            count += 1
    return count


def collect(root: Path, since_iso: str | None = None) -> dict:
    """Return the JSON-able stats dict consumed by the dashboard aggregator.

    With ``since_iso`` set, also includes ``markers_window`` (markers added in
    the window via git) — omitted entirely when git can't answer.
    """
    s = count_markers(root)
    out = {"markers": s.markers, "files_scanned": s.files_scanned}
    if since_iso is not None:
        window = markers_added_since(root, since_iso)
        if window is not None:
            out["markers_window"] = window
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.ponytail.stats",
        description="Count `ponytail:` simplification markers in a tree.",
    )
    parser.add_argument("--root", type=Path, default=None, help="Tree to scan. Default: cwd.")
    parser.add_argument("--since", default=None, help="ISO date; also count markers added in git since then.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)
    root = (args.root or Path.cwd()).resolve()
    data = collect(root, since_iso=args.since)
    if args.json:
        print(json.dumps(data))
    else:
        suffix = f"; {data['markers_window']} added since {args.since}" if "markers_window" in data else ""
        print(f"ponytail markers: {data['markers']}  (files scanned: {data['files_scanned']}{suffix})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
