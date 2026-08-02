"""Validate a Jira ticket description against `specs/jira-ticket-standard.yaml`.

ONE implementation, FOUR consumers: the PreToolUse hook in
`jira-ticket-standard.rule.py`, `create_jira_issue()` in `scripts/issue_sync.py`,
that rule's `check`/`explain` CLI, and the `/jira-ticket` skill. A closed list
that lives in two places is exactly the drift GPLO-1350 exists to stop, so the
list lives in the spec and the reading of it lives here.

WHY A FLATTENER AND NOT TWO VALIDATORS

Jira stores descriptions as ADF, not markdown, and this repo produces TWO
dialects of it:

  * `heading` nodes — what the Atlassian MCP tool writes, and what a human
    typing `##` in the Jira UI produces.
  * one giant `text` node — what `create_jira_issue()` wrote before this slice
    (issue_sync.py serialised the whole markdown body into a single paragraph),
    so `## Métricas` sits in Jira as literal characters, never as a heading.

Both are real and both are in the backlog today. Rather than two matchers that
drift apart, `adf_to_markdownish()` flattens either dialect back to markdown-ish
text and everything downstream parses that one shape. A ticket authored as
markdown (pre-POST, before Jira has seen it) skips the flattener and takes the
same path.

Rejected alternatives, so nobody re-litigates them: `renderedFields` returns
HTML, where the legacy dialect's literal `##` renders inside `<p>` and is
therefore indistinguishable from prose; REST v2 returns wiki markup, which is a
lossy translation of ADF and is on Atlassian's dead-end list.

PRESENCE OF A HEADING PROVES NOTHING

The failure mode this guards is header stuffing: every required heading present,
every body "TBD". A checker that counts headings rewards precisely that, so the
content checks (sentinels, metric-line shape, B-is-not-boilerplate, C-names-a-
referent) are the ones that actually bite.

Stdlib-only beyond pyyaml — this is imported on the hook hot path and inside
consumer checkouts that ship only the `.ai-playbook` submodule.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SPEC_RELATIVE = "specs/jira-ticket-standard.yaml"

# Kinds of finding. Kept as a closed vocabulary so `check` can aggregate by kind
# without string-matching prose.
MISSING_SECTION = "missing-section"
SENTINEL_LEFT = "sentinel-left"
EMPTY_SECTION = "empty-section"
BAD_METRIC_LINE = "bad-metric-line"
UNKNOWN_METRIC_TYPE = "unknown-metric-type"
NO_METRICS = "no-metrics"
ABC_INCOMPLETE = "abc-incomplete"
ABC_BOILERPLATE = "abc-boilerplate"
NO_TEST_REFERENCE = "no-test-reference"
UNKNOWN_ISSUE_TYPE = "unknown-issue-type"

# ADF dialects, reported separately by `check` because the split measures how
# much legacy the degenerate-ADF bug left behind.
DIALECT_HEADINGS = "adf-headings"
DIALECT_LITERAL = "adf-literal-text"
DIALECT_MARKDOWN = "markdown"


class ConfigError(Exception):
    """The contract could not be read — exit 2, never exit 1.

    Same distinction `_rule_kit.ConfigError` draws: exit 1 means "this ticket has
    findings", exit 2 means "the question could not be asked". Collapsing them
    lets a broken spec read as a clean backlog.
    """


class TicketStandardError(Exception):
    """A description failed the standard. Carries the findings, not just a string.

    Deliberately distinct from transport failures. `create_jira_issue()` used to
    return `(None, reason)` for everything, which made "this ticket is malformed"
    indistinguishable from "Jira timed out" — the caller logged both and carried
    on. A caller can now tell the difference without parsing English.
    """

    def __init__(self, findings: list[Finding]):
        self.findings = findings
        super().__init__(render_findings(findings))


@dataclass(frozen=True)
class Finding:
    kind: str
    section: str           # canonical heading, or "" when not section-scoped
    what: str              # what is wrong
    fix: str               # how to fix it, paste-ready where possible


@dataclass
class Result:
    findings: list[Finding] = field(default_factory=list)
    dialect: str = DIALECT_MARKDOWN
    # Sections answered with `N/A — reason`. Counted, not punished: a high rate
    # means the template does not fit the work, which is information about the
    # template.
    na_sections: list[str] = field(default_factory=list)
    matched_sections: list[str] = field(default_factory=list)
    exempt_reason: str | None = None

    @property
    def ok(self) -> bool:
        return not self.findings


# ---------------------------------------------------------------------------
# Spec loading
# ---------------------------------------------------------------------------

_SPEC_CACHE: dict[str, Any] = {}


def playbook_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_spec(path: Path | None = None) -> dict[str, Any]:
    """Read and lightly validate the standard. Cached — the hook re-imports often."""
    spec_path = path or (playbook_root() / SPEC_RELATIVE)
    key = str(spec_path)
    if key in _SPEC_CACHE:
        return _SPEC_CACHE[key]
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment failure
        raise ConfigError(
            "pyyaml is required to read the ticket standard; it is the one "
            "dependency the rule kit allows."
        ) from exc
    if not spec_path.exists():
        raise ConfigError(f"ticket standard not found at {spec_path}")
    try:
        raw = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ConfigError(f"{spec_path} is not parseable YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{spec_path} must be a mapping")
    for required in ("metric_types", "sections", "issue_types", "content", "normalization"):
        if required not in raw:
            raise ConfigError(f"{spec_path} is missing required key {required!r}")
    _SPEC_CACHE[key] = raw
    return raw


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_NUM_PREFIX_RE = re.compile(r"^\s*\d+\s*[.)]\s*")
_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")
# Markdown emphasis, stripped before comparison. Authors bold and italicise
# inside headings and inside metric types, and `_cobertura / compliance_` is the
# same type as `cobertura / compliance`. Measured: all four metric lines of
# GPLO-1350 — the ticket that asked for this standard — were rejected by an
# earlier version of this normaliser for exactly this reason.
_EMPHASIS_RE = re.compile(r"[*_`~]+")
_TRAILING_PUNCT = " \t.,;:·-—– "


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )


def normalize_heading(text: str, norm: dict[str, Any]) -> str:
    """Apply the spec's normalisation. Applied to BOTH sides of a comparison.

    Exact matching is the wrong default and this project proves it: GPLO-1350,
    the ticket that asked for the standard, writes both `## Métricas` and
    `## Métricas (métrica → tipo)`. A matcher that accepts one of those measures
    its own brittleness and reports it as non-compliance.
    """
    out = unicodedata.normalize("NFC", text).strip()
    out = _EMPHASIS_RE.sub("", out)
    if norm.get("strip_numeric_prefix", True):
        out = _NUM_PREFIX_RE.sub("", out)
    # Loop, because the real shape is `_tipo_ (aclaración).` — the parenthetical
    # only becomes trailing once the period is gone, and a second parenthetical
    # can hide behind the first. Bounded to keep a pathological heading cheap.
    if norm.get("strip_trailing_parenthetical", True):
        for _ in range(4):
            stripped = _TRAILING_PAREN_RE.sub("", out.rstrip(_TRAILING_PUNCT))
            if stripped == out:
                break
            out = stripped
    out = out.strip(_TRAILING_PUNCT)
    if norm.get("casefold", True):
        out = out.casefold()
    if norm.get("strip_accents", True):
        out = _strip_accents(out)
    return re.sub(r"\s+", " ", out).strip(_TRAILING_PUNCT)


# ---------------------------------------------------------------------------
# ADF → markdown-ish
# ---------------------------------------------------------------------------


def _node_text(node: Any) -> str:
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return str(node.get("text", ""))
    if node.get("type") == "hardBreak":
        return "\n"
    return "".join(_node_text(c) for c in node.get("content", []) or [])


def adf_to_markdownish(doc: Any) -> tuple[str, str]:
    """Flatten either ADF dialect to markdown-ish text. Returns (text, dialect).

    `heading` nodes become `##`/`###` lines. Everything else contributes its text
    verbatim — which is what recovers the legacy dialect, where the entire body
    (including literal `## Métricas`) sits inside one paragraph.
    """
    if doc is None:
        return "", DIALECT_LITERAL
    if isinstance(doc, str):
        return doc, DIALECT_MARKDOWN

    lines: list[str] = []
    saw_heading = False

    def walk(node: Any, list_depth: int = 0) -> None:
        nonlocal saw_heading
        if not isinstance(node, dict):
            return
        ntype = node.get("type")
        if ntype == "heading":
            saw_heading = True
            level = int((node.get("attrs") or {}).get("level", 2))
            lines.append("")
            lines.append(f"{'#' * max(1, min(level, 6))} {_node_text(node).strip()}")
            return
        if ntype in ("paragraph", "codeBlock", "blockquote"):
            lines.append(_node_text(node))
            return
        if ntype in ("listItem", "taskItem"):
            body = _node_text(node).strip()
            if body:
                lines.append(f"{'  ' * max(0, list_depth - 1)}- {body}")
            return
        if ntype in ("bulletList", "orderedList", "taskList"):
            for child in node.get("content", []) or []:
                walk(child, list_depth + 1)
            return
        for child in node.get("content", []) or []:
            walk(child, list_depth)

    walk(doc)
    text = "\n".join(lines)
    return text, (DIALECT_HEADINGS if saw_heading else DIALECT_LITERAL)


def markdown_to_adf(text: str) -> dict[str, Any]:
    """Turn a markdown body into ADF with REAL heading nodes.

    The inverse of `adf_to_markdownish`, and it lives next to it so the pair can
    be round-tripped in one test.

    This exists because `create_jira_issue()` used to post the entire body as a
    single `text` node inside one `paragraph`. Everything still "worked" — Jira
    accepted it, the issue appeared — but `## Métricas` was stored as five
    literal characters, so the ticket had no structure for any reader, human or
    machine, and the validator reading storage would have judged every
    sync-created ticket unstructured while the pre-POST gate judged the markdown
    conformant. Two gates disagreeing about the same ticket is worse than
    neither.

    Deliberately minimal: headings, bullets, paragraphs. Inline emphasis is left
    as literal text because ADF marks buy nothing here — the standard is about
    structure, and a bold word that stays bold-in-source renders as source, which
    is honest and reversible.
    """
    content: list[dict[str, Any]] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            body = "\n".join(para).strip()
            if body:
                content.append({
                    "type": "paragraph",
                    "content": [{"type": "text", "text": body}],
                })
            para.clear()

    bullets: list[dict[str, Any]] = []

    def flush_bullets() -> None:
        if bullets:
            content.append({"type": "bulletList", "content": list(bullets)})
            bullets.clear()

    for line in (text or "").splitlines():
        m = _HEADING_RE.match(line)
        if m:
            flush()
            flush_bullets()
            content.append({
                "type": "heading",
                "attrs": {"level": min(len(m.group(1)), 6)},
                "content": [{"type": "text", "text": m.group(2).strip()}],
            })
            continue
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            flush()
            bullets.append({
                "type": "listItem",
                "content": [{
                    "type": "paragraph",
                    "content": [{"type": "text", "text": stripped[2:].strip()}],
                }],
            })
            continue
        if not stripped:
            flush()
            flush_bullets()
            continue
        para.append(line)

    flush()
    flush_bullets()
    if not content:
        content = [{"type": "paragraph", "content": []}]
    return {"type": "doc", "version": 1, "content": content}


# ---------------------------------------------------------------------------
# Section splitting
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def split_sections(text: str, norm: dict[str, Any]) -> dict[str, str]:
    """Map normalised heading → body. Headings outside the allowed levels are prose."""
    levels = set(norm.get("heading_levels") or [2, 3])
    out: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) in levels:
            if current is not None:
                out[current] = "\n".join(buf).strip()
            current = normalize_heading(m.group(2), norm)
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        out[current] = "\n".join(buf).strip()
    return out


def _section_keys(section: dict[str, Any], norm: dict[str, Any]) -> list[str]:
    names = [section.get("canonical", "")] + list(section.get("aliases") or [])
    return [normalize_heading(n, norm) for n in names if n]


# ---------------------------------------------------------------------------
# Content checks
# ---------------------------------------------------------------------------


def _metric_types_index(spec: dict[str, Any], norm: dict[str, Any]) -> dict[str, str]:
    index: dict[str, str] = {}
    for mt in spec["metric_types"]:
        for name in [mt.get("canonical", "")] + list(mt.get("aliases") or []):
            if name:
                index[normalize_heading(name, norm)] = mt["id"]
    return index


_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def strip_code(text: str) -> str:
    """Remove fenced blocks and inline code before scanning for placeholders.

    Measured on the first live run: four of sixteen tickets were flagged for a
    surviving `<<...>>` sentinel, and every one was a false positive — Helm
    templating (`{{ required "secrets.emailActionSecret is required" }}`) quoted
    inside backticks, and a GUID. Quoted code is CONTENT; a ticket that explains
    a templating bug necessarily contains template syntax.

    A checker that cannot tell "the author left the form blank" from "the author
    is quoting the thing they are reporting" punishes precisely the well-written
    ticket, which is the fastest way to get a standard ignored.
    """
    return _INLINE_CODE_RE.sub(" ", _FENCE_RE.sub(" ", text))


def _is_na(body: str, content: dict[str, Any]) -> bool:
    return bool(re.search(content["na_pattern"], body, re.IGNORECASE | re.MULTILINE))


def _check_metrics(body: str, spec: dict[str, Any], norm: dict[str, Any],
                   content: dict[str, Any], canonical: str) -> list[Finding]:
    findings: list[Finding] = []
    index = _metric_types_index(spec, norm)
    line_re = re.compile(content["metric_line_pattern"])
    parsed = 0
    for raw in body.splitlines():
        line = raw.strip()
        if not line or not line.startswith(("-", "*")):
            continue
        m = line_re.match(line.replace("->", "→"))
        if not m:
            findings.append(Finding(
                BAD_METRIC_LINE, canonical,
                f"esta línea no dice de qué TIPO es la métrica: {line!r}",
                "usa el formato `- <qué mides> → <tipo>`, con el tipo de la lista cerrada.",
            ))
            continue
        parsed += 1
        declared = normalize_heading(m.group("type"), norm)
        if declared not in index:
            allowed = ", ".join(mt["canonical"] for mt in spec["metric_types"])
            findings.append(Finding(
                UNKNOWN_METRIC_TYPE, canonical,
                f"`{m.group('type').strip()}` no es un tipo de métrica válido.",
                f"usa uno de los cinco: {allowed}.",
            ))
    if parsed == 0 and not findings:
        findings.append(Finding(
            NO_METRICS, canonical,
            "no hay ninguna métrica con su tipo.",
            "añade al menos una línea `- <qué mides> → <tipo>`.",
        ))
    return findings


def _check_abc(body: str, content: dict[str, Any], canonical: str) -> list[Finding]:
    findings: list[Finding] = []
    bodies: dict[str, str] = {}
    for label in content["abc_labels"]:
        m = re.search(
            rf"(?im)^\s*[-*]?\s*\**\s*{re.escape(label)}\s*[—:.–-]\s*(.+?)\s*$",
            body,
        )
        if not m:
            findings.append(Finding(
                ABC_INCOMPLETE, canonical,
                f"falta el caso {label} del plan de prueba.",
                f"añade una línea `- **{label} — ...**: <qué prueba y cómo sabrás que pasó>`.",
            ))
        else:
            bodies[label] = m.group(1)

    b = bodies.get("B", "")
    if b:
        flat = normalize_heading(b, {"casefold": True, "strip_accents": True})
        for banned in content.get("abc_negative_control_banned") or []:
            if normalize_heading(banned, {"casefold": True, "strip_accents": True}) in flat:
                findings.append(Finding(
                    ABC_BOILERPLATE, canonical,
                    f"el control negativo es boilerplate: {b.strip()!r}",
                    "di QUÉ aserción concreta se invierte y qué error esperas. "
                    "«falla cuando debe» no es un control negativo, es una intención.",
                ))
                break
    return findings


def _check_test_reference(body: str, content: dict[str, Any], canonical: str) -> list[Finding]:
    if re.search(content["test_reference_pattern"], body, re.IGNORECASE):
        return []
    return [Finding(
        NO_TEST_REFERENCE, canonical,
        "no señala ningún test concreto.",
        "nombra una ruta o id de test existente, o escribe "
        "`ninguno aún — <por qué>`. Un campo que exige un referente del repo "
        "no se puede rellenar con boilerplate.",
    )]


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------


def is_exempt(labels: list[str] | tuple[str, ...] | None, spec: dict[str, Any]) -> str | None:
    """Return the exemption reason, or None. Exemptions are BY LABEL, never ad hoc."""
    have = {str(x) for x in (labels or [])}
    for rule in spec.get("exempt") or []:
        needed = set(rule.get("labels") or [])
        if needed and needed <= have:
            return str(rule.get("reason", "exempt"))
    return None


def validate_description(
    description: Any,
    issue_type: str,
    *,
    labels: list[str] | tuple[str, ...] | None = None,
    spec: dict[str, Any] | None = None,
) -> Result:
    """Check one description. `description` may be markdown text or an ADF dict."""
    spec = spec or load_spec()
    norm = spec["normalization"]
    content = spec["content"]
    result = Result()

    reason = is_exempt(labels, spec)
    if reason:
        result.exempt_reason = reason
        return result

    wanted = spec["issue_types"].get(issue_type)
    if wanted is None:
        # Unknown type is a CONFIG finding, not a ticket finding: the standard
        # cannot judge what it does not cover, and silently passing would let a
        # renamed issue type disable the gate for a whole class of work.
        result.findings.append(Finding(
            UNKNOWN_ISSUE_TYPE, "",
            f"el tipo de issue {issue_type!r} no está en el estándar.",
            f"añádelo a {SPEC_RELATIVE} con las secciones que le corresponden, "
            "o corrige el nombre del tipo.",
        ))
        return result

    text, dialect = adf_to_markdownish(description)
    result.dialect = dialect
    found = split_sections(text, norm)

    if content.get("sentinel_pattern"):
        for hit in set(re.findall(content["sentinel_pattern"], strip_code(text))):
            result.findings.append(Finding(
                SENTINEL_LEFT, "",
                f"queda un placeholder de la plantilla sin rellenar: {hit}",
                "sustitúyelo por contenido real. El placeholder enseña con el "
                "ejemplo Y es contrato: dejarlo puesto es un fallo, no un relleno.",
            ))

    min_words = int(content.get("min_words_per_section", 0))

    for key in wanted["sections"]:
        section = spec["sections"][key]
        canonical = section["canonical"]
        body = None
        for candidate in _section_keys(section, norm):
            if candidate in found:
                body = found[candidate]
                break
        if body is None:
            result.findings.append(Finding(
                MISSING_SECTION, canonical,
                f"falta la sección `## {canonical}`.",
                f"{section.get('prompt', '')} Copia el esqueleto de "
                "templates/jira-ticket.md.tmpl.",
            ))
            continue

        result.matched_sections.append(canonical)

        if _is_na(body, content):
            result.na_sections.append(canonical)
            continue

        if len(body.split()) < min_words:
            result.findings.append(Finding(
                EMPTY_SECTION, canonical,
                f"la sección `## {canonical}` está prácticamente vacía.",
                f"{section.get('prompt', '')} Si de verdad no aplica, escribe "
                "`N/A — <razón>`; queda registrado y se cuenta.",
            ))
            continue

        requires = section.get("requires")
        if requires == "metric_lines":
            result.findings.extend(_check_metrics(body, spec, norm, content, canonical))
        elif requires == "abc":
            result.findings.extend(_check_abc(body, content, canonical))
        elif requires == "test_reference":
            result.findings.extend(_check_test_reference(body, content, canonical))

    return result


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

EXAMPLE_URL = "https://geeplo.atlassian.net/browse/GPLO-1350"


def render_findings(findings: list[Finding]) -> str:
    """One message carrying EVERY problem, in Spanish.

    Never fail-fast on the first finding. Making an author fix one thing, resubmit,
    and discover the next is punishment dressed as validation — and with an agent
    on the other end it burns a round-trip per missing section.
    """
    if not findings:
        return ""
    lines = [
        f"El ticket no cumple el estándar de GPLO ({len(findings)} problema(s)).",
        "",
    ]
    for i, f in enumerate(findings, 1):
        where = f" [{f.section}]" if f.section else ""
        lines.append(f"{i}.{where} {f.what}")
        lines.append(f"   → {f.fix}")
    lines += [
        "",
        f"Plantilla: templates/jira-ticket.md.tmpl · Ejemplo real: {EXAMPLE_URL}",
        "Contrato: specs/jira-ticket-standard.yaml",
    ]
    return "\n".join(lines)
