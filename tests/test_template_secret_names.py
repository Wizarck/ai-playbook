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
