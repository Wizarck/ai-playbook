"""Tests for the ticket-authoring standard (GPLO-1350).

Structured as the standard's own A/B/C, because the slice dogfoods it:

  A — the happy path, anchored on the REAL GPLO-1350 description
      (tests/fixtures/jira_ticket_gplo_1350.md). Not a synthetic sample: the
      first version of the normaliser rejected all four of that ticket's metric
      lines over markdown emphasis and a trailing full stop. A fixture copied
      from production is the only kind that catches that class of bug.

  B — negative controls. Every one asserts the gate FAILS when it should, and
      names the finding kind rather than just "not ok" — a test that only checks
      falsiness passes for the wrong reason the day an unrelated check starts
      firing.

  C — regression. Both ADF dialects, the carve-outs, and the exemption.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.rules import _ticket_kit as K  # noqa: E402, N812

FIXTURE = ROOT / "tests" / "fixtures" / "jira_ticket_gplo_1350.md"
FEATURE = "Feature / Big Improvement"


def _rule_module():
    spec = importlib.util.spec_from_file_location(
        "jira_ticket_standard_rule",
        ROOT / "scripts" / "rules" / "jira-ticket-standard.rule.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def conformant() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def kinds(result: K.Result) -> set[str]:
    return {f.kind for f in result.findings}


# ---------------------------------------------------------------------------
# A — baseline
# ---------------------------------------------------------------------------


def test_real_gplo_1350_is_conformant(conformant):
    result = K.validate_description(conformant, FEATURE)
    assert result.ok, K.render_findings(result.findings)
    assert "Métricas" in result.matched_sections


def test_contract_loads_with_five_metric_types():
    spec = K.load_spec()
    assert len(spec["metric_types"]) == 5
    assert {m["id"] for m in spec["metric_types"]} == {
        "coverage", "quality", "trend", "performance", "cost"
    }


@pytest.mark.parametrize("heading", [
    "Métricas",
    "Métricas (métrica → tipo)",   # both variants appear in GPLO-1350 itself
    "MÉTRICAS",
    "Metricas",                     # no accent: a human typing in the Jira UI
    "2. Métricas",
    "**Métricas** (métrica → tipo)",
])
def test_heading_variants_all_normalise_together(heading):
    norm = K.load_spec()["normalization"]
    assert K.normalize_heading(heading, norm) == "metricas"


@pytest.mark.parametrize("declared", [
    "cobertura / compliance",
    "_cobertura / compliance_.",    # markdown emphasis + full stop, as written
    "compliance",
    "COBERTURA",
    "_rendimiento / eficiencia_ (no debe penalizar el flujo).",
])
def test_metric_type_variants_are_recognised(declared):
    spec = K.load_spec()
    body = f"- algo que se mide → {declared}"
    findings = K._check_metrics(
        body, spec, spec["normalization"], spec["content"], "Métricas"
    )
    assert not findings, [f.what for f in findings]


def test_arrow_ascii_is_accepted():
    spec = K.load_spec()
    findings = K._check_metrics(
        "- cobertura de tickets -> cobertura", spec,
        spec["normalization"], spec["content"], "Métricas",
    )
    assert not findings


# ---------------------------------------------------------------------------
# B — negative controls: the gate must FAIL
# ---------------------------------------------------------------------------


def test_missing_section_is_caught(conformant):
    truncated = conformant.split("## Métricas")[0]
    assert K.MISSING_SECTION in kinds(K.validate_description(truncated, FEATURE))


def test_metric_type_outside_closed_list_is_rejected(conformant):
    bad = conformant.replace("_tendencia_", "_número de cosas_")
    assert K.UNKNOWN_METRIC_TYPE in kinds(K.validate_description(bad, FEATURE))


def test_metric_without_a_type_is_rejected():
    """A bullet with no arrow is a malformed metric LINE, not a missing section.

    The distinction matters for the message: telling an author "no hay métricas"
    when they clearly wrote one sends them looking in the wrong place.
    """
    spec = K.load_spec()
    findings = K._check_metrics(
        "- menos bugs en producción", spec,
        spec["normalization"], spec["content"], "Métricas",
    )
    assert {f.kind for f in findings} == {K.BAD_METRIC_LINE}


def test_metrics_section_with_no_bullets_at_all_is_rejected():
    spec = K.load_spec()
    findings = K._check_metrics(
        "vamos a medirlo más adelante", spec,
        spec["normalization"], spec["content"], "Métricas",
    )
    assert {f.kind for f in findings} == {K.NO_METRICS}


def test_short_but_real_prose_is_not_treated_as_empty():
    """Guards the length backstop against its own false positives.

    `min_words_per_section` was 12 and rejected four legitimate tickets on its
    first run. Terse is not the same as empty, and a threshold tuned to catch
    padding would teach authors to pad.
    """
    body = (
        "## Contexto / Problema\nEl parser no cubre listas anidadas.\n"
        "## Alcance / Entregables\nAmpliar el walker de ADF.\n"
    )
    assert K.validate_description(body, "Subtask").ok


def _bug_with_regression_body(body: str) -> str:
    return (
        "## Contexto / Problema\nEl hook corrompe los acentos al leer stdin.\n"
        "## Repro\n1. Enviar el evento. 2. Leer el veredicto que devuelve.\n"
        "## Esperado vs Actual\nEsperado pasar limpio, actual quejarse de algo presente.\n"
        f"## Test de regresión\n{body}\n"
        "## Métricas\n- secciones mal reportadas como ausentes → calidad / exactitud\n"
    )


def test_a_bare_test_path_satisfies_the_regression_section():
    """The most precise possible answer must not be rejected for being short.

    `min_words_per_section` used to run BEFORE the structural check and `continue`
    on failure, so `tests/test_x.py` — exactly what the section asks for, and
    exactly one word — was refused as "prácticamente vacía". A section that
    satisfies its own contract is substantive however few words it took.
    """
    result = K.validate_description(
        _bug_with_regression_body("tests/test_hook_dispatcher_stdin_encoding.py"), "Bug"
    )
    assert result.ok, [f.what for f in result.findings]


def test_an_empty_regression_section_is_still_caught():
    """The negative control for the reordering above.

    Skipping the word count is only safe because each structural checker catches
    its own empty case. If that ever stops being true, this goes red rather than
    the gate going quiet.
    """
    result = K.validate_description(_bug_with_regression_body(""), "Bug")
    assert K.NO_TEST_REFERENCE in kinds(result)


def test_surviving_template_sentinel_is_rejected(conformant):
    assert K.SENTINEL_LEFT in kinds(
        K.validate_description("<<rellenar esto>>\n" + conformant, FEATURE)
    )


def test_multiline_sentinel_is_rejected(conformant):
    """The template's placeholders wrap across lines; a single-line pattern misses them."""
    sentinel = "<<qué está roto hoy\ny qué pasa si nadie lo arregla>>\n"
    assert K.SENTINEL_LEFT in kinds(
        K.validate_description(sentinel + conformant, FEATURE)
    )


