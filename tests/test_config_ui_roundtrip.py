"""config-ui: loading applied state then exporting must not drop bundle sections.

``tests/config_ui_state.mjs`` runs config-ui/app.js in Node against a stub DOM
(needs only ``node``, which CI runners ship); ``tests/config_ui_roundtrip.mjs``
drives the real page in Chromium and is skipped without a global Playwright
install. Both load ``tests/fixtures/config-ui-applied.json`` and the exported
bundle must validate against the bundle schema, so apply_config accepts it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "config-ui-applied.json"
APPLIED_SECTIONS = (
    "pre_commit_extras", "coderabbit_extras", "mcp_project_servers", "gitignore_extras",
    "file_curate_intents", "project_meta", "backup_preferences",
)


def _bundle_schema() -> dict:
    path = REPO_ROOT / "schemas" / "schema-ai-playbook-config-v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _playwright_dir() -> Path | None:
    npm = shutil.which("npm")
    if not shutil.which("node") or not npm:
        return None
    root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True, check=False).stdout.strip()
    pkg = Path(root) / "playwright"
    return pkg if (pkg / "index.mjs").is_file() else None


def test_fixture_is_a_valid_bundle() -> None:
    jsonschema.validate(json.loads(FIXTURE.read_text(encoding="utf-8")), _bundle_schema())


def test_applied_state_survives_export_without_a_browser() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, str(REPO_ROOT / "tests" / "config_ui_state.mjs"), str(REPO_ROOT), str(FIXTURE)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["errors"] == []
    assert "Loaded applied state" in out["initBanner"]
    applied = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for key in APPLIED_SECTIONS:
        assert out["exported"].get(key) == applied[key], key
    jsonschema.validate(out["exported"], _bundle_schema())
    # "Reset to defaults" clears the toggles and the Config-files extras but
    # keeps what the UI cannot re-create and the Files-tab curate decisions.
    reset = out["afterReset"]
    for key in ("project_meta", "backup_preferences", "file_curate_intents"):
        assert reset.get(key) == applied[key], key
    for key in ("pre_commit_extras", "coderabbit_extras", "mcp_project_servers",
                "gitignore_extras"):
        assert key not in reset, key
    jsonschema.validate(reset, _bundle_schema())


def test_applied_state_roundtrips_through_export() -> None:
    pw = _playwright_dir()
    if pw is None:
        pytest.skip("node + global playwright not available")
    proc = subprocess.run(
        ["node", str(REPO_ROOT / "tests" / "config_ui_roundtrip.mjs"), str(REPO_ROOT), str(pw),
         str(FIXTURE)],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    jsonschema.validate(json.loads(proc.stdout)["bundle"], _bundle_schema())
