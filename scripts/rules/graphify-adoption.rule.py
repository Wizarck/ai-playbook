"""L1 hardrule: graphify-adoption (paired with docs/rules/graphify-adoption.rule.md).

Keeps a committed graphify knowledge graph portable and conflict-free across
developer machines. When a consumer commits `graphify-out/graph.json`, it
verifies that:

  * the root `.gitignore` ignores the per-machine / per-run graph state, and
  * the root `.gitattributes` maps `graphify-out/graph.json` to a merge driver
    (installed by `graphify hook install`).

A `graphifyy` CLI older than 0.8.31 (or absent) is reported as an advisory and
does NOT change the exit code. Repos that do not commit a graph are
not-applicable (exit 0).

CLI:
    python scripts/rules/graphify-adoption.rule.py validate
    python scripts/rules/graphify-adoption.rule.py apply [--dry-run]

Exit codes:
    0 — converged, not-applicable, or skipped.
    1 — missing `.gitignore` entries or `.gitattributes` graph.json merge mapping.
    2 — fatal (no readable consumer root).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SKIP_ENV = "AIPLAYBOOK_GRAPHIFY_ADOPTION_SKIP"
MIN_VERSION = (0, 8, 31)

# Per-machine / per-run state that MUST NOT be committed.
REQUIRED_ENTRIES: tuple[str, ...] = (
    "graphify-out/.graphify_python",
    "graphify-out/.graphify_uncached.txt",
    "graphify-out/cost.json",
    "graphify-out/cache/",
    "graphify-out/????-??-??/",
)

MANAGED_HEADER = "# === graphify knowledge-graph (do not remove) ==="


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(f"   OVERRIDE: {SKIP_ENV}=1", file=sys.stderr)


def _consumer_root(cwd: Path | None = None) -> Path | None:
    """Locate the consumer root: directory containing AGENTS.md."""
    cur = (cwd or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / "AGENTS.md").is_file():
            return p
    return None


def _applicable(root: Path) -> bool:
    """The rule applies only when the consumer commits a graph."""
    return (root / "graphify-out" / "graph.json").is_file()


def _read(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _missing_entries(text: str) -> list[str]:
    """Required entries not present as a non-comment line in `text`."""
    present: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        present.add(line)
    return [e for e in REQUIRED_ENTRIES if e not in present]


def _gitattributes_ok(text: str | None) -> bool:
    """True iff some line maps graph.json to a merge driver.

    Lenient on the driver name (owned by graphify): a non-comment line that
    mentions `graph.json` and carries a `merge=` attribute counts.
    """
    if not text:
        return False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "graph.json" in line and re.search(r"merge=\S+", line):
            return True
    return False


def _version_advisory() -> str | None:
    """Best-effort graphifyy version check. Returns an advisory string or None."""
    exe = shutil.which("graphify")
    if not exe:
        return (
            "graphifyy CLI not on PATH — install `graphifyy>=0.8.31` "
            "(`uv tool install \"graphifyy>=0.8.31\"`) and run `graphify hook install`."
        )
    try:
        out = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", (out.stdout or "") + (out.stderr or ""))
    if not m:
        return None
    ver = tuple(int(g) for g in m.groups())
    if ver < MIN_VERSION:
        got = ".".join(map(str, ver))
        floor = ".".join(map(str, MIN_VERSION))
        return (
            f"graphifyy {got} < {floor} — earlier versions bake absolute machine "
            f"paths into the graph. Upgrade so the committed graph stays portable."
        )
    return None


def validate(cwd: Path | None = None) -> int:
    if os.environ.get(SKIP_ENV):
        return 0
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2
    if not _applicable(root):
        return 0  # repo does not commit a graphify graph

    failed = False

    gitignore = root / ".gitignore"
    text = _read(gitignore)
    if text is None:
        _emit_error(
            why=".gitignore missing or unreadable",
            where=str(gitignore),
            fix="run `python .ai-playbook/scripts/rules/graphify-adoption.rule.py apply`.",
        )
        failed = True
    else:
        missing = _missing_entries(text)
        if missing:
            _emit_error(
                why=f".gitignore missing graphify entries: {', '.join(missing)}",
                where=str(gitignore),
                fix="run `python .ai-playbook/scripts/rules/graphify-adoption.rule.py apply`.",
            )
            failed = True

    gitattributes = root / ".gitattributes"
    if not _gitattributes_ok(_read(gitattributes)):
        _emit_error(
            why="no merge driver registered for graphify-out/graph.json",
            where=str(gitattributes),
            fix="run `graphify hook install` once per clone (writes the .gitattributes "
            "line + the per-clone merge driver).",
        )
        failed = True

    advisory = _version_advisory()
    if advisory:
        print(f"⚠ advisory: {advisory}", file=sys.stderr)

    return 1 if failed else 0


def apply(*, dry_run: bool, cwd: Path | None = None) -> int:
    """Append missing `.gitignore` entries under a managed header. Idempotent.

    The `.gitattributes` merge-driver line is intentionally NOT synthesized here
    — its driver name is owned by graphify; `graphify hook install` writes it.
    """
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2
    if not _applicable(root):
        print("ok: no committed graphify graph (graphify-out/graph.json absent) — not applicable")
        return 0

    gitignore = root / ".gitignore"
    existing = _read(gitignore) or ""
    missing = _missing_entries(existing)

    if not missing:
        print(f"ok: {gitignore} already contains all graphify entries (no-op)")
    else:
        sep = "" if (existing == "" or existing.endswith("\n")) else "\n"
        block = sep + ("\n" if existing else "") + "\n".join([MANAGED_HEADER, *missing]) + "\n"
        if dry_run:
            print(f"[dry-run] would append {len(missing)} entry(ies) to {gitignore}:")
            for e in missing:
                print(f"           + {e}")
        else:
            try:
                gitignore.write_text(existing + block, encoding="utf-8")
            except OSError as exc:
                print(f"error: cannot write {gitignore}: {exc}", file=sys.stderr)
                return 2
            print(f"appended {len(missing)} entry(ies) to {gitignore}")

    if not _gitattributes_ok(_read(root / ".gitattributes")):
        print(
            "note: graph.json merge driver not registered — run `graphify hook install` "
            "once per clone (apply does not synthesize the driver name).",
            file=sys.stderr,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="graphify-adoption")
    parser.add_argument("subcommand", choices=["validate", "apply"])
    parser.add_argument("--dry-run", action="store_true", help="With 'apply': print plan, mutate nothing.")
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    if args.subcommand == "apply":
        return apply(dry_run=args.dry_run)
    return 2


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("graphify-adoption", main))
