"""Tests for scripts/rules/capability-wiring.rule.py.

Slice: capability-wiring (F1 of the code-entropy campaign).

Contracts under test:
- specs/wiring-assertions.schema.yaml   (field-by-field)
- docs/rules/capability-wiring.rule.md
- docs/rules/error-message-standard.rule.md  (❌/FIX/OVERRIDE shape)
- docs/concepts/code-entropy.md               (axis 4, `unwired-capability`)

THE CENTRAL TEST is `test_beat_schedule_decoy_does_not_satisfy_the_route`. It
reproduces geeplo `47717de3` hermetically: a Celery task that is imported AND
present in `beat_schedule` but absent from `task_routes`. A bare-name regex
passes on that shape — which is exactly how the bug reached `main`. If that
test ever goes green with a loose `by`, this rule has become decoration.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "rules" / "capability-wiring.rule.py"

SPEC = importlib.util.spec_from_file_location("capability_wiring_rule", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
wiring = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = wiring
SPEC.loader.exec_module(wiring)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def write(base: Path, rel: str, body: str) -> Path:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return path


def make_config(base: Path, *assertions: dict, **top: object) -> Path:
    """`base` is deliberately not named `root` — `root` is a config key that
    several tests override via **top."""
    doc = {
        "schema": wiring.SCHEMA_CONST,
        "schema_version": "1.0.0",
        "root": ".",
        "assertions": list(assertions),
        **top,
    }
    path = base / "wiring.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def run(config: Path, *argv: str) -> int:
    return wiring.main(["check", "--config", str(config), *argv])


@pytest.fixture(autouse=True)
def _no_break_glass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(wiring.SKIP_ENV, raising=False)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A minimal tree: two capabilities, one registry naming only the first."""
    write(tmp_path, "src/alpha.py", "def run(): ...")
    write(tmp_path, "src/beta.py", "def run(): ...")
    write(tmp_path, "registry.py", 'ROUTES = {\n    "alpha": 1,\n}\n')
    return tmp_path


BASIC = {
    "id": "src-module-registered",
    "description": "every src module is in ROUTES",
    "every": "src/*.py",
    "referenced_in": "registry.py",
    "by": '"{stem}"\\s*:',
    "severity": "S1",
}


# ---------------------------------------------------------------------------
# The regression proof — geeplo 47717de3
# ---------------------------------------------------------------------------


CELERY_BY = "(?<!\"task\": )[\"']app\\.tasks\\.{stem}\\.{symbol}[\"']\\s*(?:\\]\\s*=|:|,)"


def _celery_tree(root: Path, *, routed: bool) -> Path:
    """Reproduce the shape of geeplo `47717de3^`.

    The task exists, is imported, and HAS a `beat_schedule` entry. Only the
    `task_routes` line is absent. Everything a human reviewer would look for is
    present — which is why the bug shipped.
    """
    write(root, "backend/app/tasks/heartbeat_tasks.py", """
        @celery_app.task(bind=True, max_retries=2)
        def emit_liveness_heartbeat(self):
            ...
    """)
    route = (
        '        celery_app.conf.task_routes["app.tasks.heartbeat_tasks.emit_liveness_heartbeat"]'
        ' = {"queue": "scheduled"}\n'
        if routed else ""
    )
    write(root, "backend/app/celery_app.py", f"""
        from app.tasks import heartbeat_tasks  # noqa: F401

        celery_app.conf.beat_schedule = {{
            "emit-liveness-heartbeat": {{
                "task": "app.tasks.heartbeat_tasks.emit_liveness_heartbeat",
                "schedule": 60.0,
            }},
        }}
{route}
    """)
    return make_config(root, {
        "id": "celery-task-routed",
        "description": "every Celery task has an explicit task_routes entry",
        "every": "backend/app/tasks/*_tasks.py::@celery_app.task* def:*",
        "referenced_in": "backend/app/celery_app.py",
        "by": CELERY_BY,
        "severity": "S1",
    })


