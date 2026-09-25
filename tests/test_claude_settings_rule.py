"""Tests for scripts/rules/claude-settings.rule.py."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_cs_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "claude-settings.rule.py",
)
assert SPEC and SPEC.loader
_cs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_cs)


def _make_consumer(tmp_path: Path, *, with_agents: bool = True, with_claude_dir: bool = True) -> Path:
    if with_agents:
        (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    if with_claude_dir:
        (tmp_path / ".claude").mkdir()
    return tmp_path


def _canonical_settings() -> dict:
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Edit|Write|MultiEdit",
                    "hooks": [
                        {
                            "type": "command",
                            "command": 'python "$CLAUDE_PROJECT_DIR/.claude/hooks/openspec-apply-enforce.py"',
                            "timeout": 10,
                        }
                    ],
                }
            ]
        }
    }


# --- validate ------------------------------------------------------------------

def test_validate_ok_when_settings_declare_required_hook(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    (root / ".claude" / "settings.json").write_text(json.dumps(_canonical_settings()), encoding="utf-8")
    assert _cs.validate(root) == 0


def test_validate_drift_when_settings_missing(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    rc = _cs.validate(root)
    assert rc == 1
    assert "missing" in capsys.readouterr().err


def test_validate_drift_when_pretooluse_absent(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    (root / ".claude" / "settings.json").write_text(json.dumps({"hooks": {}}), encoding="utf-8")
    rc = _cs.validate(root)
    assert rc == 1
    assert "PreToolUse" in capsys.readouterr().err


def test_validate_drift_when_matcher_present_but_wrong_command(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    bad = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Edit|Write|MultiEdit",
                    "hooks": [{"type": "command", "command": "echo nope"}],
                }
            ]
        }
    }
    (root / ".claude" / "settings.json").write_text(json.dumps(bad), encoding="utf-8")
    rc = _cs.validate(root)
    assert rc == 1


def test_validate_not_applicable_when_no_claude_dir(tmp_path: Path) -> None:
    # AGENTS.md present but no .claude/ — not applicable.
    (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    assert _cs.validate(tmp_path) == 0


def test_validate_fatal_when_no_consumer_root(tmp_path: Path, capsys) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    rc = _cs.validate(nested)
    assert rc == 2
    assert "no consumer root" in capsys.readouterr().err


def test_validate_fatal_when_settings_malformed_json(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    (root / ".claude" / "settings.json").write_text("{not valid json", encoding="utf-8")
    rc = _cs.validate(root)
    assert rc == 2
    assert "malformed" in capsys.readouterr().err


def test_validate_skip_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_CLAUDE_SETTINGS_SKIP", "1")
    # Broken state but skip flag bypasses everything.
    assert _cs.validate(tmp_path) == 0


def test_validate_prefers_local_variant(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    # Local variant ok; canonical settings.json absent / different — local wins.
    (root / ".claude" / "settings.local.json").write_text(json.dumps(_canonical_settings()), encoding="utf-8")
    assert _cs.validate(root) == 0


# --- apply ---------------------------------------------------------------------

def test_apply_creates_settings_when_missing(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    rc = _cs.apply(dry_run=False, cwd=root)
    assert rc == 0
    written = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert _cs._has_required_pretooluse(written)


def test_apply_dry_run_does_not_write(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    rc = _cs.apply(dry_run=True, cwd=root)
    assert rc == 0
    assert not (root / ".claude" / "settings.json").exists()


def test_apply_merges_into_existing_user_keys(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    existing = {
        "permissions": {"allow": ["Bash"], "additionalDirectories": []},
        "hooks": {
            "SessionStart": [
                {"hooks": [{"type": "command", "command": "echo hello"}]}
            ]
        },
    }
    settings = root / ".claude" / "settings.json"
    settings.write_text(json.dumps(existing), encoding="utf-8")
    rc = _cs.apply(dry_run=False, cwd=root)
    assert rc == 0
    merged = json.loads(settings.read_text(encoding="utf-8"))
    # Required hook merged.
    assert _cs._has_required_pretooluse(merged)
    # User keys preserved.
    assert merged["permissions"] == {"allow": ["Bash"], "additionalDirectories": []}
    assert merged["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "echo hello"


def test_apply_idempotent_when_already_declared(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    settings = root / ".claude" / "settings.json"
    settings.write_text(json.dumps(_canonical_settings()), encoding="utf-8")
    rc = _cs.apply(dry_run=False, cwd=root)
    assert rc == 0
    # Subsequent run preserves the already-converged state semantically.
    second = json.loads(settings.read_text(encoding="utf-8"))
    assert _cs._has_required_pretooluse(second)
    # And a second apply is also a no-op.
    rc2 = _cs.apply(dry_run=False, cwd=root)
    assert rc2 == 0


def test_apply_fatal_when_no_consumer_root(tmp_path: Path, capsys) -> None:
    nested = tmp_path / "deep" / "nested"
    nested.mkdir(parents=True)
    rc = _cs.apply(dry_run=False, cwd=nested)
    assert rc == 2
    assert "no consumer root" in capsys.readouterr().err


def test_apply_bootstraps_claude_dir_if_missing(tmp_path: Path) -> None:
    # AGENTS.md present, no .claude/ — apply should still succeed and bootstrap.
    (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    rc = _cs.apply(dry_run=False, cwd=tmp_path)
    assert rc == 0
    assert (tmp_path / ".claude" / "settings.json").is_file()


# --- caveman UserPromptSubmit interop (Phase D follow-up) -----------------------
#
# The caveman feature adds a UserPromptSubmit hook to the consumer's
# settings.json (templates/new-project/.claude/settings.json.tmpl). The
# claude-settings rule MUST NOT reject that addition (validate stays
# permissive about unrelated hook entries) and MUST NOT clobber it
# (apply only adds the PreToolUse openspec entry, never removes others).
# These tests pin that contract.


def _caveman_userpromptsubmit_entry() -> dict:
    return {
        "hooks": [
            {
                "type": "command",
                "command": 'python "$CLAUDE_PROJECT_DIR/.ai-playbook/scripts/rules/caveman-reinforce.rule.py"',
                "timeout": 5,
            }
        ]
    }


def _canonical_settings_with_caveman() -> dict:
    s = _canonical_settings()
    s["hooks"]["UserPromptSubmit"] = [_caveman_userpromptsubmit_entry()]
    return s


def test_validate_ignores_unrelated_userpromptsubmit_entry(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    (root / ".claude" / "settings.json").write_text(
        json.dumps(_canonical_settings_with_caveman()),
        encoding="utf-8",
    )
    rc = _cs.validate(cwd=root)
    assert rc == 0  # caveman entry alongside openspec MUST validate clean


def test_apply_preserves_caveman_userpromptsubmit_entry(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    (root / ".claude" / "settings.json").write_text(
        json.dumps(_canonical_settings_with_caveman()),
        encoding="utf-8",
    )
    rc = _cs.apply(dry_run=False, cwd=root)
    assert rc == 0

    new = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "UserPromptSubmit" in new["hooks"]
    cmd = new["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
    assert "caveman-reinforce.rule.py" in cmd


def test_apply_adds_openspec_without_touching_caveman_userpromptsubmit(tmp_path: Path) -> None:
    # Starting point: only the caveman UserPromptSubmit entry, no openspec PreToolUse.
    root = _make_consumer(tmp_path)
    (root / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"UserPromptSubmit": [_caveman_userpromptsubmit_entry()]}}),
        encoding="utf-8",
    )

    rc = _cs.apply(dry_run=False, cwd=root)
    assert rc == 0

    new = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    # openspec PreToolUse added
    assert "PreToolUse" in new["hooks"]
    assert any(
        "openspec-apply-enforce.py" in (h.get("command") or "")
        for entry in new["hooks"]["PreToolUse"]
        for h in (entry.get("hooks") or [])
    )
    # caveman UserPromptSubmit preserved byte-for-byte
    assert new["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] == (
        'python "$CLAUDE_PROJECT_DIR/.ai-playbook/scripts/rules/caveman-reinforce.rule.py"'
    )


# --- cwd-independent hook commands ----------------------------------------------
#
# Claude Code runs hooks in the session's CURRENT directory. A bare relative
# `.ai-playbook/...` path breaks the moment the agent cd's into a subdirectory,
# and a failing UserPromptSubmit hook blocks every prompt.

_RELATIVE_CAVEMAN = "python .ai-playbook/scripts/rules/caveman-reinforce.rule.py"
_RELATIVE_SESSION_START = (
    "sops exec-env ../consumer-a/secrets/secrets.env -- "
    "python .ai-playbook/scripts/inject_context.py --bank-id x 2>/dev/null || true"
)


def _settings_with_relative_hooks() -> dict:
    s = _canonical_settings()
    s["hooks"]["UserPromptSubmit"] = [{"hooks": [{"type": "command", "command": _RELATIVE_CAVEMAN, "timeout": 5}]}]
    s["hooks"]["SessionStart"] = [{"hooks": [{"type": "command", "command": _RELATIVE_SESSION_START, "timeout": 60}]}]
    return s


def test_validate_flags_cwd_relative_hook_command(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    (root / ".claude" / "settings.json").write_text(json.dumps(_settings_with_relative_hooks()), encoding="utf-8")
    assert _cs.validate(root) == 1
    err = capsys.readouterr().err
    assert "cwd-relative" in err
    assert "caveman-reinforce.rule.py" in err


def test_apply_anchors_relative_hook_commands_then_validates(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    settings = root / ".claude" / "settings.json"
    settings.write_text(json.dumps(_settings_with_relative_hooks()), encoding="utf-8")
    assert _cs.apply(dry_run=False, cwd=root) == 0
    hooks = json.loads(settings.read_text(encoding="utf-8"))["hooks"]
    assert hooks["UserPromptSubmit"][0]["hooks"][0]["command"] == (
        'python "$CLAUDE_PROJECT_DIR/.ai-playbook/scripts/rules/caveman-reinforce.rule.py"'
    )
    assert hooks["SessionStart"][0]["hooks"][0]["command"] == (
        'sops exec-env "$CLAUDE_PROJECT_DIR/../consumer-a/secrets/secrets.env" -- '
        'python "$CLAUDE_PROJECT_DIR/.ai-playbook/scripts/inject_context.py" --bank-id x 2>/dev/null || true'
    )
    assert _cs.validate(root) == 0
    # Idempotent: a second apply is a no-op.
    before = settings.read_text(encoding="utf-8")
    assert _cs.apply(dry_run=False, cwd=root) == 0
    assert settings.read_text(encoding="utf-8") == before


def test_relative_hook_in_the_non_preferred_settings_file_is_caught_and_anchored(tmp_path: Path) -> None:
    """Claude Code merges settings.json and settings.local.json, so a relative
    hook in either one breaks — even when the rule's primary target is .local."""
    root = _make_consumer(tmp_path)
    (root / ".claude" / "settings.local.json").write_text(json.dumps(_canonical_settings()), encoding="utf-8")
    main = root / ".claude" / "settings.json"
    main.write_text(json.dumps({"hooks": {"SessionStart": [
        {"hooks": [{"type": "command", "command": _RELATIVE_SESSION_START}]},
    ]}}), encoding="utf-8")
    assert _cs.validate(root) == 1
    assert _cs.apply(dry_run=False, cwd=root) == 0
    cmd = json.loads(main.read_text(encoding="utf-8"))["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert '"$CLAUDE_PROJECT_DIR/.ai-playbook/scripts/inject_context.py"' in cmd
    assert _cs.validate(root) == 0


def test_relative_hook_really_breaks_outside_project_root_and_anchor_fixes_it(tmp_path: Path) -> None:
    """Not a string check: run both forms from a subdirectory, the failure the
    user hit. The relative one cannot find the script; the anchored one can."""
    import os
    import shutil
    import subprocess
    import sys

    bash = shutil.which("bash")
    py_dir = os.path.dirname(sys.executable)
    if bash is None or "system32" in bash.lower() or shutil.which("python", path=py_dir) is None:
        pytest.skip("needs a POSIX shell (as Claude Code uses for hooks) and `python` beside sys.executable")
    root = _make_consumer(tmp_path)
    script = root / ".ai-playbook" / "scripts" / "rules" / "probe.rule.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('ran')\n", encoding="utf-8")
    sub = root / "deep" / "sub"
    sub.mkdir(parents=True)
    relative = "python .ai-playbook/scripts/rules/probe.rule.py"
    anchored = _cs._settings_merge().anchor_command(relative)
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root), "PATH": py_dir + os.pathsep + os.environ.get("PATH", "")}

    def run(cmd: str) -> subprocess.CompletedProcess:
        return subprocess.run([bash, "-c", cmd], cwd=sub, env=env, capture_output=True, text=True)

    assert run(relative).returncode != 0
    ok = run(anchored)
    assert ok.returncode == 0, ok.stderr
    assert ok.stdout.strip() == "ran"
