"""Tests for scripts/drift_check.py.

Exercises each check path (inherits, auto-managed, xref, taxonomy) plus the
CLI integration: exit codes, --fix behaviour on auto-managed only, and
--force-with-reason bypass.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts import auto_managed as am
from scripts import drift_check as dc


PLAYBOOK_ROOT = am.find_playbook_root()
assert PLAYBOOK_ROOT is not None, "test suite must run from inside the playbook"


AGENTS_MD_TEMPLATE = """\
---
schema: agents-md/v1
version: 1.0.0
inherits_from:
  - github.com/Wizarck/ai-playbook@{pin}
updated: 2026-04-23
project: {name}
owner: test@example.com
capabilities_map: true
---

# {name}
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _make_consumer(root: Path, name: str, pin: str) -> Path:
    project = root / name
    _write(project / "AGENTS.md", AGENTS_MD_TEMPLATE.format(pin=pin, name=name))
    return project


def _make_registry(tmp_path: Path, projects: dict[str, Path]) -> Path:
    reg = tmp_path / "registry.yaml"
    data = {
        "schema": "ai-playbook/projects-registry/v1",
        "projects": {
            name: {"path": str(path)} for name, path in projects.items()
        },
    }
    reg.write_text(yaml.safe_dump(data), encoding="utf-8")
    return reg


# ---------------------------------------------------------------------------
# inherits_from check
# ---------------------------------------------------------------------------


def test_extract_inherits_pins_parses_semver() -> None:
    text = AGENTS_MD_TEMPLATE.format(name="x", pin="v1.2.3")
    pins = dc._extract_inherits_pins(text)
    assert pins == [(1, 2, 3)]


def test_extract_inherits_pins_missing_is_empty() -> None:
    text = "no frontmatter\n"
    assert dc._extract_inherits_pins(text) == []


def test_check_inherits_flags_stale_pin(tmp_path: Path) -> None:
    # Playbook at its real version (e.g. 0.1.0). Pin consumer way behind.
    project = _make_consumer(tmp_path, "consumer", "v0.0.1")
    # Make the consumer's pin look far behind any plausible future playbook.
    # We rebuild a fake playbook to pin a known version.
    fake_pb = tmp_path / "pb"
    (fake_pb / "specs").mkdir(parents=True)
    (fake_pb / "scripts").mkdir(parents=True)
    (fake_pb / "VERSION").write_text("2.0.0", encoding="utf-8")
    registry = {
        "projects": {"consumer": {"path": str(project)}},
    }
    findings = dc.check_inherits(registry, fake_pb)
    assert any(f.kind == "inherits" for f in findings)
    assert any("consumer" in f.why for f in findings)


def test_check_inherits_accepts_current_pin(tmp_path: Path) -> None:
    project = _make_consumer(tmp_path, "consumer", "v1.0.0")
    fake_pb = tmp_path / "pb"
    (fake_pb / "specs").mkdir(parents=True)
    (fake_pb / "scripts").mkdir(parents=True)
    (fake_pb / "VERSION").write_text("1.1.0", encoding="utf-8")
    registry = {"projects": {"consumer": {"path": str(project)}}}
    findings = dc.check_inherits(registry, fake_pb)
    assert findings == []  # 1.0 is exactly one minor behind 1.1 — allowed


def test_check_inherits_multiple_consumers(tmp_path: Path) -> None:
    a = _make_consumer(tmp_path / "roots", "a", "v2.0.0")
    b = _make_consumer(tmp_path / "roots", "b", "v1.0.0")
    fake_pb = tmp_path / "pb"
    (fake_pb / "specs").mkdir(parents=True)
    (fake_pb / "scripts").mkdir(parents=True)
    (fake_pb / "VERSION").write_text("2.5.0", encoding="utf-8")
    registry = {
        "projects": {
            "a": {"path": str(a)},
            "b": {"path": str(b)},
        }
    }
    findings = dc.check_inherits(registry, fake_pb)
    # 'b' is pinned 2 majors behind, 'a' is 5 minors behind → both flagged.
    names_flagged = {f.why.split("'")[1] for f in findings if "'" in f.why}
    assert "b" in names_flagged
    assert "a" in names_flagged


