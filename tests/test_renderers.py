"""Tests for ``scripts._renderers`` — per-file renderers."""
from __future__ import annotations

from scripts._marker_blocks import CommentStyle, parse_blocks
from scripts._renderers import (
    render_agents_md,
    render_claude_settings,
    render_claude_settings_local,
    render_coderabbit,
    render_gitignore,
    render_mcp_project,
    render_pre_commit,
)
from scripts._template_classifier import compute_sha


# ---------------------------------------------------------------------------
# AGENTS.md
# ---------------------------------------------------------------------------


def test_agents_md_substitutes_placeholders() -> None:
    template = (
        "# {{PROJECT_NAME}} — AGENTS.md\n\n"
        "<!-- ai-playbook:begin id=bootstrap-directive -->\n"
        "## §0 Bootstrap for {{PROJECT_NAME}} (bank {{PROJECT_BANK}})\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n\n"
        "## §1 Project identity\n"
        "{{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}\n"
    )
    out = render_agents_md(
        template=template,
        substitutions={"PROJECT_NAME": "myproj", "PROJECT_BANK": "myproj"},
        bundle={"project_meta": {"project_identity": "Acme project does foo."}},
    )
    assert "# myproj — AGENTS.md" in out
    assert "## §0 Bootstrap for myproj (bank myproj)" in out
    assert "Acme project does foo." in out
    assert "{{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}" not in out


def test_agents_md_default_when_project_meta_absent() -> None:
    template = (
        "## §1 Project identity\n"
        "{{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}\n"
    )
    out = render_agents_md(template=template, substitutions={}, bundle={})
    assert "TODO: 1-3 lines" in out


def test_agents_md_injects_sha_into_markers() -> None:
    canonical_content = "## §0 Bootstrap content"
    template = (
        f"<!-- ai-playbook:begin id=bootstrap-directive -->\n"
        f"{canonical_content}\n"
        f"<!-- ai-playbook:end bootstrap-directive -->\n"
    )
    out = render_agents_md(template=template, substitutions={}, bundle={})
    parsed = parse_blocks(out, CommentStyle.HTML)
    block = parsed.blocks["bootstrap-directive"]
    assert block.sha is not None
    assert block.sha == compute_sha(block.content)


def test_agents_md_idempotent_when_bundle_unchanged() -> None:
    template = (
        "<!-- ai-playbook:begin id=core -->\n"
        "canonical line\n"
        "<!-- ai-playbook:end core -->\n\n"
        "## §1 Identity\n{{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}\n"
    )
    subs = {"PROJECT_NAME": "x"}
    bundle = {"project_meta": {"project_identity": "stable text"}}
    first = render_agents_md(template=template, substitutions=subs, bundle=bundle)
    second = render_agents_md(template=template, substitutions=subs, bundle=bundle)
    assert first == second


# ---------------------------------------------------------------------------
# .gitignore
# ---------------------------------------------------------------------------


def test_gitignore_renders_marker_block_and_extras() -> None:
    template = (
        "# header\n\n"
        "# >>> ai-playbook:begin id=playbook-patterns >>>\n"
        ".ai-playbook/overrides.log\n"
        "# <<< ai-playbook:end playbook-patterns <<<\n"
    )
    out = render_gitignore(
        template=template,
        substitutions={},
        bundle={"gitignore_extras": {"patterns": ["dist/", "node_modules/"]}},
    )
    assert ".ai-playbook/overrides.log" in out
    assert "dist/" in out
    assert "node_modules/" in out
    assert "consumer patterns" in out


def test_gitignore_preserves_existing_consumer_lines() -> None:
    template = (
        "# >>> ai-playbook:begin id=playbook-patterns >>>\n"
        ".ai-playbook/overrides.log\n"
        "# <<< ai-playbook:end playbook-patterns <<<\n"
    )
    current = (
        "# My custom patterns from before\n"
        "logs/\n"
        "secrets/\n\n"
        "# >>> ai-playbook:begin id=playbook-patterns >>>\n"
        ".ai-playbook/overrides.log\n"
        "# <<< ai-playbook:end playbook-patterns <<<\n"
    )
    out = render_gitignore(
        template=template, substitutions={}, bundle={}, current_text=current,
    )
    assert "logs/" in out
    assert "secrets/" in out


def test_gitignore_dedupes_preserved_and_extras() -> None:
    template = (
        "# >>> ai-playbook:begin id=playbook-patterns >>>\n"
        "core-pattern\n"
        "# <<< ai-playbook:end playbook-patterns <<<\n"
    )
    current = (
        "duplicate-pattern\n\n"
        "# >>> ai-playbook:begin id=playbook-patterns >>>\n"
        "core-pattern\n"
        "# <<< ai-playbook:end playbook-patterns <<<\n"
    )
    out = render_gitignore(
        template=template,
        substitutions={},
        bundle={"gitignore_extras": {"patterns": ["duplicate-pattern", "new-pattern"]}},
        current_text=current,
    )
    assert out.count("duplicate-pattern") == 1
    assert "new-pattern" in out


# ---------------------------------------------------------------------------
# .pre-commit-config.yaml
# ---------------------------------------------------------------------------


def test_pre_commit_renders_baseline_and_extras() -> None:
    template = (
        "repos:\n"
        "# >>> ai-playbook:begin id=playbook-hooks >>>\n"
        "  - repo: https://github.com/pre-commit/pre-commit-hooks\n"
        "    rev: v4.6.0\n"
        "    hooks:\n"
        "      - id: trailing-whitespace\n"
        "# <<< ai-playbook:end playbook-hooks <<<\n"
    )
    out = render_pre_commit(
        template=template,
        substitutions={},
        bundle={"pre_commit_extras": {"hooks": [{"id": "custom-hook", "language": "system"}]}},
    )
    assert "trailing-whitespace" in out  # canonical preserved
    assert "custom-hook" in out
    assert "local-extras" in out


