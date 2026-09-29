"""Consumer pre-commit entries must propagate validator failures.

The ``[ ! -d .ai-playbook ] || python ...`` guard skips cleanly when the
playbook is absent, but a failing validator must fail the hook — the former
``A && python ... || exit 0`` shape swallowed every failure.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "templates" / "new-project" / ".pre-commit-config.yaml.tmpl"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="pre-commit entries run under bash")


def _entries() -> list[str]:
    text = TEMPLATE.read_text(encoding="utf-8")
    return [m.group(1) for m in re.finditer(r"^\s*#?\s*entry: (bash -c .+)$", text, re.MULTILINE)]


def _run(entry: str, cwd: Path, files: list[str]) -> subprocess.CompletedProcess:
    # pre-commit appends filenames to the entry; mimic it through a shell.
    cmd = entry + "".join(f" {f}" for f in files)
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=30)


def _stub_everything(consumer: Path, exit_code: int) -> None:
    # Every script an entry names becomes a stub that records argv and exits.
    for entry in _entries():
        for rel in re.findall(r"python (\S+\.py)", entry):
            stub = consumer / rel
            stub.parent.mkdir(parents=True, exist_ok=True)
            stub.write_text(
                "import sys\n"
                "open('argv.txt', 'a', encoding='utf-8').write(' '.join(sys.argv[1:]) + '\\n')\n"
                f"sys.exit({exit_code})\n",
                encoding="utf-8",
            )
    (consumer / "wiring.yaml").write_text("{}\n", encoding="utf-8")
    (consumer / "repo-hygiene.yaml").write_text("{}\n", encoding="utf-8")


def test_template_has_no_fail_open_shim() -> None:
    entries = _entries()
    assert len(entries) >= 7
    assert not [e for e in entries if "|| exit 0" in e]


def test_failing_validator_fails_the_hook(tmp_path: Path) -> None:
    _stub_everything(tmp_path, exit_code=1)
    for entry in _entries():
        assert _run(entry, tmp_path, ["f.md"]).returncode != 0, entry


def test_passing_validator_passes_the_hook(tmp_path: Path) -> None:
    _stub_everything(tmp_path, exit_code=0)
    for entry in _entries():
        assert _run(entry, tmp_path, ["f.md"]).returncode == 0, entry


def test_hook_skips_when_playbook_absent(tmp_path: Path) -> None:
    for entry in _entries():
        assert _run(entry, tmp_path, ["f.md"]).returncode == 0, entry


def test_filename_hooks_receive_staged_files(tmp_path: Path) -> None:
    _stub_everything(tmp_path, exit_code=0)
    for entry in _entries():
        if '"$@"' not in entry:
            continue
        (tmp_path / "argv.txt").unlink(missing_ok=True)
        _run(entry, tmp_path, ["a.md", "b.md"])
        assert (tmp_path / "argv.txt").read_text(encoding="utf-8").split()[-2:] == ["a.md", "b.md"], entry

