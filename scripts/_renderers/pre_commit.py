"""Render ``.pre-commit-config.yaml`` from template + bundle.

Playbook hooks live inside the ``id=playbook-hooks`` marker block. Consumer
hooks from ``bundle.pre_commit_extras.hooks`` are appended after the
``repos:`` block as a second ``- repo: local`` group (pre-commit accepts
several ``local`` repos; any other name would need a ``rev``), between a
``# Consumer hooks …`` header and a ``# (end of consumer hooks)`` trailer.
Each such hook must carry ``id``, ``name``, ``entry`` and ``language`` (else
the render fails: pre-commit would reject the whole config).

When the file already exists (``current_text``), it is merged instead of
regenerated: the marker block is refreshed in place, the bundle-extras region
is replaced, and everything else the consumer wrote is kept verbatim. A
current file that is not a valid YAML mapping (e.g. corrupted by an older renderer) is
regenerated from the template; the orchestrator backs it up first. A merge the
consumer's layout cannot take raises ``MergeConflictError`` (that file is
skipped as a conflict).
"""
from __future__ import annotations

import re

import yaml

from scripts._marker_blocks import CommentStyle, MarkerBlock, parse_blocks, write_blocks
from scripts._renderers._yaml_merge import MergeConflictError, duplicate_key, load_mapping
from scripts._template_classifier import compute_sha

_BLOCK_ID = "playbook-hooks"
_LOCAL_HOOK_REQUIRED = ("id", "name", "entry", "language")
_EXTRAS_HEADER = "# Consumer hooks (preserved across apply_config)"
_EXTRAS_TRAILER = "# (end of consumer hooks)"
_EXTRAS_REGION_RE = re.compile(
    r"^" + re.escape(_EXTRAS_HEADER) + r"\n"
    r"(?:"
    r".*?^" + re.escape(_EXTRAS_TRAILER) + r"[ \t]*(?:\n|\Z)"
    # Legacy (pre-trailer) region: the old emitter wrote one `local-extras`
    # group whose lines were all indented by four spaces.
    r"|  - repo: local-extras\n(?:    [^\n]*(?:\n|\Z))*"
    r")",
    re.MULTILINE | re.DOTALL,
)


def _inject_sha(text: str) -> str:
    parsed = parse_blocks(text, CommentStyle.HASH)
    if not parsed.blocks:
        return text
    desired = {
        bid: MarkerBlock(id=bid, content=block.content, sha=compute_sha(block.content),
                         style=CommentStyle.HASH)
        for bid, block in parsed.blocks.items()
    }
    return write_blocks(text, desired, style=CommentStyle.HASH)


def _render_extras_yaml(hooks: list[dict]) -> str:
    """Render the consumer hooks as one ``- repo: local`` item under ``repos:``."""
    hooks = [h for h in hooks if isinstance(h, dict)]
    if not hooks:
        return ""
    for hook in hooks:
        missing = [k for k in _LOCAL_HOOK_REQUIRED
                   if not (isinstance(hook.get(k), str) and hook[k].strip())]
        if missing:
            raise ValueError(
                f"pre_commit_extras hook {hook.get('id') or '(no id)'!r} lacks "
                f"{', '.join(missing)}: a `repo: local` hook needs id, name, entry "
                "and language, or pre-commit rejects the whole config"
            )
    dumped = yaml.safe_dump(
        [{"repo": "local", "hooks": hooks}],
        sort_keys=False, default_flow_style=False, allow_unicode=True,
        width=4096,
    )
    return "".join(f"  {line}" if line.strip() else line
                   for line in dumped.splitlines(keepends=True))


def _merge_error(body: str, *, markerless: bool) -> str:
    dup = duplicate_key(body)
    cause = ("this file has no playbook-hooks marker block, so the block was "
             "appended at its end; " if markerless else "")
    return (
        "merged .pre-commit-config.yaml is not a valid pre-commit config"
        + (f" (duplicate key {dup!r})" if dup else "")
        + f" — {cause}the playbook and consumer hooks are `  - repo:` items "
        "continuing `repos:`, so `repos:` must be the last top-level key and its "
        "items indented two spaces (pre-commit's sample config puts `-   repo:` "
        "at column 0). Re-indent the list or move the keys that follow it above "
        "it, then re-apply"
    )


def render(
    *,
    template: str,
    substitutions: dict[str, str],
    bundle: dict,
    current_text: str | None = None,
) -> str:
    body = template
    for key, value in substitutions.items():
        if value is not None:
            body = body.replace("{{" + key + "}}", str(value))
    body = _inject_sha(body)

    merging = bool(current_text) and load_mapping(current_text) is not None
    markerless = False
    appended: list = []  # repo items this render appends at the end of the file
    if merging:
        # Merge: refresh the canonical block(s) in the consumer's own file.
        sealed = parse_blocks(body, CommentStyle.HASH).blocks
        markerless = (_BLOCK_ID in sealed
                      and _BLOCK_ID not in parse_blocks(current_text, CommentStyle.HASH).blocks)
        if markerless:
            items = yaml.safe_load(sealed[_BLOCK_ID].content)
            appended.extend(items if isinstance(items, list) else [])
        body = write_blocks(current_text, sealed, style=CommentStyle.HASH)
        body, removed = _EXTRAS_REGION_RE.subn("", body)
        if removed:
            body = body.rstrip("\n") + "\n"

    hooks = (bundle.get("pre_commit_extras") or {}).get("hooks") or []
    extras_yaml = _render_extras_yaml(hooks)
    if extras_yaml:
        body = body.rstrip("\n") + "\n\n" + _EXTRAS_HEADER + "\n"
        body += extras_yaml + _EXTRAS_TRAILER + "\n"
        appended.append({"repo": "local", "hooks": [h for h in hooks if isinstance(h, dict)]})

    merged = load_mapping(body, strict=True)
    repos = (merged or {}).get("repos")
    # Appended items must land at the end of `repos:`, not under a key after it.
    if merged is None or (appended and (
            not isinstance(repos, list) or repos[-len(appended):] != appended)):
        if merging:
            raise MergeConflictError(_merge_error(body, markerless=markerless))
        raise ValueError("rendered .pre-commit-config.yaml is not a valid YAML mapping")
    return body


__all__ = ["render"]
