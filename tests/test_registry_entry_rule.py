"""Tests for scripts/rules/registry-entry.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_re_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "registry-entry.rule.py",
)
assert SPEC and SPEC.loader
_re = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_re)


def _make_consumer(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    return tmp_path


def _make_registry(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "projects.yaml"
    p.write_text(body, encoding="utf-8")
    return p


# --- validate ------------------------------------------------------------------

def test_validate_ok_when_path_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_consumer(tmp_path / "consumer")
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(exist_ok=True)
    (root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    registry = _make_registry(
        tmp_path,
        "schema: ai-playbook/projects-registry/v1\n"
        "projects:\n"
        "  consumer:\n"
        f"    path: {root.resolve().as_posix()}\n",
    )
    monkeypatch.setattr(_re, "REGISTRY_PATH", registry)
    assert _re.validate(root) == 0


def test_validate_drift_when_path_not_in_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    root = _make_consumer(tmp_path / "consumer")
    root.mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    registry = _make_registry(
        tmp_path,
        "schema: ai-playbook/projects-registry/v1\n"
        "projects:\n"
        "  other:\n"
        "    path: /some/unrelated/path\n",
    )
    monkeypatch.setattr(_re, "REGISTRY_PATH", registry)
    rc = _re.validate(root)
    assert rc == 1
    assert "not registered" in capsys.readouterr().err


def test_validate_not_applicable_when_registry_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    root = _make_consumer(tmp_path / "consumer")
    root.mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    # Point REGISTRY_PATH at a non-existent file.
    missing = tmp_path / "does-not-exist.yaml"
    monkeypatch.setattr(_re, "REGISTRY_PATH", missing)
    rc = _re.validate(root)
    # Special case: registry not initialised → exit 2 (not 1).
    assert rc == 2
    assert "not-applicable" in capsys.readouterr().err


def test_validate_fatal_when_no_consumer_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    # Even with a registry present, missing AGENTS.md is fatal.
    registry = _make_registry(tmp_path, "schema: x\nprojects: {}\n")
    monkeypatch.setattr(_re, "REGISTRY_PATH", registry)
    rc = _re.validate(nested)
    assert rc == 2
    assert "no consumer root" in capsys.readouterr().err


def test_validate_skip_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AIPLAYBOOK_REGISTRY_ENTRY_SKIP", "1")
    # Skip flag bypasses everything — even missing consumer root.
    assert _re.validate(tmp_path) == 0


def test_path_in_registry_handles_native_separators(tmp_path: Path) -> None:
    # The matcher must succeed regardless of slash style used in YAML.
    target = tmp_path / "proj"
    target.mkdir()
    text_posix = f"projects:\n  p:\n    path: {target.resolve().as_posix()}\n"
    assert _re._path_in_registry(text_posix, target) is True
    text_backslash = "projects:\n  p:\n    path: " + str(target.resolve()).replace("/", "\\") + "\n"
    assert _re._path_in_registry(text_backslash, target) is True


def test_path_in_registry_false_when_missing(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    text = "projects:\n  other:\n    path: /elsewhere\n"
    assert _re._path_in_registry(text, target) is False


# --- apply ---------------------------------------------------------------------

def test_apply_invokes_discover_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """`apply` invokes the discover_projects.py script as a subprocess."""
    root = _make_consumer(tmp_path / "consumer")
    root.mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")

    captured: dict[str, object] = {}

    class _FakeCompleted:
        returncode = 0
        stdout = "discover-ran\n"
        stderr = ""

    def _fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeCompleted()

    monkeypatch.setattr(_re.subprocess, "run", _fake_run)
    rc = _re.apply(dry_run=False, cwd=root)
    assert rc == 0
    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert any("discover_projects.py" in str(part) for part in cmd)
    out = capsys.readouterr().out
    assert "discover-ran" in out


def test_apply_dry_run_passes_dry_run_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_consumer(tmp_path / "consumer")
    root.mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")

    captured: dict[str, object] = {}

    class _FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        captured["cmd"] = cmd
        return _FakeCompleted()

    monkeypatch.setattr(_re.subprocess, "run", _fake_run)
    rc = _re.apply(dry_run=True, cwd=root)
    assert rc == 0
    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert "--dry-run" in cmd


def test_apply_idempotent_when_repeated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_consumer(tmp_path / "consumer")
    root.mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")

    class _FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(_re.subprocess, "run", lambda *a, **k: _FakeCompleted())
    assert _re.apply(dry_run=False, cwd=root) == 0
    # Second invocation: still exit 0 (discover_projects.py is itself idempotent).
    assert _re.apply(dry_run=False, cwd=root) == 0


def test_apply_propagates_nonzero_subprocess_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_consumer(tmp_path / "consumer")
    root.mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")

    class _FakeCompleted:
        returncode = 1
        stdout = ""
        stderr = "discover failed\n"

    monkeypatch.setattr(_re.subprocess, "run", lambda *a, **k: _FakeCompleted())
    rc = _re.apply(dry_run=False, cwd=root)
    assert rc == 1


def test_apply_fatal_when_no_consumer_root(tmp_path: Path, capsys) -> None:
    nested = tmp_path / "deep" / "nested"
    nested.mkdir(parents=True)
    rc = _re.apply(dry_run=False, cwd=nested)
    assert rc == 2
    assert "no consumer root" in capsys.readouterr().err
