"""Tests for ``scripts._managed_files`` — orchestration of file renders."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import _managed_files


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_lf(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))


@pytest.fixture
def fake_playbook(tmp_path: Path) -> Path:
    """Build a minimal playbook tree with the templates the orchestrator looks for."""
    root = tmp_path / "playbook"
    tdir = root / "templates" / "new-project"
    tdir.mkdir(parents=True)
    _write_lf(tdir / "AGENTS.md.tmpl", (
        "---\n"
        "schema: agents-md/v1\n"
        "project: {{PROJECT_NAME}}\n"
        "owner: {{OWNER_EMAIL}}\n"
        "---\n\n"
        "# {{PROJECT_NAME}} — AGENTS.md\n\n"
        "<!-- ai-playbook:begin id=bootstrap-directive -->\n"
        "Canonical bootstrap.\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n\n"
        "## §1 Project identity\n"
        "{{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}\n"
    ))
    _write_lf(tdir / ".gitignore.tmpl", (
        "# >>> ai-playbook:begin id=playbook-patterns >>>\n"
        ".ai-playbook/overrides.log\n"
        "# <<< ai-playbook:end playbook-patterns <<<\n"
    ))
    _write_lf(tdir / ".pre-commit-config.yaml.tmpl", (
        "repos:\n"
        "# >>> ai-playbook:begin id=playbook-hooks >>>\n"
        "  - repo: local\n"
        "    hooks: []\n"
        "# <<< ai-playbook:end playbook-hooks <<<\n"
    ))
    _write_lf(tdir / ".coderabbit.yaml.tmpl", "language: en-US\n")
    (tdir / ".claude").mkdir()
    _write_lf(tdir / ".claude" / "settings.local.json.tmpl", '{"seed": true}\n')
    _write_lf(tdir / ".claude" / "settings.json.tmpl", (
        '{\n'
        '  "hooks": {\n'
        '    "PreToolUse": [\n'
        '      {\n'
        '        "matcher": "Edit|Write|MultiEdit|Bash",\n'
        '        "hooks": [\n'
        '          {"type": "command",'
        ' "command": "python .claude/hooks/openspec-apply-enforce.py",'
        ' "timeout": 10}\n'
        '        ]\n'
        '      }\n'
        '    ]\n'
        '  },\n'
        '  "permissions": {"allow": [], "additionalDirectories": []}\n'
        '}\n'
    ))
    _write_lf(tdir / "mcp-servers.project.yaml.tmpl", (
        "schema: mcp-servers/v1\n"
        "# >>> ai-playbook:begin id=project-servers-baseline >>>\n"
        "servers:\n"
        "  hindsight:\n"
        "    id: hindsight\n"
        "# <<< ai-playbook:end project-servers-baseline <<<\n"
    ))
    return root


@pytest.fixture
def fake_consumer(tmp_path: Path) -> Path:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    _write_lf(consumer / "AGENTS.md", (
        "---\n"
        "schema: agents-md/v1\n"
        "project: myproj\n"
        "owner: dev@example.com\n"
        "---\n\n"
        "# myproj — AGENTS.md (stale)\n"
    ))
    return consumer


# ---------------------------------------------------------------------------
# compute_substitutions
# ---------------------------------------------------------------------------


def test_compute_substitutions_from_agents_md_frontmatter(fake_consumer: Path) -> None:
    subs = _managed_files.compute_substitutions(fake_consumer)
    assert subs["PROJECT_NAME"] == "myproj"
    assert subs["OWNER_EMAIL"] == "dev@example.com"
    assert subs["PROJECT_BANK"] == "myproj"
    assert "TODAY" in subs


def test_compute_substitutions_falls_back_to_dir_name(tmp_path: Path) -> None:
    consumer = tmp_path / "fresh-project"
    consumer.mkdir()
    subs = _managed_files.compute_substitutions(consumer)
    assert subs["PROJECT_NAME"] == "fresh-project"
    assert subs["OWNER_EMAIL"] == "unknown@example.com"


# ---------------------------------------------------------------------------
# apply_managed_files — no triggers
# ---------------------------------------------------------------------------


def test_no_trigger_sections_no_op(fake_playbook: Path, fake_consumer: Path) -> None:
    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer,
        playbook_root=fake_playbook,
        bundle={"schema": "ai-playbook-config/v1"},
    )
    assert result.ok
    assert "no managed-file trigger sections" in result.detail
    assert (fake_consumer / "AGENTS.md").read_text(encoding="utf-8").startswith("---")


# ---------------------------------------------------------------------------
# apply_managed_files — AGENTS.md
# ---------------------------------------------------------------------------


def test_agents_md_rendered_when_project_meta_present(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    bundle = {
        "schema": "ai-playbook-config/v1",
        "project_meta": {"project_identity": "Acme builds widgets."},
    }
    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    assert result.ok
    rendered = (fake_consumer / "AGENTS.md").read_text(encoding="utf-8")
    assert "myproj" in rendered
    assert "Acme builds widgets." in rendered
    assert "Canonical bootstrap." in rendered
    assert result.restart_session_needed  # AGENTS.md is LLM-read
    assert "AGENTS.md" in result.file_states
    assert "bootstrap-directive" in result.file_states["AGENTS.md"]["manifest"]


def test_agents_md_backup_created_on_overwrite(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    bundle = {
        "schema": "ai-playbook-config/v1",
        "project_meta": {"project_identity": "new identity"},
    }
    _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    # Default backup_preferences = next + timestamped
    backups = list(fake_consumer.glob("AGENTS.md.*.bak"))
    assert len(backups) == 1


def test_agents_md_idempotent_no_backup_no_write(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    bundle = {
        "schema": "ai-playbook-config/v1",
        "project_meta": {"project_identity": "stable"},
    }
    _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    # second apply with same bundle
    result2 = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    # Only one backup from the first apply.
    backups = list(fake_consumer.glob("AGENTS.md.*.bak"))
    assert len(backups) == 1
    assert any("identical, no write" in c for c in result2.changes)


# ---------------------------------------------------------------------------
# apply_managed_files — .gitignore preservation
# ---------------------------------------------------------------------------


def test_gitignore_preserves_consumer_lines(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    _write_lf(fake_consumer / ".gitignore", (
        "# my custom\n"
        "dist/\n"
        "logs/\n\n"
        "# >>> ai-playbook:begin id=playbook-patterns >>>\n"
        ".ai-playbook/overrides.log\n"
        "# <<< ai-playbook:end playbook-patterns <<<\n"
    ))
    bundle = {
        "schema": "ai-playbook-config/v1",
        "gitignore_extras": {"patterns": ["*.swp"]},
    }
    _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    rendered = (fake_consumer / ".gitignore").read_text(encoding="utf-8")
    assert "dist/" in rendered
    assert "logs/" in rendered
    assert "*.swp" in rendered
    assert ".ai-playbook/overrides.log" in rendered


# ---------------------------------------------------------------------------
# apply_managed_files — .claude/settings.json folded into the door
# ---------------------------------------------------------------------------


def test_settings_json_seeded_and_ensures_invariant(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    bundle = {"schema": "ai-playbook-config/v1", "settings": {}}
    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    assert result.ok
    settings = json.loads(
        (fake_consumer / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    cmds = [h.get("command", "")
            for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert any("openspec-apply-enforce.py" in c for c in cmds)
    assert result.restart_session_needed  # settings.json is LLM-read


def test_settings_json_preserves_user_keys_through_door(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    dest = fake_consumer / ".claude" / "settings.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    _write_lf(dest, json.dumps({
        "hooks": {"SessionStart": [{"hooks": [
            {"type": "command", "command": "echo keep-me"}]}]},
        "permissions": {"allow": ["Bash"]},
        "userland": 42,
    }) + "\n")
    bundle = {
        "schema": "ai-playbook-config/v1",
        "settings": {"permissions_allow": ["WebSearch"]},
    }
    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    assert result.ok
    merged = json.loads(dest.read_text(encoding="utf-8"))
    assert merged["userland"] == 42
    assert merged["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "echo keep-me"
    assert set(merged["permissions"]["allow"]) == {"Bash", "WebSearch"}
    assert any("openspec-apply-enforce.py" in h.get("command", "")
               for e in merged["hooks"]["PreToolUse"] for h in e["hooks"])


def test_settings_json_in_sync_is_byte_noop(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    bundle = {"schema": "ai-playbook-config/v1", "settings": {}}
    _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    before = (fake_consumer / ".claude" / "settings.json").read_text(encoding="utf-8")
    result2 = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    after = (fake_consumer / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert before == after
    assert any("identical, no write" in c for c in result2.changes)


# ---------------------------------------------------------------------------
# apply_managed_files — seed-only behaviour
# ---------------------------------------------------------------------------


def test_settings_local_json_seed_only_when_missing(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    bundle = {
        "schema": "ai-playbook-config/v1",
        "claude_settings_extras": {"permissions_allow": ["Edit"]},
    }
    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    dest = fake_consumer / ".claude" / "settings.local.json"
    assert dest.is_file()
    payload = json.loads(dest.read_text(encoding="utf-8"))
    assert payload["permissions"]["allow"] == ["Edit"]
    assert result.restart_session_needed


def test_settings_local_json_seed_only_kept_when_existing(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    dest = fake_consumer / ".claude" / "settings.local.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    _write_lf(dest, '{"existing": true}\n')
    bundle = {
        "schema": "ai-playbook-config/v1",
        "claude_settings_extras": {"permissions_allow": ["Edit"]},
    }
    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    # seed-only file already exists → kept as-is, NOT overwritten by extras.
    assert json.loads(dest.read_text(encoding="utf-8")) == {"existing": True}
    assert any("seed-only" in c for c in result.changes)


# ---------------------------------------------------------------------------
# apply_managed_files — dry-run
# ---------------------------------------------------------------------------


def test_dry_run_does_not_touch_disk(fake_playbook: Path, fake_consumer: Path) -> None:
    original = (fake_consumer / "AGENTS.md").read_text(encoding="utf-8")
    bundle = {
        "schema": "ai-playbook-config/v1",
        "project_meta": {"project_identity": "new"},
    }
    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
        dry_run=True,
    )
    assert (fake_consumer / "AGENTS.md").read_text(encoding="utf-8") == original
    assert "DRY-RUN" in result.detail
    assert "AGENTS.md" in result.detail


# ---------------------------------------------------------------------------
# apply_managed_files — backup central location
# ---------------------------------------------------------------------------


def test_backup_central_location_respected(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    bundle = {
        "schema": "ai-playbook-config/v1",
        "project_meta": {"project_identity": "new"},
        "backup_preferences": {"location": "central", "with_timestamp": True},
    }
    _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    next_to_file = list(fake_consumer.glob("AGENTS.md.*.bak"))
    assert next_to_file == []
    central = list((fake_consumer / ".ai-playbook-state" / "backups").rglob("AGENTS.md.*.bak"))
    assert len(central) == 1


# ---------------------------------------------------------------------------
# Transactional stage-then-commit (reconcile-foundation slice B)
# ---------------------------------------------------------------------------


def test_commit_failure_rolls_back_the_batch(
    fake_playbook: Path, fake_consumer: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A write failure mid-commit restores every already-written file from the
    session backups, leaving the batch atomic (all-or-nothing)."""
    original_gitignore = "node_modules/\n"
    _write_lf(fake_consumer / ".gitignore", original_gitignore)
    original_agents = (fake_consumer / "AGENTS.md").read_text(encoding="utf-8")

    bundle = {
        "schema": "ai-playbook-config/v1",
        "project_meta": {"project_identity": "Widgets Inc."},
        "gitignore_extras": {"patterns": ["dist/"]},
    }

    real_write = _managed_files._atomic_write_text

    def flaky_write(path: Path, content: str) -> None:
        if path.name == ".gitignore":
            raise OSError("simulated disk-full on .gitignore")
        return real_write(path, content)

    monkeypatch.setattr(_managed_files, "_atomic_write_text", flaky_write)

    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer,
        playbook_root=fake_playbook,
        bundle=bundle,
        session_id="tx-rollback",
    )

    assert result.ok is False
    assert any("rolled back" in c for c in result.changes)
    # AGENTS.md was written, then rolled back to its pre-commit content.
    assert (fake_consumer / "AGENTS.md").read_text(encoding="utf-8") == original_agents
    # .gitignore (the failing write) is untouched — atomic write never replaced it.
    assert (fake_consumer / ".gitignore").read_text(encoding="utf-8") == original_gitignore


