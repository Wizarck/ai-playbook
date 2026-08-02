"""Tests for scripts/sweep_scan.py.

Slice: sweep (F3 of the code-entropy campaign) — axes 1 `orphan-file` and
2 `dead-symbol`.

Contracts under test:
- schemas/schema-sweep-manifest-v1.json      (the emitted ledger, validated)
- docs/concepts/code-entropy.md              (axes 1/2, never-auto-delete)
- docs/rules/error-message-standard.rule.md  (❌/FIX/OVERRIDE shape)

THE CENTRAL TEST is `test_a_resolver_blind_to_path_aliases_fails_the_probe_gate`.
It reproduces the real failure this scanner was designed around: measured against
geeplo, a resolver that ignored `tsconfig.json` `compilerOptions.paths` reported
89 live files as dead, including the app's own layout and auth provider. An
adjudicating model fed that output would have written 89 convincing rationales
for 89 wrong findings.

The probe gate exists to make that failure loud and structural instead of
plausible. If that test ever passes with a blind resolver, this scanner has
become a liability rather than a tool — it would be confidently wrong, at scale,
about which files may be deleted.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import jsonschema
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "sweep_scan.py"
LEDGER_SCHEMA = json.loads(
    (REPO_ROOT / "schemas" / "schema-sweep-manifest-v1.json").read_text(encoding="utf-8")
)

SPEC = importlib.util.spec_from_file_location("sweep_scan", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
sweep = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sweep
SPEC.loader.exec_module(sweep)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write(root: Path, rel: str, text: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def make_config(root: Path, **body) -> Path:
    doc = {
        "schema": "ai-playbook/sweep-config/v1",
        "schema_version": "1.0.0",
        **body,
    }
    path = root / "sweep.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def scan(config: Path, *argv: str) -> int:
    return sweep.main(["scan", "--config", str(config), *argv])


def ledger_of(config: Path, tmp_path: Path) -> dict:
    out = tmp_path / "ledger.json"
    assert scan(config, "--out", str(out)) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def ts_tree(root: Path, *, with_tsconfig: bool = True) -> None:
    """A miniature Next-style app whose imports go through a path alias."""
    write(root, "fe/tsconfig.json", json.dumps({
        "compilerOptions": {"paths": {
            "@components/*": ["./app/components/*"],
            "@/*": ["./*"],
        }}
    }))
    write(root, "fe/app/page.tsx", "import Layout from '@components/Layout';\nexport default Layout;\n")
    write(root, "fe/app/components/Layout.tsx", "export default function Layout() { return null; }\n")
    write(root, "fe/app/components/Orphan.tsx", "export default function Orphan() { return null; }\n")
    if not with_tsconfig:
        (root / "fe" / "tsconfig.json").unlink()


def ts_config(root: Path, *, resolve: bool = True, probes: list[str] | None = None) -> Path:
    fe: dict = {
        "id": "frontend",
        "language": "typescript",
        "include": ["fe/**/*.ts", "fe/**/*.tsx"],
    }
    if resolve:
        fe["resolve_from"] = "fe/tsconfig.json"
    return make_config(
        root,
        presets=["next-app-router"],
        roots=[fe],
        probes=probes if probes is not None else ["fe/app/components/Layout.tsx"],
    )


# ---------------------------------------------------------------------------
# THE ACCEPTANCE GATE
# ---------------------------------------------------------------------------


def test_a_resolver_blind_to_path_aliases_fails_the_probe_gate(tmp_path, capsys) -> None:
    """THE central test.

    Drop `resolve_from` and the scanner can no longer follow `@components/...`.
    `Layout.tsx` — a file the consumer declared live — reads as unreachable. The
    scan MUST refuse to emit a ledger rather than report it as an orphan.

    This is the exact bug that produced 89 false positives on geeplo.
    """
    ts_tree(tmp_path)
    config = ts_config(tmp_path, resolve=False)

    assert scan(config) == 1
    captured = capsys.readouterr()
    assert "❌" in captured.err
    assert "Layout.tsx" in captured.err
    assert "UNREACHABLE" in captured.err
    assert "RESOLVER is wrong" in captured.err


def test_no_ledger_is_written_when_the_probe_gate_fails(tmp_path) -> None:
    """A scan that cannot see a file you know is live must produce NOTHING.

    Emitting a partial ledger would be worse than failing: downstream, a ledger
    is an authorisation to act.
    """
    ts_tree(tmp_path)
    config = ts_config(tmp_path, resolve=False)
    out = tmp_path / "ledger.json"

    assert scan(config, "--out", str(out)) == 1
    assert not out.exists()


def test_the_same_tree_scans_clean_once_the_resolver_reads_tsconfig(tmp_path) -> None:
    """The positive half: identical tree, `resolve_from` restored, gate passes and
    only the genuinely unreferenced file is reported."""
    ts_tree(tmp_path)
    ledger = ledger_of(ts_config(tmp_path), tmp_path)
    paths = [f["path"] for f in ledger["findings"]]
    assert paths == ["fe/app/components/Orphan.tsx"]


def test_probes_are_mandatory(tmp_path) -> None:
    """A reachability scan nobody validated is an opinion with a schema."""
    ts_tree(tmp_path)
    config = make_config(
        tmp_path,
        roots=[{"id": "frontend", "language": "typescript", "include": ["fe/**/*.tsx"]}],
        probes=[],
    )
    assert scan(config) == 2


def test_a_probe_outside_every_root_is_a_failure_not_a_pass(tmp_path, capsys) -> None:
    """Silently ignoring an out-of-scope probe would let the gate be disarmed by
    a typo."""
    ts_tree(tmp_path)
    config = ts_config(tmp_path, probes=["fe/app/components/DoesNotExist.tsx"])
    assert scan(config) == 1
    assert "not matched by any root" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Framework presets — entry points are framework facts
# ---------------------------------------------------------------------------


def test_next_router_files_are_entrypoints_not_orphans(tmp_path) -> None:
    """`page.tsx` is routed by the file system and imported by nothing. Without
    this preset it is the single largest false-positive source in a Next tree
    (118 files on geeplo)."""
    ts_tree(tmp_path)
    ledger = ledger_of(ts_config(tmp_path), tmp_path)
    assert "fe/app/page.tsx" not in [f["path"] for f in ledger["findings"]]


def test_pytest_and_alembic_files_are_entrypoints(tmp_path) -> None:
    """389 test modules and 108 migrations on geeplo — all reachable by a loader,
    none by an import."""
    write(tmp_path, "be/app/__init__.py")
    write(tmp_path, "be/app/main.py", "from app import live\n")
    write(tmp_path, "be/app/live.py", "X = 1\n")
    write(tmp_path, "be/tests/test_thing.py", "def test_x(): pass\n")
    write(tmp_path, "be/alembic/versions/0001_init.py", "revision = '0001'\n")
    write(tmp_path, "be/app/dead.py", "Y = 2\n")

    config = make_config(
        tmp_path,
        presets=["python-pytest", "python-alembic", "python-package-init"],
        roots=[{"id": "backend", "language": "python", "include": ["be/**/*.py"]}],
        entrypoints=["be/app/main.py"],
        probes=["be/app/live.py"],
    )
    paths = [f["path"] for f in ledger_of(config, tmp_path)["findings"]]
    assert paths == ["be/app/dead.py"]


def test_an_unknown_preset_is_a_config_error(tmp_path) -> None:
    ts_tree(tmp_path)
    config = make_config(
        tmp_path,
        presets=["nextjs"],           # near-miss of `next-app-router`
        roots=[{"id": "frontend", "language": "typescript", "include": ["fe/**/*.tsx"]}],
        probes=["fe/app/components/Layout.tsx"],
    )
    assert scan(config) == 2


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_same_named_files_in_two_directories_do_not_cross_credit(tmp_path) -> None:
    """Failure mode #2 from the measurement.

    `sam/Modal.tsx` is imported; `gm/Modal.tsx` is not. A name-based reference
    count credits the live one's importers to the dead one and reports a clean
    tree — a falsely reassuring NEGATIVE. Resolution must be path-based.
    """
    write(tmp_path, "fe/tsconfig.json", json.dumps({"compilerOptions": {"paths": {}}}))
    write(tmp_path, "fe/app/page.tsx", "import M from './sam/Modal';\nexport default M;\n")
    write(tmp_path, "fe/app/sam/Modal.tsx", "export default function Modal() { return null; }\n")
    write(tmp_path, "fe/app/gm/Modal.tsx", "export default function Modal() { return null; }\n")

    config = make_config(
        tmp_path,
        presets=["next-app-router"],
        roots=[{"id": "frontend", "language": "typescript",
                "include": ["fe/**/*.tsx"], "resolve_from": "fe/tsconfig.json"}],
        probes=["fe/app/sam/Modal.tsx"],
    )
    paths = [f["path"] for f in ledger_of(config, tmp_path)["findings"]]
    assert paths == ["fe/app/gm/Modal.tsx"]


def test_directory_imports_resolve_through_an_index_file(tmp_path) -> None:
    write(tmp_path, "fe/tsconfig.json", json.dumps({"compilerOptions": {"paths": {}}}))
    write(tmp_path, "fe/app/page.tsx", "import x from './widget';\nexport default x;\n")
    write(tmp_path, "fe/app/widget/index.tsx", "export default 1;\n")
    config = make_config(
        tmp_path,
        presets=["next-app-router"],
        roots=[{"id": "frontend", "language": "typescript",
                "include": ["fe/**/*.tsx"], "resolve_from": "fe/tsconfig.json"}],
        probes=["fe/app/widget/index.tsx"],
    )
    assert ledger_of(config, tmp_path)["findings"] == []


def test_python_relative_imports_resolve(tmp_path) -> None:
    write(tmp_path, "be/app/__init__.py")
    write(tmp_path, "be/app/main.py", "from . import sibling\nfrom .sub import deep\n")
    write(tmp_path, "be/app/sibling.py", "X = 1\n")
    write(tmp_path, "be/app/sub/__init__.py")
    write(tmp_path, "be/app/sub/deep.py", "Y = 2\n")
    config = make_config(
        tmp_path,
        presets=["python-package-init"],
        roots=[{"id": "backend", "language": "python", "include": ["be/**/*.py"]}],
        entrypoints=["be/app/main.py"],
        probes=["be/app/sibling.py", "be/app/sub/deep.py"],
    )
    assert ledger_of(config, tmp_path)["findings"] == []


def test_a_lazily_imported_module_is_reachable(tmp_path) -> None:
    """An import inside a function still makes its target reachable — several of
    geeplo's feature-gated modules are exactly that shape."""
    write(tmp_path, "be/app/__init__.py")
    write(tmp_path, "be/app/main.py", """\
        def start():
            from app import optional
            return optional
    """)
    write(tmp_path, "be/app/optional.py", "X = 1\n")
    config = make_config(
        tmp_path,
        presets=["python-package-init"],
        roots=[{"id": "backend", "language": "python", "include": ["be/**/*.py"]}],
        entrypoints=["be/app/main.py"],
        probes=["be/app/optional.py"],
    )
    assert ledger_of(config, tmp_path)["findings"] == []


