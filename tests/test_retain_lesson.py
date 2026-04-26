"""Tests for the scripts.retain_lesson deprecation shim (v0.3.0+).

The real tests live in tests/test_retain_memory.py. These verify that the
deprecation shim still imports + emits a warning + delegates correctly so
older runbooks/hooks/scripts that haven't migrated yet continue to work.

Will be removed in v1.0.0 alongside scripts/retain_lesson.py itself.
"""
from __future__ import annotations

import warnings

import pytest

from scripts import _hindsight as hs


def _resp(body: bytes, status: int = 200):
    class _R:
        def __init__(self, b: bytes, s: int) -> None:
            self._b = b
            self.status = s

        def read(self) -> bytes:
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    return _R(body, status)


def test_shim_re_exports_public_api() -> None:
    """Old `from scripts.retain_lesson import X` calls must still work."""
    from scripts import retain_lesson  # noqa: F401

    # Symbols that downstream callers may have imported.
    assert hasattr(retain_lesson, "RetainItem")
    assert hasattr(retain_lesson, "ALLOWED_KINDS")
    assert hasattr(retain_lesson, "QUEUE_FILE")
    assert hasattr(retain_lesson, "main")


def test_shim_main_emits_deprecation_warning(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HINDSIGHT_URL", "https://h.example/")
    monkeypatch.setenv("CF_ACCESS_CLIENT_ID", "cid")
    monkeypatch.setenv("CF_ACCESS_CLIENT_SECRET", "csec")
    monkeypatch.setattr(hs.urlrequest, "urlopen",
                        lambda req, timeout: _resp(b'{"items_count":1}'))
    monkeypatch.setattr(
        "sys.argv",
        ["retain_lesson", "--bank", "consumer-d", "--content", "x" * 30, "--dry-run"],
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        from scripts import retain_lesson

        rc = retain_lesson.main()

    assert rc == 0
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
    err = capsys.readouterr().err
    assert "deprecated" in err.lower()
