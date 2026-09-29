"""Tests for scripts/rules/pre-commit-hooks.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

SPEC = importlib.util.spec_from_file_location(
    "_pch_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "pre-commit-hooks.rule.py",
)
assert SPEC and SPEC.loader
_pch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_pch)


BASE_CONFIG_WITHOUT_PLAYBOOK = """\
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
"""

CONFIG_WITH_REMOTE_PLAYBOOK = """\
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace

  - repo: https://github.com/Wizarck/ai-playbook
    rev: v0.20.0
    hooks:
      - id: validate-pairing
"""

CONFIG_WITH_LOCAL_PLAYBOOK = """\
repos:
  - repo: local
    hooks:
      - id: validate-pairing
        name: validate-pairing
        entry: python .ai-playbook/scripts/validate_pairing.py
        language: system
        pass_filenames: false
"""


def _make_consumer(tmp_path: Path, *, with_agents: bool = True, config: str | None = None) -> Path:
    if with_agents:
        (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    if config is not None:
        (tmp_path / ".pre-commit-config.yaml").write_text(config, encoding="utf-8")
    return tmp_path


# --- validate ------------------------------------------------------------------

def test_validate_ok_when_remote_playbook_declared(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path, config=CONFIG_WITH_REMOTE_PLAYBOOK)
    assert _pch.validate(root) == 0


def test_validate_ok_when_local_playbook_declared(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path, config=CONFIG_WITH_LOCAL_PLAYBOOK)
    assert _pch.validate(root) == 0


def test_validate_drift_when_playbook_missing(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path, config=BASE_CONFIG_WITHOUT_PLAYBOOK)
    rc = _pch.validate(root)
    assert rc == 1
    assert "does not declare" in capsys.readouterr().err


def test_validate_drift_ignores_comment_only_mention(tmp_path: Path, capsys) -> None:
    config = "repos:\n  # this is the ai-playbook reference comment\n  - repo: foo\n    rev: bar\n    hooks: []\n"
    root = _make_consumer(tmp_path, config=config)
    rc = _pch.validate(root)
    assert rc == 1
    assert "does not declare" in capsys.readouterr().err


def test_validate_not_applicable_when_no_config(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    assert _pch.validate(root) == 0


def test_validate_fatal_when_no_consumer_root(tmp_path: Path, capsys) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    rc = _pch.validate(nested)
    assert rc == 2
    assert "no consumer root" in capsys.readouterr().err


def test_validate_skip_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_PRE_COMMIT_HOOKS_SKIP", "1")
    # Broken state but skip flag bypasses everything.
    assert _pch.validate(tmp_path) == 0


# --- apply ---------------------------------------------------------------------

def test_apply_appends_block_when_missing(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path, config=BASE_CONFIG_WITHOUT_PLAYBOOK)
    rc = _pch.apply(dry_run=False, cwd=root)
    assert rc == 0
    out = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "Wizarck/ai-playbook" in out
    # Original content preserved.
    assert "trailing-whitespace" in out
    assert "end-of-file-fixer" in out


def test_apply_dry_run_does_not_write(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path, config=BASE_CONFIG_WITHOUT_PLAYBOOK)
    before = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    rc = _pch.apply(dry_run=True, cwd=root)
    assert rc == 0
    after = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert before == after


def test_apply_idempotent_when_already_declared(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path, config=CONFIG_WITH_REMOTE_PLAYBOOK)
    before = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    rc = _pch.apply(dry_run=False, cwd=root)
    assert rc == 0
    after = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert before == after  # truly no-op (no diff)


def test_apply_idempotent_double_run(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path, config=BASE_CONFIG_WITHOUT_PLAYBOOK)
    rc1 = _pch.apply(dry_run=False, cwd=root)
    first = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    rc2 = _pch.apply(dry_run=False, cwd=root)
    second = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert rc1 == 0 and rc2 == 0
    assert first == second  # second run is a true no-op


def test_apply_uses_head_rev_when_no_submodule_pin(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path, config=BASE_CONFIG_WITHOUT_PLAYBOOK)
    _pch.apply(dry_run=False, cwd=root)
    out = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "rev: HEAD" in out


def test_apply_fails_when_config_missing(tmp_path: Path, capsys) -> None:
    # AGENTS.md present, no .pre-commit-config.yaml — apply refuses (it's a precondition).
    (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    rc = _pch.apply(dry_run=False, cwd=tmp_path)
    assert rc == 1
    assert "missing" in capsys.readouterr().err


def test_apply_fatal_when_no_consumer_root(tmp_path: Path, capsys) -> None:
    nested = tmp_path / "deep" / "nested"
    nested.mkdir(parents=True)
    rc = _pch.apply(dry_run=False, cwd=nested)
    assert rc == 2
    assert "no consumer root" in capsys.readouterr().err


def test_declares_playbook_helper_matches_remote(tmp_path: Path) -> None:
    assert _pch._declares_playbook(CONFIG_WITH_REMOTE_PLAYBOOK) is True


def test_declares_playbook_helper_matches_local(tmp_path: Path) -> None:
    assert _pch._declares_playbook(CONFIG_WITH_LOCAL_PLAYBOOK) is True


def test_declares_playbook_helper_rejects_base(tmp_path: Path) -> None:
    assert _pch._declares_playbook(BASE_CONFIG_WITHOUT_PLAYBOOK) is False


# --- hook ids + YAML integrity ---------------------------------------------------

REPO = Path(__file__).resolve().parent.parent

ZERO_INDENT_WITH_TRAILING_KEY = """\
repos:
- repo: https://github.com/pre-commit/pre-commit-hooks
  rev: v4.6.0
  hooks:
  - id: trailing-whitespace