def test_a_missing_tsconfig_is_a_config_error(tmp_path) -> None:
    """Silently continuing without the project's resolution config is how the
    whole tree reads as dead."""
    ts_tree(tmp_path, with_tsconfig=False)
    assert scan(ts_config(tmp_path)) == 2


def test_a_root_matching_no_files_is_a_config_error(tmp_path) -> None:
    ts_tree(tmp_path)
    config = make_config(
        tmp_path,
        roots=[{"id": "frontend", "language": "typescript", "include": ["nowhere/**/*.tsx"]}],
        probes=["fe/app/components/Layout.tsx"],
    )
    assert scan(config) == 2


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------


def test_the_emitted_ledger_validates_against_the_v1_schema(tmp_path) -> None:
    """The contract shipped in F0 is the acceptance test for the emitter."""
    ts_tree(tmp_path)
    jsonschema.validate(ledger_of(ts_config(tmp_path), tmp_path), LEDGER_SCHEMA)


def test_an_empty_ledger_still_validates_and_names_the_axes_scanned(tmp_path) -> None:
    """`findings: []` asserts 'clean' only for the axes that actually ran."""
    write(tmp_path, "fe/tsconfig.json", json.dumps({"compilerOptions": {"paths": {}}}))
    write(tmp_path, "fe/app/page.tsx", "export default 1;\n")
    config = make_config(
        tmp_path,
        presets=["next-app-router"],
        roots=[{"id": "frontend", "language": "typescript",
                "include": ["fe/**/*.tsx"], "resolve_from": "fe/tsconfig.json"}],
        probes=["fe/app/page.tsx"],
    )
    ledger = ledger_of(config, tmp_path)
    jsonschema.validate(ledger, LEDGER_SCHEMA)
    assert ledger["findings"] == []
    assert ledger["scan"]["axes_scanned"] == ["orphan-file"]


