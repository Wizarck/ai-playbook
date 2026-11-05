"""YAML helpers shared by the renderers that merge into the consumer's file."""
from __future__ import annotations

import yaml

_MERGE_TAG = "tag:yaml.org,2002:merge"


def duplicate_key(text: str) -> str | None:
    """Return the first mapping key that appears twice in ``text``, else None.

    PyYAML keeps the last duplicate silently, so a merge that opens a second
    top-level ``servers:`` / ``repos:`` passes ``yaml.safe_load`` while hiding
    the first mapping; pre-commit's ``check-yaml`` rejects the file.
    """
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return None
    stack, visited = [root], set()
    while stack:
        node = stack.pop()
        if node is None or id(node) in visited:
            continue
        visited.add(id(node))
        if isinstance(node, yaml.MappingNode):
            keys: set[tuple[str, str]] = set()
            for key_node, value_node in node.value:
                if isinstance(key_node, yaml.ScalarNode) and key_node.tag != _MERGE_TAG:
                    key = (key_node.tag, key_node.value)
                    if key in keys:
                        return key_node.value
                    keys.add(key)
                stack.extend((key_node, value_node))
        elif isinstance(node, yaml.SequenceNode):
            stack.extend(node.value)
    return None


def load_mapping(text: str, *, strict: bool = False) -> dict | None:
    """``yaml.safe_load(text)`` when it is a mapping, else None.

    ``strict`` also treats a duplicate key as invalid; use it on merged output
    before it is written.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    if strict and duplicate_key(text) is not None:
        return None
    return data


__all__ = ["duplicate_key", "load_mapping"]