ci:
  autofix_prs: false
"""

SAMPLE_CONFIG_LAYOUT = """\
# See https://pre-commit.com for more information
repos:
-   repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v3.2.0
    hooks:
    -   id: trailing-whitespace
    -   id: end-of-file-fixer
"""


def _exported_ids() -> set[str]:
    data = yaml.safe_load((REPO / ".pre-commit-hooks.yaml").read_text(encoding="utf-8"))
    return {h["id"] for h in data}


def test_exported_hook_ids_match_pre_commit_hooks_yaml() -> None:
    assert set(_pch.EXPORTED_HOOK_IDS) == _exported_ids()


def test_doc_canonical_block_uses_only_exported_ids() -> None:
    doc = (REPO / "docs" / "rules" / "pre-commit-hooks.rule.md").read_text(encoding="utf-8")
    import re
    fenced = "".join(re.findall(r"```yaml\n(.*?)```", doc, re.DOTALL))
    ids = set(re.findall(r"- id: ([\w-]+)", fenced)) - {"trailing-whitespace", "end-of-file-fixer"}
    assert ids and ids <= _exported_ids()


@pytest.mark.parametrize("config", [
    BASE_CONFIG_WITHOUT_PLAYBOOK, ZERO_INDENT_WITH_TRAILING_KEY, SAMPLE_CONFIG_LAYOUT,
])
def test_apply_output_parses_and_uses_exported_ids(tmp_path: Path, config: str) -> None:
    root = _make_consumer(tmp_path, config=config)
    assert _pch.apply(dry_run=False, cwd=root) == 0
    data = yaml.safe_load((root / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    assert len(data["repos"]) == 2
    pb = data["repos"][-1]
    assert pb["repo"] == _pch.PLAYBOOK_REPO_URL
    assert {h["id"] for h in pb["hooks"]} == _exported_ids()
    assert data["repos"][0]["hooks"][0]["id"] == "trailing-whitespace"
    if "ci:" in config:
        assert data["ci"] == {"autofix_prs": False}


def test_apply_refuses_unparseable_target(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path, config="repos: [\n")
    before = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert _pch.apply(dry_run=False, cwd=root) == 2
    assert (root / ".pre-commit-config.yaml").read_text(encoding="utf-8") == before


def test_validate_flags_unexported_hook_id(tmp_path: Path) -> None:
    bad = BASE_CONFIG_WITHOUT_PLAYBOOK + (
        "  - repo: https://github.com/Wizarck/ai-playbook\n"
        "    rev: v0.20.0\n    hooks:\n      - id: ai-playbook\n"
    )
    root = _make_consumer(tmp_path, config=bad)
    assert _pch.validate(cwd=root) == 1
