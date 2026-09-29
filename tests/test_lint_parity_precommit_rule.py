"""Tests for scripts/rules/lint-parity-precommit.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

SPEC = importlib.util.spec_from_file_location(
    "_lpp_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "lint-parity-precommit.rule.py",
)
assert SPEC and SPEC.loader
_lpp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_lpp)


CI_WITH_RUFF_PINNED = """\
jobs:
  backend:
    steps:
      - name: Install
        run: pip install ruff==0.9.3
      - name: Ruff lint
        run: ruff check .
"""

CI_WITH_RUFF_UNPINNED = """\
jobs:
  backend:
    steps:
      - name: Ruff lint
        run: python -m ruff check backend
"""

CI_WITHOUT_RUFF = """\
jobs:
  backend:
    steps:
      - name: Tests
        run: pytest -q  # ruff check is NOT invoked here (comment only)
"""

PRECOMMIT_WITHOUT_RUFF = """\
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
"""

PRECOMMIT_WITH_RUFF = """\
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.3
    hooks:
      - id: ruff
        args: [--fix]
"""


def _consumer(tmp_path: Path, *, ci: str | None, precommit: str | None) -> Path:
    (tmp_path / "AGENTS.md").write_text("# consumer\n", encoding="utf-8")
    if ci is not None:
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(ci, encoding="utf-8")
    if precommit is not None:
        (tmp_path / ".pre-commit-config.yaml").write_text(precommit, encoding="utf-8")
    return tmp_path


def test_not_applicable_without_workflows(tmp_path: Path) -> None:
    root = _consumer(tmp_path, ci=None, precommit=PRECOMMIT_WITHOUT_RUFF)
    assert _lpp.validate(cwd=root) == 0


def test_not_applicable_when_ruff_absent_from_ci(tmp_path: Path) -> None:
    root = _consumer(tmp_path, ci=CI_WITHOUT_RUFF, precommit=PRECOMMIT_WITHOUT_RUFF)
    assert _lpp.validate(cwd=root) == 0


def test_not_applicable_without_precommit_config(tmp_path: Path) -> None:
    root = _consumer(tmp_path, ci=CI_WITH_RUFF_PINNED, precommit=None)
    assert _lpp.validate(cwd=root) == 0


def test_fails_when_ruff_gates_ci_but_missing_from_precommit(tmp_path: Path) -> None:
    root = _consumer(tmp_path, ci=CI_WITH_RUFF_PINNED, precommit=PRECOMMIT_WITHOUT_RUFF)
    assert _lpp.validate(cwd=root) == 1


def test_passes_with_parity(tmp_path: Path) -> None:
    root = _consumer(tmp_path, ci=CI_WITH_RUFF_PINNED, precommit=PRECOMMIT_WITH_RUFF)
    assert _lpp.validate(cwd=root) == 0


def test_pin_drift_warns_but_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    drifted = PRECOMMIT_WITH_RUFF.replace("v0.9.3", "v0.8.0")
    root = _consumer(tmp_path, ci=CI_WITH_RUFF_PINNED, precommit=drifted)
    assert _lpp.validate(cwd=root) == 0
    assert "pin drift" in capsys.readouterr().err


def test_skip_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_lpp.SKIP_ENV, "1")
    root = _consumer(tmp_path, ci=CI_WITH_RUFF_PINNED, precommit=PRECOMMIT_WITHOUT_RUFF)
    assert _lpp.validate(cwd=root) == 0


def test_apply_appends_block_with_ci_pin(tmp_path: Path) -> None:
    root = _consumer(tmp_path, ci=CI_WITH_RUFF_PINNED, precommit=PRECOMMIT_WITHOUT_RUFF)
    assert _lpp.apply(dry_run=False, cwd=root) == 0
    text = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "ruff-pre-commit" in text
    assert "rev: v0.9.3" in text
    # Existing content preserved (append-only).
    assert "trailing-whitespace" in text
    # Idempotent second run.
    assert _lpp.apply(dry_run=False, cwd=root) == 0
    assert text == (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")


def test_apply_dry_run_mutates_nothing(tmp_path: Path) -> None:
    root = _consumer(tmp_path, ci=CI_WITH_RUFF_PINNED, precommit=PRECOMMIT_WITHOUT_RUFF)
    assert _lpp.apply(dry_run=True, cwd=root) == 0
    assert "ruff" not in (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")


def test_apply_refuses_to_invent_a_rev(tmp_path: Path) -> None:
    root = _consumer(tmp_path, ci=CI_WITH_RUFF_UNPINNED, precommit=PRECOMMIT_WITHOUT_RUFF)
    assert _lpp.apply(dry_run=False, cwd=root) == 1


def test_apply_explicit_rev_overrides(tmp_path: Path) -> None:
    root = _consumer(tmp_path, ci=CI_WITH_RUFF_UNPINNED, precommit=PRECOMMIT_WITHOUT_RUFF)
    assert _lpp.apply(dry_run=False, rev="v0.11.0", cwd=root) == 0
    assert "rev: v0.11.0" in (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")


@pytest.mark.parametrize("precommit", [
    PRECOMMIT_WITHOUT_RUFF,
    # zero-indent sequence + trailing top-level key (pre-commit.ci)
    "repos:\n- repo: https://github.com/pre-commit/pre-commit-hooks\n  rev: v4.6.0\n"
    "  hooks:\n  - id: trailing-whitespace\nci:\n  autofix_prs: false\n",
    # `pre-commit sample-config` layout, CRLF
    "repos:\r\n-   repo: https://github.com/pre-commit/pre-commit-hooks\r\n    rev: v3.2.0\r\n"
    "    hooks:\r\n    -   id: trailing-whitespace\r\n",
])
def test_apply_inserts_parseable_repo_item(tmp_path: Path, precommit: str) -> None:
    root = _consumer(tmp_path, ci=CI_WITH_RUFF_PINNED, precommit=precommit)
    (root / ".pre-commit-config.yaml").write_bytes(precommit.encode("utf-8"))
    assert _lpp.apply(dry_run=False, cwd=root) == 0
    data = yaml.safe_load((root / ".pre-commit-config.yaml").read_bytes().decode("utf-8"))
    assert [r["repo"] for r in data["repos"]] == [
        "https://github.com/pre-commit/pre-commit-hooks", _lpp.RUFF_PRECOMMIT_REPO,
    ]
    assert data["repos"][0]["hooks"] == [{"id": "trailing-whitespace"}]
    assert data["repos"][1]["rev"] == "v0.9.3"
    if "ci:" in precommit:
        assert data["ci"] == {"autofix_prs": False}


def test_apply_refuses_when_result_would_not_parse(tmp_path: Path) -> None:
    root = _consumer(tmp_path, ci=CI_WITH_RUFF_PINNED, precommit="repos: [\n")
    assert _lpp.apply(dry_run=False, cwd=root) == 2
    assert (root / ".pre-commit-config.yaml").read_text(encoding="utf-8") == "repos: [\n"
