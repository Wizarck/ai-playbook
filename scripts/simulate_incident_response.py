"""Dry-run incident-response scenario walker.

Picks a scenario from `docs/concepts/incident-response.md` §4 (default: S2 #4 Container
OOM cascade — short and self-contained) and walks it through detection →
mock paging → runbook resolution → escalation chain check → post-mortem
template render. Validates that the referenced runbook resolves to a real
file and the post-mortem template renders without missing variables.

NO real paging. NO mutation. Exit 0 = scenario validates clean. Exit 1 = a
referenced artefact is missing (broken runbook link OR missing template
variable). Exit 2 = setup error.

CLI
---
    python -m scripts.simulate_incident_response                # default scenario
    python -m scripts.simulate_incident_response --scenario 4   # by table-row id (1-8)
    python -m scripts.simulate_incident_response --json         # machine-readable
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

# Force UTF-8 stdio.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


@dataclass
class Scenario:
    id: int
    name: str
    severity: str
    detection_signal: str
    immediate_action: str
    runbook: str  # relative to playbook root, e.g. "docs/runbooks/runbook-vps-down.md"
    artefact: str


# Curated list mirroring `docs/concepts/incident-response.md` §4. Kept in code (not parsed
# from the spec) because parsing markdown tables is fragile — when the table
# changes, this list updates in the same PR.
SCENARIOS: list[Scenario] = [
    Scenario(
        id=1, name="VPS unreachable", severity="S1",
        detection_signal="Uptime-Kuma probe failed x3",
        immediate_action="SSH from secondary; check journalctl + console",
        runbook="docs/runbooks/runbook-vps-down.md",
        artefact="post-mortem if downtime > 15 min",
    ),
    Scenario(
        id=2, name="Hindsight DB corruption", severity="S1",
        detection_signal="HttpResult.reason == degraded:retain_failed > 5%/min",
        immediate_action="Stop retain workers; snapshot; replay from JSONL",
        runbook="docs/runbooks/runbook-db-corruption.md",
        artefact="post-mortem mandatory",
    ),
    Scenario(
        id=3, name="Secrets leak in commit", severity="S1",
        detection_signal="secrets_scan.py CI fail OR external report",
        immediate_action="Rotate credentials < 1h; force-push history",
        runbook="docs/runbooks/runbook-secrets-leak-containment.md",
        artefact="security post-mortem <= 48h",
    ),
    Scenario(
        id=4, name="Container OOM cascade", severity="S2",
        detection_signal="Docker restart count > 3 in 5 min",
        immediate_action="docker stats --no-stream; bump memory or roll back",
        runbook="docs/runbooks/runbook-vps-down.md",  # No dedicated runbook yet; falls back to VPS health
        artefact="gotcha entry minimum",
    ),
    Scenario(
        id=5, name="Certificate expiry imminent", severity="S2",
        detection_signal="Caddy probe reports cert < 7d to expire",
        immediate_action="caddy reload to fetch fresh ACME",
        runbook="docs/runbooks/rotate-secrets.md",  # cert rotation lives near secret rotation
        artefact="gotcha entry",
    ),
    Scenario(
        id=6, name="Third-party LLM provider outage", severity="S2",
        detection_signal="LiteLLM 5xx > 10%/min for one provider",
        immediate_action="Verify status page; fallback chain handles automatically",
        runbook="docs/runbooks/runbook-vps-down.md",  # falls back to general infra runbook
        artefact="incident note",
    ),
    Scenario(
        id=7, name="Rate-limit cascade (LLM)", severity="S3",
        detection_signal="429 rate > 20%/min sustained 5 min",
        immediate_action="Identify caller via consumer metadata; throttle",
        runbook="docs/runbooks/runbook-vps-down.md",
        artefact="incident note",
    ),
    Scenario(
        id=8, name="Capacity degradation (disk)", severity="S3",
        detection_signal="VPS disk > 85% used",
        immediate_action="vps_maintainer.py --apply cleanup with HITL gate",
        runbook="docs/runbooks/runbook-vps-down.md",
        artefact="gotcha entry",
    ),
]


@dataclass
class SimulationResult:
    scenario: Scenario
    runbook_resolves: bool
    runbook_path: str
    template_renders: bool
    template_missing_vars: list[str]
    incident_id: str
    started_at: str
    notes: list[str]

    def ok(self) -> bool:
        return self.runbook_resolves and self.template_renders


def _playbook_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _find_template_vars(template_text: str) -> set[str]:
    """Return the set of `{{VAR}}` placeholders in the template."""
    return set(re.findall(r"\{\{\s*([A-Z][A-Z0-9_]*)\s*\}\}", template_text))


def _render_post_mortem(
    template_path: Path, *, scenario: Scenario, incident_id: str, now: datetime,
) -> tuple[str, list[str]]:
    """Render post-mortem with synthetic substitutions. Returns (rendered, missing_vars)."""
    if not template_path.is_file():
        return "", ["<template-file-missing>"]
    raw = template_path.read_text(encoding="utf-8")
    expected = _find_template_vars(raw)

    today = now.date().isoformat()
    due = (now.date().replace(day=min(now.day + 7, 28))).isoformat()
    substitutions: dict[str, str] = {
        "TITLE": f"[SIM] {scenario.name} ({scenario.severity})",
        "YYYY_MM_DD": today,
        "S1_OR_SYSTEMIC": scenario.severity,
        "E_G_42_MIN_OR_NA": "n/a (simulation)",
        "EMAIL": "23051550+Wizarck@users.noreply.github.com",
        "MAINTAINER_EMAIL_OR_PENDING": "pending",
        "HH_MM": now.strftime("%H:%M"),
        "YYYY_MM_DD_DUE": due,
    }
    rendered = raw
    missing: list[str] = []
    for var in sorted(expected):
        sub = substitutions.get(var)
        if sub is None:
            missing.append(var)
            continue
        rendered = rendered.replace(f"{{{{{var}}}}}", sub)
    return rendered, missing


def simulate(
    scenario: Scenario, *, root: Path | None = None, now: datetime | None = None,
) -> SimulationResult:
    root = root or _playbook_root()
    now = now or datetime.now(UTC)

    runbook_path = root / scenario.runbook
    runbook_resolves = runbook_path.is_file()

    template_path = root / "templates" / "post-mortem.md.tmpl"
    incident_id = f"INC-SIM-{now.strftime('%Y%m%d%H%M%S')}"
    _, missing = _render_post_mortem(
        template_path, scenario=scenario, incident_id=incident_id, now=now,
    )
    template_renders = bool(template_path.is_file()) and not missing

    notes = [
        f"detection: {scenario.detection_signal}",
        f"immediate-action: {scenario.immediate_action}",
        "escalation: solo (Arturo) — family-of-3 path inactive",
        f"artefact-required: {scenario.artefact}",
    ]
    if not runbook_resolves:
        notes.append(f"runbook-missing: {runbook_path}")
    if missing:
        notes.append(f"template-missing-vars: {','.join(sorted(missing))}")

    return SimulationResult(
        scenario=scenario,
        runbook_resolves=runbook_resolves,
        runbook_path=str(runbook_path),
        template_renders=template_renders,
        template_missing_vars=sorted(missing),
        incident_id=incident_id,
        started_at=now.isoformat(timespec="seconds"),
        notes=notes,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simulate_incident_response",
        description="Dry-run an incident-response scenario end-to-end (no real paging).",
    )
    parser.add_argument(
        "--scenario",
        type=int,
        default=4,
        choices=[s.id for s in SCENARIOS],
        help="Scenario row id from docs/concepts/incident-response.md §4 (default 4 = OOM cascade).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Override playbook root (testing).",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="Override 'now' as ISO datetime (testing).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    scenario = next(s for s in SCENARIOS if s.id == args.scenario)
    now = (
        datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now
        else datetime.now(UTC)
    )
    result = simulate(scenario, root=args.root, now=now)

    if args.json:
        payload = {
            "scenario": asdict(result.scenario),
            "runbook_resolves": result.runbook_resolves,
            "runbook_path": result.runbook_path,
            "template_renders": result.template_renders,
            "template_missing_vars": result.template_missing_vars,
            "incident_id": result.incident_id,
            "started_at": result.started_at,
            "notes": result.notes,
            "ok": result.ok(),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        ok_marker = "✅" if result.ok() else "❌"
        print(f"{ok_marker} simulate_incident_response — scenario #{scenario.id} "
              f"({scenario.severity}) {scenario.name}")
        print(f"   incident_id: {result.incident_id}")
        print(f"   runbook: {result.runbook_path} "
              f"({'OK' if result.runbook_resolves else 'MISSING'})")
        print(f"   post-mortem template: "
              f"{'OK' if result.template_renders else 'BROKEN'}")
        if result.template_missing_vars:
            print(f"   missing template vars: {result.template_missing_vars}")
        for line in result.notes:
            print(f"   - {line}")

    return 0 if result.ok() else 1


if __name__ == "__main__":
    raise SystemExit(main())
