"""Regression tests for auto-managed orphan detection in cleanup-zombies.

Slice: fix/cleanup-zombies-auto-managed-parser.

Background — the bug these tests pin down. The `auto-managed-orphan-blocks`
manifest entry shipped as Tier 1 (auto-delete) on top of a hand-rolled marker
parser that, unlike the canonical one in `scripts/auto_managed.py`:

  1. matched the BEGIN marker anywhere in a line (`re.search`), so prose that
     merely *documented* the syntax was read as a real block;
  2. never reset its skip state when no END followed, so it deleted from the
     false BEGIN to end of file;
  3. resolved `<source>` against the consumer root, so it could not recognise
     the `caveman/*` and `ponytail/*` namespaces and classified every live
     block from those subsystems as an orphan.

Run against the playbook's own tree it destroyed 623 lines across 7 files,
truncating several mid-sentence. Each `SAMPLE_*` below is a reduced form of a
file it actually damaged.

Contracts:
- docs/rules/cleanup-zombies.rule.md (tier semantics)
- docs/concepts/auto-managed-sections.md (marker parsing contract)
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "rules" / "cleanup-zombies.rule.py"
MANIFEST_PATH = REPO_ROOT / "specs" / "zombies-manifest.yaml"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SPEC = importlib.util.spec_from_file_location("cleanup_zombies_rule", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
_cz = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = _cz  # dataclasses resolves types via sys.modules
SPEC.loader.exec_module(_cz)


# --- Reduced forms of the files the buggy parser actually destroyed ----------

# docs/operations/caveman-architecture.md — the marker appears inside a
# sentence. Everything from here to EOF was deleted.
SAMPLE_PROSE_MENTION = """# Architecture

Every consumer `AGENTS.md` carries a `<!-- BEGIN auto-managed: caveman/ruleset:... -->` block.

## 7 Cross-references

- [scripts/caveman/](../../scripts/caveman/) — the implementation.
"""

# docs/runbooks/ponytail-toggle.md — the marker is a full line, but inside a
# fenced code block showing the reader what gets written.
SAMPLE_FENCED_EXAMPLE = """# Toggle

3. Writes `<project>/AGENTS.md` with a new marker-fenced block:

   ```html
   <!-- BEGIN auto-managed: ponytail/ruleset:full -->
   ...the ladder + mode + boundaries...
   <!-- END auto-managed -->
   ```

The block is composed from sections in the spec.
"""

# AGENTS.md — a real, live block owned by the caveman toggle.
SAMPLE_LIVE_CAVEMAN = """# AGENTS

<!-- BEGIN auto-managed: caveman/ruleset:ultra -->
**Caveman mode: ON - intensity ultra**
<!-- END auto-managed -->

Trailing content that must survive.
"""

# A BEGIN with no END. The old parser deleted to EOF; the canonical parser
# raises, and "cannot parse" must mean "touch nothing".
SAMPLE_UNTERMINATED = """# Broken

<!-- BEGIN auto-managed: specs/taxonomy:runtime -->
content with no closing marker

Trailing content that must survive.
"""

# The genuine article: well-formed block, `specs/` namespace, source that no
# longer resolves to any playbook anchor.
SAMPLE_GENUINE_ORPHAN = """# Consumer

<!-- BEGIN auto-managed: specs/deleted-spec:gone -->
stale generated content
<!-- END auto-managed -->

