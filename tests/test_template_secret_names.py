"""GitHub secret names are [A-Za-z0-9_] only; anything else fails the workflow at parse time."""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_workflow_secret_names_are_valid() -> None:
    files = [*(REPO_ROOT / "templates").rglob("*.yml*"), *(REPO_ROOT / ".github").rglob("*.yml")]
    bad = [
        f"{f.relative_to(REPO_ROOT).as_posix()}: {m.group(1)}"
        for f in files
        for m in re.finditer(r"\bsecrets\.([^\s}|)]+)", f.read_text(encoding="utf-8"))
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", m.group(1))
    ]
    assert bad == []


def test_runbook_names_every_secret_the_coderabbit_fallback_uses() -> None:
    """Consumers copy this workflow by hand (it is not a managed file), so the
    onboarding runbook is where they learn which secrets it needs."""
    template = REPO_ROOT / "templates" / "new-project" / ".github" / "workflows" / "coderabbit-fallback.yml.tmpl"
    used = set(re.findall(r"\bsecrets\.([A-Za-z_][A-Za-z0-9_]*)", template.read_text(encoding="utf-8")))
    runbook = (REPO_ROOT / "docs" / "runbooks" / "onboard-new-project.md").read_text(encoding="utf-8")
    paragraph = next(p for p in runbook.split("\n\n") if p.startswith("`project-status.yml` auto-transitions"))
    assert used and {s for s in used if f"secrets.{s}" not in paragraph} == set()