def test_every_finding_is_report_only_tier_three(tmp_path) -> None:
    """A reachability candidate is never execution authority. Tier 1 requires a
    human, per the schema — this scanner may not mint it."""
    ts_tree(tmp_path)
    for finding in ledger_of(ts_config(tmp_path), tmp_path)["findings"]:
        assert finding["adjudication"]["tier"] == 3
        assert finding["action"] == "report"
        assert finding["safety"] == "report_only"
        assert finding["evidence"]["detector_tier"] == 3


def test_findings_carry_the_typed_evidence_the_schema_demands(tmp_path) -> None:
    """Evidence is the prior an adjudicator consumes instead of re-deriving the
    analysis; a finding that cannot point at a location is prose."""
    ts_tree(tmp_path)
    finding = ledger_of(ts_config(tmp_path), tmp_path)["findings"][0]
    ev = finding["evidence"]
    assert ev["verdict"] == "unreachable"
    assert ev["consumers_found"] == 0
    assert ev["search_scope"]
    assert ev["locations"][0]["path"] == finding["path"]
    assert ev["locations"][0]["role"] == "subject"


def test_finding_ids_are_stable_across_runs(tmp_path) -> None:
    """A run-scoped random id would make the ledger amnesiac: no suppression, no
    `seen_count`, no 'already dismissed once'."""
    ts_tree(tmp_path)
    config = ts_config(tmp_path)
    first = [f["id"] for f in ledger_of(config, tmp_path)["findings"]]
    second = [f["id"] for f in ledger_of(config, tmp_path)["findings"]]
    assert first == second and first


