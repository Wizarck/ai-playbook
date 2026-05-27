"""Render ``.coderabbit.yaml`` from template + bundle.

The current template is large YAML with no marker blocks. We treat the
template post-substitution as canonical and append consumer extras
(``bundle.coderabbit_extras``) at the bottom as YAML comments + extra
list entries. CodeRabbit tolerates extra top-level keys; injecting under
``reviews.path_filters`` would require a YAML parser round-trip which we
defer for simplicity.

Phase 4 ships a minimal renderer: full overwrite of the canonical
template, with extras documented as appended comments. Future iteration
may introduce a proper YAML merge.
"""
from __future__ import annotations


def _format_extras(coderabbit_extras: dict | None) -> str:
    coderabbit_extras = coderabbit_extras or {}
    extra_filters = coderabbit_extras.get("path_filters") or []
    extra_instructions = coderabbit_extras.get("path_instructions") or []
    if not extra_filters and not extra_instructions:
        return ""
    lines: list[str] = []
    lines.append("")
    lines.append("# >>> consumer extras (managed by apply_config) >>>")
    if extra_filters:
        lines.append("# Extra path_filters to merge into the reviews section above:")
        for pattern in extra_filters:
            lines.append(f"#   - {pattern!r}")
    if extra_instructions:
        lines.append("# Extra path_instructions:")
        for entry in extra_instructions:
            path = entry.get("path", "")
            inst = entry.get("instructions", "").replace("\n", "\n#       ")
            lines.append(f"#   - path: {path!r}")
            lines.append(f"#     instructions: |")
            lines.append(f"#       {inst}")
    lines.append("# <<< consumer extras <<<")
    return "\n".join(lines) + "\n"


def render(
    *,
    template: str,
    substitutions: dict[str, str],
    bundle: dict,
) -> str:
    body = template
    for key, value in substitutions.items():
        if value is not None:
            body = body.replace("{{" + key + "}}", str(value))
    extras = _format_extras(bundle.get("coderabbit_extras"))
    if extras:
        if not body.endswith("\n"):
            body += "\n"
        body += extras
    return body


__all__ = ["render"]