def test_beat_schedule_decoy_does_not_satisfy_the_route(tmp_path: Path, capsys) -> None:
    """THE acceptance gate: the engine must fail on the real bug's shape."""
    config = _celery_tree(tmp_path, routed=False)
    assert run(config) == 1
    out = capsys.readouterr()
    assert "emit_liveness_heartbeat" in out.out
    assert "❌" in out.err
    assert "emit_liveness_heartbeat" in out.err, "stderr alone must stay actionable"


def test_the_same_tree_passes_once_the_route_line_exists(tmp_path: Path) -> None:
    assert run(_celery_tree(tmp_path, routed=True)) == 0


def test_a_bare_name_regex_would_have_false_greened(tmp_path: Path) -> None:
    """Why the anchored `by` is necessary, stated as an executable fact.

    This is the negative control. The naive regex passes on the buggy tree
    because the task name also appears in `beat_schedule`.
    """
    _celery_tree(tmp_path, routed=False)
    naive = dict(
        id="celery-naive", description="naive",
        every="backend/app/tasks/*_tasks.py::@celery_app.task* def:*",
        referenced_in="backend/app/celery_app.py",
        by="app\\.tasks\\.{stem}\\.{symbol}", severity="S1",
    )
    assert run(make_config(tmp_path, naive)) == 0, (
        "the naive regex is expected to pass on the buggy tree — that is the "
        "whole reason the strict one is required"
    )


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------


def test_unreferenced_capability_blocks(repo: Path, capsys) -> None:
    assert run(make_config(repo, BASIC)) == 1
    out = capsys.readouterr()
    assert "src/beta.py" in out.out
    assert "src/alpha.py" not in out.out


def test_error_follows_the_canonical_shape(repo: Path, capsys) -> None:
    run(make_config(repo, BASIC))
    err = capsys.readouterr().err
    assert err.startswith("❌ ")
    assert "FIX:" in err
    assert f"OVERRIDE: {wiring.SKIP_ENV}" in err


def test_fully_wired_tree_passes(repo: Path) -> None:
    write(repo, "registry.py", 'ROUTES = {\n    "alpha": 1,\n    "beta": 2,\n}\n')
    assert run(make_config(repo, BASIC)) == 0


def test_s3_prints_but_never_blocks(repo: Path, capsys) -> None:
    assert run(make_config(repo, {**BASIC, "severity": "S3"})) == 0
    assert "src/beta.py" in capsys.readouterr().out


def test_advisory_status_never_blocks_even_at_s1(repo: Path) -> None:
    assert run(make_config(repo, {**BASIC, "status": "advisory"})) == 0


def test_exclude_removes_files_before_evaluation(repo: Path) -> None:
    assert run(make_config(repo, {**BASIC, "exclude": ["src/beta.py"]})) == 0


def test_allow_entry_suppresses_a_reviewed_exception(repo: Path) -> None:
    entry = {**BASIC, "allow": [{"match": "src/beta.py", "reason": "mounted elsewhere"}]}
    assert run(make_config(repo, entry)) == 0


def test_allow_trailing_star_is_a_prefix_match(repo: Path) -> None:
    entry = {**BASIC, "allow": [{"match": "src/bet*", "reason": "prefix"}]}
    assert run(make_config(repo, entry)) == 0


def test_stale_allow_entry_is_a_config_error(repo: Path, capsys) -> None:
    """A rotting exception must break the build, or the ruleset drifts into fiction."""
    entry = {**BASIC, "allow": [{"match": "src/deleted.py", "reason": "gone"}]}
    assert run(make_config(repo, entry)) == 2
    assert "stale allow entry" in capsys.readouterr().err


def test_expired_exemption_becomes_a_finding_again(repo: Path, capsys) -> None:
    entry = {**BASIC, "allow": [
        {"match": "src/beta.py", "reason": "temporary", "expires": "2020-01-01"},
    ]}
    assert run(make_config(repo, entry)) == 1
    assert "expired exemption" in capsys.readouterr().out


