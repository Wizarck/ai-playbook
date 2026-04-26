"""Tests for scripts/schema_validate.py. Populated in T09."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts import schema_validate as sv

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


VALID_FRONTMATTER = """---
schema: agents-md/v1
version: 1.0.0
inherits_from:
  - github.com/Wizarck/ai-playbook@v0.1.0
updated: 2026-04-23
project: acme-shop
owner: jane@acme.example
capabilities_map: false
---

# body
"""


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parse_frontmatter_valid() -> None:
    fm = sv.parse_frontmatter(VALID_FRONTMATTER)
    assert fm.present is True
    assert fm.data["project"] == "acme-shop"
    assert fm.data["owner"] == "jane@acme.example"
    assert fm.body.startswith("\n# body")


def test_parse_frontmatter_missing() -> None:
    fm = sv.parse_frontmatter("# No frontmatter here\n")
    assert fm.present is False
    assert fm.data == {}
    assert fm.body == "# No frontmatter here\n"


def test_parse_frontmatter_crlf_normalised() -> None:
    text = VALID_FRONTMATTER.replace("\n", "\r\n")
    fm = sv.parse_frontmatter(text)
    assert fm.present is True
    assert fm.data["project"] == "acme-shop"


def test_parse_frontmatter_unterminated() -> None:
    text = "---\nschema: agents-md/v1\n\n# body without closing fence\n"
    fm = sv.parse_frontmatter(text)
    assert fm.present is False


# ---------------------------------------------------------------------------
# Autofix helpers
# ---------------------------------------------------------------------------


def test_slugify() -> None:
    assert sv.slugify("Acme Shop") == "acme-shop"
    assert sv.slugify("my_project") == "my-project"
    assert sv.slugify("  Weird___Name  ") == "weird-name"
    assert sv.slugify("already-valid") == "already-valid"


def test_normalise_date_variants() -> None:
    assert sv.normalise_date("2026-04-23") == "2026-04-23"
    assert sv.normalise_date("2026/04/23") == "2026-04-23"
    assert sv.normalise_date("2026-4-23") == "2026-04-23"
    assert sv.normalise_date("April 23 2026") == "2026-04-23"
    assert sv.normalise_date("April 23, 2026") == "2026-04-23"
    assert sv.normalise_date("23 April 2026") == "2026-04-23"
    assert sv.normalise_date(date(2026, 4, 23)) == "2026-04-23"
    assert sv.normalise_date("not-a-date") is None


def test_read_pinned_version_fallback(tmp_path: Path) -> None:
    # No .ai-playbook/VERSION file -> fallback v0.1.0
    assert sv.read_pinned_version(tmp_path) == sv.DEFAULT_PINNED_VERSION


def test_read_pinned_version_from_file(tmp_path: Path) -> None:
    version_dir = tmp_path / ".ai-playbook"
    version_dir.mkdir()
    (version_dir / "VERSION").write_text("0.2.1\n", encoding="utf-8")
    assert sv.read_pinned_version(tmp_path) == "v0.2.1"


# ---------------------------------------------------------------------------
# Autofix application
# ---------------------------------------------------------------------------


def test_autofix_injects_when_no_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    p = _write(tmp_path / "AGENTS.md", "# Just a heading\n")
    fm = sv.parse_frontmatter(p.read_text(encoding="utf-8"))
    new_fm, fixes = sv.apply_autofix(fm, file_path=p)
    assert new_fm.present is True
    assert new_fm.data["schema"] == "agents-md/v1"
    assert new_fm.data["owner"] == "test@example.com"
    assert any("injected full default" in f for f in fixes)


def test_autofix_preserves_valid_slug(tmp_path: Path) -> None:
    content = """---
schema: agents-md/v1
version: 1.0.0
updated: 2026-04-23
project: openTrattOS
owner: owner@example.com
capabilities_map: true
inherits_from:
  - github.com/Wizarck/ai-playbook@v0.1.0
---
# body
"""
    p = _write(tmp_path / "AGENTS.md", content)
    fm = sv.parse_frontmatter(p.read_text(encoding="utf-8"))
    new_fm, fixes = sv.apply_autofix(fm, file_path=p)
    # openTrattOS is a valid slug (camelCase allowed). Must NOT be rewritten.
    assert new_fm.data["project"] == "openTrattOS"
    # No project-related fix should be in the list.
    assert not any("slugified" in f for f in fixes)


def test_autofix_slugifies_invalid_project(tmp_path: Path) -> None:
    content = """---
schema: agents-md/v1
version: 1.0.0
updated: 2026-04-23
project: My Shop
owner: owner@example.com
---
"""
    p = _write(tmp_path / "AGENTS.md", content)
    fm = sv.parse_frontmatter(p.read_text(encoding="utf-8"))
    new_fm, fixes = sv.apply_autofix(fm, file_path=p)
    assert new_fm.data["project"] == "my-shop"
    assert any("slugified" in f for f in fixes)


def test_autofix_repairs_updated_date(tmp_path: Path) -> None:
    content = """---
