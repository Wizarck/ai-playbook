"""Tests for scripts.caveman.compress — byte-preservation contract + retry logic."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from scripts.caveman import compress


# ---------------------------------------------------------------------------
# extract_contract
# ---------------------------------------------------------------------------


def test_extract_contract_headings() -> None:
    text = "# H1\n\nbody\n\n## H2 with stuff\n\nmore\n\n### Deep\n"
    c = compress.extract_contract(text)
    assert "# H1" in c.headings
    assert "## H2 with stuff" in c.headings
    assert "### Deep" in c.headings


def test_extract_contract_code_blocks() -> None:
    text = "intro\n\n```python\nx = 1\n```\n\nmid\n\n```bash\necho ok\n```\n"
    c = compress.extract_contract(text)
    assert len(c.code_blocks) == 2
    assert "```python\nx = 1\n```" in c.code_blocks
    assert "```bash\necho ok\n```" in c.code_blocks


def test_extract_contract_urls() -> None:
    text = "see https://example.com and also http://foo.bar/path?q=1"
    c = compress.extract_contract(text)
    assert "https://example.com" in c.urls
    assert "http://foo.bar/path?q=1" in c.urls


def test_extract_contract_paths() -> None:
    text = "edit scripts/caveman/cli.py and docs/concepts/caveman-mode.md"
    c = compress.extract_contract(text)
    assert "scripts/caveman/cli.py" in c.paths
    assert "docs/concepts/caveman-mode.md" in c.paths


def test_extract_contract_skips_paths_inside_code_blocks() -> None:
    text = (
        "real/outside.py is referenced.\n"
        "\n"
        "```python\n"
        "import scripts/inside.py\n"
        "```\n"
        "\n"
        "Only the outside path counts.\n"
    )
    c = compress.extract_contract(text)
    # scripts/inside.py is inside a fenced block — covered by the code-block
    # contract, must NOT also be listed as a separate path.
    assert "scripts/inside.py" not in c.paths
    assert "real/outside.py" in c.paths


# ---------------------------------------------------------------------------
# violations
# ---------------------------------------------------------------------------


def test_violations_clean_output() -> None:
    c = compress.PreservationContract(
        headings=["# Title"],
        code_blocks=["```\ncode\n```"],
        urls=["https://example.com"],
        paths=["foo/bar.py"],
    )
    output = "# Title\n```\ncode\n```\nhttps://example.com and foo/bar.py"
    assert compress.violations(c, output) == []


def test_violations_finds_missing_heading() -> None:
    c = compress.PreservationContract(headings=["## Lost"])
    missing = compress.violations(c, "## Found\nbody")
    assert any("Lost" in m for m in missing)


def test_violations_finds_missing_code_block() -> None:
    c = compress.PreservationContract(code_blocks=["```\nvanished\n```"])
    missing = compress.violations(c, "no code here")
    assert any("code block" in m for m in missing)


def test_violations_finds_missing_url_and_path() -> None:
    c = compress.PreservationContract(urls=["https://lost.example"], paths=["lost/file.py"])
    missing = compress.violations(c, "nothing here")
    assert any("lost.example" in m for m in missing)
    assert any("lost/file.py" in m for m in missing)


# ---------------------------------------------------------------------------
# compress() — happy path with mock LLM
# ---------------------------------------------------------------------------


def _mock_llm(text_responses: list[str]) -> Callable[[str, str, int], tuple[str, str | None]]:
    """Return a callable that yields each response in order."""
    state = {"i": 0}

    def call(prompt: str, system: str, max_tokens: int) -> tuple[str, str | None]:
        i = state["i"]
        if i >= len(text_responses):
            raise RuntimeError("mock LLM exhausted")
        state["i"] += 1
        return text_responses[i], "mock-model-v1"

    return call


def _write_fixture(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "doc.md"
    p.write_text(content, encoding="utf-8")
    return p


def test_compress_happy_path(tmp_path: Path) -> None:
    source = _write_fixture(
        tmp_path,
        (
            "# Title\n\n"
            "This is a verbose paragraph that should get compressed.\n\n"
            "```python\nx = 1\n```\n\n"
            "See https://example.com for details.\n"
        ),
    )
    compressed_output = (
        "# Title\n\n"
        "Verbose paragraph. Compressed.\n\n"
        "```python\nx = 1\n```\n\n"
        "See https://example.com details.\n"
    )
    result = compress.compress(
        source,
        mode="full",
        llm_call=_mock_llm([compressed_output]),
    )
    assert result.retries_used == 0
    assert result.source == source
    assert result.backup.is_file()
    assert source.read_text(encoding="utf-8").startswith("# Title")
    assert "```python\nx = 1\n```" in source.read_text(encoding="utf-8")
    assert result.compressed_bytes < result.original_bytes


def test_compress_creates_original_md_backup(tmp_path: Path) -> None:
    source = _write_fixture(tmp_path, "# X\nbody\n")
    expected_backup = source.with_name("doc.md.original.md")
    compress.compress(
        source,
        mode="full",
        llm_call=_mock_llm(["# X\ncompressed\n"]),
    )
    assert expected_backup.is_file()
    assert expected_backup.read_text(encoding="utf-8") == "# X\nbody\n"


def test_compress_retries_on_missing_heading(tmp_path: Path) -> None:
    source = _write_fixture(tmp_path, "# Important Heading\n\nbody body body\n")
    bad_output = "Heading dropped. body.\n"  # missing the H1
    good_output = "# Important Heading\n\nbody.\n"
    result = compress.compress(
        source,
        mode="full",
        max_retries=2,
        llm_call=_mock_llm([bad_output, good_output]),
    )
    assert result.retries_used == 1
    assert "# Important Heading" in source.read_text(encoding="utf-8")


def test_compress_restores_source_when_retries_exhausted(tmp_path: Path) -> None:
    original = "# A\n```code\nx = 1\n```\n"
    source = _write_fixture(tmp_path, original)
    # Three bad outputs (1 initial + 2 retries) → fail → restore.
    bad = "no heading no code"
    with pytest.raises(compress.CompressionFailedError):
        compress.compress(
            source,
            mode="full",
            max_retries=2,
            llm_call=_mock_llm([bad, bad, bad]),
        )
    # Source must be restored
    assert source.read_text(encoding="utf-8") == original


def test_compress_rejects_invalid_mode(tmp_path: Path) -> None:
    source = _write_fixture(tmp_path, "# X\n")
    with pytest.raises(ValueError, match="invalid mode"):
        compress.compress(source, mode="telegraphic", llm_call=_mock_llm(["# X\n"]))


def test_compress_rejects_non_markdown(tmp_path: Path) -> None:
    p = tmp_path / "doc.txt"
    p.write_text("text", encoding="utf-8")
    with pytest.raises(ValueError, match="only .md files"):
        compress.compress(p, mode="full", llm_call=_mock_llm(["x"]))


def test_compress_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        compress.compress(tmp_path / "ghost.md", llm_call=_mock_llm(["x"]))


def test_compress_rejects_empty_source(tmp_path: Path) -> None:
    p = tmp_path / "empty.md"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        compress.compress(p, llm_call=_mock_llm(["x"]))


def test_compress_rejects_large_file_without_force(tmp_path: Path) -> None:
    p = tmp_path / "big.md"
    p.write_text("# X\n" + ("x " * 60_000), encoding="utf-8")  # >100 KB
    with pytest.raises(ValueError, match="force_large=True"):
        compress.compress(p, llm_call=_mock_llm(["# X\n"]))


def test_compress_refuses_when_stale_backup_differs(tmp_path: Path) -> None:
    source = _write_fixture(tmp_path, "# Current\n")
    stale_backup = source.with_name("doc.md.original.md")
    stale_backup.write_text("# Older content\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="differs from source"):
        compress.compress(source, llm_call=_mock_llm(["# Current\n"]))


def test_compress_accepts_matching_existing_backup(tmp_path: Path) -> None:
    # If a backup already exists AND matches the current source byte-for-byte,
    # treat it as a resumption of a previous session (no error).
    source = _write_fixture(tmp_path, "# Same\nbody\n")
    matching_backup = source.with_name("doc.md.original.md")
    matching_backup.write_text("# Same\nbody\n", encoding="utf-8")
    result = compress.compress(
        source,
        llm_call=_mock_llm(["# Same\nbody compressed.\n"]),
    )
    assert result.backup == matching_backup
