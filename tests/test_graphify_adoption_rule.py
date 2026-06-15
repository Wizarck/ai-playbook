"""Tests for scripts/rules/graphify-adoption.rule.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_graphify_adoption_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "graphify-adoption.rule.py",
)
assert SPEC and SPEC.loader
_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_mod)

ALL_ENTRIES = "\n".join(_mod.REQUIRED_ENTRIES) + "\n"
GITATTR_OK = "graphify-out/graph.json merge=graphify\n"


def _consumer(
    root: Path,
    *,
    graph: bool = True,
    gitignore: str | None = "",
    gitattributes: str | None = None,
) -> Path:
    """Build a fake consumer repo under `root`."""
    (root / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
    if graph:
        gdir = root / "graphify-out"
        gdir.mkdir(parents=True, exist_ok=True)
        (gdir / "graph.json").write_text("{}", encoding="utf-8")
    if gitignore is not None:
        (root / ".gitignore").write_text(gitignore, encoding="utf-8")
    if gitattributes is not None:
        (root / ".gitattributes").write_text(gitattributes, encoding="utf-8")
    return root


def test_not_applicable_when_no_graph(tmp_path: Path) -> None:
    c = _consumer(tmp_path, graph=False, gitignore="", gitattributes="")
    assert _mod.validate(cwd=c) == 0


def test_missing_everything_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    c = _consumer(tmp_path, gitignore="", gitattributes="")
    assert _mod.validate(cwd=c) == 1
    err = capsys.readouterr().err.lower()
    assert "gitignore missing graphify entries" in err
    assert "merge driver" in err


def test_gitignore_ok_but_no_merge_driver_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    c = _consumer(tmp_path, gitignore=ALL_ENTRIES, gitattributes="")
    assert _mod.validate(cwd=c) == 1
    err = capsys.readouterr().err.lower()
    assert "gitignore missing graphify entries" not in err
    assert "merge driver" in err


def test_fully_converged_passes(tmp_path: Path) -> None:
    c = _consumer(tmp_path, gitignore=ALL_ENTRIES, gitattributes=GITATTR_OK)
    assert _mod.validate(cwd=c) == 0


def test_apply_appends_then_idempotent(tmp_path: Path) -> None:
    c = _consumer(tmp_path, gitignore="# pre-existing\n", gitattributes=GITATTR_OK)
    assert _mod.apply(dry_run=False, cwd=c) == 0
    txt = (c / ".gitignore").read_text(encoding="utf-8")
    assert "# pre-existing" in txt  # preserved verbatim
    for e in _mod.REQUIRED_ENTRIES:
        assert e in txt
    # validate now passes
    assert _mod.validate(cwd=c) == 0
    # second apply is a no-op: no duplicate managed header
    assert _mod.apply(dry_run=False, cwd=c) == 0
    txt2 = (c / ".gitignore").read_text(encoding="utf-8")
    assert txt2 == txt
    assert txt2.count(_mod.MANAGED_HEADER) == 1


def test_apply_dry_run_writes_nothing(tmp_path: Path) -> None:
    c = _consumer(tmp_path, gitignore="", gitattributes=GITATTR_OK)
    before = (c / ".gitignore").read_text(encoding="utf-8")
    assert _mod.apply(dry_run=True, cwd=c) == 0
    assert (c / ".gitignore").read_text(encoding="utf-8") == before


def test_apply_not_applicable_when_no_graph(tmp_path: Path) -> None:
    c = _consumer(tmp_path, graph=False, gitignore="")
    assert _mod.apply(dry_run=False, cwd=c) == 0
    # gitignore left untouched (no graph → nothing to enforce)
    assert (c / ".gitignore").read_text(encoding="utf-8") == ""


def test_skip_env_short_circuits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _consumer(tmp_path, gitignore="", gitattributes="")
    monkeypatch.setenv(_mod.SKIP_ENV, "1")
    assert _mod.validate(cwd=c) == 0


def test_no_consumer_root_is_fatal(tmp_path: Path) -> None:
    # tmp_path has no AGENTS.md and (pytest tmp dirs) no AGENTS.md up the tree.
    assert _mod.validate(cwd=tmp_path) == 2


def test_gitattributes_lenient_matching() -> None:
    assert _mod._gitattributes_ok("graphify-out/graph.json merge=graphify\n")
    assert _mod._gitattributes_ok("graph.json merge=anyname")  # driver name is opaque
    assert not _mod._gitattributes_ok("# graphify-out/graph.json merge=x")  # comment line
    assert not _mod._gitattributes_ok("graph.json text eol=lf")  # no merge= attribute
    assert not _mod._gitattributes_ok("")
    assert not _mod._gitattributes_ok(None)


def test_missing_entries_ignores_comments_and_blanks() -> None:
    text = "# a comment\n\ngraphify-out/cost.json\n"
    missing = _mod._missing_entries(text)
    assert "graphify-out/cost.json" not in missing
    assert "graphify-out/cache/" in missing
