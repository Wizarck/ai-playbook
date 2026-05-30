"""Tests for ``scripts._dispatcher_shape`` — structural curate-drift detector."""
from __future__ import annotations

from scripts._dispatcher_shape import (
    DEST_ABSORB_AGENTS,
    DEST_DISPATCH_LEAF,
    collect_drift,
    has_curate_drift,
    is_dispatcher_file,
    is_leaf_doc,
    loose_prose_sections,
)


def _long_prose(n: int = 15) -> str:
    return "\n".join(f"This is substantive paragraph line number {i} with real content." for i in range(n))


# --- classification --------------------------------------------------------


def test_is_dispatcher_file() -> None:
    for ok in ("AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursorrules",
               ".cursor/rules/style.mdc", "sub/dir/CLAUDE.md"):
        assert is_dispatcher_file(ok), ok
    for no in ("docs/concepts/x.md", "README.md", "scripts/foo.py", "notes.txt"):
        assert not is_dispatcher_file(no), no


def test_is_leaf_doc() -> None:
    assert is_leaf_doc("docs/concepts/x.md")
    assert is_leaf_doc("docs/INDEX.md")
    assert not is_leaf_doc("AGENTS.md")
    assert not is_leaf_doc("docs/notes.txt")


# --- loose prose detection -------------------------------------------------


def test_pointer_shaped_dispatcher_has_no_drift() -> None:
    text = (
        "---\nschema: agents-md/v1\n---\n\n"
        "# AGENTS.md\n\n"
        "## Architecture\n"
        "See [the architecture doc](docs/concepts/architecture.md).\n\n"
        "## Runbooks\n"
        "- [Onboard](docs/runbooks/onboard.md)\n"
        "- [Deploy](docs/runbooks/deploy.md)\n"
    )
    assert not has_curate_drift(text, rel_path="AGENTS.md")
    assert loose_prose_sections(text, rel_path="AGENTS.md") == []


def test_long_loose_prose_is_drift() -> None:
    text = "# AGENTS.md\n\n## Notes\n" + _long_prose(15) + "\n"
    chunks = loose_prose_sections(text, rel_path="AGENTS.md")
    assert len(chunks) == 1
    assert chunks[0].line_count >= 15
    assert chunks[0].heading == "Notes"
    assert chunks[0].suggestion == DEST_DISPATCH_LEAF  # AGENTS.md => leaf doc


def test_per_model_dispatcher_suggests_absorb_into_agents() -> None:
    text = "# CLAUDE.md\n\n" + _long_prose(12) + "\n"
    chunks = loose_prose_sections(text, rel_path="CLAUDE.md")
    assert chunks
    assert chunks[0].suggestion == DEST_ABSORB_AGENTS


def test_prose_inside_marker_block_is_sanctioned() -> None:
    text = (
        "# AGENTS.md\n\n"
        "<!-- ai-playbook:begin id=core -->\n"
        + _long_prose(20) + "\n"
        "<!-- ai-playbook:end core -->\n"
    )
    # Inside a canonical block ⇒ NOT loose prose (playbook-owned, sanctioned).
    assert not has_curate_drift(text, rel_path="AGENTS.md")


def test_short_prose_under_threshold_is_not_drift() -> None:
    text = "# AGENTS.md\n\n## Identity\nWe build widgets.\nThree lines only.\nStill short.\n"
    assert not has_curate_drift(text, rel_path="AGENTS.md")


# --- aggregation -----------------------------------------------------------


def test_collect_drift_skips_leaf_docs_and_keeps_provenance() -> None:
    files = {
        "AGENTS.md": "# AGENTS\n\n## Big\n" + _long_prose(15) + "\n",
        "CLAUDE.md": "# CLAUDE\n\n" + _long_prose(15) + "\n",
        "docs/concepts/x.md": "# Doc\n\n" + _long_prose(40) + "\n",  # leaf ⇒ exempt
        "README.md": "# Readme\n\n" + _long_prose(40) + "\n",         # not a dispatcher
    }
    drift = collect_drift(files)
    paths = {d.rel_path for d in drift}
    assert paths == {"AGENTS.md", "CLAUDE.md"}
    for d in drift:
        assert d.has_drift
        assert all(c.rel_path == d.rel_path for c in d.chunks)


def test_idempotency_prose_moved_to_leaf_doc_clears_drift() -> None:
    """After curate moves prose into a leaf doc and leaves a pointer, the
    dispatcher has no loose prose — a re-run is a structural no-op (D3)."""
    dispatcher_after = (
        "# AGENTS.md\n\n## Notes\nSee [notes](docs/notes.md).\n"
    )
    leaf_after = "# Notes\n\n" + _long_prose(15) + "\n"
    files = {"AGENTS.md": dispatcher_after, "docs/notes.md": leaf_after}
    assert collect_drift(files) == []
