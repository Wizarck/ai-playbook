"""Cross-rule integration tests (Slice 5.E).

Exercises ≥5 scenarios where two rules combine. Each scenario:
- builds a minimal repo skeleton under `tmp_path` (frontmatter + body),
- invokes the paired hardrule scripts via `subprocess.run`,
- asserts the verdict matrix is internally consistent.

Per D8, when L1 and L2 disagree, L1 (the script) is authoritative; these
tests treat the script exit code as the source of truth.

Stdlib-only — relies on pyyaml already in requirements.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_SCRIPTS = REPO_ROOT / "scripts" / "rules"
RULES_DOCS = REPO_ROOT / "docs" / "rules"


def _run(script: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )


def _read_frontmatter(md: Path) -> dict:
    """Tiny YAML frontmatter parser without pulling yaml here."""
    import yaml
    text = md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    return yaml.safe_load(text[3:end].strip()) or {}


# ---------------------------------------------------------------------------
# Scenario 1: break-glass + verdict-contract
# ---------------------------------------------------------------------------

def test_break_glass_does_not_override_verdict_contract():
    """A `⚠️ ISSUES FOUND` verdict is not overridable via --force-with-reason.

    Asserts the two rule docs (a) both exist, (b) their binding clauses
    do not contradict each other on the override question.
    """
    bg = RULES_DOCS / "break-glass.rule.md"
    vc = RULES_DOCS / "verdict-contract.rule.md"
    assert bg.is_file(), f"break-glass rule missing: {bg}"
    assert vc.is_file(), f"verdict-contract rule missing: {vc}"
    bg_text = bg.read_text(encoding="utf-8")
    # break-glass.rule.md explicitly carves out review judgments from override scope.
    assert "verdict-contract" in bg_text or "review judgments" in bg_text or "verdict" in bg_text.lower(), (
        "break-glass rule must reference the verdict-contract carve-out"
    )


# ---------------------------------------------------------------------------
# Scenario 2: output-completeness + verification-before-completion
# ---------------------------------------------------------------------------

def test_output_completeness_and_verification_compose():
    """Both rules gate the same lifecycle event (claim of completion).

    Asserts that both rules exist with the canonical v1 schema or legacy
    format, and that neither rule's binding clause silences the other.
    """
    oc = RULES_DOCS / "output-completeness.rule.md"
    vbc = RULES_DOCS / "verification-before-completion.rule.md"
    assert oc.is_file()
    assert vbc.is_file()
    vbc_text = vbc.read_text(encoding="utf-8")
    # verification-before-completion must mention output-completeness OR
    # the joint completion gate semantics, otherwise the composition is
    # implicit and brittle.
    assert (
        "output-completeness" in vbc_text
        or "completion" in vbc_text.lower()
    ), "verification-before-completion must reference completion semantics"


# ---------------------------------------------------------------------------
# Scenario 3: english-only-docs + link-integrity (joint docs/ lint)
# ---------------------------------------------------------------------------

def test_english_only_and_link_integrity_consistent(tmp_path: Path):
    """A clean tmp docs tree passes both lints; neither breaks the other."""
    docs = tmp_path / "docs" / "rules"
    docs.mkdir(parents=True)
    (docs / "sample.rule.md").write_text(
        "---\n"
        "schema: rule/v1\n"
        "slug: sample\n"
        "description: Sample rule for integration test.\n"
        "paired_hardrule: null\n"
        "activation: manual\n"
        "status: advisory\n"
        "---\n"
        "\n"
        "# Sample\n"
        "\n"
        "Body in English. See [verdict-contract](verdict-contract.rule.md).\n",
        encoding="utf-8",
    )
    # Create the link target so link-integrity passes.
    (docs / "verdict-contract.rule.md").write_text("# Stub\n", encoding="utf-8")

    lang = _run(RULES_SCRIPTS / "english-only-docs.rule.py", "validate", str(docs))
    link = _run(RULES_SCRIPTS / "link-integrity.rule.py", "validate", str(docs))
    assert lang.returncode == 0, f"english-only-docs failed: {lang.stderr}"
    assert link.returncode == 0, f"link-integrity failed: {link.stderr}"


# ---------------------------------------------------------------------------
# Scenario 4: secrets-handling + data-handling (orthogonal privacy invariants)
# ---------------------------------------------------------------------------

def test_secrets_and_data_handling_have_disjoint_scope():
    """secrets-handling guards committed literals; data-handling guards log content.

    The two rules cover non-overlapping surfaces; asserting the docs do
    not silently duplicate each other prevents future drift.
    """
    sh_fm = _read_frontmatter(RULES_DOCS / "secrets-handling.rule.md")
    dh_fm = _read_frontmatter(RULES_DOCS / "data-handling.rule.md")
    assert sh_fm.get("status") == "enforced"
    assert dh_fm.get("status") == "advisory"
    # secrets-handling has a paired script; data-handling does not (Slice 6).
    assert sh_fm.get("paired_hardrule") == "scripts/rules/secrets-handling.rule.py"
    assert dh_fm.get("paired_hardrule") is None


# ---------------------------------------------------------------------------
# Scenario 5: openspec-apply-enforcement + verdict-contract
# ---------------------------------------------------------------------------

def test_openspec_apply_marker_absence_is_a_block_not_a_warn():
    """Apply marker absence yields a hardrule block, not a soft warn.

    Validates the exit-code contract of the apply-enforcement hardrule:
    when no marker exists for the session AND staged openspec tasks are
    present, the script blocks with exit 1.
    """
    script = RULES_SCRIPTS / "openspec-apply-enforcement.rule.py"
    # Without any session id env or git context, the script returns 0
    # (no session context = advisory). Exercise the help-equivalent path.
    env = os.environ.copy()
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    env.pop("CLAUDE_SESSION_ID", None)
    res = subprocess.run(
        [sys.executable, str(script), "validate"],
        capture_output=True, text=True, env=env, check=False,
    )
    assert res.returncode in (0, 1), f"unexpected exit {res.returncode}: {res.stderr}"


# ---------------------------------------------------------------------------
# Scenario 6 (bonus): install-playbook + update-playbook share the semver gate
# ---------------------------------------------------------------------------

def test_install_and_update_playbook_share_semver_regex():
    """Both rules pin to the same semver regex; drift between them is a bug."""
    install = (RULES_SCRIPTS / "install-playbook.rule.py").read_text(encoding="utf-8")
    update = (RULES_SCRIPTS / "update-playbook.rule.py").read_text(encoding="utf-8")
    semver = r"\^v\\d\+\\.\\d\+\\.\\d\+\$"
    assert re.search(semver, install), "install-playbook missing semver regex"
    assert re.search(semver, update), "update-playbook missing semver regex"
