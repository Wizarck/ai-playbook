"""Render ``.coderabbit.yaml`` from template + bundle.

This renderer performs a structural YAML merge:

* The template's canonical YAML is loaded.
* ``bundle.coderabbit_extras.path_filters`` extends the
  ``reviews.path_filters`` list (de-duplicated, order preserved with
  consumer entries appended after playbook ones).
* ``bundle.coderabbit_extras.path_instructions`` extends
  ``reviews.path_instructions`` (extra entries appended).
* The merged structure is re-emitted as YAML.

The output is valid YAML that CodeRabbit can consume directly — no more
"consumer extras as comments" gap from the Phase-4 minimal version.
"""
from __future__ import annotations

from typing import Any

import yaml


def _apply_subs(text: str, substitutions: dict[str, str]) -> str:
    out = text
    for key, value in substitutions.items():
        if value is not None:
            out = out.replace("{{" + key + "}}", str(value))
    return out


def _merge_path_filters(
    base: list[Any] | None, extras: list[str] | None,
) -> list[str] | None:
    if not extras and not base:
        return base
    base = list(base or [])
    extras = list(extras or [])
    out: list[str] = []
    seen: set[str] = set()
    for entry in (*base, *extras):
        if not isinstance(entry, str):
            continue
        if entry in seen:
            continue
        seen.add(entry)
        out.append(entry)
    return out


def _merge_path_instructions(
    base: list[Any] | None, extras: list[dict] | None,
) -> list[Any] | None:
    if not extras and not base:
        return base
    base = list(base or [])
    extras_list = list(extras or [])
    out: list[Any] = list(base)
    existing_paths = {
        e["path"] for e in out
        if isinstance(e, dict) and isinstance(e.get("path"), str)
    }
    for entry in extras_list:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if not isinstance(path, str):
            continue
        if path in existing_paths:
            # Consumer override: replace the playbook entry at the same path.
            out = [
                e if not (isinstance(e, dict) and e.get("path") == path) else entry
                for e in out
            ]
        else:
            out.append(entry)
            existing_paths.add(path)
    return out


def render(
    *,
    template: str,
    substitutions: dict[str, str],
    bundle: dict,
) -> str:
    body = _apply_subs(template, substitutions)
    extras = bundle.get("coderabbit_extras") or {}
    extra_filters = extras.get("path_filters")
    extra_instructions = extras.get("path_instructions")
    if not extra_filters and not extra_instructions:
        return body

    try:
        data: Any = yaml.safe_load(body)
    except yaml.YAMLError:
        # Fall back to plain template if YAML parse fails (defensive).
        return body
    if not isinstance(data, dict):
        return body

    reviews = data.setdefault("reviews", {})
    if not isinstance(reviews, dict):
        reviews = {}
        data["reviews"] = reviews

    if extra_filters:
        merged_filters = _merge_path_filters(reviews.get("path_filters"), extra_filters)
        if merged_filters is not None:
            reviews["path_filters"] = merged_filters

    if extra_instructions:
        merged_instructions = _merge_path_instructions(
            reviews.get("path_instructions"), extra_instructions,
        )
        if merged_instructions is not None:
            reviews["path_instructions"] = merged_instructions

    return yaml.safe_dump(
        data,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        indent=2,
    )


__all__ = ["render"]