def test_future_expiry_still_exempts(repo: Path) -> None:
    entry = {**BASIC, "allow": [
        {"match": "src/beta.py", "reason": "temporary", "expires": "2999-01-01"},
    ]}
    assert run(make_config(repo, entry)) == 0


def test_unreferenced_max_tolerates_a_chain_tip(repo: Path, capsys) -> None:
    assert run(make_config(repo, {**BASIC, "unreferenced_max": 1})) == 0
    assert "within tolerance" in capsys.readouterr().out


def test_unreferenced_max_still_fires_past_the_tolerance(repo: Path) -> None:
    write(repo, "src/gamma.py", "def run(): ...")
    assert run(make_config(repo, {**BASIC, "unreferenced_max": 1})) == 1


def test_exactly_one_flags_a_duplicate_registration(repo: Path, capsys) -> None:
    write(repo, "registry.py", 'A = {\n "alpha": 1,\n}\nB = {\n "alpha": 2,\n}\n')
    entry = {**BASIC, "every": "src/alpha.py", "expect": "exactly_one"}
    assert run(make_config(repo, entry)) == 1
    assert "found 2" in capsys.readouterr().out


def test_exclude_self_stops_a_file_satisfying_itself(tmp_path: Path) -> None:
    """Without it, a self-overlapping set is permanently and falsely green."""
    write(tmp_path, "chain/a.py", 'revision = "a"\ndown_revision = None\n')
    write(tmp_path, "chain/b.py", 'revision = "b"\ndown_revision = "a"\n')
    entry = {
        "id": "chain-linked", "description": "each revision is someone's parent",
        "every": "chain/*.py", "referenced_in": "chain/*.py",
        "capture": '^revision\\s*=\\s*"(?P<value>[^"]+)"',
        "by": 'down_revision\\s*=\\s*"{capture}"',
        "severity": "S1", "unreferenced_max": 1,
    }
    assert run(make_config(tmp_path, entry)) == 0, "exactly one tip is expected"

    write(tmp_path, "chain/c.py", 'revision = "c"\ndown_revision = None\n')
    assert run(make_config(tmp_path, entry)) == 1, "a second head must fire"


# ---------------------------------------------------------------------------
# Population construction
# ---------------------------------------------------------------------------


def test_decorator_filter_selects_only_decorated_symbols(tmp_path: Path) -> None:
    write(tmp_path, "src/x_tasks.py", """
        @celery_app.task(bind=True)
        def wired(): ...

        def helper(): ...
    """)
    write(tmp_path, "registry.py", '"wired": 1\n')
    entry = {
        "id": "decorated-only", "description": "d",
        "every": "src/*_tasks.py::@celery_app.task* def:*",
        "referenced_in": "registry.py", "by": '"{symbol}"', "severity": "S1",
    }
    assert run(make_config(tmp_path, entry)) == 0, "`helper` must not be in the population"


def test_member_kind_walks_string_literals_of_the_named_container(tmp_path: Path) -> None:
    write(tmp_path, "src/mods.py", 'KNOWN = (\n    "a",\n    "b",\n)\nOTHER = ("z",)\n')
    write(tmp_path, "labels.ts", "const L = { a: 1 };\n")
    entry = {
        "id": "modules-labeled", "description": "d",
        "every": "src/mods.py::member:KNOWN", "referenced_in": "labels.ts",
        "by": "\\b{symbol}\\b\\s*:", "severity": "S1",
    }
    assert run(make_config(tmp_path, entry)) == 1, "`b` is unlabelled; `z` is out of population"


def test_absent_container_is_a_finding_not_a_silent_skip(tmp_path: Path, capsys) -> None:
    """A selector that matches nothing must never read as 'all wired'."""
    write(tmp_path, "src/mods.py", 'SOMETHING_ELSE = ("a",)\n')
    write(tmp_path, "labels.ts", "const L = {};\n")
    entry = {
        "id": "modules-labeled", "description": "d",
        "every": "src/mods.py::member:KNOWN", "referenced_in": "labels.ts",
        "by": "\\b{symbol}\\b", "severity": "S1",
    }
    assert run(make_config(tmp_path, entry), "--json") == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["assertions"][0]["findings"][0]["kind"] == "symbol-selector-empty"