def test_staging_render_failure_leaves_disk_untouched(
    fake_playbook: Path, fake_consumer: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A render failure during staging aborts before any write — no file
    mutated, no .bak created."""
    original_agents = (fake_consumer / "AGENTS.md").read_text(encoding="utf-8")

    def boom_renderer(**_kwargs: object) -> str:
        raise RuntimeError("render exploded")

    boom_mf = _managed_files.ManagedFile(
        rel_path="AGENTS.md",
        template_rel="AGENTS.md.tmpl",
        renderer=boom_renderer,
        trigger_section="project_meta",
        style=_managed_files.CommentStyle.HTML,
        use_current_text=True,
    )
    monkeypatch.setattr(_managed_files, "MANAGED_FILES", [boom_mf])

    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer,
        playbook_root=fake_playbook,
        bundle={"schema": "ai-playbook-config/v1", "project_meta": {"project_identity": "X"}},
        session_id="tx-stage",
    )

    assert result.ok is False
    assert (fake_consumer / "AGENTS.md").read_text(encoding="utf-8") == original_agents
    assert list(fake_consumer.glob("AGENTS.md.*.bak")) == []


# ---------------------------------------------------------------------------
# Conflict gate — two-state SHA enforcement (never overwrite silently)
# ---------------------------------------------------------------------------


def _seal_agents_md(fake_playbook: Path, fake_consumer: Path) -> None:
    """First apply: render AGENTS.md so the bootstrap-directive block gets a
    sealed sha= matching its content."""
    _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook,
        bundle={"schema": "ai-playbook-config/v1",
                "project_meta": {"project_identity": "seed"}},
    )


def test_drifted_block_without_decision_is_a_conflict(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    """A consumer edit inside a sealed canonical block, with no curate
    decision, blocks the write and marks the section failed."""
    _seal_agents_md(fake_playbook, fake_consumer)
    agents = fake_consumer / "AGENTS.md"
    edited = agents.read_text(encoding="utf-8").replace(
        "Canonical bootstrap.", "I edited this canonical block by hand."
    )
    agents.write_text(edited, encoding="utf-8")

    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook,
        bundle={"schema": "ai-playbook-config/v1",
                "project_meta": {"project_identity": "seed"}},
    )

    assert result.ok is False
    assert any("conflict" in c for c in result.changes)
    # The consumer's hand edit is preserved (not overwritten).
    assert "I edited this canonical block by hand." in agents.read_text(encoding="utf-8")
    assert result.file_states["AGENTS.md"]["conflict"] == ["bootstrap-directive"]


def test_drifted_block_keep_mine_preserves_and_reseals(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    """keep_mine restores the consumer's content and re-seals the sha so the
    next apply is a clean no-op (idempotent)."""
    _seal_agents_md(fake_playbook, fake_consumer)
    agents = fake_consumer / "AGENTS.md"
    edited = agents.read_text(encoding="utf-8").replace(
        "Canonical bootstrap.", "Keep my version."
    )
    agents.write_text(edited, encoding="utf-8")

    bundle = {
        "schema": "ai-playbook-config/v1",
        "project_meta": {"project_identity": "seed"},
        "file_curate_intents": {
            "AGENTS.md": {"blocks": {"bootstrap-directive": "keep_mine"}}
        },
    }
    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    assert result.ok is True
    assert "Keep my version." in agents.read_text(encoding="utf-8")

    # Second apply is now clean (the sha was re-sealed to the kept content).
    result2 = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    assert result2.ok is True
    assert any("identical, no write" in c for c in result2.changes)


def test_drifted_block_take_playbook_overwrites_with_backup(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    """take_playbook lets the template content win and backs up the prior file."""
    _seal_agents_md(fake_playbook, fake_consumer)
    agents = fake_consumer / "AGENTS.md"
    edited = agents.read_text(encoding="utf-8").replace(
        "Canonical bootstrap.", "throwaway local edit"
    )
    agents.write_text(edited, encoding="utf-8")

    bundle = {
        "schema": "ai-playbook-config/v1",
        "project_meta": {"project_identity": "seed"},
        "file_curate_intents": {
            "AGENTS.md": {"default_action": "take_playbook"}
        },
    }
    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    assert result.ok is True
    text = agents.read_text(encoding="utf-8")
    assert "Canonical bootstrap." in text
    assert "throwaway local edit" not in text
    assert len(list(fake_consumer.glob("AGENTS.md.*.bak"))) >= 1


def test_dry_run_reports_conflict_as_failure(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    """`--check` (dry-run) surfaces an unresolved conflict as ok=False, untouched disk."""
    _seal_agents_md(fake_playbook, fake_consumer)
    agents = fake_consumer / "AGENTS.md"
    before = agents.read_text(encoding="utf-8").replace(
        "Canonical bootstrap.", "drifted in check mode"
    )
    agents.write_text(before, encoding="utf-8")

    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook,
        bundle={"schema": "ai-playbook-config/v1",
                "project_meta": {"project_identity": "seed"}},
        dry_run=True,
    )
    assert result.ok is False
    assert "conflict" in result.detail
    assert agents.read_text(encoding="utf-8") == before  # nothing written


def test_legacy_block_without_sha_is_not_a_conflict(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    """A canonical block whose on-disk marker carries no sha= (legacy / first
    touch) is a clean seed, never a conflict — the playbook re-seals it."""
    # Consumer AGENTS.md with a sha-less canonical block whose content differs
    # from the template (would be 'drift' if a sha were present).
    _write_lf(fake_consumer / "AGENTS.md", (
        "---\nschema: agents-md/v1\nproject: myproj\nowner: dev@example.com\n---\n\n"
        "# myproj\n\n"
        "<!-- ai-playbook:begin id=bootstrap-directive -->\n"
        "legacy hand-written content, no sha marker\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n"
    ))
    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook,
        bundle={"schema": "ai-playbook-config/v1",
                "project_meta": {"project_identity": "seed"}},
    )
    assert result.ok is True
    text = (fake_consumer / "AGENTS.md").read_text(encoding="utf-8")
    # Re-sealed to the template's canonical content with a fresh sha.
    assert "Canonical bootstrap." in text
    assert "sha=" in text


def test_conflict_in_one_file_does_not_block_others(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    """Per-file skip: a conflict on AGENTS.md still lets .gitignore commit."""
    _seal_agents_md(fake_playbook, fake_consumer)
    agents = fake_consumer / "AGENTS.md"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace(
            "Canonical bootstrap.", "edited, undecided"),
        encoding="utf-8",
    )
    bundle = {
        "schema": "ai-playbook-config/v1",
        "project_meta": {"project_identity": "seed"},
        "gitignore_extras": {"patterns": ["*.tmp"]},
    }
    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    assert result.ok is False  # overall: unresolved conflict
    # .gitignore still got written (per-file skip, not full-batch abort).
    gitignore = (fake_consumer / ".gitignore").read_text(encoding="utf-8")
    assert "*.tmp" in gitignore
    # AGENTS.md kept the consumer edit.
    assert "edited, undecided" in agents.read_text(encoding="utf-8")