def test_the_scanner_exposes_no_delete_path() -> None:
    """Structural guard, same as repo-hygiene. `cleanup-zombies` v0.19.29 shipped
    a Tier-1 auto-delete and destroyed 623 lines of live code. This writes a
    ledger and stops."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    for forbidden in ("shutil.rmtree", "os.remove", "os.unlink", ".unlink()", "DELETABLE"):
        assert forbidden not in source, f"sweep must never delete: found {forbidden}"


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_no_config_in_the_consumer_is_a_silent_pass(tmp_path) -> None:
    assert sweep.main(["scan", "--config", str(tmp_path / "absent.yaml")]) == 0


def test_probe_subcommand_runs_the_gate_alone(tmp_path, capsys) -> None:
    ts_tree(tmp_path)
    assert sweep.main(["probe", "--config", str(ts_config(tmp_path))]) == 0
    assert "probe(s) OK" in capsys.readouterr().out


def test_validate_does_not_scan(tmp_path, capsys) -> None:
    ts_tree(tmp_path)
    assert sweep.main(["validate", "--config", str(ts_config(tmp_path))]) == 0
    assert "is valid" in capsys.readouterr().out


@pytest.mark.parametrize("preset", sorted(sweep.PRESETS))
def test_every_preset_documents_why_it_exists(preset: str) -> None:
    """A preset is an assertion that a class of file is an entry point. Without a
    stated reason it is indistinguishable from a suppression."""
    assert len(sweep.PRESETS[preset]["why"]) > 30
    assert sweep.PRESETS[preset]["entrypoints"]


def test_the_scanner_runs_from_a_consumer_root_by_path(tmp_path) -> None:
    """The real invocation mode: `python .ai-playbook/scripts/sweep_scan.py`, which
    puts neither the playbook root nor scripts/rules on sys.path."""
    ts_tree(tmp_path)
    config = ts_config(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "scan", "--config", str(config)],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    assert "probe(s) OK" in proc.stdout
