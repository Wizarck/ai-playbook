"""Smoke tests for scripts/discover_projects.py.

Populated in T02-pre (functional, not a stub) because the registry is
load-bearing for T02d/e/f dispatcher resolution.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts import discover_projects as dp

AGENTS_MD_TEMPLATE = """\
---
schema: agents-md/v1
version: 1.0.0
inherits_from:
  - github.com/Wizarck/ai-playbook@v0.1.0
updated: 2026-04-23
project: {name}
owner: test@example.com
capabilities_map: true
{extra}
---

# {name}
"""


def _write_project(
    parent: Path,
    name: str,
    *,
    personal: bool = False,
    addon_name: str | None = None,
) -> Path:
    project_dir = parent / name
    project_dir.mkdir(parents=True, exist_ok=True)
    extras = []
    if personal:
        extras.append("personal: true")
    if addon_name:
        extras.append(f"personal_addon: {addon_name}")
    extra_block = "\n".join(extras)
    (project_dir / "AGENTS.md").write_text(
        AGENTS_MD_TEMPLATE.format(name=name, extra=extra_block),
        encoding="utf-8",
    )
    if addon_name:
        (project_dir / addon_name).write_text("# personal addon\n", encoding="utf-8")
    return project_dir


def test_parse_frontmatter_valid(tmp_path: Path) -> None:
    project = _write_project(tmp_path, "alpha")
    fm = dp.parse_frontmatter(project / "AGENTS.md")
    assert fm is not None
    assert fm["schema"] == "agents-md/v1"
    assert fm["project"] == "alpha"


def test_parse_frontmatter_missing(tmp_path: Path) -> None:
    f = tmp_path / "AGENTS.md"
    f.write_text("no frontmatter\n", encoding="utf-8")
    assert dp.parse_frontmatter(f) is None


def test_parse_frontmatter_wrong_schema(tmp_path: Path) -> None:
    f = tmp_path / "AGENTS.md"
    f.write_text("---\nschema: agents-md/v0\n---\nbody\n", encoding="utf-8")
    fm = dp.parse_frontmatter(f)
    assert fm is not None
    assert fm["schema"] == "agents-md/v0"  # caller filters, parser just reads


def test_scan_finds_projects(tmp_path: Path) -> None:
    _write_project(tmp_path, "alpha")
    _write_project(tmp_path / "nested", "beta")
    # decoy: dir without AGENTS.md
    (tmp_path / "not-a-project").mkdir()
    found = {name for _, fm in dp.scan(tmp_path) for name in [fm["project"]]}
    assert found == {"alpha", "beta"}


def test_scan_skips_ignored_dirs(tmp_path: Path) -> None:
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "AGENTS.md").write_text(
        AGENTS_MD_TEMPLATE.format(name="leaked", extra=""),
        encoding="utf-8",
    )
    _write_project(tmp_path, "alpha")
    names = [fm["project"] for _, fm in dp.scan(tmp_path)]
    assert "alpha" in names
    assert "leaked" not in names


def test_build_entry_personal_with_addon(tmp_path: Path) -> None:
    project = _write_project(tmp_path, "eligia-core", personal=True, addon_name="ELIGIA.md")
    fm = dp.parse_frontmatter(project / "AGENTS.md")
    assert fm is not None
    entry = dp.build_entry(project, fm)
    assert entry.name == "eligia-core"
    assert entry.personal is True
    assert entry.personal_addon is not None
    assert entry.personal_addon.endswith("ELIGIA.md")


def test_load_registry_missing_returns_skeleton(tmp_path: Path) -> None:
    data = dp.load_registry(tmp_path / "nope.yaml")
    assert data["schema"] == dp.REGISTRY_SCHEMA
    assert data["projects"] == {}


def test_write_and_load_roundtrip(tmp_path: Path) -> None:
    project = _write_project(tmp_path, "alpha")
    fm = dp.parse_frontmatter(project / "AGENTS.md")
    assert fm is not None
    entry = dp.build_entry(project, fm)
    registry_path = tmp_path / "registry.yaml"
    data = {"schema": dp.REGISTRY_SCHEMA, "projects": {entry.name: dp.entry_to_dict(entry)}}
    dp.write_registry(registry_path, data)
    reloaded = dp.load_registry(registry_path)
    assert reloaded["projects"]["alpha"]["path"].endswith("alpha")


def test_main_refresh_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_project(tmp_path, "alpha")
    _write_project(tmp_path / "subdir", "beta", personal=True, addon_name="ELIGIA.md")
    registry = tmp_path / "registry.yaml"
    # Isolate from the user's real env
    monkeypatch.delenv("AIPLAYBOOK_PROJECTS_ROOTS", raising=False)
    monkeypatch.delenv("AIPLAYBOOK_PROJECTS_FILE", raising=False)
    rc = dp.main(["--roots", str(tmp_path), "--registry", str(registry)])
    assert rc == 0
    data = yaml.safe_load(registry.read_text(encoding="utf-8"))
    assert set(data["projects"].keys()) == {"alpha", "beta"}
    assert data["projects"]["beta"]["personal"] is True
    assert data["projects"]["beta"]["personal_addon"].endswith("ELIGIA.md")


def test_main_dry_run_does_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _write_project(tmp_path, "alpha")
    registry = tmp_path / "registry.yaml"
    monkeypatch.delenv("AIPLAYBOOK_PROJECTS_ROOTS", raising=False)
    rc = dp.main(["--roots", str(tmp_path), "--registry", str(registry), "--dry-run"])
    assert rc == 0
    assert not registry.exists()
    out = capsys.readouterr().out
    assert "alpha" in out


def test_main_add(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _write_project(tmp_path, "alpha")
    registry = tmp_path / "registry.yaml"
    monkeypatch.delenv("AIPLAYBOOK_PROJECTS_FILE", raising=False)
    rc = dp.main(["--add", str(project), "--registry", str(registry)])
    assert rc == 0
    data = yaml.safe_load(registry.read_text(encoding="utf-8"))
    assert "alpha" in data["projects"]


def test_main_add_missing_agents_md(tmp_path: Path) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    rc = dp.main(["--add", str(target), "--registry", str(tmp_path / "r.yaml")])
    assert rc == 1