def test_capture_failure_is_reported_never_skipped(tmp_path: Path, capsys) -> None:
    """A file whose identity cannot be read is the one most likely to be unwired."""
    write(tmp_path, "chain/a.py", 'revision = "a"\n')
    write(tmp_path, "chain/broken.py", "# no revision line at all\n")
    write(tmp_path, "registry.py", 'parents = ["a"]\n')
    entry = {
        "id": "captured", "description": "d", "every": "chain/*.py",
        "referenced_in": "registry.py",
        "capture": '^revision\\s*=\\s*"(?P<value>[^"]+)"',
        "by": '"{capture}"', "severity": "S1",
    }
    assert run(make_config(tmp_path, entry)) == 1
    assert "capture" in capsys.readouterr().out


def test_literal_parens_and_brackets_in_paths_are_not_glob_metacharacters(tmp_path: Path) -> None:
    """Next.js route groups — `app/(ops)/...` — and any bracketed path."""
    write(tmp_path, "src/alpha.py", "x = 1")
    write(tmp_path, "frontend/app/(ops)/page.tsx", "const L = { alpha: 1 };\n")
    entry = {
        "id": "route-group", "description": "d", "every": "src/*.py",
        "referenced_in": "frontend/app/(ops)/page.tsx",
        "by": "\\b{stem}\\b", "severity": "S1",
    }
    assert run(make_config(tmp_path, entry)) == 0

    write(tmp_path, "frontend/app/[id]/page.tsx", "const L = { alpha: 1 };\n")
    bracket = {**entry, "referenced_in": "frontend/app/[id]/page.tsx"}
    assert run(make_config(tmp_path, bracket)) == 0, "`[id]` must resolve literally"


def test_single_star_does_not_cross_a_directory_separator(tmp_path: Path) -> None:
    write(tmp_path, "src/alpha.py", "x = 1")
    write(tmp_path, "src/nested/beta.py", "x = 1")
    write(tmp_path, "registry.py", '"alpha":\n')
    assert run(make_config(tmp_path, BASIC)) == 0, "`src/*.py` must not reach `src/nested/`"


def test_double_star_does_cross(tmp_path: Path) -> None:
    write(tmp_path, "src/alpha.py", "x = 1")
    write(tmp_path, "src/nested/beta.py", "x = 1")
    write(tmp_path, "registry.py", '"alpha":\n')
    assert run(make_config(tmp_path, {**BASIC, "every": "src/**/*.py"})) == 1


def test_interpolated_values_cannot_inject_regex_metacharacters(tmp_path: Path) -> None:
    """`{stem}` is `re.escape`d, so a dotted name matches literally, not as `.`."""
    write(tmp_path, "src/a.b.py", "x = 1")
    write(tmp_path, "registry.py", '"aXb"\n')
    entry = {**BASIC, "by": '"{stem}"'}
    assert run(make_config(tmp_path, entry)) == 1, "`a.b` must not match `aXb`"


# ---------------------------------------------------------------------------
# Config errors — exit 2, never a false green
# ---------------------------------------------------------------------------


def test_glob_matching_nothing_is_a_config_error(tmp_path: Path, capsys) -> None:
    """A detector that inspects nothing reports green forever."""
    write(tmp_path, "registry.py", "x = 1")
    assert run(make_config(tmp_path, {**BASIC, "every": "nowhere/*.py"})) == 2
    assert "dead assertion" in capsys.readouterr().err


def test_missing_registry_is_a_config_error_not_n_findings(repo: Path, capsys) -> None:
    assert run(make_config(repo, {**BASIC, "referenced_in": "absent.py"})) == 2
    assert "matched no file" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("mutation", "needle"),
    [
        ({"schema": "something/else"}, "not a wiring-assertions file"),
        ({"schema_version": "1.0"}, "MAJOR.MINOR.PATCH"),
        ({"schema_version": "2.0.0"}, "unsupported schema_version"),
        ({"assertions": []}, "non-empty list"),
        ({"defaults": {"by": "x"}}, "may not be set in `defaults`"),
        ({"root": "nowhere"}, "does not exist"),
    ],
)
def test_top_level_config_errors(repo: Path, capsys, mutation: dict, needle: str) -> None:
    config = make_config(repo, BASIC, **mutation)
    assert run(config) == 2
    assert needle in capsys.readouterr().err


