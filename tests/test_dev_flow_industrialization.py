"""Tests for the v0.9.3 dev-flow industrialization PR (#33).

Coverage:

- scripts/auto_tick_tasks (Followup #4 OPT 1):
    - parse_subject extracts groups / sections / tasks correctly
    - tick_tasks_md ticks group + section + task scopes
    - tick_tasks_md is idempotent (running twice = no-op on already-ticked)
    - depth-aware scope reset (Group 2 doesn't bleed into §3)
    - non-conventional commit subject = no-op (exit 0)
    - missing tasks.md = no-op (exit 0, never blocks)
    - branch outside `<type>/<change-id>` = no-op without --change-id

- scripts/schema_validate (Opción 2 — dev-flow cross-ref check):
    - check_dev_flow_cross_ref returns True/False correctly
    - validate_one warn-only path: missing link → exit 0 + stderr warning
    - validate_one strict path: missing link → exit 1 + canonical error
    - validate_one happy path: link present → exit 0 silent

NOTE (v0.19.0): Opción 1 was retired when the push pipeline was removed — the
cross-ref row had long since landed in every consumer's AGENTS.md, so the
migration is complete. The validator (Opción 2) is the surviving guarantee.
"""
from __future__ import annotations

from pathlib import Path

from scripts import auto_tick_tasks as att
from scripts import schema_validate as sv

# ---------------------------------------------------------------------------
# auto_tick_tasks.parse_subject
# ---------------------------------------------------------------------------


class TestParseSubject:
    def test_groups_range(self):
        refs = att.parse_subject("groups 1-3")
        assert refs["groups"] == {"1", "2", "3"}
        assert refs["sections"] == set()
        assert refs["tasks"] == set()

    def test_single_group(self):
        refs = att.parse_subject("group 2 implementation")
        assert refs["groups"] == {"2"}

    def test_section_major_only(self):
        refs = att.parse_subject("§3 wiring")
        assert refs["sections"] == {"3"}
        assert refs["tasks"] == set()

    def test_section_major_minor_populates_both(self):
        # Per the parser: §N.M adds BOTH section "N.M" AND task "N.M".
        # Rationale: handles files with `## §3` headers and `3.1` tasks inside.
        refs = att.parse_subject("§3.1 + §3.2 done")
        assert refs["sections"] == {"3.1", "3.2"}
        assert refs["tasks"] == {"3.1", "3.2"}

    def test_task_single(self):
        refs = att.parse_subject("task 5")
        assert refs["tasks"] == {"5"}

    def test_tasks_list(self):
        refs = att.parse_subject("tasks 1,3,5")
        assert refs["tasks"] == {"1", "3", "5"}

    def test_tasks_range(self):
        refs = att.parse_subject("tasks 2-4")
        assert refs["tasks"] == {"2", "3", "4"}

    def test_combined(self):
        refs = att.parse_subject("groups 1-2 + §3.1")
        assert refs["groups"] == {"1", "2"}
        assert refs["sections"] == {"3.1"}
        assert refs["tasks"] == {"3.1"}

    def test_no_refs(self):
        refs = att.parse_subject("just a free-form prose subject with no refs")
        assert refs["groups"] == set()
        assert refs["sections"] == set()
        assert refs["tasks"] == set()


# ---------------------------------------------------------------------------
# auto_tick_tasks.tick_tasks_md — the real workhorse
# ---------------------------------------------------------------------------