def test_pre_commit_empty_extras_returns_canonical() -> None:
    template = (
        "repos:\n"
        "# >>> ai-playbook:begin id=playbook-hooks >>>\n"
        "  - repo: local\n"
        "    hooks: []\n"
        "# <<< ai-playbook:end playbook-hooks <<<\n"
    )
    out = render_pre_commit(template=template, substitutions={}, bundle={})
    assert "local-extras" not in out
    assert "local" in out


# ---------------------------------------------------------------------------
# .coderabbit.yaml
# ---------------------------------------------------------------------------


def test_coderabbit_merges_extras_into_yaml_structure() -> None:
    template = "language: en-US\nreviews:\n  profile: chill\n  path_filters:\n    - '!playbook/**'\n"
    out = render_coderabbit(
        template=template,
        substitutions={},
        bundle={"coderabbit_extras": {
            "path_filters": ["!myproject/**"],
            "path_instructions": [{"path": "src/**", "instructions": "review carefully"}],
        }},
    )
    # Re-parse to confirm structural merge.
    import yaml
    parsed = yaml.safe_load(out)
    assert parsed["language"] == "en-US"
    assert parsed["reviews"]["profile"] == "chill"
    # path_filters merged: playbook entry preserved, consumer appended.
    assert "!playbook/**" in parsed["reviews"]["path_filters"]
    assert "!myproject/**" in parsed["reviews"]["path_filters"]
    # path_instructions added.
    assert any(
        e.get("path") == "src/**" and "review carefully" in e.get("instructions", "")
        for e in parsed["reviews"]["path_instructions"]
    )


def test_coderabbit_dedupes_path_filters() -> None:
    template = "reviews:\n  path_filters:\n    - '!shared/**'\n"
    out = render_coderabbit(
        template=template,
        substitutions={},
        bundle={"coderabbit_extras": {"path_filters": ["!shared/**", "!new/**"]}},
    )
    import yaml
    parsed = yaml.safe_load(out)
    filters = parsed["reviews"]["path_filters"]
    assert filters.count("!shared/**") == 1
    assert "!new/**" in filters


def test_coderabbit_consumer_overrides_playbook_path_instructions() -> None:
    template = (
        "reviews:\n"
        "  path_instructions:\n"
        "    - path: 'src/**'\n"
        "      instructions: 'playbook default'\n"
    )
    out = render_coderabbit(
        template=template,
        substitutions={},
        bundle={"coderabbit_extras": {
            "path_instructions": [{"path": "src/**", "instructions": "consumer override"}],
        }},
    )
    import yaml
    parsed = yaml.safe_load(out)
    entries = [e for e in parsed["reviews"]["path_instructions"] if e["path"] == "src/**"]
    assert len(entries) == 1
    assert entries[0]["instructions"] == "consumer override"


def test_coderabbit_no_extras_returns_canonical() -> None:
    template = "language: en-US\nreviews:\n  profile: chill\n"
    out = render_coderabbit(template=template, substitutions={}, bundle={})
    assert "language: en-US" in out


# ---------------------------------------------------------------------------
# .claude/settings.json + .local
# ---------------------------------------------------------------------------


def test_claude_settings_main_is_pure_substitution() -> None:
    template = '{"project": "{{PROJECT_NAME}}"}\n'
    out = render_claude_settings(template=template, substitutions={"PROJECT_NAME": "x"}, bundle={})
    assert '"project": "x"' in out


def test_claude_settings_local_uses_bundle_extras() -> None:
    template = '{}\n'
    out = render_claude_settings_local(
        template=template,
        substitutions={},
        bundle={"claude_settings_extras": {
            "permissions_allow": ["Edit", "Write"],
            "additional_directories": ["/extra"],
        }},
    )
    assert '"Edit"' in out
    assert '"Write"' in out
    assert '"/extra"' in out
    # Round-trip via json.loads to verify structural validity.
    import json
    parsed = json.loads(out)
    assert parsed["permissions"]["allow"] == ["Edit", "Write"]
    assert parsed["permissions"]["additionalDirectories"] == ["/extra"]


def test_claude_settings_local_seed_only_when_no_extras() -> None:
    template = '{"seed": true}\n'
    out = render_claude_settings_local(template=template, substitutions={}, bundle={})
    assert out == template


# ---------------------------------------------------------------------------
# mcp-servers.project.yaml
# ---------------------------------------------------------------------------


def test_mcp_project_appends_extras() -> None:
    template = (
        "schema: mcp-servers/v1\n"
        "# >>> ai-playbook:begin id=project-servers-baseline >>>\n"
        "servers:\n"
        "  hindsight:\n"
        "    id: hindsight\n"
        "# <<< ai-playbook:end project-servers-baseline <<<\n"
    )
    out = render_mcp_project(
        template=template,
        substitutions={},
        bundle={"mcp_project_servers": {
            "custom-server": {
                "id": "custom-server",
                "transport": "stdio",
                "command": "node",
            },
        }},
    )
    assert "hindsight:" in out
    assert "custom-server:" in out
    assert "command: node" in out


def test_mcp_project_empty_extras() -> None:
    template = (
        "schema: mcp-servers/v1\n"
        "# >>> ai-playbook:begin id=project-servers-baseline >>>\n"
        "servers:\n"
        "  hindsight:\n"
        "    id: hindsight\n"
        "# <<< ai-playbook:end project-servers-baseline <<<\n"
    )
    out = render_mcp_project(template=template, substitutions={}, bundle={})
    assert "Consumer-added" not in out
    assert "hindsight:" in out
