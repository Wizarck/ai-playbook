"""Per-file renderers used by ``apply_config`` (Phase 5 wiring).

Each renderer turns a (template, substitutions, bundle) triple into the
final file content. The renderers are pure: they read no filesystem,
write no filesystem, and have no side effects. The caller
(``apply_config``) handles backup + atomic write.

Convention
----------
Every renderer exposes a top-level ``render`` function with the same
shape::

    def render(*, template: str, substitutions: dict, bundle: dict) -> str: ...

* ``template`` — raw text of ``templates/new-project/<file>.tmpl``.
* ``substitutions`` — placeholder mapping (PROJECT_NAME, OWNER_EMAIL,
  TODAY, PLAYBOOK_PIN, PROJECT_BANK).
* ``bundle`` — full bundle JSON dict.

Each renderer also fills the SHA attribute of any marker block it emits,
so the resulting file is self-describing (the UI can later read the
file alone and verify drift against the bundle's ``file_states.manifest``).
"""

from scripts._renderers.agents_md import render as render_agents_md
from scripts._renderers.claude_settings import (
    render_main as render_claude_settings,
    render_local as render_claude_settings_local,
)
from scripts._renderers.coderabbit import render as render_coderabbit
from scripts._renderers.gitignore import render as render_gitignore
from scripts._renderers.mcp_project import render as render_mcp_project
from scripts._renderers.pre_commit import render as render_pre_commit

__all__ = [
    "render_agents_md",
    "render_claude_settings",
    "render_claude_settings_local",
    "render_coderabbit",
    "render_gitignore",
    "render_mcp_project",
    "render_pre_commit",
]
