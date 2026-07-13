"""Tests for scripts/rules/migrate-seed-smoke.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_mss_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "migrate-seed-smoke.rule.py",
)
assert SPEC and SPEC.loader
_mss = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_mss)


WORKFLOW_WITH_SMOKE = """\
jobs:
  migrate-seed-smoke:
    steps:
      - run: python -m alembic upgrade head
      - run: |
          python scripts/bootstrap-test-db.py
          python scripts/bootstrap-test-db.py
"""

WORKFLOW_WITHOUT_SMOKE = """\
jobs:
  e2e:
    steps:
      - run: docker compose up --wait
      - run: npx playwright test
"""


def _consumer(
    tmp_path: Path,
    *,
    alembic: bool = True,
    seed: str | None = "bootstrap-test-db.py",
    workflow: str | None = None,
) -> Path:
    (tmp_path / "AGENTS.md").write_text("# consumer\n", encoding="utf-8")
    if alembic:
        versions = tmp_path / "backend" / "alembic" / "versions"
        versions.mkdir(parents=True)
        (versions / "0001_init.py").write_text("revision = '0001_init'\n", encoding="utf-8")
    if seed:
        scripts = tmp_path / "scripts"
        scripts.mkdir(exist_ok=True)
        (scripts / seed).write_text("print('seed')\n", encoding="utf-8")
    if workflow is not None:
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(workflow, encoding="utf-8")
    return tmp_path


def test_not_applicable_without_alembic(tmp_path: Path) -> None:
    root = _consumer(tmp_path, alembic=False, workflow=WORKFLOW_WITHOUT_SMOKE)
    assert _mss.validate(cwd=root) == 0


def test_not_applicable_without_seed(tmp_path: Path) -> None:
    root = _consumer(tmp_path, seed=None, workflow=WORKFLOW_WITHOUT_SMOKE)
    assert _mss.validate(cwd=root) == 0


def test_fails_when_contract_not_exercised(tmp_path: Path) -> None:
    root = _consumer(tmp_path, workflow=WORKFLOW_WITHOUT_SMOKE)
    assert _mss.validate(cwd=root) == 1


def test_fails_with_no_workflows_at_all(tmp_path: Path) -> None:
    root = _consumer(tmp_path, workflow=None)
    assert _mss.validate(cwd=root) == 1


def test_passes_when_smoke_job_present(tmp_path: Path) -> None:
    root = _consumer(tmp_path, workflow=WORKFLOW_WITH_SMOKE)
    assert _mss.validate(cwd=root) == 0


def test_seed_detected_one_level_down(tmp_path: Path) -> None:
    root = _consumer(tmp_path, seed=None, workflow=WORKFLOW_WITHOUT_SMOKE)
    nested = root / "backend" / "scripts"
    nested.mkdir(parents=True)
    (nested / "seed_db.py").write_text("print('seed')\n", encoding="utf-8")
    assert _mss.validate(cwd=root) == 1


def test_node_modules_ignored(tmp_path: Path) -> None:
    root = _consumer(tmp_path, alembic=False, seed=None, workflow=WORKFLOW_WITHOUT_SMOKE)
    fake = root / "node_modules" / "pkg" / "alembic" / "versions"
    fake.mkdir(parents=True)
    (fake / "0001_x.py").write_text("revision = '0001_x'\n", encoding="utf-8")
    assert _mss.validate(cwd=root) == 0


def test_skip_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_mss.SKIP_ENV, "1")
    root = _consumer(tmp_path, workflow=WORKFLOW_WITHOUT_SMOKE)
    assert _mss.validate(cwd=root) == 0
