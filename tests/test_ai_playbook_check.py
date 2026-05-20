"""Tests for scripts/ai_playbook_check.py (L4 advisory orchestrator)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts import ai_playbook_check as orch  # noqa: E402

# --- discover_consumer_root ----------------------------------------------------

def test_discover_consumer_root_finds_gitmodules(tmp_path: Path) -> None:
    (tmp_path / ".gitmodules").write_text(
        '[submodule ".ai-playbook"]\n\tpath = .ai-playbook\n\turl = ...\n',
        encoding="utf-8",
    )
    nested = tmp_path / "deep" / "nested"
    nested.mkdir(parents=True)
    assert orch.discover_consumer_root(nested) == tmp_path.resolve()


def test_discover_consumer_root_ignores_unrelated_gitmodules(tmp_path: Path) -> None:
    (tmp_path / ".gitmodules").write_text(
        '[submodule "some-other"]\n\tpath = vendor/other\n\turl = ...\n',
        encoding="utf-8",
    )
    # No ai-playbook reference + no playbook-shape => returns None.
    assert orch.discover_consumer_root(tmp_path) is None


def test_discover_consumer_root_dogfood_playbook_itself(tmp_path: Path) -> None:
    # Simulate the playbook directory itself (has AGENTS.md + docs/rules/).
    (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    (tmp_path / "docs" / "rules").mkdir(parents=True)
    assert orch.discover_consumer_root(tmp_path) == tmp_path


# --- _rule_supports_apply ------------------------------------------------------

def _write_rule(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / f"{name}.rule.py"
    p.write_text(body, encoding="utf-8")
    return p


VALIDATE_ONLY_RULE = textwrap.dedent("""
    import argparse, sys
    def main(argv=None):
        p = argparse.ArgumentParser()
        p.add_argument("subcommand", choices=["validate"])
        p.parse_args(argv)
        return 0
    if __name__ == "__main__":
        sys.exit(main())
""")

VALIDATE_AND_APPLY_RULE = textwrap.dedent("""
    import argparse, sys
    def main(argv=None):
        p = argparse.ArgumentParser()
        p.add_argument("subcommand", choices=["validate", "apply"])
        p.add_argument("--dry-run", action="store_true")
        args = p.parse_args(argv)
        return 0
    if __name__ == "__main__":
        sys.exit(main())
""")


def test_rule_supports_apply_negative(tmp_path: Path) -> None:
    rule_path = _write_rule(tmp_path, "vonly", VALIDATE_ONLY_RULE)
    assert orch._rule_supports_apply(rule_path) is False


def test_rule_supports_apply_positive(tmp_path: Path) -> None:
    rule_path = _write_rule(tmp_path, "vapply", VALIDATE_AND_APPLY_RULE)
    assert orch._rule_supports_apply(rule_path) is True


# --- _invoke_validate ----------------------------------------------------------

DRIFT_RULE = textwrap.dedent("""
    import argparse, sys
    def main(argv=None):
        p = argparse.ArgumentParser()
        p.add_argument("subcommand", choices=["validate", "apply"])
        p.add_argument("--dry-run", action="store_true")
        args = p.parse_args(argv)
        if args.subcommand == "validate":
            print("drift detected: foo missing", file=sys.stderr)
            return 1
        return 0
    if __name__ == "__main__":
        sys.exit(main())
