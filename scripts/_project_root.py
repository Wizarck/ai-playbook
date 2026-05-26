"""Resolve the consumer project root by walking up from cwd.

Centralised because multiple modules (``scripts.caveman.toggle``,
``scripts.rules_toggle``, ``scripts.rules.caveman-reinforce.rule``)
previously reproduced the same walk and all suffered the same trap:
when cwd is inside the playbook submodule
(``<consumer>/.ai-playbook/`` or
``<consumer>/.skills-sources/ai-playbook/``), the walk hit the
submodule's own ``AGENTS.md`` first and mis-resolved the project root
to the submodule directory — producing nested
``.ai-playbook/.ai-playbook/<state>.json`` artefacts in consumer repos
and polluting the submodule's git status.

Fix: when walking up, skip any candidate sitting inside a
``.ai-playbook/`` or ``.skills-sources/`` directory. Those dotfile
names are reserved by convention for playbook checkouts; a consumer
project root is never named that. The playbook repo itself (typically
``<somewhere>/ai-playbook/``, no dot) is unaffected, so dogfooding
``caveman``/``rules_toggle`` on the playbook still works.

Stdlib-only — safe to import from latency-sensitive hooks.
"""
from __future__ import annotations

from pathlib import Path

# Directory-name segments that mark a playbook checkout. Both are dotfile
# names by convention (``.ai-playbook`` = git submodule mount;
# ``.skills-sources`` = parent of skill-source mirrors, including a
# ``.skills-sources/ai-playbook/`` copy). A consumer project's root
# directory is never named either of these.
PLAYBOOK_CHECKOUT_SEGMENTS = frozenset({".ai-playbook", ".skills-sources"})


def is_inside_playbook_checkout(candidate: Path) -> bool:
    """True if ``candidate`` lives inside a playbook submodule checkout.

    Match is on exact path segments (not substrings), so a consumer
    directory like ``.ai-playbook-stuff`` is not flagged.
    """
    return any(part in PLAYBOOK_CHECKOUT_SEGMENTS for part in candidate.parts)


def find_project_root(start: Path | None = None) -> Path | None:
    """Find the consumer project root.

    A "project root" is a directory containing ``AGENTS.md``. Walks up
    from ``start`` (defaults to cwd), returning the first match that is
    NOT inside a playbook checkout. Returns ``None`` if no qualifying
    root is found on the parent chain.

    Note: an ``.ai-playbook/`` directory alone is NOT sufficient — the
    user's home holds ``~/.ai-playbook/projects.yaml`` (the personal
    registry, not a project), and matching on that would resolve every
    directory under ``$HOME`` to the home dir. Consumer projects per
    ``docs/concepts/projects-registry.md`` always carry an ``AGENTS.md``.
    """
    here = (start or Path.cwd()).resolve()
    if here.is_file():
        here = here.parent
    for candidate in (here, *here.parents):
        if not (candidate / "AGENTS.md").is_file():
            continue
        if is_inside_playbook_checkout(candidate):
            continue
        return candidate
    return None


__all__ = [
    "PLAYBOOK_CHECKOUT_SEGMENTS",
    "find_project_root",
    "is_inside_playbook_checkout",
]