Trailing content that must survive.
"""

SAMPLES = {
    "prose-mention.md": SAMPLE_PROSE_MENTION,
    "fenced-example.md": SAMPLE_FENCED_EXAMPLE,
    "live-caveman.md": SAMPLE_LIVE_CAVEMAN,
    "unterminated.md": SAMPLE_UNTERMINATED,
    "genuine-orphan.md": SAMPLE_GENUINE_ORPHAN,
}


@pytest.fixture
def consumer(tmp_path: Path) -> Path:
    """A consumer tree with the playbook submodule stubbed and caveman ON."""
    playbook = tmp_path / ".ai-playbook"
    (playbook / "scripts").mkdir(parents=True)
    (playbook / "scripts" / "auto_managed.py").write_text("", encoding="utf-8")
    (playbook / "caveman.json").write_text(
        json.dumps({"schema": "caveman-toggle/v1", "enabled": True, "mode": "ultra"}),
        encoding="utf-8",
    )
    (playbook / "ponytail.json").write_text(
        json.dumps({"schema": "ponytail-toggle/v1", "enabled": True, "mode": "full"}),
        encoding="utf-8",
    )
    # Under a subdirectory on purpose: `**/*.md` is fnmatch'd against the
    # repo-relative path, and a root-level `AGENTS.md` has no `/` to match. The
    # real damage was confined to `.ai-playbook/**` for exactly this reason.
    (tmp_path / "docs").mkdir()
    for name, body in SAMPLES.items():
        (tmp_path / "docs" / name).write_text(body, encoding="utf-8")
    return tmp_path


def _orphans(consumer: Path, name: str) -> list[str]:
    return _cz._auto_managed_orphans(consumer / "docs" / name, consumer)


# --- Detection --------------------------------------------------------------


def test_prose_mention_is_not_a_block(consumer: Path) -> None:
    assert _orphans(consumer, "prose-mention.md") == []


def test_fenced_example_is_not_a_block(consumer: Path) -> None:
    assert _orphans(consumer, "fenced-example.md") == []


def test_unterminated_begin_reports_nothing(consumer: Path) -> None:
    """Unparseable must mean "no finding", never "delete the rest of the file"."""
    assert _orphans(consumer, "unterminated.md") == []


def test_live_block_is_not_orphan_when_its_feature_is_on(consumer: Path) -> None:
    assert _orphans(consumer, "live-caveman.md") == []


def test_live_block_is_orphan_once_its_feature_is_off(consumer: Path) -> None:
    (consumer / ".ai-playbook" / "caveman.json").write_text(
        json.dumps({"schema": "caveman-toggle/v1", "enabled": False}), encoding="utf-8"
    )
    assert _orphans(consumer, "live-caveman.md") == ["caveman/ruleset:ultra"]


def test_unknown_namespace_is_never_orphan(consumer: Path) -> None:
    """An owner this script cannot reason about earns silence, not a deletion."""
    (consumer / "docs" / "third-party.md").write_text(
        "<!-- BEGIN auto-managed: someplugin/thing:x -->\nbody\n<!-- END auto-managed -->\n",
        encoding="utf-8",
    )
    assert _orphans(consumer, "third-party.md") == []


def test_genuine_orphan_is_still_detected(consumer: Path) -> None:
    assert _orphans(consumer, "genuine-orphan.md") == ["specs/deleted-spec:gone"]


def test_playbook_submodule_is_out_of_scope(consumer: Path) -> None:
    """`**/*.md` from the consumer root must not walk the playbook's own docs."""
    (consumer / ".ai-playbook" / "vendored.md").write_text(SAMPLE_PROSE_MENTION, encoding="utf-8")
    walked = {p.name for p in _cz._consumer_markdown(consumer, "**/*.md")}
    assert "vendored.md" not in walked
    assert "prose-mention.md" in walked


# --- Execution --------------------------------------------------------------


def test_apply_never_mutates_any_sample(consumer: Path) -> None:
    """End-to-end: --apply over the real manifest leaves every file byte-identical.

    The entry is Tier 3 now, so even the genuine orphan is only reported.
    """
    before = {name: (consumer / "docs" / name).read_bytes() for name in SAMPLES}
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--consumer-root", str(consumer), "--apply", "--quiet"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    for name, original in before.items():
        assert (consumer / "docs" / name).read_bytes() == original, f"{name} was mutated"


def test_prune_action_removes_only_the_genuine_orphan(consumer: Path) -> None:
    """The `prune_blocks` action itself stays correct for any future entry."""
    entry = {"path": "**/*.md", "id": "t", "tier": 1, "action": "prune_blocks"}
    _cz._do_prune_blocks(entry, consumer)
    for name in ("prose-mention.md", "fenced-example.md", "live-caveman.md", "unterminated.md"):
        assert (consumer / "docs" / name).read_text(encoding="utf-8") == SAMPLES[name], name
    pruned = (consumer / "docs" / "genuine-orphan.md").read_text(encoding="utf-8")
    assert "specs/deleted-spec:gone" not in pruned
    assert "stale generated content" not in pruned
    assert "Trailing content that must survive." in pruned


# --- Manifest + tier contract ----------------------------------------------


def test_manifest_entry_is_report_only() -> None:
    entries = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))["entries"]
    entry = next(e for e in entries if e["id"] == "auto-managed-orphan-blocks")
    assert entry["tier"] == 3
    assert entry["action"] == "report"


def test_tier3_never_reaches_the_action_dispatch(consumer: Path) -> None:
    """The documented Tier 3 guarantee, enforced structurally rather than by luck."""
    entry = {
        "id": "guard",
        "tier": 3,
        "action": "delete",  # would be executed if the guard were missing
        "safety": "auto_managed_orphan",
        "path": "**/*.md",
        "reason": "structural guard probe",
    }
    outcome = _cz._process_entry(entry, consumer, apply=True)
    assert outcome is not None
    assert outcome.action_taken == "advisory"
    for name, body in SAMPLES.items():
        assert (consumer / "docs" / name).read_text(encoding="utf-8") == body
