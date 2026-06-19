"""Tests for ``scripts._renderers`` — per-file renderers."""
from __future__ import annotations

import json

from scripts._marker_blocks import CommentStyle, parse_blocks
from scripts._renderers import (
    render_agents_md,
    render_claude_settings,
    render_claude_settings_local,
    render_coderabbit,
    render_gitignore,
    render_mcp_project,
    render_pre_commit,
    render_settings_json,
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


def test_agents_md_keep_mine_overrides_block_content() -> None:
    template = (
        "<!-- ai-playbook:begin id=bootstrap-directive -->\n"
        "Canonical from playbook\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n"
    )
    current = (
        "<!-- ai-playbook:begin id=bootstrap-directive sha=abc -->\n"
        "My personalised bootstrap\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n"
    )
    bundle = {
        "file_curate_intents": {
            "AGENTS.md": {"blocks": {"bootstrap-directive": "keep_mine"}}
        }
    }
    out = render_agents_md(
        template=template, substitutions={}, bundle=bundle, current_text=current,
    )
    assert "My personalised bootstrap" in out
    assert "Canonical from playbook" not in out


def test_agents_md_take_playbook_is_default() -> None:
    template = (
        "<!-- ai-playbook:begin id=bootstrap-directive -->\n"
        "Canonical from playbook\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n"
    )
    current = (
        "<!-- ai-playbook:begin id=bootstrap-directive -->\n"
        "My personalised content\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n"
    )
    out = render_agents_md(
        template=template, substitutions={}, bundle={}, current_text=current,
    )
    assert "Canonical from playbook" in out
    assert "My personalised content" not in out


def test_agents_md_default_action_keep_mine_applies_to_all_blocks() -> None:
    template = (
        "<!-- ai-playbook:begin id=block-a -->\nPLAYBOOK A\n<!-- ai-playbook:end block-a -->\n"
        "<!-- ai-playbook:begin id=block-b -->\nPLAYBOOK B\n<!-- ai-playbook:end block-b -->\n"
    )
    current = (
        "<!-- ai-playbook:begin id=block-a -->\nMINE A\n<!-- ai-playbook:end block-a -->\n"
        "<!-- ai-playbook:begin id=block-b -->\nMINE B\n<!-- ai-playbook:end block-b -->\n"
    )
    bundle = {
        "file_curate_intents": {
            "AGENTS.md": {"default_action": "keep_mine"}
        }
    }
    out = render_agents_md(
        template=template, substitutions={}, bundle=bundle, current_text=current,
    )
    assert "MINE A" in out
    assert "MINE B" in out
    assert "PLAYBOOK" not in out


def test_agents_md_per_block_override_beats_default() -> None:
    template = (
        "<!-- ai-playbook:begin id=block-a -->\nPLAYBOOK A\n<!-- ai-playbook:end block-a -->\n"
        "<!-- ai-playbook:begin id=block-b -->\nPLAYBOOK B\n<!-- ai-playbook:end block-b -->\n"
    )
    current = (
        "<!-- ai-playbook:begin id=block-a -->\nMINE A\n<!-- ai-playbook:end block-a -->\n"
        "<!-- ai-playbook:begin id=block-b -->\nMINE B\n<!-- ai-playbook:end block-b -->\n"
    )
    bundle = {
        "file_curate_intents": {
            "AGENTS.md": {
                "default_action": "keep_mine",
                "blocks": {"block-b": "take_playbook"},
            }
        }
    }
    out = render_agents_md(
        template=template, substitutions={}, bundle=bundle, current_text=current,
    )
    assert "MINE A" in out
    assert "PLAYBOOK B" in out
    assert "MINE B" not in out


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


def test_shipped_gitignore_ignores_rendered_mcp_outputs() -> None:
    # Rendered MCP configs are LOCAL build artifacts (base+project+personal merge)
    # — they must stay gitignored so personal/tenant servers never land in a
    # committed file. Guards the playbook-patterns block in the shipped template.
    from pathlib import Path

    tmpl = (
        Path(__file__).resolve().parents[1] / "templates" / "new-project" / ".gitignore.tmpl"
    ).read_text(encoding="utf-8")
    out = render_gitignore(template=tmpl, substitutions={}, bundle={})
    assert ".mcp.json" in out
    assert ".gemini/settings.json" in out


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


def test_pre_commit_bool_fields_render_lowercase_yaml() -> None:
    """Booleans (e.g. pass_filenames) must emit YAML-idiomatic lowercase, not str(bool)."""
    template = (
        "repos:\n"
        "# >>> ai-playbook:begin id=playbook-hooks >>>\n"
        "  - repo: local\n"
        "    hooks: []\n"
        "# <<< ai-playbook:end playbook-hooks <<<\n"
    )
    out = render_pre_commit(
        template=template,
        substitutions={},
        bundle={"pre_commit_extras": {"hooks": [
            {"id": "h", "pass_filenames": False, "args": ["--fix"]},
        ]}},
    )
    assert "pass_filenames: false" in out
    assert "pass_filenames: False" not in out
    import yaml  # the extras fragment must stay valid YAML
    yaml.safe_load(out)


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


# ---------------------------------------------------------------------------
# .claude/settings.json — agnostic identity-merge renderer
# ---------------------------------------------------------------------------


_SETTINGS_TMPL_WITH_BASH = json.dumps({
    "_comment": "canonical",
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "Edit|Write|MultiEdit|Bash",
                "hooks": [
                    {"type": "command",
                     "command": "python .claude/hooks/openspec-apply-enforce.py",
                     "timeout": 10},
                ],
            },
            {
                "matcher": "Edit|Write|MultiEdit|Bash",
                "hooks": [
                    {"type": "command",
                     "command": "python .ai-playbook/scripts/hook_dispatcher.py PreToolUse",
                     "timeout": 10},
                ],
            },
        ]
    },
    "permissions": {"allow": [], "additionalDirectories": []},
}, indent=2) + "\n"


