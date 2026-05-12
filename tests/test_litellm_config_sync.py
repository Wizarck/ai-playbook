"""Sync test: every task-class in `.ai-playbook/configs/litellm-router.yaml`
MUST also exist in `helm/eligia-stack/templates/configmaps.yaml`'s
`litellm-config` ConfigMap data block.

Per OpenSpec change `add-litellm-enforcement` T1.10: LiteLLM accepts only
ONE --config file at startup, so the playbook yaml (spec source-of-truth)
must be mirrored into the ConfigMap (production-deployed). This test fails
the build when the two drift, preventing the silent regression we hit on
2026-05-11 (proxy had only 7 consumer aliases, 0 of 11 task classes —
every `_llm.call` would have 404'd).

Once the helm chart auto-renders the ConfigMap from the playbook yaml (a
future enhancement), this test can be retired.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK_YAML = REPO_ROOT / ".ai-playbook" / "configs" / "litellm-router.yaml"
CONFIGMAP_YAML = REPO_ROOT / "helm" / "eligia-stack" / "templates" / "configmaps.yaml"


def _extract_configmap_litellm_block(text: str) -> dict:
    """Pull the inline `config.yaml: |` data from the litellm-config ConfigMap.

    `configmaps.yaml` is a multi-doc Helm template with go-template syntax
    (`{{ include ... }}`). The litellm-config ConfigMap's `data.config.yaml`
    is plain yaml indented under `config.yaml: |`. We extract it textually
    so we don't have to run `helm template` (which would require the helm
    binary).
    """
    in_litellm = False
    in_data = False
    in_config = False
    indent_marker: int | None = None
    out_lines: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()

        # Detect the `name: litellm-config` ConfigMap.
        if not in_litellm and stripped == "name: litellm-config":
            in_litellm = True
            continue
        if in_litellm and stripped.startswith("---"):
            in_litellm = False
            in_data = False
            in_config = False
            indent_marker = None
            continue
        if not in_litellm:
            continue

        if stripped == "data:":
            in_data = True
            continue
        if in_data and stripped.startswith("config.yaml: |"):
            in_config = True
            indent_marker = None
            continue

        if in_config:
            # First non-blank line after `config.yaml: |` defines the indent.
            if indent_marker is None and stripped:
                indent_marker = len(line) - len(line.lstrip(" "))
            # Capture lines at the configured indent (and deeper); strip the
            # base indent. Stop when we hit a line dedented below the marker.
            if not stripped:
                out_lines.append("")
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent_marker is not None and indent < indent_marker:
                # End of `config.yaml: |` block.
                in_config = False
                continue
            assert indent_marker is not None  # for mypy
            out_lines.append(line[indent_marker:])

    raw = "\n".join(out_lines)
    # The ConfigMap may contain go-template syntax (`{{ include ... }}`)
    # in unrelated keys; the data block itself in this chart is pure yaml.
    parsed = yaml.safe_load(raw)
    if not isinstance(parsed, dict):
        raise AssertionError(
            "Expected a dict at top of litellm-config data.config.yaml; "
            f"got {type(parsed).__name__}. Raw block:\n{raw[:500]}"
        )
    return parsed


def test_playbook_yaml_parses():
    """Sanity: the playbook yaml is valid yaml."""
    with PLAYBOOK_YAML.open() as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), f"Expected dict, got {type(data).__name__}"
    assert "model_list" in data, "Missing top-level `model_list:` key"
    assert isinstance(data["model_list"], list), "`model_list` must be a list"


def test_configmap_litellm_block_parses():
    """Sanity: the ConfigMap's inline yaml is extractable + valid."""
    text = CONFIGMAP_YAML.read_text()
    data = _extract_configmap_litellm_block(text)
    assert "model_list" in data, "Missing `model_list:` in extracted ConfigMap block"
    assert isinstance(data["model_list"], list)


def test_every_playbook_task_class_present_in_configmap():
    """The critical sync check.

    Every `model_name` in the playbook yaml MUST appear in the ConfigMap.
    The ConfigMap may have EXTRA entries (consumer aliases like
    `default-hermes`, `gpt-oss-20b-rag`) — those are fine. Strict subset.
    """
    with PLAYBOOK_YAML.open() as f:
        playbook = yaml.safe_load(f)
    configmap = _extract_configmap_litellm_block(CONFIGMAP_YAML.read_text())

    playbook_names = {m["model_name"] for m in playbook["model_list"]}
    configmap_names = {m["model_name"] for m in configmap["model_list"]}

    missing = playbook_names - configmap_names
    assert not missing, (
        f"{len(missing)} task class(es) defined in the playbook yaml are "
        f"NOT mirrored in the ConfigMap (proxy will 404 on these): "
        f"{sorted(missing)}\n"
        f"Fix: edit helm/eligia-stack/templates/configmaps.yaml's "
        f"litellm-config block to add the missing entries (copy from "
        f".ai-playbook/configs/litellm-router.yaml)."
    )


def test_task_class_model_consistency():
    """When a task_class appears in both files, the primary `model` must match.

    Catches silent drift where someone edits the model in the ConfigMap
    without updating the playbook yaml.
    """
    with PLAYBOOK_YAML.open() as f:
        playbook = yaml.safe_load(f)
    configmap = _extract_configmap_litellm_block(CONFIGMAP_YAML.read_text())

    playbook_by_name = {m["model_name"]: m for m in playbook["model_list"]}
    configmap_by_name = {m["model_name"]: m for m in configmap["model_list"]}

    drifts = []
    for name, pb_entry in playbook_by_name.items():
        cm_entry = configmap_by_name.get(name)
        if cm_entry is None:
            # Caught by the previous test; skip here.
            continue
        pb_model = pb_entry["litellm_params"]["model"]
        cm_model = cm_entry["litellm_params"]["model"]
        if pb_model != cm_model:
            drifts.append(f"{name}: playbook={pb_model!r} vs configmap={cm_model!r}")

    assert not drifts, (
        f"Model drift between the playbook yaml and the ConfigMap on "
        f"{len(drifts)} task class(es):\n  " + "\n  ".join(drifts) +
        "\n\nFix: align both files. Playbook yaml is the spec source-of-truth."
    )
