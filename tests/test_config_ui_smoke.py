"""Smoke tests for config-ui/ — file presence, JSON validity, schema coherence."""
from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
UI_DIR = REPO_ROOT / "config-ui"
SCHEMAS = REPO_ROOT / "schemas"


def test_ui_assets_present() -> None:
    for name in (
        "index.html",
        "app.js",
        "style.css",
        "rules-inventory.json",
        "features-inventory.json",
        "global-flags-inventory.json",
        "defaults.json",
        # .js sidecars (build_ui_sidecars.py) must be committed so the UI works
        # under file:// after a plain clone/submodule checkout — no build step.
        "rules-inventory.js",
        "features-inventory.js",
        "global-flags-inventory.js",
        "skills-inventory.js",
        "mcps-inventory.js",
        "defaults.js",
    ):
        assert (UI_DIR / name).is_file(), f"missing UI asset: {name}"


def test_index_html_references_app_and_style() -> None:
    text = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'src="app.js"' in text
    assert 'href="style.css"' in text


def test_index_html_loads_applied_config_sidecar() -> None:
    """The script tag for the applied-config sidecar must be present so the UI
    can render the current applied state on open over file:// (where fetch()
    is blocked)."""
    text = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'src="../applied-config.js"' in text
    # The onerror handler must set a flag so app.js can detect a missing sidecar
    # and fall back to defaults.json.
    assert "APPLIED_CONFIG_MISSING" in text


def test_app_js_consumes_applied_config() -> None:
    """app.js must check window.APPLIED_CONFIG before falling back to defaults."""
    text = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "window.APPLIED_CONFIG" in text
    assert "ai-playbook-config/v1" in text


def test_app_js_init_degrades_gracefully() -> None:
    """init() must not collapse on a single inventory fetch failure (file:// CORS,
    missing JSON, network). Every fetch needs a .catch fallback so Promise.all
    never rejects and wireEvents()/renderAll() always run."""
    text = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "offlineCount" in text, "expected offlineCount tracking in init()"
    assert "onFail" in text, "expected onFail() helper wrapping each fetch"


def test_app_js_updates_enforce_summary_on_individual_toggle() -> None:
    """toggleSkillEnforced/toggleMcpEnforced must refresh the #skills-summary /
    #mcps-summary text — not only the tab badge — otherwise the summary stays
    stale until a full re-render (search, filter, enable/disable-all)."""
    text = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "updateSkillsSummary" in text
    assert "updateMcpsSummary" in text


def test_app_js_loads_inventories_via_sidecar_with_fetch_fallback() -> None:
    """init() prefers each inventory's window global (the .js sidecar, which
    works under file://) and falls back to fetch() of the .json over http(s).
    Both the global name and the .json URL must appear for every inventory."""
    text = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "loadInv(" in text, "expected the loadInv() global-preferring loader"
    for global_name, url in (
        ("RULES_INVENTORY", "rules-inventory.json"),
        ("FEATURES_INVENTORY", "features-inventory.json"),
        ("GLOBAL_FLAGS_INVENTORY", "global-flags-inventory.json"),
        ("SKILLS_INVENTORY", "skills-inventory.json"),
        ("MCPS_INVENTORY", "mcps-inventory.json"),
        ("DEFAULTS", "defaults.json"),
    ):
        assert global_name in text, f"app.js does not reference window.{global_name}"
        assert f'"{url}"' in text, f"app.js does not keep {url} as a fetch fallback"
    # The fallback path must still go through fetch().
    assert "fetch(url)" in text, "expected fetch(url) fallback inside loadInv"


def test_index_html_loads_inventory_sidecars() -> None:
    """index.html must load each inventory .js sidecar via <script src> (the
    file://-safe path) with an onerror flag for the offline-mode banner."""
    text = (UI_DIR / "index.html").read_text(encoding="utf-8")
    for base, flag in (
        ("rules-inventory", "RULES_INVENTORY_MISSING"),
        ("features-inventory", "FEATURES_INVENTORY_MISSING"),
        ("global-flags-inventory", "GLOBAL_FLAGS_INVENTORY_MISSING"),
        ("skills-inventory", "SKILLS_INVENTORY_MISSING"),
        ("mcps-inventory", "MCPS_INVENTORY_MISSING"),
        ("defaults", "DEFAULTS_MISSING"),
    ):
        assert f'src="{base}.js"' in text, f"index.html does not load {base}.js"
        assert flag in text, f"index.html missing onerror flag {flag}"


def test_defaults_validates_against_bundle_schema() -> None:
    schema = json.loads((SCHEMAS / "schema-ai-playbook-config-v1.json").read_text(encoding="utf-8"))
    defaults = json.loads((UI_DIR / "defaults.json").read_text(encoding="utf-8"))
    jsonschema.validate(defaults, schema)


def test_rules_inventory_shape() -> None:
    inv = json.loads((UI_DIR / "rules-inventory.json").read_text(encoding="utf-8"))
    assert inv["schema"] == "rules-inventory/v1"
    assert isinstance(inv["rules"], list)
    assert len(inv["rules"]) >= 10
    # Every entry must carry the minimal keys the UI consumes.
    required = {"slug", "status", "has_l1", "has_l3", "triggers", "description", "doc_path"}
    for r in inv["rules"]:
        missing = required - set(r.keys())
        assert not missing, f"rule {r.get('slug')} missing keys: {missing}"