@pytest.mark.parametrize("quoted", [
    '`{{ required "secrets.emailActionSecret is required" }}`',
    "`{{ca2c7060-e004-4e1b-9d52-106e0d2b2eff}}`",
    "```\n{{ helm templating }}\n```",
])
def test_jira_monospace_markup_is_not_a_sentinel(conformant, quoted):
    """Regression for the sentinel's first shape, which collided with Jira itself.

    `{{...}}` is Jira's inline-monospace markup. Measured across sixteen real
    tickets it produced 29 hits, all legitimate — file paths, shell commands,
    commit SHAs, a GUID, and Helm templating inside a ticket ABOUT Helm. A
    sentinel must not reuse a shape the host renderer already means something by,
    or the check fires hardest on the most carefully written tickets.
    """
    result = K.validate_description(quoted + "\n" + conformant, FEATURE)
    assert K.SENTINEL_LEFT not in kinds(result)


def test_template_placeholders_are_detected_as_sentinels():
    """The template must fail its own check — otherwise the sentinels are decorative."""
    template = (ROOT / "templates" / "jira-ticket.md.tmpl").read_text(encoding="utf-8")
    spec = K.load_spec()
    import re as _re
    assert _re.findall(spec["content"]["sentinel_pattern"], template)


@pytest.mark.parametrize("boilerplate", [
    "verificar que no funciona",
    "comprobar que falla",
    "revertir y ver que falla",
])
def test_boilerplate_negative_control_is_rejected(boilerplate):
    spec = K.load_spec()
    body = (
        "- **A — baseline**: el flujo completo pasa de punta a punta.\n"
        f"- **B — control negativo**: {boilerplate}\n"
        "- **C — regresión**: tests/test_jira_ticket_standard.py sigue verde.\n"
    )
    findings = K._check_abc(body, spec["content"], "Plan de prueba (A/B/C)")
    assert K.ABC_BOILERPLATE in {f.kind for f in findings}


