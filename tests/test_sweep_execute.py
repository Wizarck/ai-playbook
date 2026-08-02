"""Tests for scripts/sweep_execute.py.

THE CENTRAL TEST is `test_the_tombstone_command_actually_restores_the_file`. It
takes the restore command out of the generated row, runs it verbatim, and asserts
the file comes back byte for byte. That test is the entire argument for deleting
instead of quarantining: if the recorded command does not work, the tombstone is
a promise the repo cannot keep, and a quarantine directory would be the honest
design after all.

The rest guard the blast radius. The precedent is concrete: v0.19.29 of
`cleanup-zombies` shipped a Tier 1 auto-delete that ran from a `--quiet` hook,
destroyed 623 lines of live code, and went unnoticed for three weeks. Every
refusal below exists so that this script cannot repeat it.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "sweep_execute.py"

SPEC = importlib.util.spec_from_file_location("sweep_execute", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
ex = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ex
SPEC.loader.exec_module(ex)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def git(root: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with one committed orphan file."""
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "orphan.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "app" / "live.py").write_text("VALUE = 2\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "seed")
    return tmp_path


def make_ledger(repo: Path, *, tier: int = 3, decided_by: str = "detector",
                decision: str = "confirm", commit: str | None = None,
                path: str = "app/orphan.py") -> Path:
    ledger = {
        "schema": "ai-playbook/sweep-manifest/v1",
        "version": "1.0.0",
        "generated_at": "2026-08-02T00:00:00Z",
        "scan": {
            "tool_version": "0.1.0",
            "commit": commit if commit is not None else git(repo, "rev-parse", "HEAD"),
            "axes_scanned": ["orphan-file"],
        },
        "findings": [{
            "id": "orphan-app-orphan-py-deadbeef",
            "axis": "orphan-file",
            "path": path,
            "action": "report",
            "safety": "report_only",
            "reason": "No path from any declared entry point reaches it.",
            "adjudication": {
                "decided_by": decided_by,
                "decision": decision,
                "tier": tier,
                "decided_at": "2026-08-02T00:00:00Z",
            },
        }],
    }
    out = repo / "ledger.json"
    out.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    return out


def run(repo: Path, *argv: str) -> int:
    return ex.main(["--root", str(repo), *argv])


def authorize(repo: Path, ledger: Path) -> None:
    assert run(repo, "authorize", "--ledger", str(ledger),
               "--id", "orphan-app-orphan-py-deadbeef",
               "--actor", "arturo",
               "--rationale", "No importer, no dynamic load, no alias. Verified by hand.") == 0


# ---------------------------------------------------------------------------
# THE ACCEPTANCE GATE
# ---------------------------------------------------------------------------


def test_the_tombstone_command_actually_restores_the_file(repo: Path) -> None:
    """THE central test: the recorded command is executed, not merely inspected.

    A tombstone whose restore command does not work is worse than no tombstone —
    it is a promise that fails at the one moment anyone relies on it, six months
    later when the original context is gone.
    """
    original = (repo / "app" / "orphan.py").read_bytes()
    ledger = make_ledger(repo)
    authorize(repo, ledger)

    assert run(repo, "apply", "--ledger", str(ledger), "--expect", "1") == 0
    assert not (repo / "app" / "orphan.py").exists()

    row = (repo / "docs" / "operations" / "removed-code.md").read_text(encoding="utf-8").splitlines()[-1]
    command = row.split("|")[-2].strip().strip("`")
    assert command.startswith("git checkout ")

    subprocess.run(command.split(), cwd=repo, check=True, capture_output=True)
    assert (repo / "app" / "orphan.py").read_bytes() == original


def test_the_row_carries_the_reasoning_not_just_the_path(repo: Path) -> None:
    """Grepping a name six months later must return the WHY, or the row is a log
    line rather than a record."""
    ledger = make_ledger(repo)
    authorize(repo, ledger)
    run(repo, "apply", "--ledger", str(ledger), "--expect", "1")

    text = (repo / "docs" / "operations" / "removed-code.md").read_text(encoding="utf-8")
    assert "app/orphan.py" in text
    assert "No importer, no dynamic load" in text
    assert "arturo" in text
    assert "orphan-app-orphan-py-deadbeef" in text          # back-link to the ledger row