def test_features_inventory_shape() -> None:
    inv = json.loads((UI_DIR / "features-inventory.json").read_text(encoding="utf-8"))
    assert inv["schema"] == "features-inventory/v1"
    assert "caveman" in inv["features"]
    cv = inv["features"]["caveman"]
    assert "modes" in cv
    assert "components" in cv
    keys = {c["key"] for c in cv["components"]}
    # Mirrors schema-caveman-toggle-v1.json#/properties/components.
    assert keys == {
        "response_style", "compress_docs", "subagents_cavecrew",
        "commit_caveman", "review_caveman", "mcp_shrink",
    }


def test_global_flags_inventory_shape() -> None:
    inv = json.loads((UI_DIR / "global-flags-inventory.json").read_text(encoding="utf-8"))
    assert inv["schema"] == "global-flags-inventory/v1"
    assert isinstance(inv["flags"], list)
    for f in inv["flags"]:
        for k in ("key", "label", "env_var", "default", "value_on", "value_off"):
            assert k in f, f"flag {f.get('key')} missing {k}"


def test_app_js_emits_bundle_schema_literal() -> None:
    """The Export logic must produce schema='ai-playbook-config/v1'."""
    text = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "ai-playbook-config/v1" in text


def test_app_js_marker_strings_match_apply_config() -> None:
    """The Import validation in app.js checks `data.schema !== 'ai-playbook-config/v1'`."""
    text = (UI_DIR / "app.js").read_text(encoding="utf-8")
    # Either string literal form should appear.
    assert re.search(r"['\"]ai-playbook-config/v1['\"]", text), "schema literal missing from app.js"


def test_advanced_sub_toggles_listed_in_rules_inventory() -> None:
    """apply-skill-enforcement must carry the bash_inspection advanced entry."""
    inv = json.loads((UI_DIR / "rules-inventory.json").read_text(encoding="utf-8"))
    ase = next(r for r in inv["rules"] if r["slug"] == "apply-skill-enforcement")
    assert "advanced" in ase
    keys = {a["key"] for a in ase["advanced"]}
    assert "bash_inspection" in keys
    bi = next(a for a in ase["advanced"] if a["key"] == "bash_inspection")
    assert bi["env_var"] == "AIPLAYBOOK_BASH_INSPECTION"


def test_app_js_uses_show_save_file_picker() -> None:
    """Direct-save path requires the File System Access API and IndexedDB to
    persist the chosen handle across exports."""
    text = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "showSaveFilePicker" in text
    assert "indexedDB" in text
    # Permission re-prompt path for stale/denied handles.
    assert "queryPermission" in text
    assert "requestPermission" in text
    # Stale-handle cleanup.
    assert "clearStoredHandle" in text


def test_app_js_writes_via_writable_stream() -> None:
    """The direct-save path must use FileSystemFileHandle.createWritable, not
    a download anchor, when the API is available."""
    text = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "createWritable" in text


def test_app_js_falls_back_to_download_anchor() -> None:
    """Firefox/Safari (no showSaveFilePicker) must still get a working export."""
    text = (UI_DIR / "app.js").read_text(encoding="utf-8")
    # The fallback uses a Blob + anchor click; both markers must be present
    # alongside the modern API.
    assert "new Blob(" in text
    assert "createObjectURL" in text


def test_index_html_has_next_steps_panel() -> None:
    """The Next Steps panel must declare the four command-copy targets
    (move-pwsh fallback, apply pwsh + posix, claude prompt) plus the
    dismiss button."""
    text = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="next-steps"' in text
    assert 'id="ns-dismiss"' in text
    assert 'id="ns-saved-info"' in text
    assert 'id="ns-move"' in text
    # Command targets the copy buttons reference via data-copy.
    for target in ("ns-pwsh", "ns-posix", "ns-claude", "ns-move-pwsh", "ns-move-posix"):
        assert f'id="{target}"' in text, f"missing command target #{target}"
        assert f'data-copy="{target}"' in text, f"missing copy button for #{target}"


def test_next_steps_panel_carries_apply_config_command() -> None:
    """The static commands must invoke scripts.apply_config with the canonical
    applied-config.json path under .ai-playbook/."""
    text = (UI_DIR / "index.html").read_text(encoding="utf-8")
    # PowerShell variant.
    assert "python -m scripts.apply_config .ai-playbook\\applied-config.json" in text
    # POSIX variant.
    assert "python -m scripts.apply_config .ai-playbook/applied-config.json" in text


def test_app_js_wires_copy_buttons() -> None:
    """Copy buttons must use the Clipboard API (with execCommand fallback)."""
    text = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "navigator.clipboard" in text
    assert "execCommand" in text
    assert "data-copy" in text


def test_app_js_shows_next_steps_after_save() -> None:
    """After a successful export, the panel reveals itself with mode-specific
    info text (direct vs download fallback)."""
    text = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "showNextSteps" in text
    assert "#next-steps" in text
    # The two modes the panel switches between.
    assert '"direct"' in text
    assert '"download"' in text