def test_a_named_inverted_assertion_is_accepted():
    """The control that proves the boilerplate check is not just rejecting all Bs."""
    spec = K.load_spec()
    body = (
        "- **A — baseline**: un ticket completo se emite y `check` lo marca conforme.\n"
        "- **B — control negativo**: quito `## Métricas` del payload y el hook "
        "devuelve deny con `missing-section`.\n"
        "- **C — regresión**: tests/test_jira_ticket_standard.py sigue verde.\n"
    )
    assert not K._check_abc(body, spec["content"], "Plan de prueba (A/B/C)")


def test_missing_abc_case_is_caught():
    spec = K.load_spec()
    body = "- **A — baseline**: funciona.\n- **C — regresión**: tests/x.py\n"
    assert K.ABC_INCOMPLETE in {
        f.kind for f in K._check_abc(body, spec["content"], "Plan de prueba (A/B/C)")
    }


def test_regression_section_without_a_referent_is_rejected():
    spec = K.load_spec()
    findings = K._check_test_reference(
        "no romper nada", spec["content"], "Test de regresión"
    )
    assert {f.kind for f in findings} == {K.NO_TEST_REFERENCE}


@pytest.mark.parametrize("body", [
    "tests/test_jira_ticket_standard.py",
    "test_real_gplo_1350_is_conformant",
    "ninguno aún — el módulo se estrena en esta slice",
])
def test_regression_section_accepts_a_real_referent(body):
    spec = K.load_spec()
    assert not K._check_test_reference(body, spec["content"], "Test de regresión")


def test_unknown_issue_type_is_a_finding_not_a_pass(conformant):
    """A renamed issue type must not silently disable the gate for a whole class."""
    result = K.validate_description(conformant, "Historia Inventada")
    assert K.UNKNOWN_ISSUE_TYPE in kinds(result)


def test_header_stuffing_is_caught():
    stuffed = (
        "## Contexto / Problema\nTBD\n"
        "## Alcance / Entregables\nTBD\n"
        "## Plan de prueba (A/B/C)\nTBD\n"
        "## Métricas\nTBD\n"
    )
    assert K.EMPTY_SECTION in kinds(K.validate_description(stuffed, FEATURE))


# ---------------------------------------------------------------------------
# B — the hook and the sync gate
# ---------------------------------------------------------------------------


def test_hook_denies_a_non_conformant_mcp_create():
    """The whole point: a synthetic PreToolUse event, no live session needed."""
    module = _rule_module()
    verdict = module.pretooluse({
        "tool_name": "mcp__claude_ai_Atlassian__createJiraIssue",
        "tool_input": {"issueTypeName": "Bug", "description": "Se rompe algo."},
    })
    assert verdict is not None and verdict.blocked
    assert "Métricas" in verdict.message


def test_hook_allows_a_conformant_create(conformant):
    module = _rule_module()
    verdict = module.pretooluse({
        "tool_name": "mcp__claude_ai_Atlassian__createJiraIssue",
        "tool_input": {"issueTypeName": FEATURE, "description": conformant},
    })
    assert verdict is None


def test_hook_matches_any_mcp_server_alias():
    """The alias differs per client config; a literal tool name would go stale."""
    module = _rule_module()
    for tool in (
        "mcp__claude_ai_Atlassian__createJiraIssue",
        "mcp__atlassian__createJiraIssue",
        "mcp__whatever_alias__editJiraIssue",
    ):
        assert module._MCP_CREATE_RE.match(tool), tool
    for tool in ("Bash", "Edit", "mcp__claude_ai_Atlassian__getJiraIssue"):
        assert not module._MCP_CREATE_RE.match(tool), tool


def test_hook_ignores_unrelated_tools():
    module = _rule_module()
    assert module.pretooluse({"tool_name": "Bash", "tool_input": {"command": "ls"}}) is None


def test_hook_ignores_an_edit_that_does_not_touch_the_description():
    module = _rule_module()
    verdict = module.pretooluse({
        "tool_name": "mcp__claude_ai_Atlassian__editJiraIssue",
        "tool_input": {"fields": {"priority": {"name": "Low"}}},
    })
    assert verdict is None