@pytest.mark.parametrize(
    ("mutation", "needle"),
    [
        ({"id": "X"}, "`id` must match"),
        ({"severity": "S0"}, "not in"),
        ({"severity": "S9"}, "not in"),
        ({"status": "maybe"}, "enforced|advisory"),
        ({"expect": "two"}, "at_least_one|exactly_one"),
        ({"orphan_direction": "reverse"}, "forward|both"),
        ({"flags": "x"}, "unsupported regex flag"),
        ({"unreferenced_max": -1}, "non-negative"),
        ({"by": '"{nope}"'}, "unknown interpolation token"),
        ({"by": '"{symbol}"'}, "`every` has no `::` suffix"),
        ({"by": '"{capture}"'}, "no `capture` regex"),
        ({"description": ""}, "`description` is required"),
        ({"every": "src/*.py::bogus:*"}, "unknown kind"),
        ({"every": "src/*.py::def"}, "missing the `<kind>:<name>` colon"),
        ({"allow": [{"match": "src/beta.py"}]}, "needs `match` and `reason`"),
        ({"allow": [{"match": "a", "reason": "b", "expires": "soon"}]}, "YYYY-MM-DD"),
        ({"capture": "(?P<other>x)"}, "named group `value`"),
    ],
)
def test_per_assertion_config_errors(repo: Path, capsys, mutation: dict, needle: str) -> None:
    assert run(make_config(repo, {**BASIC, **mutation})) == 2
    assert needle in capsys.readouterr().err


def test_duplicate_assertion_ids_are_rejected(repo: Path, capsys) -> None:
    assert run(make_config(repo, BASIC, dict(BASIC))) == 2
    assert "duplicate assertion id" in capsys.readouterr().err


def test_unknown_assertion_id_is_a_config_error(repo: Path) -> None:
    assert run(make_config(repo, BASIC), "--assertion", "nope") == 2


def test_missing_explicit_config_is_a_config_error(tmp_path: Path) -> None:
    assert wiring.main(["check", "--config", str(tmp_path / "absent.yaml")]) == 2


def test_absent_wiring_yaml_is_a_no_op_not_an_error(tmp_path: Path, monkeypatch, capsys) -> None:
    """Not every consumer adopts this rule; silence is the correct posture."""
    monkeypatch.chdir(tmp_path)
    assert wiring.main(["check"]) == 0
    assert "nothing to check" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Break-glass — docs/rules/break-glass.rule.md
# ---------------------------------------------------------------------------


