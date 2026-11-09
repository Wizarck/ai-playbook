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
    project = _write_project(tmp_path, "acme-corp", personal=True, addon_name="acme-corp.md")
    fm = dp.parse_frontmatter(project / "AGENTS.md")
    assert fm is not None
    entry = dp.build_entry(project, fm)
    assert entry.name == "acme-corp"
    assert entry.personal is True
    assert entry.personal_addon is not None
    assert entry.personal_addon.endswith("acme-corp.md")


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
    _write_project(tmp_path / "subdir", "beta", personal=True, addon_name="acme-corp.md")
    registry = tmp_path / "registry.yaml"
    # Isolate from the user's real env
    monkeypatch.delenv("AIPLAYBOOK_PROJECTS_ROOTS", raising=False)
    monkeypatch.delenv("AIPLAYBOOK_PROJECTS_FILE", raising=False)
    rc = dp.main(["--roots", str(tmp_path), "--registry", str(registry)])
    assert rc == 0
    data = yaml.safe_load(registry.read_text(encoding="utf-8"))
    assert set(data["projects"].keys()) == {"alpha", "beta"}
    assert data["projects"]["beta"]["personal"] is True
    assert data["projects"]["beta"]["personal_addon"].endswith("acme-corp.md")


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


def test_main_refresh_keeps_added_and_prunes_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refresh merges: --add'ed entries outside the scan roots survive; entries
    whose path no longer holds a v1 AGENTS.md are pruned."""
    monkeypatch.delenv("AIPLAYBOOK_PROJECTS_ROOTS", raising=False)
    registry = tmp_path / "registry.yaml"
    alpha = _write_project(tmp_path / "elsewhere", "alpha")
    gone = _write_project(tmp_path / "elsewhere", "gone")
    _write_project(tmp_path / "roots", "beta")
    assert dp.main(["--add", str(alpha), "--registry", str(registry)]) == 0
    assert dp.main(["--add", str(gone), "--registry", str(registry)]) == 0
    (gone / "AGENTS.md").unlink()

    rc = dp.main(["--roots", str(tmp_path / "roots"), "--registry", str(registry)])

    assert rc == 0
    data = yaml.safe_load(registry.read_text(encoding="utf-8"))
    assert set(data["projects"]) == {"alpha", "beta"}


def _registry_with(path: Path, entries: dict) -> Path:
    dp.write_registry(path, {"schema": dp.REGISTRY_SCHEMA, "projects": entries})
    return path


def test_refresh_keeps_an_unreachable_entry_prunes_one_gone_from_a_scanned_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unmounted drive / share made parse_frontmatter return None and the
    entry was pruned, although the code comment promised it would survive."""
    monkeypatch.delenv("AIPLAYBOOK_PROJECTS_ROOTS", raising=False)
    roots = tmp_path / "roots"
    _write_project(roots, "beta")
    registry = _registry_with(tmp_path / "registry.yaml", {
        "onnas": {"path": str(tmp_path / "not-mounted" / "onnas"), "owner": "o@x"},
        "deleted": {"path": str(roots / "deleted")},
    })

    assert dp.main(["--roots", str(roots), "--registry", str(registry)]) == 0

    projects = yaml.safe_load(registry.read_text(encoding="utf-8"))["projects"]
    assert set(projects) == {"beta", "onnas"}
    assert projects["onnas"] == {"path": str(tmp_path / "not-mounted" / "onnas"), "owner": "o@x"}


def test_refresh_does_not_repoint_a_registered_path_that_still_holds_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Bare layout: a same-name slice worktree under the scan roots silently
    replaced the --add'ed main checkout (the project-a re-point footgun)."""
    monkeypatch.delenv("AIPLAYBOOK_PROJECTS_ROOTS", raising=False)
    registry = tmp_path / "registry.yaml"
    main = tmp_path / "elsewhere" / "project-a-main"
    main.mkdir(parents=True)
    (main / "AGENTS.md").write_text(AGENTS_MD_TEMPLATE.format(name="project-a", extra=""), encoding="utf-8")
    assert dp.main(["--add", str(main), "--registry", str(registry)]) == 0
    slice_wt = _write_project(tmp_path / "roots" / "project-a", "feat-wt")
    (slice_wt / "AGENTS.md").write_text(AGENTS_MD_TEMPLATE.format(name="project-a", extra=""), encoding="utf-8")

    assert dp.main(["--roots", str(tmp_path / "roots"), "--registry", str(registry)]) == 0

    projects = yaml.safe_load(registry.read_text(encoding="utf-8"))["projects"]
    assert projects["project-a"]["path"] == str(main.resolve())
    assert "re-point" in capsys.readouterr().err


def test_refresh_same_dir_through_a_symlink_is_not_a_repoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("AIPLAYBOOK_PROJECTS_ROOTS", raising=False)
    real = _write_project(tmp_path / "roots", "alpha")
    link = tmp_path / "alpha-link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    registry = _registry_with(tmp_path / "registry.yaml", {"alpha": {"path": str(link)}})

    assert dp.main(["--roots", str(tmp_path / "roots"), "--registry", str(registry)]) == 0

    assert "re-point" not in capsys.readouterr().err
    assert yaml.safe_load(registry.read_text(encoding="utf-8"))["projects"]["alpha"]["path"] == str(real.resolve())


def test_refresh_rekeys_a_renamed_project_instead_of_keeping_an_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AIPLAYBOOK_PROJECTS_ROOTS", raising=False)
    registry = tmp_path / "registry.yaml"
    in_roots = _write_project(tmp_path / "roots", "proj")
    outside = _write_project(tmp_path / "elsewhere", "tool")
    for p in (in_roots, outside):
        assert dp.main(["--add", str(p), "--registry", str(registry)]) == 0
    (in_roots / "AGENTS.md").write_text(AGENTS_MD_TEMPLATE.format(name="proj2", extra=""), encoding="utf-8")
    (outside / "AGENTS.md").write_text(
        AGENTS_MD_TEMPLATE.format(name="tool2", extra="version: 9.9.9"), encoding="utf-8",
    )

    assert dp.main(["--roots", str(tmp_path / "roots"), "--registry", str(registry)]) == 0

    projects = yaml.safe_load(registry.read_text(encoding="utf-8"))["projects"]
    assert set(projects) == {"proj2", "tool2"}
    assert projects["tool2"]["path"] == str(outside.resolve())


def test_refresh_refreshes_kept_entry_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIPLAYBOOK_PROJECTS_ROOTS", raising=False)
    registry = tmp_path / "registry.yaml"
    alpha = _write_project(tmp_path / "elsewhere", "alpha")
    assert dp.main(["--add", str(alpha), "--registry", str(registry)]) == 0
    (alpha / "AGENTS.md").write_text(
        AGENTS_MD_TEMPLATE.format(name="alpha", extra="personal: true"), encoding="utf-8",
    )

    assert dp.main(["--roots", str(tmp_path / "roots-empty"), "--registry", str(registry)]) == 0

    assert yaml.safe_load(registry.read_text(encoding="utf-8"))["projects"]["alpha"]["personal"] is True


def test_main_add_missing_agents_md(tmp_path: Path) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    rc = dp.main(["--add", str(target), "--registry", str(tmp_path / "r.yaml")])
    assert rc == 1