def test_sync_gate_raises_typed_error_without_posting(monkeypatch):
    """Malformed must be distinguishable from a transport failure, and must not POST."""
    from scripts.issue_sync import JiraCreds, create_jira_issue

    def explode(*a, **kw):  # pragma: no cover - must never run
        raise AssertionError("POSTed a non-conformant description")

    monkeypatch.setattr("urllib.request.urlopen", explode)
    with pytest.raises(K.TicketStandardError) as excinfo:
        create_jira_issue(
            creds=JiraCreds(url="https://example.invalid", username="u", api_token="t"),
            project_key="GPLO", summary="s", description="texto suelto",
            issue_type="Bug", labels=["manual"],
        )
    assert excinfo.value.findings


# ---------------------------------------------------------------------------
# C — regression
# ---------------------------------------------------------------------------


def test_adf_heading_dialect_validates(conformant):
    adf = K.markdown_to_adf(conformant)
    result = K.validate_description(adf, FEATURE)
    assert result.ok, K.render_findings(result.findings)
    assert result.dialect == K.DIALECT_HEADINGS


def test_adf_legacy_literal_text_dialect_validates(conformant):
    """The shape issue_sync stored before this slice: one text node, no headings.

    Reading it must still work, or the ratchet would report every pre-existing
    sync-created ticket as unstructured.
    """
    legacy = {
        "type": "doc", "version": 1,
        "content": [{"type": "paragraph",
                     "content": [{"type": "text", "text": conformant}]}],
    }
    result = K.validate_description(legacy, FEATURE)
    assert result.ok, K.render_findings(result.findings)
    assert result.dialect == K.DIALECT_LITERAL


def test_markdown_to_adf_emits_real_heading_nodes(conformant):
    adf = K.markdown_to_adf(conformant)
    headings = [n for n in adf["content"] if n["type"] == "heading"]
    assert len(headings) == 5
    assert all(n["attrs"]["level"] == 2 for n in headings)


def test_adf_round_trip_preserves_sections(conformant):
    text, dialect = K.adf_to_markdownish(K.markdown_to_adf(conformant))
    norm = K.load_spec()["normalization"]
    assert dialect == K.DIALECT_HEADINGS
    assert "metricas" in K.split_sections(text, norm)


def test_null_description_does_not_crash():
    """Jira returns description: null for issues created without one."""
    result = K.validate_description(None, FEATURE)
    assert not result.ok
    assert K.MISSING_SECTION in kinds(result)


def test_subtask_carve_out_needs_no_test_plan():
    body = (
        "## Contexto / Problema\nEl parser no cubre el caso de listas anidadas.\n"
        "## Alcance / Entregables\nAmpliar el walker de ADF y su test unitario.\n"
    )
    assert K.validate_description(body, "Subtask").ok


def test_epic_carve_out_needs_no_test_plan():
    body = (
        "## Contexto / Problema\nLa gobernanza del playbook no tiene épica propia.\n"
        "## Alcance / Entregables\nAgrupar reglas, skills y ratchets de proceso.\n"
    )
    assert K.validate_description(body, "Epic").ok


def test_sync_tracker_stubs_are_exempt_by_label():
    result = K.validate_description(
        "Auto-created by ai-playbook issue_sync.", "Story",
        labels=["openspec", "ai-playbook-managed"],
    )
    assert result.ok
    assert result.exempt_reason


def test_exemption_requires_the_label_not_merely_a_short_body():
    result = K.validate_description("Auto-created by something else.", "Bug")
    assert not result.ok


def test_na_escape_hatch_is_per_section_and_counted():
    body = (
        "## Contexto / Problema\nEl validador no reporta uso del escape hatch.\n"
        "## Alcance / Entregables\nContar N/A por sección y publicarlo en check.\n"
        "## Plan de prueba (A/B/C)\nN/A — cambio de una línea cubierto por el test C.\n"
        "## Métricas\n- tasa de N/A por sección → tendencia\n"
    )
    result = K.validate_description(body, FEATURE)
    assert result.ok, K.render_findings(result.findings)
    assert "Plan de prueba (A/B/C)" in result.na_sections


def test_findings_render_as_one_message_not_one_at_a_time():
    """Fail-fast would cost an agent a round trip per missing section."""
    result = K.validate_description("nada", "Bug")
    message = K.render_findings(result.findings)
    assert len(result.findings) >= 4
    for finding in result.findings:
        assert finding.section in message or finding.what[:20] in message


def test_contract_validate_subcommand_passes():
    module = _rule_module()
    assert module.main(["validate"]) == 0