def test_break_glass_skips_the_whole_run(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv(wiring.SKIP_ENV, "1")
    assert run(make_config(repo, BASIC)) == 0
    assert wiring.SKIP_ENV in capsys.readouterr().err


def test_break_glass_can_name_a_single_assertion(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv(wiring.SKIP_ENV, "src-module-registered")
    assert run(make_config(repo, BASIC)) == 0
    assert "src-module-registered" in capsys.readouterr().err


def test_break_glass_naming_another_assertion_does_not_help(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv(wiring.SKIP_ENV, "some-other-rule")
    assert run(make_config(repo, BASIC)) == 1


# ---------------------------------------------------------------------------
# --changed-only, --json, explain, orphan_direction
# ---------------------------------------------------------------------------


def test_changed_only_narrows_the_population_but_reads_registries_in_full(
    repo: Path, monkeypatch
) -> None:
    """The bug class is 'capability changed, registry untouched' — so the
    registry must never be filtered by the changed set."""
    monkeypatch.setattr(wiring, "changed_files", lambda root: {"src/beta.py"})
    assert run(make_config(repo, BASIC), "--changed-only") == 1

    monkeypatch.setattr(wiring, "changed_files", lambda root: {"src/alpha.py"})
    assert run(make_config(repo, BASIC), "--changed-only") == 0


def test_changed_only_does_not_turn_an_empty_slice_into_a_dead_assertion(
    repo: Path, monkeypatch
) -> None:
    monkeypatch.setattr(wiring, "changed_files", lambda root: set())
    assert run(make_config(repo, BASIC), "--changed-only") == 0


def test_changed_only_does_not_report_a_partial_population_as_stale_allow(
    repo: Path, monkeypatch
) -> None:
    monkeypatch.setattr(wiring, "changed_files", lambda root: {"src/alpha.py"})
    entry = {**BASIC, "allow": [{"match": "src/beta.py", "reason": "reviewed"}]}
    assert run(make_config(repo, entry), "--changed-only") == 0


def test_json_output_is_machine_readable(repo: Path, capsys) -> None:
    run(make_config(repo, BASIC), "--json")
    payload = json.loads(capsys.readouterr().out)
    assert payload["blocking"] == 1
    only = payload["assertions"][0]
    assert only["population"] == 2
    assert only["referenced"] == 1
    assert only["unreferenced"] == ["src/beta.py"]
    assert only["findings"][0]["kind"] == "unreferenced"


def test_explain_prints_a_real_matched_line_per_item(repo: Path, capsys) -> None:
    config = make_config(repo, BASIC)
    assert wiring.main(["explain", "src-module-registered", "--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert "registry.py:2" in out, "the proof must cite the registry line, not just say OK"
    assert "✓ src/alpha.py" in out
    assert "✗ src/beta.py" in out
    assert "1 unproven" in out


def test_explain_rejects_an_unknown_id(repo: Path) -> None:
    config = make_config(repo, BASIC)
    assert wiring.main(["explain", "nope", "--config", str(config)]) == 2


def test_validate_lints_the_config_without_scanning(repo: Path, capsys) -> None:
    config = make_config(repo, BASIC)
    assert wiring.main(["validate", "--config", str(config)]) == 0
    assert "1 assertion(s)" in capsys.readouterr().out


def test_orphan_direction_both_catches_a_stale_registry_entry(repo: Path, capsys) -> None:
    """The mirror bug: the capability was deleted, the registry entry outlived it."""
    write(repo, "registry.py", 'ROUTES = {\n    "alpha": 1,\n    "deleted": 2,\n}\n')
    entry = {**BASIC, "orphan_direction": "both",
             "allow": [{"match": "src/beta.py", "reason": "reviewed"}]}
    assert run(make_config(repo, entry)) == 1
    assert "orphan-registry-entry" in json.dumps(_json_of(repo, entry))


def _json_of(repo: Path, entry: dict) -> dict:
    import io
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        wiring.main(["check", "--config", str(make_config(repo, entry)), "--json"])
    return json.loads(buffer.getvalue())


# ---------------------------------------------------------------------------
# Contract agreement — the doc and the hardrule must not drift
# ---------------------------------------------------------------------------


def test_doc_and_hardrule_agree_on_the_cli_surface() -> None:
    doc = (REPO_ROOT / "docs" / "rules" / "capability-wiring.rule.md").read_text(encoding="utf-8")
    for token in ("check", "explain", "validate", "--changed-only", "--json", wiring.SKIP_ENV):
        assert token in doc, f"{token!r} is implemented but undocumented"


def test_schema_spec_and_engine_agree_on_the_token_set() -> None:
    spec = (REPO_ROOT / "specs" / "wiring-assertions.schema.yaml").read_text(encoding="utf-8")
    for token in wiring.TOKENS:
        assert "{%s}" % token in spec, f"token {token!r} is implemented but not in the schema"


def test_schema_spec_and_engine_agree_on_the_symbol_kinds() -> None:
    spec = yaml.safe_load(
        (REPO_ROOT / "specs" / "wiring-assertions.schema.yaml").read_text(encoding="utf-8")
    )
    assert set(spec["symbol_pattern"]["kinds"]) == set(wiring.KINDS)