def _write_tasks(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


SAMPLE_TASKS = """\
# tasks.md

## Group 1 — Ingredients

- [ ] 1.1 Define ingredient model
- [ ] 1.2 Add SQLAlchemy mapper
- [ ] 1.3 Tests

## Group 2 — Suppliers

- [ ] 2.1 Define supplier model
- [ ] 2.2 Endpoint
- [ ] 2.3 Tests

## §3 Final

- [ ] 3.1 README
- [ ] 3.2 Migration script
"""


class TestTickTasksMd:
    def test_groups_only(self, tmp_path: Path):
        f = tmp_path / "tasks.md"
        _write_tasks(f, SAMPLE_TASKS)
        refs = att.parse_subject("groups 1-2")
        changed, ticked = att.tick_tasks_md(f, refs=refs)
        assert changed is True
        assert len(ticked) == 6
        body = f.read_text(encoding="utf-8")
        assert body.count("[x]") == 6
        # §3 boxes untouched.
        assert "[ ] 3.1" in body
        assert "[ ] 3.2" in body

    def test_section_with_subtask(self, tmp_path: Path):
        f = tmp_path / "tasks.md"
        _write_tasks(f, SAMPLE_TASKS)
        refs = att.parse_subject("§3.1")
        changed, ticked = att.tick_tasks_md(f, refs=refs)
        assert changed is True
        assert len(ticked) == 1
        body = f.read_text(encoding="utf-8")
        assert "[x] 3.1" in body
        assert "[ ] 3.2" in body  # not ticked
        assert body.count("[x]") == 1

    def test_combined_groups_and_section(self, tmp_path: Path):
        f = tmp_path / "tasks.md"
        _write_tasks(f, SAMPLE_TASKS)
        refs = att.parse_subject("groups 1-2 + §3.1")
        changed, ticked = att.tick_tasks_md(f, refs=refs)
        assert changed is True
        assert len(ticked) == 7  # 6 from groups + 1 from §3.1
        body = f.read_text(encoding="utf-8")
        assert body.count("[x]") == 7
        assert "[ ] 3.2" in body  # only 3.2 left

    def test_idempotent(self, tmp_path: Path):
        f = tmp_path / "tasks.md"
        _write_tasks(f, SAMPLE_TASKS)
        refs = att.parse_subject("groups 1-2")
        att.tick_tasks_md(f, refs=refs)
        first_body = f.read_text(encoding="utf-8")
        # Second call.
        changed, _ = att.tick_tasks_md(f, refs=refs)
        assert changed is False
        assert f.read_text(encoding="utf-8") == first_body

    def test_depth_aware_scope_reset(self, tmp_path: Path):
        """Group 2 scope must NOT bleed into §3 (same depth `## ` reset)."""
        f = tmp_path / "tasks.md"
        _write_tasks(f, SAMPLE_TASKS)
        refs = att.parse_subject("group 2")
        changed, ticked = att.tick_tasks_md(f, refs=refs)
        assert changed is True
        assert len(ticked) == 3  # 2.1, 2.2, 2.3 — NOT 3.1 / 3.2
        body = f.read_text(encoding="utf-8")
        assert "[ ] 3.1" in body
        assert "[ ] 3.2" in body

    def test_no_match(self, tmp_path: Path):
        f = tmp_path / "tasks.md"
        _write_tasks(f, SAMPLE_TASKS)
        refs = att.parse_subject("group 99")  # no such group
        changed, _ = att.tick_tasks_md(f, refs=refs)
        assert changed is False

    def test_missing_file_is_noop(self, tmp_path: Path):
        f = tmp_path / "absent.md"
        refs = att.parse_subject("group 1")
        changed, ticked = att.tick_tasks_md(f, refs=refs)
        assert changed is False
        assert ticked == []


# ---------------------------------------------------------------------------
# auto_tick_tasks.main — CLI happy-path / no-op contract
# ---------------------------------------------------------------------------


class TestAutoTickMain:
    def test_non_conventional_subject_noop(self, tmp_path: Path):
        msg = tmp_path / "msg.txt"
        msg.write_text("just a plain subject\n", encoding="utf-8")
        rc = att.main(
            ["--quiet", "--no-stage", "--repo-root", str(tmp_path), str(msg)],
        )
        assert rc == 0

    def test_no_refs_in_subject_noop(self, tmp_path: Path):
        msg = tmp_path / "msg.txt"
        msg.write_text("feat: something done\n", encoding="utf-8")
        rc = att.main(
            ["--quiet", "--no-stage", "--repo-root", str(tmp_path), str(msg)],
        )
        assert rc == 0

    def test_missing_change_id_noop(self, tmp_path: Path):
        msg = tmp_path / "msg.txt"
        msg.write_text("feat(persistence): groups 1-2\n", encoding="utf-8")
        # No --change-id, no branch resolution → noop.
        rc = att.main(
            [
                "--quiet",
                "--no-stage",
                "--repo-root",
                str(tmp_path),
                str(msg),
            ],
        )
        assert rc == 0

    def test_happy_path(self, tmp_path: Path):
        # Create fake repo structure.
        change_dir = tmp_path / "openspec" / "changes" / "test-change"
        change_dir.mkdir(parents=True)
        _write_tasks(change_dir / "tasks.md", SAMPLE_TASKS)

        msg = tmp_path / "msg.txt"
        msg.write_text("feat(persistence): groups 1-2 + §3.1\n", encoding="utf-8")

        rc = att.main(
            [
                "--quiet",
                "--no-stage",
                "--change-id",
                "test-change",
                "--repo-root",
                str(tmp_path),
                str(msg),
            ],
        )
        assert rc == 0
        body = (change_dir / "tasks.md").read_text(encoding="utf-8")
        assert body.count("[x]") == 7

    def test_missing_commit_msg_file_returns_2(self, tmp_path: Path):
        rc = att.main(
            [
                "--quiet",
                "--no-stage",
                "--repo-root",
                str(tmp_path),
                str(tmp_path / "absent.txt"),
            ],
        )
        assert rc == 2


# ---------------------------------------------------------------------------
# schema_validate cross-ref check (Opción 2)
# ---------------------------------------------------------------------------


class TestSchemaCrossRef:
    def test_cross_ref_detector_present(self):
        body = "## 2 Dispatcher index\n| Topic | Pointer |\n|---|---|\n| Foo | development-flow.md |"
        assert sv.check_dev_flow_cross_ref(body) is True

    def test_cross_ref_detector_absent(self):
        body = "## 2 Dispatcher index\n| Topic | Pointer |\n|---|---|\n| Foo | bar |"
        assert sv.check_dev_flow_cross_ref(body) is False

    def test_warn_only_default_exits_zero(self, tmp_path: Path, capsys):
        agents = tmp_path / "AGENTS.md"
        agents.write_text(
            "---\n"
            "schema: agents-md/v1\n"
            "version: 1.0.0\n"
            "inherits_from:\n"
            "  - github.com/Wizarck/ai-playbook@v0.9.3\n"
            "updated: 2026-05-05\n"
            "project: testproj\n"
            "owner: t@e.com\n"
            "capabilities_map: false\n"
            "---\n\n# Body without dev-flow link\n",
            encoding="utf-8",
        )
        schema = sv.load_schema()
        rc = sv.validate_one(
            agents,
            schema=schema,
            autofix=False,
            strict_dev_flow_cross_ref=False,
        )
        assert rc == 0
        captured = capsys.readouterr()
        assert "lacks a link to development-flow.md" in captured.err
        assert "currently warn-only" in captured.err

    def test_strict_mode_exits_one_when_missing(self, tmp_path: Path, capsys):
        agents = tmp_path / "AGENTS.md"
        agents.write_text(
            "---\n"
            "schema: agents-md/v1\n"
            "version: 1.0.0\n"
            "inherits_from:\n"
            "  - github.com/Wizarck/ai-playbook@v0.9.3\n"
            "updated: 2026-05-05\n"
            "project: testproj\n"
            "owner: t@e.com\n"
            "capabilities_map: false\n"
            "---\n\n# Body without dev-flow link\n",
            encoding="utf-8",
        )
        schema = sv.load_schema()
        rc = sv.validate_one(
            agents,
            schema=schema,
            autofix=False,
            strict_dev_flow_cross_ref=True,
        )
        assert rc == 1

    def test_strict_mode_exits_zero_when_present(self, tmp_path: Path):
        agents = tmp_path / "AGENTS.md"
        agents.write_text(
            "---\n"
            "schema: agents-md/v1\n"
            "version: 1.0.0\n"
            "inherits_from:\n"
            "  - github.com/Wizarck/ai-playbook@v0.9.3\n"
            "updated: 2026-05-05\n"
            "project: testproj\n"
            "owner: t@e.com\n"
            "capabilities_map: false\n"
            "---\n\n## 2\n\n[link](development-flow.md)\n",
            encoding="utf-8",
        )
        schema = sv.load_schema()
        rc = sv.validate_one(
            agents,
            schema=schema,
            autofix=False,
            strict_dev_flow_cross_ref=True,
        )
        assert rc == 0


# NOTE: Opción 1 was removed in v0.19.0. The dev-flow
# cross-ref row migration completed in every consumer's AGENTS.md before the
# push pipeline retired; the validator (Opción 2, TestSchemaValidateCrossRef)
# remains as the surviving guarantee.