# ---------------------------------------------------------------------------
# Blast radius — every one of these is a refusal
# ---------------------------------------------------------------------------


def test_an_unauthorised_finding_is_never_deleted(repo: Path) -> None:
    """Tier 3 is what the scanner emits. Deleting it would make the whole
    adjudication step decorative."""
    ledger = make_ledger(repo, tier=3, decided_by="detector")
    assert run(repo, "apply", "--ledger", str(ledger), "--expect", "0") == 0
    assert (repo / "app" / "orphan.py").exists()


def test_a_model_cannot_authorise_its_own_deletion(repo: Path) -> None:
    """`decided_by: llm` at Tier 1 is the shape of a model that ignored its
    instructions. The executor must not be the place that trust is extended."""
    ledger = make_ledger(repo, tier=1, decided_by="llm")
    assert run(repo, "apply", "--ledger", str(ledger), "--expect", "1") == 2
    assert (repo / "app" / "orphan.py").exists()


def test_a_dismissed_finding_cannot_be_authorised(repo: Path, capsys) -> None:
    """`dismiss` means the adjudication found it alive. Authorising it anyway
    would delete a file someone already argued for."""
    ledger = make_ledger(repo, decision="dismiss")
    rc = run(repo, "authorize", "--ledger", str(ledger),
             "--id", "orphan-app-orphan-py-deadbeef",
             "--actor", "arturo", "--rationale", "x")
    assert rc == 2
    assert "not a confirmed finding" in capsys.readouterr().err
    assert (repo / "app" / "orphan.py").exists()


