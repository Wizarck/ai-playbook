"""Tests for scripts/rules/repo-hygiene.rule.py.

Slice: repo-hygiene (F2 of the code-entropy campaign) — axes 3 and 5.

Contracts under test:
- specs/repo-hygiene.schema.yaml            (field-by-field)
- docs/rules/repo-hygiene.rule.md
- docs/rules/error-message-standard.rule.md (❌/FIX/OVERRIDE shape)
- docs/concepts/code-entropy.md             (axes 3 and 5)

THE TWO CENTRAL TESTS are the negative controls, and they encode the two
measurements that motivated this engine:

  `test_a_naive_import_only_check_false_positives_on_the_console_script`
      reproduces the geeplo axis-3 measurement: `uvicorn` is declared and never
      imported, because it is invoked as a console script from the Dockerfile.
      `declared − imported` called it unused. It was one of 16 such false
      positives, and all 16 were wrong.

  `test_a_signal_that_the_generator_skips_rewriting_reports_permanent_stale`
      reproduces the axis-5 measurement: graphify re-reads the tree, finds no
      topology change, and deliberately leaves `graph.json` untouched. Anchoring
      freshness on the payload reports STALE forever on a perfectly fresh graph;
      anchoring it on `manifest.json` reports fresh.

If either goes green with the naive configuration, this rule has become
decoration.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "rules" / "repo-hygiene.rule.py"

SPEC = importlib.util.spec_from_file_location("repo_hygiene_rule", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
hygiene = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = hygiene
SPEC.loader.exec_module(hygiene)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def make_config(root: Path, *, dependencies=None, artifacts=None, **top) -> Path:
    body = {
        "schema": "ai-playbook/repo-hygiene/v1",
        "schema_version": "1.0.0",
        "dependencies": dependencies or [],
        "artifacts": artifacts or [],
        **top,
    }
    path = root / "repo-hygiene.yaml"
    path.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return path


def run(config: Path, *argv: str) -> int:
    return hygiene.main(["check", "--config", str(config), *argv])


def run_json(config: Path, *argv: str) -> dict:
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        hygiene.main(["check", "--config", str(config), "--json", *argv])
    return json.loads(buf.getvalue())


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True, text=True)


def git_repo(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t.t")
    git(root, "config", "user.name", "t")


IMPORT_CHANNEL = {"id": "python-import", "kind": "import", "language": "python", "corpus": "src/**/*.py"}


def dep_check(**over) -> dict:
    base = {
        "id": "backend-deps",
        "description": "every declared dependency is provably used",
        "manifest": "requirements.txt",
        "format": "requirements-txt",
        "severity": "S3",
        "status": "enforced",
        "channels": [dict(IMPORT_CHANNEL)],
    }
    base.update(over)
    return base


def basic_tree(root: Path, requirements: str, source: str = "import fastapi\n") -> None:
    write(root, "requirements.txt", requirements)
    write(root, "src/app.py", source)


# ---------------------------------------------------------------------------
# THE ACCEPTANCE GATE — axis 3
# ---------------------------------------------------------------------------


def test_a_naive_import_only_check_false_positives_on_the_console_script(tmp_path, capsys) -> None:
    """THE negative control for axis 3.

    `uvicorn` is declared and never imported: the Dockerfile invokes it as a
    console script. An import-only check calls it unused — which is exactly what
    `declared − imported` did to 16 packages in geeplo, every one wrongly.
    """
    basic_tree(tmp_path, "fastapi==0.1\nuvicorn==0.2\n")
    write(tmp_path, "Dockerfile", 'CMD ["uvicorn", "app:app", "--port", "8000"]\n')

    config = make_config(tmp_path, dependencies=[dep_check()])
    assert run(config) == 0, "S3 does not block"
    out = capsys.readouterr().out
    assert "uvicorn" in out, "the naive check is expected to flag uvicorn — that is the whole point"
    assert "unused" in out


def test_declaring_the_console_script_channel_clears_the_false_positive(tmp_path, capsys) -> None:
    """The fix is DATA, not code: one more channel and the false positive is gone."""
    basic_tree(tmp_path, "fastapi==0.1\nuvicorn==0.2\n")
    write(tmp_path, "Dockerfile", 'CMD ["uvicorn", "app:app", "--port", "8000"]\n')

    config = make_config(tmp_path, dependencies=[dep_check(channels=[
        dict(IMPORT_CHANNEL),
        {
            "id": "console-script",
            "kind": "search",
            "corpus": ["Dockerfile"],
            # Anchored on the quoted argv slot, not on the bare name: a bare
            # `{dist}` would also match the package name in a comment.
            "by": r'"{dist}"',
        },
    ])])
    assert run(config) == 0
    out = capsys.readouterr().out
    assert "uvicorn" not in out
    assert "0 finding(s)" in out


def test_a_genuinely_unused_dependency_is_still_caught(tmp_path, capsys) -> None:
    """The channels must not turn the check into a rubber stamp."""
    basic_tree(tmp_path, "fastapi==0.1\nleftpad==1.0\n")
    write(tmp_path, "Dockerfile", 'CMD ["uvicorn", "app:app"]\n')

    config = make_config(tmp_path, dependencies=[dep_check(channels=[
        dict(IMPORT_CHANNEL),
        {"id": "console-script", "kind": "search", "corpus": ["Dockerfile"], "by": r'"{dist}"'},
    ])])
    assert run(config) == 0
    out = capsys.readouterr().out
    assert "leftpad" in out and "unused" in out
    assert "fastapi" not in out


def test_a_blocking_severity_exits_one_and_names_the_items_on_stderr(tmp_path, capsys) -> None:
    basic_tree(tmp_path, "fastapi==0.1\nleftpad==1.0\n")
    config = make_config(tmp_path, dependencies=[dep_check(severity="S1")])
    assert run(config) == 1
    captured = capsys.readouterr()
    assert "leftpad" in captured.out, "findings are data and go to stdout"
    assert "❌" in captured.err
    assert "leftpad" in captured.err, "stderr alone must stay actionable"
    assert "FIX:" in captured.err and "OVERRIDE:" in captured.err


def test_advisory_never_reaches_a_non_zero_exit(tmp_path) -> None:
    basic_tree(tmp_path, "fastapi==0.1\nleftpad==1.0\n")
    config = make_config(tmp_path, dependencies=[dep_check(severity="S1", status="advisory")])
    assert run(config) == 0


# ---------------------------------------------------------------------------
# Axis 3 — name resolution
# ---------------------------------------------------------------------------


def test_regular_name_mangling_is_automatic(tmp_path) -> None:
    """`python-dotenv` -> `dotenv` needs an alias; `msgpack` -> `msgpack` does not."""
    basic_tree(tmp_path, "msgpack==1.0\n", "import msgpack\n")
    assert run_json(make_config(tmp_path, dependencies=[dep_check()]))["checks"][0]["clean"] == 1


def test_an_irregular_import_name_needs_an_alias(tmp_path) -> None:
    basic_tree(tmp_path, "beautifulsoup4==4.0\n", "from bs4 import BeautifulSoup\n")
    without = run_json(make_config(tmp_path, dependencies=[dep_check()]))
    assert without["checks"][0]["findings"][0]["item"] == "beautifulsoup4"

    with_alias = run_json(make_config(tmp_path, dependencies=[
        dep_check(aliases={"beautifulsoup4": ["bs4"]})
    ]))
    assert with_alias["checks"][0]["findings"] == []


def test_requirements_parsing_handles_markers_extras_and_direct_references(tmp_path) -> None:
    write(tmp_path, "requirements.txt", """\
        # a comment
        -r other.txt
        fastapi[all]==0.1
        uvicorn>=0.2,<0.3
        pywin32==1.0 ; sys_platform == "win32"
        mypkg @ https://example.invalid/mypkg.whl
    """)
    names = hygiene.parse_manifest(tmp_path / "requirements.txt", "requirements-txt", ["dependencies"])
    assert names == ["fastapi", "uvicorn", "pywin32", "mypkg"]


def test_package_json_sections_are_selectable(tmp_path) -> None:
    write(tmp_path, "package.json", json.dumps({
        "dependencies": {"react": "^19"},
        "devDependencies": {"vitest": "^2"},
    }))
    only_prod = hygiene.parse_manifest(tmp_path / "package.json", "package-json", ["dependencies"])
    both = hygiene.parse_manifest(tmp_path / "package.json", "package-json", ["dependencies", "devDependencies"])
    assert only_prod == ["react"]
    assert both == ["react", "vitest"]


def test_a_tsconfig_path_alias_is_not_a_package(tmp_path) -> None:
    """`@/app/x` is a path alias. Reading it as a scoped package would invent a
    dependency named `@/app` on nearly every file in a Next.js tree."""
    assert hygiene.typescript_imports("import { x } from '@/app/lib';") == set()
    assert hygiene.typescript_imports("import y from '@scope/pkg';") == {"@scope/pkg"}
    assert hygiene.typescript_imports("const a = require('lodash/merge');") == {"lodash"}
    assert hygiene.typescript_imports("requireAuth('not-a-package');") == set()


def test_an_unparseable_source_file_is_noted_never_silently_skipped(tmp_path) -> None:
    basic_tree(tmp_path, "fastapi==0.1\n", "import fastapi\n")
    write(tmp_path, "src/broken.py", "def (:\n")
    result = run_json(make_config(tmp_path, dependencies=[dep_check()]))
    assert any("unparseable" in n for n in result["checks"][0]["notes"])


# ---------------------------------------------------------------------------
# Axis 3 — allow semantics
# ---------------------------------------------------------------------------


def test_an_allow_entry_documents_the_mechanism_and_clears_the_finding(tmp_path) -> None:
    basic_tree(tmp_path, "fastapi==0.1\nscikit-learn==1.5\n")
    config = make_config(tmp_path, dependencies=[dep_check(allow=[{
        "match": "scikit-learn",
        "reason": "loaded by joblib.load() when deserialising the vendored pipeline",
    }])])
    assert run_json(config)["checks"][0]["findings"] == []


def test_a_stale_allow_entry_is_a_config_error(tmp_path) -> None:
    """A rotting exception must break the build, or the contract drifts into fiction."""
    basic_tree(tmp_path, "fastapi==0.1\n")
    config = make_config(tmp_path, dependencies=[dep_check(allow=[
        {"match": "package-that-was-removed", "reason": "was needed once"},
    ])])
    assert run(config) == 2


def test_an_expired_exemption_becomes_a_finding(tmp_path, capsys) -> None:
    basic_tree(tmp_path, "fastapi==0.1\nleftpad==1.0\n")
    config = make_config(tmp_path, dependencies=[dep_check(allow=[
        {"match": "leftpad", "reason": "temporary", "expires": "2020-01-01"},
    ])])
    run(config)
    assert "expired-exemption" in capsys.readouterr().out


def test_a_prefix_allow_covers_a_plugin_family(tmp_path) -> None:
    basic_tree(tmp_path, "fastapi==0.1\nopentelemetry-instrumentation-flask==0.1\n"
                         "opentelemetry-instrumentation-redis==0.1\n")
    config = make_config(tmp_path, dependencies=[dep_check(allow=[
        {"match": "opentelemetry-instrumentation-*", "reason": "loaded via entry points at startup"},
    ])])
    assert run_json(config)["checks"][0]["findings"] == []


# ---------------------------------------------------------------------------
# THE ACCEPTANCE GATE — axis 5
# ---------------------------------------------------------------------------


def _artifact_tree(tmp_path: Path, *, signal_mtime: float, payload_mtime: float, input_mtime: float) -> None:
    git_repo(tmp_path)
    write(tmp_path, ".gitignore", "out/\n")
    write(tmp_path, "src/app.py", "x = 1\n")
    write(tmp_path, "out/graph.json", "{}\n")
    write(tmp_path, "out/manifest.json", "{}\n")
    import os
    os.utime(tmp_path / "out" / "manifest.json", (signal_mtime, signal_mtime))
    os.utime(tmp_path / "out" / "graph.json", (payload_mtime, payload_mtime))
    os.utime(tmp_path / "src" / "app.py", (input_mtime, input_mtime))


def art_check(**over) -> dict:
    base = {
        "id": "graph-fresh",
        "description": "the knowledge graph must describe the tree that exists",
        "path": "out",
        "severity": "S3",
        "status": "enforced",
        "freshness": {"signal": "out/manifest.json", "inputs": ["src/**/*.py"]},
    }
    base.update(over)
    return base


def test_a_signal_that_the_generator_skips_rewriting_reports_permanent_stale(tmp_path) -> None:
    """THE negative control for axis 5.

    The generator ran at t=2000 and, finding no topology change, deliberately
    left the payload at t=1000. Sources last changed at t=1500.

    Anchored on the payload (`graph.json`) the artefact reads STALE — forever,
    on every subsequent run, while being perfectly fresh. Anchored on the signal
    the generator always rewrites (`manifest.json`) it reads fresh. That is the
    entire reason `freshness.signal` is a declared field.
    """
    _artifact_tree(tmp_path, signal_mtime=2000, payload_mtime=1000, input_mtime=1500)

    naive = make_config(tmp_path, artifacts=[art_check(
        freshness={"signal": "out/graph.json", "inputs": ["src/**/*.py"]})])
    assert run_json(naive)["checks"][0]["findings"][0]["verdict"] == "stale", (
        "the payload-anchored check is expected to report a false STALE — that is "
        "the whole reason the signal is declared separately")

    correct = make_config(tmp_path, artifacts=[art_check()])
    assert run_json(correct)["checks"][0]["findings"] == []


def test_a_genuinely_stale_artefact_is_caught(tmp_path) -> None:
    _artifact_tree(tmp_path, signal_mtime=1000, payload_mtime=1000, input_mtime=2000)
    result = run_json(make_config(tmp_path, artifacts=[art_check()]))
    finding = result["checks"][0]["findings"][0]
    assert finding["verdict"] == "stale"
    assert "src/app.py" in finding["detail"]


def test_grace_absorbs_checkout_skew(tmp_path) -> None:
    """`git checkout` stamps every touched file with the current time, which
    would otherwise read as staleness on every branch switch."""
    _artifact_tree(tmp_path, signal_mtime=1000, payload_mtime=1000, input_mtime=1030)
    tight = make_config(tmp_path, artifacts=[art_check()])
    assert run_json(tight)["checks"][0]["findings"][0]["verdict"] == "stale"

    forgiving = make_config(tmp_path, artifacts=[art_check(
        freshness={"signal": "out/manifest.json", "inputs": ["src/**/*.py"], "grace": 60})])
    assert run_json(forgiving)["checks"][0]["findings"] == []


def test_an_absent_artefact_is_skipped_not_reported(tmp_path) -> None:
    """A fresh clone has not built its artefacts yet. Reporting that would train
    readers to ignore this rule."""
    git_repo(tmp_path)
    write(tmp_path, "src/app.py", "x = 1\n")
    result = run_json(make_config(tmp_path, artifacts=[art_check()]))
    assert result["checks"][0]["skipped"] is True
    assert result["checks"][0]["findings"] == []


def test_a_present_artefact_with_no_signal_is_unknowable_not_clean(tmp_path) -> None:
    git_repo(tmp_path)
    write(tmp_path, ".gitignore", "out/\n")
    write(tmp_path, "src/app.py", "x = 1\n")
    write(tmp_path, "out/graph.json", "{}\n")
    result = run_json(make_config(tmp_path, artifacts=[art_check()]))
    assert result["checks"][0]["findings"][0]["verdict"] == "signal-missing"


# ---------------------------------------------------------------------------
# Axis 5 — the `git add -A` footgun
# ---------------------------------------------------------------------------


def test_an_unignored_untracked_artefact_is_committable(tmp_path) -> None:
    git_repo(tmp_path)
    write(tmp_path, "src/app.py", "x = 1\n")
    write(tmp_path, "out/graph.json", "{}\n")
    write(tmp_path, "out/manifest.json", "{}\n")
    result = run_json(make_config(tmp_path, artifacts=[art_check(freshness=None)]))
    verdicts = [f["verdict"] for f in result["checks"][0]["findings"]]
    assert "committable" in verdicts


def test_an_ignored_artefact_is_clean(tmp_path) -> None:
    git_repo(tmp_path)
    write(tmp_path, ".gitignore", "out/\n")
    write(tmp_path, "src/app.py", "x = 1\n")
    write(tmp_path, "out/graph.json", "{}\n")
    write(tmp_path, "out/manifest.json", "{}\n")
    result = run_json(make_config(tmp_path, artifacts=[art_check(freshness=None)]))
    assert result["checks"][0]["findings"] == []


def test_an_already_committed_artefact_reports_tracked_not_committable(tmp_path) -> None:
    """The remedies differ: ignoring it now changes nothing, it needs `git rm --cached`."""
    git_repo(tmp_path)
    write(tmp_path, "src/app.py", "x = 1\n")
    write(tmp_path, "out/graph.json", "{}\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "oops")
    result = run_json(make_config(tmp_path, artifacts=[art_check(freshness=None)]))
    finding = result["checks"][0]["findings"][0]
    assert finding["verdict"] == "tracked"
    assert "rm --cached" in finding["detail"]


def test_must_be_ignored_false_disables_the_git_probe(tmp_path) -> None:
    git_repo(tmp_path)
    write(tmp_path, "src/app.py", "x = 1\n")
    write(tmp_path, "out/graph.json", "{}\n")
    result = run_json(make_config(tmp_path, artifacts=[
        art_check(freshness=None, must_be_ignored=False)]))
    assert result["checks"][0]["findings"] == []


# ---------------------------------------------------------------------------
# Contract validation — every one of these must be exit 2, never a silent pass
# ---------------------------------------------------------------------------


def test_a_corpus_matching_nothing_is_a_config_error(tmp_path) -> None:
    """A channel that reads nothing proves nothing, and would push every
    dependency toward `unused`."""
    basic_tree(tmp_path, "fastapi==0.1\n")
    config = make_config(tmp_path, dependencies=[dep_check(channels=[
        {"id": "python-import", "kind": "import", "corpus": "nowhere/**/*.py"},
    ])])
    assert run(config) == 2


def test_a_manifest_with_zero_declarations_is_a_config_error(tmp_path) -> None:
    write(tmp_path, "requirements.txt", "# only comments\n")
    write(tmp_path, "src/app.py", "x = 1\n")
    assert run(make_config(tmp_path, dependencies=[dep_check()])) == 2


def test_a_missing_manifest_is_a_config_error(tmp_path) -> None:
    write(tmp_path, "src/app.py", "x = 1\n")
    assert run(make_config(tmp_path, dependencies=[dep_check()])) == 2


def test_an_empty_contract_is_a_config_error(tmp_path) -> None:
    """A consumer that wired the engine and declared nothing has a broken
    adoption, not a clean repo."""
    assert run(make_config(tmp_path)) == 2


def test_a_check_with_no_channels_is_a_config_error(tmp_path) -> None:
    basic_tree(tmp_path, "fastapi==0.1\n")
    assert run(make_config(tmp_path, dependencies=[dep_check(channels=[])])) == 2


def test_a_search_channel_without_by_is_a_config_error(tmp_path) -> None:
    basic_tree(tmp_path, "fastapi==0.1\n")
    config = make_config(tmp_path, dependencies=[dep_check(channels=[
        {"id": "console", "kind": "search", "corpus": "src/**/*.py"},
    ])])
    assert run(config) == 2


def test_an_unknown_interpolation_token_is_a_config_error(tmp_path) -> None:
    basic_tree(tmp_path, "fastapi==0.1\n")
    config = make_config(tmp_path, dependencies=[dep_check(channels=[
        {"id": "console", "kind": "search", "corpus": "src/**/*.py", "by": "{nope}"},
    ])])
    assert run(config) == 2


def test_a_schema_version_ahead_of_the_engine_is_a_config_error(tmp_path) -> None:
    basic_tree(tmp_path, "fastapi==0.1\n")
    config = make_config(tmp_path, dependencies=[dep_check()], schema_version="99.0.0")
    assert run(config) == 2


def test_a_wrong_schema_discriminator_is_a_config_error(tmp_path) -> None:
    path = tmp_path / "repo-hygiene.yaml"
    path.write_text(yaml.safe_dump({"schema": "something/else", "schema_version": "1.0.0"}), encoding="utf-8")
    assert run(path) == 2


def test_a_meaningful_field_cannot_be_globally_defaulted(tmp_path) -> None:
    """A silent global for a field that carries meaning is unreviewable."""
    basic_tree(tmp_path, "fastapi==0.1\n")
    config = make_config(tmp_path, dependencies=[dep_check()], defaults={"manifest": "requirements.txt"})
    assert run(config) == 2


def test_severity_and_status_may_be_defaulted(tmp_path) -> None:
    basic_tree(tmp_path, "fastapi==0.1\n")
    entry = dep_check()
    del entry["severity"]
    del entry["status"]
    config = make_config(tmp_path, dependencies=[entry], defaults={"severity": "S3", "status": "advisory"})
    assert run(config) == 0


def test_duplicate_ids_across_both_lists_are_rejected(tmp_path) -> None:
    basic_tree(tmp_path, "fastapi==0.1\n")
    config = make_config(
        tmp_path,
        dependencies=[dep_check(id="same-id")],
        artifacts=[art_check(id="same-id", freshness=None)],
    )
    assert run(config) == 2


def test_an_allow_entry_without_a_reason_is_rejected(tmp_path) -> None:
    basic_tree(tmp_path, "fastapi==0.1\nleftpad==1.0\n")
    config = make_config(tmp_path, dependencies=[dep_check(allow=[{"match": "leftpad"}])])
    assert run(config) == 2


def test_a_freshness_block_without_a_signal_is_rejected(tmp_path) -> None:
    git_repo(tmp_path)
    write(tmp_path, "out/x", "1\n")
    write(tmp_path, "src/app.py", "x = 1\n")
    config = make_config(tmp_path, artifacts=[art_check(freshness={"inputs": ["src/**/*.py"]})])
    assert run(config) == 2


def test_freshness_inputs_matching_nothing_is_a_config_error(tmp_path) -> None:
    _artifact_tree(tmp_path, signal_mtime=1000, payload_mtime=1000, input_mtime=1000)
    config = make_config(tmp_path, artifacts=[art_check(
        freshness={"signal": "out/manifest.json", "inputs": ["nowhere/**/*.py"]})])
    assert run(config) == 2


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_no_contract_in_the_consumer_is_a_silent_pass(tmp_path) -> None:
    """The rule is a no-op until a consumer opts in by declaring a contract."""
    assert hygiene.main(["check", "--config", str(tmp_path / "absent.yaml")]) == 0


def test_break_glass_skips_everything_and_says_so(tmp_path, monkeypatch, capsys) -> None:
    basic_tree(tmp_path, "fastapi==0.1\nleftpad==1.0\n")
    config = make_config(tmp_path, dependencies=[dep_check(severity="S1")])
    monkeypatch.setenv("AIPLAYBOOK_HYGIENE_SKIP", "1")
    assert run(config) == 0
    assert "SKIPPED" in capsys.readouterr().err, "a silent break-glass is indistinguishable from a pass"


def test_break_glass_can_target_one_check(tmp_path, monkeypatch, capsys) -> None:
    basic_tree(tmp_path, "fastapi==0.1\nleftpad==1.0\n")
    config = make_config(tmp_path, dependencies=[dep_check(id="backend-deps", severity="S1")])
    monkeypatch.setenv("AIPLAYBOOK_HYGIENE_SKIP", "backend-deps")
    assert run(config) == 0
    assert "backend-deps" in capsys.readouterr().err


def test_check_filter_limits_to_one_id(tmp_path) -> None:
    basic_tree(tmp_path, "fastapi==0.1\nleftpad==1.0\n")
    config = make_config(tmp_path, dependencies=[dep_check(id="backend-deps")])
    assert len(run_json(config, "--check", "backend-deps")["checks"]) == 1
    assert run(config, "--check", "no-such-check") == 2


def test_changed_only_narrows_on_the_manifest(tmp_path) -> None:
    """A source edit can only make a dependency MORE used, so narrowing on the
    corpus would be unsound; narrowing on the manifest is the honest filter."""
    git_repo(tmp_path)
    basic_tree(tmp_path, "fastapi==0.1\nleftpad==1.0\n")
    config = make_config(tmp_path, dependencies=[dep_check()])
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "init")

    assert run_json(config, "--changed-only")["checks"] == [], "unchanged manifest is not re-read"

    (tmp_path / "requirements.txt").write_text("fastapi==0.1\nleftpad==1.0\nrightpad==1.0\n", encoding="utf-8")
    assert len(run_json(config, "--changed-only")["checks"]) == 1


def test_explain_names_the_channel_that_proved_each_dependency(tmp_path, capsys) -> None:
    """A channel merged without a verified line is unreviewable: the reader
    cannot distinguish a regex that works from one that has matched nothing."""
    basic_tree(tmp_path, "fastapi==0.1\nuvicorn==0.2\n")
    write(tmp_path, "Dockerfile", 'CMD ["uvicorn", "app:app"]\n')
    config = make_config(tmp_path, dependencies=[dep_check(channels=[
        dict(IMPORT_CHANNEL),
        {"id": "console-script", "kind": "search", "corpus": ["Dockerfile"], "by": r'"{dist}"'},
    ])])
    assert hygiene.main(["explain", "backend-deps", "--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert "fastapi" in out and "python-import" in out
    assert "uvicorn" in out and "console-script" in out


def test_validate_accepts_a_good_contract(tmp_path, capsys) -> None:
    basic_tree(tmp_path, "fastapi==0.1\n")
    config = make_config(tmp_path, dependencies=[dep_check()])
    assert hygiene.main(["validate", "--config", str(config)]) == 0
    assert "is valid" in capsys.readouterr().out


def test_the_engine_exposes_no_delete_path(tmp_path) -> None:
    """Structural guard. `cleanup-zombies` v0.19.29 shipped a Tier-1 auto-delete
    and destroyed 623 lines of live code. This engine reports; a human decides."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    for forbidden in ("shutil.rmtree", "os.remove", "os.unlink", "Path.unlink", ".unlink()", "DELETABLE"):
        assert forbidden not in source, f"repo-hygiene must never delete: found {forbidden}"


@pytest.mark.parametrize("verdict", ["unused", "stale", "committable", "tracked", "signal-missing"])
def test_every_verdict_renders_one_greppable_line(verdict) -> None:
    finding = hygiene.Finding("chk", "item", "S3", "enforced", verdict, "detail")
    line = finding.render()
    assert line.startswith("item: S3 [chk]")
    assert "\n" not in line