def test_settings_json_seeds_invariant_when_missing() -> None:
    out = render_settings_json(
        template=_SETTINGS_TMPL_WITH_BASH,
        substitutions={"PROJECT_BANK": "x"},
        bundle={"settings": {}},
        current_text=None,
    )
    parsed = json.loads(out)
    cmds = [
        h.get("command", "")
        for e in parsed["hooks"]["PreToolUse"] for h in e["hooks"]
    ]
    assert any("openspec-apply-enforce.py" in c for c in cmds)
    # The generic L1 dispatcher entry is also ensured (Fase E2).
    assert any("hook_dispatcher.py" in c for c in cmds)


def test_settings_json_no_duplicate_when_bash_matcher_present() -> None:
    """Both required PreToolUse hooks already present (enforce + dispatcher) → the
    renderer is a byte-level no-op and never duplicates either."""
    out = render_settings_json(
        template=_SETTINGS_TMPL_WITH_BASH,
        substitutions={},
        bundle={"settings": {}},
        current_text=_SETTINGS_TMPL_WITH_BASH,
    )
    # No semantic change ⇒ verbatim passthrough (byte-identical).
    assert out == _SETTINGS_TMPL_WITH_BASH
    cmds = [
        h.get("command", "")
        for e in json.loads(out)["hooks"]["PreToolUse"] for h in e["hooks"]
    ]
    assert sum("openspec-apply-enforce.py" in c for c in cmds) == 1
    assert sum("hook_dispatcher.py" in c for c in cmds) == 1