def test_a_moved_head_expires_the_authorisation(repo: Path, capsys) -> None:
    """Reachability is a property of ONE tree. On a tree that moved, a file
    authorised as unreachable may have gained an importer since."""
    ledger = make_ledger(repo)
    authorize(repo, ledger)
    (repo / "app" / "new.py").write_text("VALUE = 3\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "move HEAD")

    assert run(repo, "apply", "--ledger", str(ledger), "--expect", "1") == 2
    assert "authorisation has expired" in capsys.readouterr().err
    assert (repo / "app" / "orphan.py").exists()


def test_a_wrong_expect_count_refuses(repo: Path, capsys) -> None:
    """The count is the operator's checksum. It is the guard the 623-line
    incident did not have."""
    ledger = make_ledger(repo)
    authorize(repo, ledger)
    assert run(repo, "apply", "--ledger", str(ledger), "--expect", "5") == 2
    assert "checksum" in capsys.readouterr().err
    assert (repo / "app" / "orphan.py").exists()


def test_a_dirty_worktree_refuses(repo: Path, capsys) -> None:
    """A removal commit mixed with unrelated edits cannot be reverted on its own,
    which is the whole recovery story."""
    ledger = make_ledger(repo)
    authorize(repo, ledger)
    (repo / "app" / "live.py").write_text("VALUE = 99\n", encoding="utf-8")

    assert run(repo, "apply", "--ledger", str(ledger), "--expect", "1") == 2
    assert "uncommitted changes" in capsys.readouterr().err
    assert (repo / "app" / "orphan.py").exists()


def test_a_path_missing_from_the_tree_refuses_the_whole_batch(repo: Path) -> None:
    """A ledger that disagrees with the tree cannot be trusted about the rest of
    it, so one bad row stops all of them rather than most of them."""
    ledger = make_ledger(repo, path="app/never_existed.py")
    run(repo, "authorize", "--ledger", str(ledger),
        "--id", "orphan-app-orphan-py-deadbeef", "--actor", "a", "--rationale", "r")
    assert run(repo, "apply", "--ledger", str(ledger), "--expect", "1") == 2
    assert (repo / "app" / "orphan.py").exists()


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_plan_changes_nothing(repo: Path, capsys) -> None:
    ledger = make_ledger(repo)
    before = git(repo, "status", "--porcelain")
    assert run(repo, "plan", "--ledger", str(ledger)) == 0
    assert git(repo, "status", "--porcelain") == before
    assert (repo / "app" / "orphan.py").exists()
    assert "hold" in capsys.readouterr().out


def test_plan_names_why_each_row_is_held(repo: Path, capsys) -> None:
    ledger = make_ledger(repo, tier=3, decided_by="detector")
    run(repo, "plan", "--ledger", str(ledger))
    out = capsys.readouterr().out
    assert "tier=3" in out and "decided_by=detector" in out


def test_apply_stages_but_does_not_commit(repo: Path) -> None:
    """The commit is the last checkpoint where a mistake is still free, so it
    stays with the human."""
    ledger = make_ledger(repo)
    authorize(repo, ledger)
    before = git(repo, "rev-parse", "HEAD")
    run(repo, "apply", "--ledger", str(ledger), "--expect", "1")
    assert git(repo, "rev-parse", "HEAD") == before
    assert "D  app/orphan.py" in git(repo, "status", "--porcelain")


def test_tombstones_are_append_only(repo: Path) -> None:
    """A second removal must not erase the first — the file's whole value is that
    old rows survive long enough to be useful."""
    ledger = make_ledger(repo)
    authorize(repo, ledger)
    assert run(repo, "apply", "--ledger", str(ledger), "--expect", "1") == 0
    git(repo, "commit", "-qm", "first removal")

    # `add -A` deliberately avoided: it would track the ledger itself, and
    # rewriting it would then read as a dirty worktree — which is the script
    # working correctly, but not what this test is about.
    (repo / "app" / "second.py").write_text("VALUE = 4\n", encoding="utf-8")
    git(repo, "add", "--", "app/second.py")
    git(repo, "commit", "-qm", "add second")
    ledger2 = make_ledger(repo, path="app/second.py")
    authorize(repo, ledger2)
    assert run(repo, "apply", "--ledger", str(ledger2), "--expect", "1") == 0

    text = (repo / "docs" / "operations" / "removed-code.md").read_text(encoding="utf-8")
    assert "app/orphan.py" in text and "app/second.py" in text
    assert text.count("| Path | Removed |") == 1              # one header, not two


def test_a_pipe_in_a_rationale_cannot_break_the_table(repo: Path) -> None:
    ledger = make_ledger(repo)
    run(repo, "authorize", "--ledger", str(ledger),
        "--id", "orphan-app-orphan-py-deadbeef", "--actor", "a",
        "--rationale", "checked `grep -r x | wc -l`\nand the registry too")
    run(repo, "apply", "--ledger", str(ledger), "--expect", "1")

    rows = [
        ln for ln in (repo / "docs" / "operations" / "removed-code.md")
        .read_text(encoding="utf-8").splitlines() if ln.startswith("| `app/")
    ]
    assert len(rows) == 1                                     # one line, not two
    assert rows[0].count("|") == 5                            # exactly 4 cells


def test_the_executor_exposes_no_bulk_authorise(repo: Path, capsys) -> None:
    """`--all` would restore the blast radius the tiers exist to bound, so the
    CLI must not accept it — asserted against the parser, not the source text."""
    ledger = make_ledger(repo)
    with pytest.raises(SystemExit):
        ex.main(["--root", str(repo), "authorize", "--ledger", str(ledger),
                 "--id", "orphan-app-orphan-py-deadbeef",
                 "--actor", "a", "--rationale", "r", "--all"])
    assert "unrecognized arguments" in capsys.readouterr().err


def test_an_untracked_ledger_does_not_count_as_a_dirty_worktree(repo: Path) -> None:
    """The adjudicated ledger normally sits untracked in the repo being cleaned.
    Treating that as dirt would make the tool unusable in its own normal shape."""
    ledger = make_ledger(repo)
    assert not ex.worktree_is_dirty(repo)
    assert ledger.exists()