""")


def test_invoke_validate_ok(tmp_path: Path) -> None:
    rule = _write_rule(tmp_path, "ok_rule", VALIDATE_ONLY_RULE)
    rc, _stdout, _stderr = orch._invoke_validate(rule, tmp_path)
    assert rc == 0


def test_invoke_validate_drift(tmp_path: Path) -> None:
    rule = _write_rule(tmp_path, "drift_rule", DRIFT_RULE)
    rc, _stdout, stderr = orch._invoke_validate(rule, tmp_path)
    assert rc == 1
    assert "drift detected" in stderr


# --- _version_tuple ------------------------------------------------------------

@pytest.mark.parametrize(
    "tag,expected",
    [
        ("v0.20.0", (0, 20, 0)),
        ("v1.2.3", (1, 2, 3)),
        ("v0.11.0", (0, 11, 0)),
    ],
)
def test_version_tuple_valid(tag: str, expected: tuple) -> None:
    assert orch._version_tuple(tag) == expected


@pytest.mark.parametrize("tag", ["1.2.3", "v1.x.0", "vNext", ""])
def test_version_tuple_invalid(tag: str) -> None:
    assert orch._version_tuple(tag) is None


def test_version_tuple_compares_correctly() -> None:
    # The orchestrator uses tuple comparison to flag upgrade availability.
    assert orch._version_tuple("v0.19.2") < orch._version_tuple("v0.20.0")
    assert orch._version_tuple("v0.11.0") < orch._version_tuple("v0.19.0")


# --- Rendering -----------------------------------------------------------------

def test_render_text_empty_report(tmp_path: Path) -> None:
    report = orch.CheckReport(target=tmp_path, playbook_root=REPO_ROOT)
    out = orch.render_text(report)
    assert "ai-playbook-check" in out
    assert str(tmp_path) in out
    assert "no rules evaluated" in out


def test_render_text_with_rules(tmp_path: Path) -> None:
    report = orch.CheckReport(target=tmp_path, playbook_root=REPO_ROOT)
    report.rules = [
        orch.RuleResult(slug="rule-a", status=orch.STATUS_OK, apply_available=False),
        orch.RuleResult(
            slug="rule-b",
            status=orch.STATUS_DRIFT,
            detail="invariant violation",
            apply_available=True,
        ),
        orch.RuleResult(
            slug="rule-c",
            status=orch.STATUS_MANUAL_ONLY,
            detail="advisory-only",
        ),
    ]
    out = orch.render_text(report)
    assert "ok=1" in out
    assert "drift=1" in out
    assert "manual-only=1" in out
    assert "[auto-apply available]" in out
    assert "[manual fix only]" in out
    # Drift entries sort before ok entries (highest visibility).
    drift_pos = out.index("rule-b")
    ok_pos = out.index("rule-a")
    assert drift_pos < ok_pos


def test_render_json_round_trip(tmp_path: Path) -> None:
    report = orch.CheckReport(target=tmp_path, playbook_root=REPO_ROOT)
    report.pinned_tag = "v0.19.0"
    report.latest_tag = "v0.20.0"
    report.upgrade_available = True
    report.rules = [
        orch.RuleResult(slug="x", status=orch.STATUS_DRIFT, detail="d", apply_available=True),
    ]
    payload = json.loads(orch.render_json(report))
    assert payload["pinned_tag"] == "v0.19.0"
    assert payload["latest_tag"] == "v0.20.0"
    assert payload["upgrade_available"] is True
    assert len(payload["rules"]) == 1
    assert payload["rules"][0]["slug"] == "x"
    assert payload["rules"][0]["apply_available"] is True


# --- CheckReport helpers -------------------------------------------------------

def test_actionable_rules_filters_drift_with_apply(tmp_path: Path) -> None:
    report = orch.CheckReport(target=tmp_path, playbook_root=REPO_ROOT)
    report.rules = [
        orch.RuleResult(slug="a", status=orch.STATUS_DRIFT, apply_available=True),
        orch.RuleResult(slug="b", status=orch.STATUS_DRIFT, apply_available=False),
        orch.RuleResult(slug="c", status=orch.STATUS_OK, apply_available=True),
    ]
    actionable = report.actionable_rules()
    assert [r.slug for r in actionable] == ["a"]


def test_has_drift_true(tmp_path: Path) -> None:
    report = orch.CheckReport(target=tmp_path, playbook_root=REPO_ROOT)
    report.rules = [orch.RuleResult(slug="a", status=orch.STATUS_DRIFT)]
    assert report.has_drift() is True


def test_has_drift_false_when_only_ok(tmp_path: Path) -> None:
    report = orch.CheckReport(target=tmp_path, playbook_root=REPO_ROOT)
    report.rules = [orch.RuleResult(slug="a", status=orch.STATUS_OK)]
    assert report.has_drift() is False


# --- _truncate -----------------------------------------------------------------

def test_truncate_short_passthrough() -> None:
    assert orch._truncate("hello", 10) == "hello"


def test_truncate_long_with_ellipsis() -> None:
    out = orch._truncate("a" * 100, 20)
    assert len(out) == 20
    assert out.endswith("...")


# --- End-to-end against playbook itself (dogfood smoke) -----------------------

def test_e2e_dogfood_playbook_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the orchestrator against the playbook tree itself.

    This is a smoke test — it does NOT assert specific drift outcomes (those
    depend on which rules exist and what state the tree is in). It only
    verifies the orchestrator runs end-to-end without crashing and emits
    valid JSON.
    """
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "ai_playbook_check.py"),
            str(REPO_ROOT),
            "--check",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(REPO_ROOT),
        env={**os.environ, "PLAYBOOK_NO_PROMPT": "1"},
    )
    # Exit code 0 (default) or 2 (orchestrator internal failure — we want to
    # see why if that happens, hence the assert message).
    assert proc.returncode in (0, 1), (
        f"orchestrator failed: rc={proc.returncode}\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    payload = json.loads(proc.stdout)
    assert "rules" in payload
    assert "playbook_root" in payload
    assert isinstance(payload["rules"], list)
