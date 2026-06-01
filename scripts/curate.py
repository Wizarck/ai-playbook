"""``curate`` — LLM-assisted, human-gated, ONE-SHOT consolidation of dispatcher prose.

This is the deliberate counterpart to ``reconcile`` (= ``apply_config``):

* ``reconcile`` is the deterministic door — no LLM, idempotent, runs in the loop.
* ``curate`` is OUTSIDE the loop. It moves legacy free prose out of dispatcher
  ``.md`` files (CLAUDE.md/GEMINI.md/AGENTS.md/.cursor) into leaf docs or the
  canonical AGENTS.md, leaving thin pointers — so the dispatchers stay
  pointer-shaped (principle #2). It is LLM-assisted, **human-gated** (``--yes``),
  one-shot, and NEVER importable from ``apply`` (it must not run inside a
  reconcile / dry-run).

Pipeline (all-or-nothing):

    detect (structural drift)  → announce
      → guardrail (secrets_scan + prompt_injection_filter on the prose; ABORT on
        any finding — tainted content never reaches the LLM)
      → LLM proposes a curate-plan/v1 of MOVES (verbatim excerpts only)
      → validate structurally (_curate_validate: no fabrication, no traversal)
      → snapshot BASE (pre-curate) → perform the moves → leave pointers.

The LLM never writes to disk; it only returns a plan. Idempotency is structural
(D3): once prose is in a leaf doc (exempt), a re-run detects no drift and is a
no-op.

CLI::

    python -m scripts.curate [--target PATH] [--dry-run] [--yes] [--json]

Exit codes::
    0  no drift (nothing to curate) OR dry-run preview OR apply succeeded
    1  validation failed / plan rejected
    2  guardrail tripped (secret / injection) OR environment/LLM error / no consent
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts import _curate_validate  # noqa: E402
from scripts._backup_helper import backup_base  # noqa: E402
from scripts._dispatcher_shape import (  # noqa: E402
    CANONICAL_DISPATCHER,
    collect_drift,
    is_dispatcher_file,
)

# Files curate scans for drift (existing dispatcher .md in the consumer root).
_CANDIDATE_FILES = (
    "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursorrules",
)
_LLM_TASK_CLASS = "doc_writing_edit"


@dataclass
class CurateResult:
    ok: bool
    rc: int
    detail: str
    moves_applied: int = 0
    changes: list[str] | None = None


# ---------------------------------------------------------------------------
# Filesystem helpers (kept tiny; curate is a CLI, not a library)
# ---------------------------------------------------------------------------


def _read_dispatchers(consumer_root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in _CANDIDATE_FILES:
        p = consumer_root / rel
        if p.is_file():
            try:
                out[rel] = p.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
            except OSError:
                continue
    # Also pick up .cursor/rules/*.mdc.
    cursor_rules = consumer_root / ".cursor" / "rules"
    if cursor_rules.is_dir():
        for p in sorted(cursor_rules.glob("*.mdc")):
            rel = p.relative_to(consumer_root).as_posix()
            try:
                out[rel] = p.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
            except OSError:
                continue
    return {rel: text for rel, text in out.items() if is_dispatcher_file(rel)}


def _guardrail(text: str) -> list[str]:
    """Return a list of guardrail findings (empty ⇒ safe to send to the LLM)."""
    findings: list[str] = []
    try:
        from scripts.secrets_scan import scan as _secrets_scan

        for m in _secrets_scan(text):
            findings.append(f"secret: {getattr(m, 'kind', 'unknown')}")
    except Exception as exc:  # noqa: BLE001 — a broken scanner must fail SAFE (treat as finding)
        findings.append(f"secrets_scan unavailable ({exc}) — refusing to send content")
    try:
        from scripts.prompt_injection_filter import filter_text as _inj_filter

        verdict = _inj_filter(text)
        if getattr(verdict, "verdict", "safe") == "injection":
            findings.append(f"prompt-injection: {getattr(verdict, 'reason', 'flagged')}")
    except Exception:  # noqa: BLE001 — injection filter is best-effort; absence is not a finding
        pass
    return findings


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".curate-tmp")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# LLM plan request (mockable — tests monkeypatch this; never hits a real proxy)
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = (
    "You consolidate AI-agent dispatcher files. Dispatcher .md files "
    "(AGENTS.md/CLAUDE.md/GEMINI.md/.cursor) must stay pointer-shaped: any "
    "section over ~10 lines belongs in a leaf doc under docs/ with a thin "
    "pointer left behind, or absorbed into the canonical AGENTS.md. Return ONLY "
    "a JSON object matching curate-plan/v1: {\"schema\":\"curate-plan/v1\","
    "\"moves\":[{\"source_rel_path\",\"source_excerpt\",\"dest_rel_path\","
    "\"pointer\"}]}. source_excerpt MUST be copied VERBATIM from the source "
    "(byte-for-byte); never paraphrase, summarise, or invent content. pointer "
    "is one short markdown link to dest_rel_path. dest_rel_path is a docs/ leaf "
    f"or {CANONICAL_DISPATCHER}. No prose outside the JSON."
)


def request_plan(drift_files: dict[str, str]) -> dict:
    """Ask the LLM for a curate-plan. Isolated so tests monkeypatch it.

    Raises ``RuntimeError`` if the proxy is unreachable or returns non-JSON.
    """
    from scripts import _llm

    payload_files = {rel: text for rel, text in drift_files.items()}
    prompt = (
        "Consolidate the loose prose in these dispatcher files. Files (JSON):\n\n"
        + json.dumps(payload_files, ensure_ascii=False)
    )
    resp = _llm.call(
        _LLM_TASK_CLASS, prompt, system=_SYSTEM_PROMPT,
        max_tokens=4000, application="curate",
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(resp.text)
    except (json.JSONDecodeError, AttributeError) as exc:
        raise RuntimeError(f"LLM did not return valid JSON: {exc}") from exc


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def _apply_moves(
    consumer_root: Path, moves: list[_curate_validate.CurateMove],
) -> list[str]:
    """Snapshot BASE, then perform each validated move. All-or-nothing is the
    caller's contract (the plan was validated as a whole); here we execute the
    moves sequentially, accumulating edits per file in memory then writing once."""
    changes: list[str] = []

    # Snapshot BASE for every file the plan touches (idempotent: once only).
    touched = {m.source_rel_path for m in moves} | {m.dest_rel_path for m in moves}
    for rel in sorted(touched):
        p = consumer_root / rel
        if p.is_file():
            backup_base(consumer_root, p)

    # Accumulate edits in memory keyed by rel_path so multiple moves compose.
    src_text: dict[str, str] = {}
    dest_append: dict[str, list[str]] = {}
    for m in moves:
        sp = consumer_root / m.source_rel_path
        if m.source_rel_path not in src_text:
            src_text[m.source_rel_path] = sp.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
        excerpt = m.source_excerpt.replace("\r\n", "\n").replace("\r", "\n")
        if excerpt not in src_text[m.source_rel_path]:
            # Should not happen (validated), but never silently lose content.
            raise RuntimeError(f"excerpt no longer found in {m.source_rel_path}; aborting")
        src_text[m.source_rel_path] = src_text[m.source_rel_path].replace(
            excerpt, m.pointer.strip() + "\n", 1,
        )
        dest_append.setdefault(m.dest_rel_path, []).append(excerpt.strip())

    # Write sources (pointers spliced in).
    for rel, text in src_text.items():
        _atomic_write(consumer_root / rel, text)
        changes.append(f"✓ {rel}: prose relocated, pointer left")

    # Append to destinations (create leaf docs as needed).
    for rel, chunks in dest_append.items():
        dest = consumer_root / rel
        existing = ""
        if dest.is_file():
            existing = dest.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
            if existing and not existing.endswith("\n"):
                existing += "\n"
        body = existing + "\n".join(c + "\n" for c in chunks)
        _atomic_write(dest, body)
        verb = "appended to" if existing else "created"
        changes.append(f"✓ {rel}: {verb} ({len(chunks)} chunk(s))")

    return changes


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def curate(
    consumer_root: Path,
    *,
    dry_run: bool = False,
    consent: bool = False,
    plan_provider=request_plan,
) -> CurateResult:
    """Run the curate pipeline. ``plan_provider`` is injected for testing."""
    sources = _read_dispatchers(consumer_root)
    drift = collect_drift(sources)
    if not drift:
        return CurateResult(ok=True, rc=0, detail="no dispatcher drift — nothing to curate")

    n_chunks = sum(len(d.chunks) for d in drift)
    summary = f"{n_chunks} loose-prose chunk(s) across {len(drift)} file(s): " + ", ".join(
        d.rel_path for d in drift
    )

    # Guardrail: never send tainted prose to the LLM.
    drift_files = {d.rel_path: sources[d.rel_path] for d in drift}
    findings: list[str] = []
    for text in drift_files.values():
        findings.extend(_guardrail(text))
    if findings:
        return CurateResult(
            ok=False, rc=2,
            detail="guardrail tripped — refusing to curate:\n  - " + "\n  - ".join(sorted(set(findings))),
        )

    if not dry_run and not consent:
        return CurateResult(
            ok=False, rc=2,
            detail=f"{summary}\nRe-run with --dry-run to preview the plan, or --yes to apply.",
        )

    # Ask the LLM for a move-plan, then validate it structurally.
    try:
        plan = plan_provider(drift_files)
    except Exception as exc:  # noqa: BLE001 — surface LLM/proxy errors as rc=2
        return CurateResult(ok=False, rc=2, detail=f"LLM plan request failed: {exc}")

    validation = _curate_validate.validate_plan(plan, drift_files)
    if not validation.ok:
        return CurateResult(
            ok=False, rc=1,
            detail="curate plan rejected:\n  - " + "\n  - ".join(validation.errors),
        )

    if dry_run:
        lines = [f"DRY-RUN curate plan ({len(validation.moves)} move(s)):"]
        for m in validation.moves:
            lines.append(f"  {m.source_rel_path} → {m.dest_rel_path}  (pointer: {m.pointer.strip()})")
        return CurateResult(ok=True, rc=0, detail="\n".join(lines), moves_applied=0)

    # Consent given + plan valid → snapshot BASE and perform the moves.
    try:
        changes = _apply_moves(consumer_root, validation.moves)
    except Exception as exc:  # noqa: BLE001
        return CurateResult(ok=False, rc=1, detail=f"apply failed: {exc}")
    return CurateResult(
        ok=True, rc=0,
        detail=f"curated {len(validation.moves)} move(s)",
        moves_applied=len(validation.moves), changes=changes,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="curate",
        description="LLM-assisted, human-gated one-shot consolidation of dispatcher prose.",
    )
    parser.add_argument("--target", type=Path, default=None, help="Consumer root (default: cwd).")
    parser.add_argument("--dry-run", action="store_true", help="Preview the plan; write nothing.")
    parser.add_argument("--yes", action="store_true", help="Consent to apply the moves.")
    parser.add_argument("--json", action="store_true", help="Emit a JSON result.")
    args = parser.parse_args(argv)

    target = (args.target or Path.cwd()).expanduser().resolve()
    if not target.is_dir():
        print(f"❌ target {target} is not a directory", file=sys.stderr)
        return 2

    result = curate(target, dry_run=args.dry_run, consent=args.yes)
    if args.json:
        print(json.dumps({
            "ok": result.ok, "rc": result.rc, "detail": result.detail,
            "moves_applied": result.moves_applied, "changes": result.changes or [],
        }, ensure_ascii=False, indent=2))
    else:
        print(result.detail)
        for c in result.changes or []:
            print(c)
    return result.rc


if __name__ == "__main__":
    from scripts.rules._telemetry import script_emit

    sys.exit(script_emit("curate", main))
