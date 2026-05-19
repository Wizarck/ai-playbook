"""Tests for scripts/init_org.py — fork parametrisation."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import init_org as io


def _make_fake_playbook(root: Path) -> None:
    rendered = root / "templates" / "rendered"
    rendered.mkdir(parents=True, exist_ok=True)
    (rendered / "mcp-servers-base.yaml.tmpl").write_text(
        "schema: mcp-servers/v1\n", encoding="utf-8",
    )
    (root / "AGENTS.md").write_text(
        "---\nschema: agents-md/v1\nproject: ai-playbook\n---\n# body\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "# Wizarck/ai-playbook\nConsumed at github.com/Wizarck/ai-playbook.\n",
        encoding="utf-8",
    )
    runbooks = root / "docs" / "runbooks"
    runbooks.mkdir(parents=True)
    (runbooks / "release.md").write_text("Push to Wizarck/consumer-c.\n", encoding="utf-8")
    (runbooks / "rotate-secrets.md").write_text("Wizarck/acme-corp secret rotation.\n", encoding="utf-8")
    (runbooks / "hindsight-retain.md").write_text("https://acme-corp-hindsight.consumer-bfood.com\n", encoding="utf-8")
    concepts = root / "docs" / "concepts"
    concepts.mkdir(parents=True)
    (concepts / "env-vars.md").write_text("https://acme-corp-hindsight.consumer-bfood.com\n", encoding="utf-8")
    (concepts / "session-start-hook.md").write_text(
        "https://acme-corp-hindsight.consumer-bfood.com\n",
        encoding="utf-8",
    )
    templates = root / "templates" / "new-project"
    templates.mkdir(parents=True)
    (templates / "AGENTS.md.tmpl").write_text(
        "owner: 23051550+Wizarck@users.noreply.github.com\n"
        "https://acme-corp-hindsight.consumer-bfood.com\n"
        "../acme-corp/secrets/secrets.env\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_org_name_rejects_uppercase() -> None:
    with pytest.raises(SystemExit):
        io._validate_org_name("Acme")


def test_validate_org_name_rejects_too_short() -> None:
    with pytest.raises(SystemExit):
        io._validate_org_name("ab")


def test_validate_org_name_accepts_valid_kebab() -> None:
    io._validate_org_name("acme")
    io._validate_org_name("my-org")
    io._validate_org_name("a1b2-c3")


def test_detect_playbook_root_walks_up(tmp_path: Path) -> None:
    _make_fake_playbook(tmp_path)
    sub = tmp_path / "subdir" / "deep"
    sub.mkdir(parents=True)
    found = io._detect_playbook_root(sub)
    assert found == tmp_path


def test_detect_playbook_root_fails_when_not_found(tmp_path: Path) -> None:
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(SystemExit):
        io._detect_playbook_root(bare)


# ---------------------------------------------------------------------------
# Edit application
# ---------------------------------------------------------------------------


def test_apply_replaces_wizarck_with_acme(tmp_path: Path) -> None:
    _make_fake_playbook(tmp_path)
    plan = io.build_edit_plan(
        root=tmp_path,
        org_name="acme",
        owner_email="ops@acme.example",
        hindsight_url="https://hindsight.acme.example",
        secrets_env_path="acme-core/secrets/secrets.env",
    )
    files, replacements = io.apply_edits(tmp_path, plan, dry_run=False)

    assert files >= 3

    # README.md uses the new org.
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "Wizarck" not in readme
    assert "acme" in readme

    # Hindsight URL applied.
    sst = (tmp_path / "docs" / "concepts" / "session-start-hook.md").read_text(encoding="utf-8")
    assert sst.strip() == "https://hindsight.acme.example"

    # SOPS path in templates.
    tmpl = (tmp_path / "templates" / "new-project" / "AGENTS.md.tmpl").read_text(encoding="utf-8")
    assert "acme-core/secrets/secrets.env" in tmpl
    assert "ops@acme.example" in tmpl


def test_apply_dry_run_does_not_mutate(tmp_path: Path) -> None:
    _make_fake_playbook(tmp_path)
    original = (tmp_path / "README.md").read_text(encoding="utf-8")
    plan = io.build_edit_plan(
        root=tmp_path, org_name="acme", owner_email="x@x.com",
        hindsight_url=None, secrets_env_path=None,
    )
    io.apply_edits(tmp_path, plan, dry_run=True)
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == original


def test_main_full_flow(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_fake_playbook(tmp_path)
    rc = io.main([
        "--org-name", "acme",
        "--owner-email", "ops@acme.example",
        "--root", str(tmp_path),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Touched" in out
    assert "Next steps" in out