# ---------------------------------------------------------------------------
# auto-managed drift check (delegates to auto_managed)
# ---------------------------------------------------------------------------


def test_check_auto_managed_detects_stale(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    _write(
        consumer / "doc.md",
        "<!-- BEGIN auto-managed: specs/taxonomy:runtime -->\n"
        "stale placeholder\n"
        "<!-- END auto-managed -->\n",
    )
    findings = dc.check_auto_managed([consumer], PLAYBOOK_ROOT, fix=False)
    assert any(f.kind == "auto-managed" for f in findings)
    # Not fixed — file untouched on disk.
    assert "stale placeholder" in (consumer / "doc.md").read_text(encoding="utf-8")


def test_check_auto_managed_fix_applies(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    f = _write(
        consumer / "doc.md",
        "<!-- BEGIN auto-managed: specs/taxonomy:runtime -->\n"
        "stale\n"
        "<!-- END auto-managed -->\n",
    )
    dc.check_auto_managed([consumer], PLAYBOOK_ROOT, fix=True)
    assert "stale" not in f.read_text(encoding="utf-8")
    assert "| Agent |" in f.read_text(encoding="utf-8")


def test_check_auto_managed_marker_error(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    _write(
        consumer / "doc.md",
        "<!-- BEGIN auto-managed: a -->\n"
        "<!-- BEGIN auto-managed: b -->\n"
        "<!-- END auto-managed -->\n"
        "<!-- END auto-managed -->\n",
    )
    findings = dc.check_auto_managed([consumer], PLAYBOOK_ROOT, fix=False)
    assert any("marker syntax" in f.why for f in findings)


# ---------------------------------------------------------------------------
# xref check
# ---------------------------------------------------------------------------


def test_check_xrefs_flags_missing_target(tmp_path: Path) -> None:
    fake_pb = tmp_path / "pb"
    specs = fake_pb / "specs"
    specs.mkdir(parents=True)
    _write(specs / "a.md", "see [missing](nonexistent.md)\n")
    findings = dc.check_xrefs(fake_pb)
    assert any(f.kind == "xref" for f in findings)
    assert any("nonexistent.md" in f.why for f in findings)


def test_check_xrefs_accepts_http_and_anchors(tmp_path: Path) -> None:
    fake_pb = tmp_path / "pb"
    specs = fake_pb / "specs"
    specs.mkdir(parents=True)
    _write(
        specs / "a.md",
        "see [ok](https://example.com/x)\n"
        "see [anchor](#section)\n"
        "see [self](a.md)\n",
    )
    findings = dc.check_xrefs(fake_pb)
    assert findings == []


# ---------------------------------------------------------------------------
# taxonomy check
# ---------------------------------------------------------------------------


def test_check_taxonomy_threshold_filters(tmp_path: Path) -> None:
    fake_pb = tmp_path / "pb"
    (fake_pb / "specs").mkdir(parents=True)
    (fake_pb / "docs").mkdir(parents=True)
    # Minimal taxonomy with a single term.
    _write(
        fake_pb / "specs" / "taxonomy.md",
        "# taxonomy\n\n"
        "## 1 Runtime entities\n\n"
        "| Term | Definition | Example | Scope |\n"
        "|---|---|---|---|\n"
        "| Widget | The only defined term. | x | x |\n\n"
        "## 2 Config artefacts\n\n"
        "| Term | Definition | Example | Scope |\n"
        "|---|---|---|---|\n\n"
        "## 3 Process concepts\n\n"
        "| Term | Definition | Example | Scope |\n"
        "|---|---|---|---|\n\n"
        "## 4 Distinctions worth hammering\n\n"
        "tail\n",
    )
    # An undefined term 'Frobnicator' in only 2 files (below threshold).
    _write(fake_pb / "docs" / "a.md", "Frobnicator appears here.\n")
    _write(fake_pb / "docs" / "b.md", "Also Frobnicator here.\n")
    findings = dc.check_taxonomy(fake_pb)
    assert not any("Frobnicator" in f.why for f in findings)


def test_check_taxonomy_triggers_at_threshold(tmp_path: Path) -> None:
    fake_pb = tmp_path / "pb"
    (fake_pb / "specs").mkdir(parents=True)
    (fake_pb / "docs").mkdir(parents=True)
    _write(
        fake_pb / "specs" / "taxonomy.md",
        "# taxonomy\n\n"
        "## 1 Runtime entities\n\n"
        "| Term | Definition | Example | Scope |\n"
        "|---|---|---|---|\n"
        "| Widget | known term | x | x |\n\n"
        "## 4 Distinctions worth hammering\n\n"
        "tail\n",
    )
    for name in ("a", "b", "c"):
        _write(fake_pb / "docs" / f"{name}.md", "Frobnicator rules.\n")
    findings = dc.check_taxonomy(fake_pb)
    assert any("Frobnicator" in f.why for f in findings)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_clean_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """All checks clean on an empty consumer set + real playbook."""
    registry = _make_registry(tmp_path, {})
    rc = dc.main(
        [
            "--registry", str(registry),
            "--playbook-root", str(PLAYBOOK_ROOT),
            "--check", "auto-managed",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "No drift detected" in out


def test_cli_auto_managed_drift_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    consumer = tmp_path / "consumer"
    _write(
        consumer / "doc.md",
        "<!-- BEGIN auto-managed: specs/taxonomy:runtime -->\n"
        "stale\n"
        "<!-- END auto-managed -->\n",
    )
    registry = _make_registry(tmp_path, {})
    rc = dc.main(
        [
            "--registry", str(registry),
            "--playbook-root", str(PLAYBOOK_ROOT),
            "--consumer-root", str(consumer),
            "--check", "auto-managed",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "auto-managed" in err


def test_cli_fix_applies_to_auto_managed(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    f = _write(
        consumer / "doc.md",
        "<!-- BEGIN auto-managed: specs/taxonomy:runtime -->\n"
        "stale\n"
        "<!-- END auto-managed -->\n",
    )
    registry = _make_registry(tmp_path, {})
    rc = dc.main(
        [
            "--registry", str(registry),
            "--playbook-root", str(PLAYBOOK_ROOT),
            "--consumer-root", str(consumer),
            "--check", "auto-managed",
            "--fix",
        ]
    )
    # After --fix, the file is clean, so a second internal scan reports clean.
    assert rc == 0
    assert "| Agent |" in f.read_text(encoding="utf-8")


def test_cli_force_with_reason_bypasses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    consumer = tmp_path / "consumer"
    _write(
        consumer / "doc.md",
        "<!-- BEGIN auto-managed: specs/taxonomy:runtime -->\n"
        "stale\n"
        "<!-- END auto-managed -->\n",
    )
    registry = _make_registry(tmp_path, {})
    rc = dc.main(
        [
            "--registry", str(registry),
            "--playbook-root", str(PLAYBOOK_ROOT),
            "--consumer-root", str(consumer),
            "--check", "auto-managed",
            "--force-with-reason", "hotfix — drift will land next commit",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "OVERRIDE APPLIED" in out


def test_cli_bad_playbook_root_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = dc.main(
        [
            "--playbook-root", str(tmp_path / "nope"),
            "--check", "auto-managed",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "playbook root not found" in err or "specs/" in err


def test_cli_xref_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--check xref scans playbook only; we point at a fake broken playbook."""
    fake_pb = tmp_path / "pb"
    (fake_pb / "specs").mkdir(parents=True)
    (fake_pb / "scripts").mkdir(parents=True)
    _write(fake_pb / "VERSION", "0.1.0\n")
    _write(fake_pb / "specs" / "broken.md", "see [gone](gone.md)\n")
    registry = _make_registry(tmp_path, {})
    rc = dc.main(
        [
            "--registry", str(registry),
            "--playbook-root", str(fake_pb),
            "--check", "xref",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "gone.md" in err
