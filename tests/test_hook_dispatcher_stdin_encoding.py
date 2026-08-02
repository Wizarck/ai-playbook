"""The dispatcher's PROCESS BOUNDARY: stdin/stdout encoding.

Every other dispatcher test builds `str` objects and calls a rule in-process,
which is exactly why none of them could see the bug this file exists for: the
corruption happens while DECODING BYTES on stdin, before any `str` exists. A
test that never crosses that boundary cannot observe what happens at it.

Measured on Windows, 2026-08-02: a `jira-ticket-standard` ticket carrying
`## Métricas` and `## Test de regresión` was refused for MISSING both. Those are
the only two canonical section names with accents; cp1252 mangled them on the
way in, so the normalised headings never matched. The gate refused the compliant
author and told them to add sections they already had.

`PYTHONIOENCODING=cp1252` below is not decoration — it is the whole test. Drop
it and this file passes on a UTF-8 CI host no matter what the dispatcher does,
and would have shipped green beside the broken code.
"""
from __future__ import annotations

import json
import subprocess
import sys

from scripts import hook_dispatcher as HD  # noqa: N812

_DISPATCHER = HD.REPO_ROOT / "scripts" / "hook_dispatcher.py"

_BODY = [
    "## Contexto / Problema",
    "",
    "Una seccion con prosa real y suficientes palabras para el minimo.",
    "",
    "## Repro",
    "",
    "1. Ejecutar el dispatcher. 2. Mirar el veredicto que devuelve.",
    "",
    "## Esperado vs Actual",
    "",
    "Esperado que pase limpio, actual que se queja de algo presente.",
    "",
    "## Test de regresión",
    "",
    "tests/test_hook_dispatcher_stdin_encoding.py",
    "",
]

_METRICS = ["## Métricas", "", "- secciones mal reportadas como ausentes → calidad / exactitud", ""]


def _event(description: str) -> bytes:
    """UTF-8 BYTES, deliberately — this is what a real hook payload is."""
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "mcp__atlassian__createJiraIssue",
        "tool_input": {"issueTypeName": "Bug", "description": description},
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _run(payload: bytes) -> subprocess.CompletedProcess:
    """Spawn the dispatcher with a NON-UTF-8 default encoding, as Windows has."""
    return subprocess.run(
        [sys.executable, str(_DISPATCHER), "PreToolUse"],
        input=payload,
        capture_output=True,
        env={**dict(__import__("os").environ), "PYTHONIOENCODING": "cp1252"},
    )


def test_the_fixture_actually_carries_non_ascii() -> None:
    """Guard against this whole file quietly becoming vacuous.

    If the accented headings ever drift to ASCII, every assertion below still
    passes while testing nothing at all.
    """
    payload = _event("\n".join(_BODY + _METRICS))
    assert any(b > 0x7F for b in payload), "fixture lost its non-ASCII characters"


def test_conformant_spanish_ticket_survives_a_cp1252_console() -> None:
    result = _run(_event("\n".join(_BODY + _METRICS)))
    stderr = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 0, f"conformant ticket refused:\n{stderr}"
    assert "falta la secci" not in stderr


def test_a_genuinely_missing_section_is_still_refused_under_cp1252() -> None:
    """The negative control: the fix must not be 'stop checking'.

    Métricas is really absent here, so the refusal is correct — and it must name
    ONLY that section, not the accented one that is present.
    """
    result = _run(_event("\n".join(_BODY)))
    stderr = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 2, f"non-conformant ticket allowed:\n{stderr}"
    assert "Métricas" in stderr
    assert "Test de regresión" not in stderr
