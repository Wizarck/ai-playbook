#!/usr/bin/env python3
"""Execute an adjudicated sweep ledger: delete the file, leave a tombstone.

Companion to `sweep_scan.py`. The scanner finds candidates and never deletes;
this removes them and records how to get them back. Both halves stay separate on
purpose — finding and destroying should not be the same command, and no hook or
CI job should ever be able to invoke this one.

WHY A TOMBSTONE AND NOT A QUARANTINE DIRECTORY

The obvious design is to move dead files somewhere safe instead of deleting
them. It is worse in four ways, and the fourth is the one that matters:

1. It does not remove the cost. The tax on dead code is being IN THE TREE, not
   being imported — a quarantined file is still grepped, still searched by the
   IDE, still swept up by a rename refactor, still type-checked, still in the
   SBOM. Measured here: a repo-wide rename touched a file that nothing has
   called since the initial commit.
2. It can still run. A Python module under the package tree stays importable
   from anywhere you park it, and a TypeScript file stays bundleable. "In
   quarantine" is not "off", which is the most dangerous state of all because
   you believe otherwise.
3. It destroys the signal. The value of removal is that CI or production tells
   you immediately when you were wrong. If the file still resolves, nothing
   breaks, nothing is learned, and the quarantine period proves nothing.
4. Nothing ever empties it. There is no trigger, so it grows forever, and this
   scanner would report every file in it, every month, until someone excludes
   the directory — creating an unwatched region of the repo, which is the exact
   opposite of the point.

Git is already a perfect quarantine: exact content, original path, date, author.
What git lacks is DISCOVERABILITY — nobody runs `git log --diff-filter=D` six
months later wondering whether a URL sanitiser ever existed. So the tombstone
supplies only the missing half: one greppable line per removed file, carrying the
rationale and a restore command that can be pasted without thinking.

THE SAFETY MODEL IS THE LEDGER CONTRACT, NOT NEW INVENTION

`schema-sweep-manifest-v1.json` already says a Tier 1 action must not be applied
if HEAD has moved, and that `human` is the only authority that may authorise
Tier 1. This script enforces exactly that and adds nothing to it:

    deletable  <=>  decision == confirm
                    AND tier == 1
                    AND decided_by == human
                    AND scan.commit == HEAD
                    AND the worktree is clean

The last two together are stronger than they look: an unmoved HEAD plus a clean
worktree means the tree IS the tree that was scanned, byte for byte, so no
per-file content hash is needed to prove the authorisation is still valid.

`--expect N` is the human's checksum. The precedent is not hypothetical: v0.19.29
of `cleanup-zombies` shipped a Tier 1 auto-delete, it ran from a `--quiet` hook,
it destroyed 623 lines of live code, and nobody noticed for three weeks. A count
the operator has to type is cheap; discovering the loss three weeks later is not.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Executed by PATH and loaded by `spec_from_file_location` in tests; neither puts
# the playbook root on sys.path, so make the sibling helper importable by its own
# directory rather than by package path.
sys.path.insert(0, str(Path(__file__).resolve().parent / "rules"))

from _rule_kit import ConfigError, emit_error  # noqa: E402

TOOL_VERSION = "0.1.0"
DEFAULT_TOMBSTONES = "docs/operations/removed-code.md"

TOMBSTONE_HEADER = """# Removed code — the tombstone ledger

Every file deliberately deleted after a `sweep` scan, with the reasoning that
justified it and the command that brings it back.

This exists because git already stores the content but does not make it
findable. Six months from now the question is not "how do I restore a file" —
it is "did we ever have one that did X?". Grep this file for a name, an area, or
a symbol; the row you find carries a restore command you can paste as-is.

Rows are append-only. A row is written by the same commit that performs the
deletion, and the SHA it names is the commit BEFORE that deletion — so the file
is present at that SHA and `git checkout <sha> -- <path>` restores it exactly.