schema: agents-md/v1
version: 1.0.0
updated: "2026/04/23"
project: myrepo
owner: o@example.com
---
"""
    p = _write(tmp_path / "AGENTS.md", content)
    fm = sv.parse_frontmatter(p.read_text(encoding="utf-8"))
    new_fm, fixes = sv.apply_autofix(fm, file_path=p)
    assert new_fm.data["updated"] == "2026-04-23"
    assert any("normalised `updated:" in f for f in fixes)


def test_autofix_adds_capabilities_map_and_inherits_from(tmp_path: Path) -> None:
    content = """---
schema: agents-md/v1
version: 1.0.0
updated: 2026-04-23
project: myrepo
owner: o@example.com
---
"""
    p = _write(tmp_path / "AGENTS.md", content)
    fm = sv.parse_frontmatter(p.read_text(encoding="utf-8"))
    new_fm, fixes = sv.apply_autofix(fm, file_path=p)
    assert new_fm.data["capabilities_map"] is False
    assert new_fm.data["inherits_from"] == [
        f"github.com/Wizarck/ai-playbook@{sv.DEFAULT_PINNED_VERSION}"
    ]
    assert any("capabilities_map" in f for f in fixes)
    assert any("inherits_from" in f for f in fixes)


def test_autofix_does_not_touch_owner_or_unknown_fields(tmp_path: Path) -> None:
    content = """---
schema: agents-md/v1
version: 1.0.0
updated: 2026-04-23
project: myrepo
owner: invalid-not-an-email
capabilities_map: false
inherits_from:
  - github.com/Wizarck/ai-playbook@v0.1.0
custom_field: keep_me
---
"""
    p = _write(tmp_path / "AGENTS.md", content)
    fm = sv.parse_frontmatter(p.read_text(encoding="utf-8"))
    new_fm, _fixes = sv.apply_autofix(fm, file_path=p)
    assert new_fm.data["owner"] == "invalid-not-an-email"
    assert new_fm.data.get("custom_field") == "keep_me"


# ---------------------------------------------------------------------------
# Full CLI (validate_one)
# ---------------------------------------------------------------------------


def test_validate_one_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _write(tmp_path / "AGENTS.md", VALID_FRONTMATTER)
    rc = sv.validate_one(p, schema=sv.load_schema(), autofix=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "frontmatter valid" in out


def test_validate_one_missing_frontmatter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = _write(tmp_path / "AGENTS.md", "# no fm here\n")
    rc = sv.validate_one(p, schema=sv.load_schema(), autofix=False)
    assert rc == 1
    err = capsys.readouterr().err
    assert "no YAML frontmatter" in err
    assert "FIX:" in err
    assert "OVERRIDE:" in err


def test_validate_one_missing_required_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = """---
schema: agents-md/v1
version: 1.0.0
updated: 2026-04-23
project: myrepo
---
"""
    p = _write(tmp_path / "AGENTS.md", content)
    rc = sv.validate_one(p, schema=sv.load_schema(), autofix=False)
    assert rc == 1
    err = capsys.readouterr().err
    # owner is a required field per the schema
    assert "owner" in err or "required" in err


def test_validate_one_autofix_writes_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "fix@example.com")
    p = _write(tmp_path / "AGENTS.md", "# no frontmatter\n")
    rc = sv.validate_one(p, schema=sv.load_schema(), autofix=True)
    assert rc == 0
    post = p.read_text(encoding="utf-8")
    assert post.startswith("---\n")
    assert "schema: agents-md/v1" in post
    assert "owner: fix@example.com" in post


def test_validate_one_nonexistent_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = sv.validate_one(tmp_path / "nope.md", schema=sv.load_schema(), autofix=False)
    assert rc == 1
    err = capsys.readouterr().err
    assert "not found" in err


# ---------------------------------------------------------------------------
# Full CLI (main)
# ---------------------------------------------------------------------------


def test_main_defaults_to_cwd_agents_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "AGENTS.md", VALID_FRONTMATTER)
    monkeypatch.chdir(tmp_path)
    rc = sv.main([])
    assert rc == 0


def test_main_break_glass_allows_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = _write(tmp_path / "AGENTS.md", "# no frontmatter\n")
    monkeypatch.chdir(tmp_path)
    rc = sv.main([
        str(p),
        "--force-with-reason=bootstrapping this repo for initial playbook wiring",
    ])
    assert rc == 0
    # Override log must exist
    log = tmp_path / ".ai-playbook" / "overrides.log"
    assert log.exists()
    content = log.read_text(encoding="utf-8")
    assert "bootstrapping this repo for initial playbook wiring" in content