def test_settings_json_ensures_dispatcher_when_only_enforce_present() -> None:
    """An older consumer with just the enforce hook gains the dispatcher entry,
    deduped by basename (idempotent on a second render)."""
    only_enforce = json.dumps({
        "hooks": {"PreToolUse": [{
            "matcher": "Edit|Write|MultiEdit",
            "hooks": [{"type": "command",
                       "command": "python .claude/hooks/openspec-apply-enforce.py",
                       "timeout": 10}],
        }]},
    }) + "\n"
    out = render_settings_json(
        template=_SETTINGS_TMPL_WITH_BASH, substitutions={},
        bundle={"settings": {}}, current_text=only_enforce,
    )
    cmds = [h.get("command", "") for e in json.loads(out)["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert sum("hook_dispatcher.py" in c for c in cmds) == 1
    # idempotent: re-render adds nothing
    out2 = render_settings_json(
        template=_SETTINGS_TMPL_WITH_BASH, substitutions={},
        bundle={"settings": {}}, current_text=out,
    )
    assert out2 == out


_ONLY_ENFORCE = json.dumps({
    "hooks": {"PreToolUse": [{
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [{"type": "command",
                   "command": "python .claude/hooks/openspec-apply-enforce.py",
                   "timeout": 10}],
    }]},
}) + "\n"


def test_settings_json_skips_dispatcher_when_unavailable() -> None:
    """When the consumer's submodule pin lacks hook_dispatcher.py the caller sets
    DISPATCHER_AVAILABLE=0; the dispatcher hook must NOT be wired (an absent
    script would exit 2 and block every Edit/Write/Bash). The enforce invariant
    still lands."""
    out = render_settings_json(
        template=_SETTINGS_TMPL_WITH_BASH,
        substitutions={"DISPATCHER_AVAILABLE": "0"},
        bundle={"settings": {}},
        current_text=_ONLY_ENFORCE,
    )
    cmds = [h.get("command", "") for e in json.loads(out)["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert any("openspec-apply-enforce.py" in c for c in cmds)
    assert not any("hook_dispatcher.py" in c for c in cmds)


def test_settings_json_dispatcher_anchored_to_project_dir() -> None:
    """The wired dispatcher command anchors to $CLAUDE_PROJECT_DIR (not a bare
    relative path) so the hook is cwd-independent and cannot resolve into a
    sibling repo."""
    out = render_settings_json(
        template=_SETTINGS_TMPL_WITH_BASH,
        substitutions={},  # default ⇒ available
        bundle={"settings": {}},
        current_text=_ONLY_ENFORCE,
    )
    dispatch = [
        h.get("command", "")
        for e in json.loads(out)["hooks"]["PreToolUse"] for h in e["hooks"]
        if "hook_dispatcher.py" in h.get("command", "")
    ]
    assert len(dispatch) == 1
    assert "$CLAUDE_PROJECT_DIR" in dispatch[0]


def test_settings_json_preserves_user_keys() -> None:
    current = json.dumps({
        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]},
        "permissions": {"allow": ["Bash"]},
        "myCustomKey": {"deep": [1, 2, 3]},
    }) + "\n"
    out = render_settings_json(
        template=_SETTINGS_TMPL_WITH_BASH,
        substitutions={},
        bundle={"settings": {}},
        current_text=current,
    )
    parsed = json.loads(out)
    # Invariant added,
    assert any(
        "openspec-apply-enforce.py" in h.get("command", "")
        for e in parsed["hooks"]["PreToolUse"] for h in e["hooks"]
    )
    # user content preserved.
    assert parsed["myCustomKey"] == {"deep": [1, 2, 3]}
    assert parsed["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "echo hi"
    assert "Bash" in parsed["permissions"]["allow"]


def test_settings_json_projects_agnostic_hooks_claude_only() -> None:
    current = json.dumps({
        "hooks": {"PreToolUse": [
            {"matcher": "Edit|Write|MultiEdit|Bash",
             "hooks": [{"type": "command",
                        "command": "python .claude/hooks/openspec-apply-enforce.py",
                        "timeout": 10}]}
        ]},
    }) + "\n"
    bundle = {"settings": {"hooks": [
        {"event": "SessionStart", "command": "python claude-only.py", "targets": ["claude"]},
        {"event": "SessionStart", "command": "python gemini-only.py", "targets": ["gemini"]},
        {"event": "Stop", "command": "python all-models.py"},
    ]}}
    out = render_settings_json(
        template=_SETTINGS_TMPL_WITH_BASH, substitutions={}, bundle=bundle,
        current_text=current,
    )
    parsed = json.loads(out)
    all_cmds = [
        h.get("command", "")
        for entries in parsed["hooks"].values() for e in entries for h in e["hooks"]
    ]
    assert any("claude-only.py" in c for c in all_cmds)
    assert any("all-models.py" in c for c in all_cmds)        # no targets ⇒ applies
    assert not any("gemini-only.py" in c for c in all_cmds)   # gemini-only ⇒ skipped


def test_settings_json_unions_permissions_and_legacy_extras() -> None:
    current = json.dumps({
        "hooks": {"PreToolUse": [
            {"matcher": "Edit|Write|MultiEdit",
             "hooks": [{"type": "command",
                        "command": "python .claude/hooks/openspec-apply-enforce.py"}]}
        ]},
        "permissions": {"allow": ["Read"]},
    }) + "\n"
    bundle = {
        "settings": {"permissions_allow": ["WebSearch"]},
        "claude_settings_extras": {"permissions_allow": ["Bash"],
                                   "additional_directories": ["../shared"]},
    }
    out = render_settings_json(
        template=_SETTINGS_TMPL_WITH_BASH, substitutions={}, bundle=bundle,
        current_text=current,
    )
    perms = json.loads(out)["permissions"]
    assert set(perms["allow"]) == {"Read", "WebSearch", "Bash"}
    assert perms["additionalDirectories"] == ["../shared"]


def test_settings_json_malformed_current_returned_verbatim() -> None:
    bad = "{ this is not json"
    out = render_settings_json(
        template=_SETTINGS_TMPL_WITH_BASH, substitutions={}, bundle={"settings": {}},
        current_text=bad,
    )
    assert out == bad  # never clobber a malformed file; L1 validate flags it


def test_shipped_agents_template_renders_without_marker_mismatch() -> None:
    # Regression: a prose EXAMPLE like `<!-- ai-playbook:begin id=… -->` inside the
    # shipped template was parsed as a real (unclosed) marker, raising "marker
    # mismatch" in render → breaking `bootstrap --update` managed_files for every
    # consumer. The shipped template must always render + round-trip its managed
    # blocks cleanly.
    from pathlib import Path

    tmpl = (
        Path(__file__).resolve().parents[1] / "templates" / "new-project" / "AGENTS.md.tmpl"
    ).read_text(encoding="utf-8")
    out = render_agents_md(
        template=tmpl,
        substitutions={"PROJECT_NAME": "demo", "PROJECT_BANK": "demo-bank"},
        bundle={"project_meta": {}},
        current_text=None,
    )
    ids = set(parse_blocks(out, CommentStyle.HTML).blocks)
    assert {"bootstrap-directive", "dispatcher-index", "capability-map", "mcp-sources"} <= ids