| Path | Removed | Why | Restore |
|---|---|---|---|
"""


def git(root: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        raise ConfigError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def head_sha(root: Path) -> str:
    return git(root, "rev-parse", "HEAD")


def worktree_is_dirty(root: Path) -> bool:
    """Tracked changes only — untracked files are not an obstacle.

    The concern is a removal commit polluted by unrelated edits, and only tracked
    modifications can be swept into one. Untracked files cannot: nothing here
    stages them. Counting them would also make the tool unusable in its normal
    shape, since the adjudicated ledger itself is an untracked file sitting in
    the repo you are about to clean.
    """
    return any(
        not line.startswith("??")
        for line in git(root, "status", "--porcelain").splitlines()
        if line.strip()
    )


def load_ledger(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read the ledger at {path}: {exc}") from exc


def authorized(finding: dict[str, Any]) -> bool:
    """The ledger contract's Tier 1 test, and nothing besides.

    All three conditions are load-bearing. `confirm` alone is the DETECTOR's
    opinion; Tier 1 alone can be reached by an adjudicating model that ignored
    its instructions; `human` alone says who ruled but not what they ruled.
    """
    adj = finding.get("adjudication") or {}
    return (
        adj.get("decision") == "confirm"
        and adj.get("tier") == 1
        and adj.get("decided_by") == "human"
    )


def blocked_reason(finding: dict[str, Any]) -> str:
    adj = finding.get("adjudication") or {}
    if not adj:
        return "not adjudicated"
    bits = []
    if adj.get("decision") != "confirm":
        bits.append(f"decision={adj.get('decision')}")
    if adj.get("tier") != 1:
        bits.append(f"tier={adj.get('tier')}")
    if adj.get("decided_by") != "human":
        bits.append(f"decided_by={adj.get('decided_by')}")
    return ", ".join(bits)


def _one_line(text: str, limit: int = 300) -> str:
    """Collapse a rationale onto one line so `grep` returns the whole story.

    The six-months-later use case is a single grep, and a match that spills over
    several lines shows the reader a fragment. Table cells also cannot contain a
    literal `|`.
    """
    flat = " ".join(text.split()).replace("|", "/")
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def tombstone_row(finding: dict[str, Any], sha: str, when: str) -> str:
    adj = finding.get("adjudication") or {}
    why = adj.get("rationale") or finding.get("reason") or "no rationale recorded"
    actor = adj.get("actor") or "unknown"
    path = finding["path"]
    return (
        f"| `{path}` "
        f"| {when} · `{sha[:10]}` · {actor} "
        f"| {_one_line(why)} (`{finding['id']}`) "
        f"| `git checkout {sha[:10]} -- {path}` |\n"
    )


def append_tombstones(root: Path, rel: str, rows: list[str]) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(TOMBSTONE_HEADER, encoding="utf-8")
    with path.open("a", encoding="utf-8") as fh:
        fh.writelines(rows)
    return path


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_plan(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ledger = load_ledger(Path(args.ledger))
    findings = ledger.get("findings", [])
    ready = [f for f in findings if authorized(f)]
    held = [f for f in findings if not authorized(f)]

    print(f"sweep-execute: {len(ready)} authorised, {len(held)} held, of {len(findings)}")
    for f in ready:
        print(f"  DELETE  {f['path']}")
    for f in held:
        print(f"  hold    {f['path']}  ({blocked_reason(f)})")

    scan_commit = (ledger.get("scan") or {}).get("commit", "")
    now = head_sha(root)
    if scan_commit and not now.startswith(scan_commit):
        print(
            f"\n  ⚠ HEAD has moved since the scan ({scan_commit[:10]} -> {now[:10]}). "
            "`apply` will refuse: the tree it was authorised against no longer exists."
        )
    if ready:
        print(f"\n  to execute: sweep_execute.py apply --ledger {args.ledger} --expect {len(ready)}")
    return 0


def cmd_authorize(args: argparse.Namespace) -> int:
    """Raise specific rows to Tier 1. The one place `human` authority is written.

    Deliberately per-id and never `--all`: the point of this step is that a
    person looked at each file. A flag that authorises everything at once would
    reintroduce exactly the bulk-delete blast radius the tiers exist to bound.
    """
    path = Path(args.ledger)
    ledger = load_ledger(path)
    by_id = {f["id"]: f for f in ledger.get("findings", [])}

    missing = [i for i in args.id if i not in by_id]
    if missing:
        emit_error(
            why=(
                f"no finding with id {', '.join(missing)} — "
                "an id that is not in the ledger cannot be authorised"
            ),
            where=str(path),
            fix="run `plan` to list the ids exactly as the scanner wrote them.",
            override="none",
        )
        return 2

    not_confirmed = [i for i in args.id if (by_id[i].get("adjudication") or {}).get("decision") != "confirm"]
    if not_confirmed:
        emit_error(
            why=(
                f"{', '.join(not_confirmed)} is not a confirmed finding — "
                "authorising a dismissed or downgraded row would delete a file the "
                "adjudication decided was alive"
            ),
            where=str(path),
            fix="re-adjudicate the row to `confirm` first, or drop it from this call.",
            override="none",
        )
        return 2

    when = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    for i in args.id:
        by_id[i]["adjudication"] = {
            **(by_id[i].get("adjudication") or {}),
            "decided_by": "human",
            "decision": "confirm",
            "tier": 1,
            "decided_at": when,
            "actor": args.actor,
            "rationale": args.rationale,
        }
    path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    print(f"sweep-execute: authorised {len(args.id)} finding(s) for deletion as {args.actor}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    ledger_path = Path(args.ledger)
    ledger = load_ledger(ledger_path)
    scan = ledger.get("scan") or {}
    ready = [f for f in ledger.get("findings", []) if authorized(f)]

    # The count is checked BEFORE the empty case, deliberately. `--expect 1` with
    # nothing authorised is not success: the operator asked for one deletion and
    # got none, and exit 0 would report that as done. Only `--expect 0` may pass
    # quietly.
    if len(ready) != args.expect:
        emit_error(
            why=(
                f"--expect {args.expect} but {len(ready)} finding(s) are authorised — "
                "the count is the operator's checksum against deleting more than they "
                "reviewed. A previous playbook rule auto-deleted 623 lines of live code "
                "from a --quiet hook and it went unnoticed for three weeks"
            ),
            where=str(ledger_path),
            fix=f"run `plan` to see the list, then re-run with --expect {len(ready)}.",
            override="none",
        )
        return 2

    if not ready:
        print("sweep-execute: nothing authorised — run `authorize` first. Nothing was changed.")
        return 0

    if worktree_is_dirty(root):
        emit_error(
            why=(
                "the worktree has uncommitted changes — "
                "this stages deletions; mixing them with unrelated edits makes the "
                "removal commit unreviewable and un-revertable on its own"
            ),
            where=str(root),
            fix="commit or stash your changes, then re-run.",
            override="none",
        )
        return 2

    now = head_sha(root)
    scan_commit = scan.get("commit", "")
    if not scan_commit or not now.startswith(scan_commit):
        emit_error(
            why=(
                f"HEAD is {now[:10]}, the ledger was computed against "
                f"{scan_commit[:10] or '(unrecorded)'} — "
                "reachability is a property of one tree. On a tree that has moved, a file "
                "authorised as unreachable may have gained an importer in the meantime — "
                "the authorisation has expired, it has not merely aged"
            ),
            where=str(ledger_path),
            fix="re-run `sweep_scan.py scan`, re-adjudicate, re-authorise against this HEAD.",
            override="none",
        )
        return 2

    owing = [f for f in ready if (f.get("evidence") or {}).get("unfinished_commitments")]
    if owing:
        # Structural, not advisory. A file that records work nobody discharged is
        # not entropy — it is an obligation with no watcher, and deleting it
        # deletes the only record. Precedent: a consumer's PROGRESS.md sat
        # unreferenced at the repo root for four weeks owing a teardown on a live
        # customer Workspace.
        #
        # `authorize` cannot wave this through either: the point is that the
        # obligation must MOVE somewhere it will be seen — a ticket, a runbook,
        # the deferred-items ledger — and once it has, the marker goes with it and
        # a re-scan clears the row honestly.
        detail = "; ".join(
            f"{f['path']} ({(f['evidence'])['unfinished_commitments']})" for f in owing[:4]
        )
        emit_error(
            why=(
                f"{len(owing)} authorised file(s) still record undischarged work: {detail} — "
                "deleting them would delete the only record of an obligation nobody is "
                "watching, which is strictly worse than leaving the file"
            ),
            where=str(root),
            fix=(
                "move each obligation somewhere it will be seen — a ticket, a runbook, "
                "the deferred-items ledger — then remove the marker from the file and "
                "re-scan. The row clears honestly once the debt has an owner."
            ),
            override="none",
        )
        return 2

    absent = [f["path"] for f in ready if not (root / f["path"]).is_file()]
    if absent:
        emit_error(
            why=(
                f"{len(absent)} authorised path(s) do not exist: {', '.join(absent[:3])} — "
                "a ledger that disagrees with the tree cannot be trusted about the rest of it"
            ),
            where=str(root),
            fix="re-run the scan; the ledger is stale in a way HEAD did not reveal.",
            override="none",
        )
        return 2

    when = datetime.now(UTC).date().isoformat()
    rows = [tombstone_row(f, now, when) for f in ready]

    for f in ready:
        git(root, "rm", "-q", "--", f["path"])
    tomb = append_tombstones(root, args.tombstones, rows)
    git(root, "add", "--", str(tomb.relative_to(root)).replace("\\", "/"))

    print(f"sweep-execute: removed {len(ready)} file(s), {len(rows)} tombstone(s) -> {args.tombstones}")
    for f in ready:
        print(f"  removed  {f['path']}")
    print(
        "\nStaged, NOT committed. Review `git status`, then commit — the message is yours "
        "to write, and the review is the last place a mistake is still free."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sweep-execute", description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    plan = sub.add_parser("plan", help="Show what would be removed. Writes nothing.")
    plan.add_argument("--ledger", required=True)
    plan.set_defaults(func=cmd_plan)

    auth = sub.add_parser("authorize", help="Raise named findings to Tier 1 as a human.")
    auth.add_argument("--ledger", required=True)
    auth.add_argument("--id", action="append", required=True, help="Finding id; repeatable.")
    auth.add_argument("--actor", required=True, help="Who is authorising. Recorded on the tombstone.")
    auth.add_argument("--rationale", required=True, help="Why. Recorded on the tombstone.")
    auth.set_defaults(func=cmd_authorize)

    app = sub.add_parser("apply", help="Delete authorised files and write tombstones.")
    app.add_argument("--ledger", required=True)
    app.add_argument("--expect", type=int, required=True, help="How many deletions you reviewed.")
    app.add_argument("--tombstones", default=DEFAULT_TOMBSTONES)
    app.set_defaults(func=cmd_apply)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ConfigError as exc:
        emit_error(
            why=f"{exc} — sweep-execute cannot proceed against an unreadable contract",
            where=str(getattr(args, "ledger", "")),
            fix="fix the input and re-run.",
            override="none",
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
