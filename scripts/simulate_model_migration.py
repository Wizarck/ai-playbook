"""Dry-run model-migration playbook walker.

Picks a pinned model (via env var `MODEL_MIGRATION_REQUESTED=<from>:<to>` OR
the first entry in `configs/anthropic-retirement-list.yaml` within the
horizon), generates the migration PR diff against the synthetic substitute,
runs `verify_llm_routing.py` if available against the proposed substitute,
prints the result.

NO git commit. NO PR open. Exit 0 = simulation OK. Exit 1 = a precondition
failed (no trigger, missing successor). Exit 2 = setup error.

CLI
---
    # Take from env var:
    MODEL_MIGRATION_REQUESTED=claude-haiku-4-5:claude-haiku-5-0 \\
        python -m scripts.simulate_model_migration

    # Or from anthropic-retirement-list.yaml (first qualifying entry):
    python -m scripts.simulate_model_migration

    # Emit a PR-body draft:
    python -m scripts.simulate_model_migration --emit-pr-body

    # JSON output:
    python -m scripts.simulate_model_migration --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    yaml = None

# Force UTF-8 stdio.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


@dataclass
class MigrationPlan:
    from_model: str
    to_model: str
    source: str  # "env" | "retirement-list"
    retirement_date: str  # ISO; "n/a" when source == "env"
    deprecation_url: str  # "" when not available
    notes: list[str]


@dataclass
class SimulationResult:
    plan: MigrationPlan
    verifier_present: bool
    verifier_findings_count: int
    pr_body: str
    started_at: str
    ok: bool


def _playbook_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _read_retirement_list(path: Path, *, now: datetime) -> dict[str, Any] | None:
    if yaml is None or not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    retirements = data.get("retirements") or []
    if not isinstance(retirements, list):
        return None
    today = now.date()
    qualifying: list[dict[str, Any]] = []
    for entry in retirements:
        if not isinstance(entry, dict):
            continue
        retire_raw = entry.get("retirement_date")
        if not retire_raw:
            continue
        try:
            from datetime import date
            if isinstance(retire_raw, str):
                retire = date.fromisoformat(retire_raw)
            elif isinstance(retire_raw, date):
                retire = retire_raw
            else:
                continue
        except ValueError:
            continue
        days_remaining = (retire - today).days
        if days_remaining > 90:
            continue
        qualifying.append({**entry, "_days_remaining": days_remaining})
    if not qualifying:
        return None
    qualifying.sort(key=lambda x: x["_days_remaining"])
    return qualifying[0]


def derive_plan(
    *,
    env_var: str | None,
    retirement_yaml: Path,
    now: datetime,
) -> MigrationPlan | None:
    """Return a MigrationPlan from env var (preferred) or retirement YAML.

    Env var format: `MODEL_MIGRATION_REQUESTED=<from>:<to>`. Returns None if
    neither source produces a valid plan.
    """
    if env_var:
        if ":" not in env_var:
            return None
        from_model, to_model = env_var.split(":", 1)
        from_model, to_model = from_model.strip(), to_model.strip()
        if not from_model or not to_model:
            return None
        return MigrationPlan(
            from_model=from_model,
            to_model=to_model,
            source="env",
            retirement_date="n/a",
            deprecation_url="",
            notes=[
                "Source: MODEL_MIGRATION_REQUESTED env var (manual override).",
                f"From: {from_model} -> To: {to_model}",
            ],
        )
    entry = _read_retirement_list(retirement_yaml, now=now)
    if entry is None:
        return None
    successor = entry.get("successor", "")
    if not successor:
        return None
    return MigrationPlan(
        from_model=str(entry.get("model_id", "")),
        to_model=str(successor),
        source="retirement-list",
        retirement_date=str(entry.get("retirement_date", "")),
        deprecation_url=str(entry.get("deprecation_url", "")),
        notes=[
            f"Source: configs/anthropic-retirement-list.yaml ({retirement_yaml.name}).",
            f"Days remaining: {entry.get('_days_remaining')}",
            f"Provider: {entry.get('provider', '')}",
        ],
    )


def _try_run_verifier(root: Path) -> tuple[bool, int]:
    """Run verify_llm_routing.scan if importable. Return (present, findings_count)."""
    verifier = root / "scripts" / "verify_llm_routing.py"
    if not verifier.is_file():
        return False, 0
    sys.path.insert(0, str(root / "scripts"))
    try:
        import verify_llm_routing  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 — defensive: simulator should never crash on optional verifier
        return False, 0
    finally:
        try:
            sys.path.remove(str(root / "scripts"))
        except ValueError:
            pass
    try:
        findings = verify_llm_routing.scan(root)
    except Exception:  # noqa: BLE001
        return True, -1
    return True, len(findings)


def _render_pr_body(
    plan: MigrationPlan, *, verifier_present: bool, findings_count: int, root: Path,
) -> str:
    horizon_note = (
        f"Retirement date: {plan.retirement_date}." if plan.retirement_date != "n/a"
        else "Manual override (no provider deprecation announcement)."
    )
    findings_section = (
        f"`verify_llm_routing.py` reports **{findings_count}** direct-SDK call sites "
        f"to migrate alongside the model swap."
        if verifier_present and findings_count >= 0
        else "`verify_llm_routing.py` not available — fall back to manual regex sweep."
    )
    url = plan.deprecation_url or "n/a"
    return (
        f"# Model migration: `{plan.from_model}` → `{plan.to_model}`\n\n"
        f"## Trigger\n\n"
        f"- Source: `{plan.source}`.\n"
        f"- {horizon_note}\n"
        f"- Deprecation notice: {url}\n\n"
        f"## Substitution reasoning\n\n"
        f"Per [model-routing.md](../docs/concepts/model-routing.md) §1, `{plan.from_model}` "
        f"and `{plan.to_model}` belong to the same task-class tier. Substitute is a "
        f"drop-in within the routing matrix; revisit if CI canary (§5) fails the "
        f"hard-block thresholds.\n\n"
        f"## Call sites\n\n"
        f"{findings_section}\n\n"
        f"## CI canary plan\n\n"
        f"- Cost ≤ 2× baseline (hard block on >).\n"
        f"- p95 latency ≤ 1.5× baseline (hard block on >).\n"
        f"- Trace structure within ±1 span (soft warn on ±2).\n\n"
        f"## Rollback\n\n"
        f"Revert this PR; deprecated model still works during deprecation window. "
        f"If unavailable post-retirement, the only path is forward — see "
        f"[docs/concepts/model-migration.md](../docs/concepts/model-migration.md) §5.\n\n"
        f"## Provenance\n\n"
        f"Generated by `scripts/simulate_model_migration.py` at "
        f"{datetime.now(UTC).isoformat(timespec='seconds')}.\n"
    )


def simulate(
    *,
    env_var: str | None = None,
    retirement_yaml: Path | None = None,
    root: Path | None = None,
    now: datetime | None = None,
) -> SimulationResult | None:
    root = root or _playbook_root()
    now = now or datetime.now(UTC)
    retirement_yaml = retirement_yaml or (
        root / "configs" / "anthropic-retirement-list.yaml"
    )

    plan = derive_plan(env_var=env_var, retirement_yaml=retirement_yaml, now=now)
    if plan is None:
        return None

    verifier_present, findings_count = _try_run_verifier(root)
    pr_body = _render_pr_body(
        plan, verifier_present=verifier_present, findings_count=findings_count, root=root,
    )

    return SimulationResult(
        plan=plan,
        verifier_present=verifier_present,
        verifier_findings_count=findings_count,
        pr_body=pr_body,
        started_at=now.isoformat(timespec="seconds"),
        ok=True,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simulate_model_migration",
        description="Dry-run a model migration end-to-end (no PR, no commit).",
    )
    parser.add_argument(
        "--retirement-yaml",
        type=Path,
        default=None,
        help="Path to anthropic-retirement-list.yaml (default: <playbook>/configs/...).",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Override playbook root (testing).",
    )
    parser.add_argument(
        "--env-var",
        default=None,
        help=(
            "Inline value for MODEL_MIGRATION_REQUESTED (overrides the env var). "
            "Format: <from>:<to>."
        ),
    )
    parser.add_argument(
        "--emit-pr-body",
        action="store_true",
        help="Print only the rendered PR body to stdout.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="Override 'now' as ISO datetime (testing).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    env_var = args.env_var if args.env_var else os.environ.get("MODEL_MIGRATION_REQUESTED")
    now = (
        datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now
        else datetime.now(UTC)
    )
    result = simulate(
        env_var=env_var,
        retirement_yaml=args.retirement_yaml,
        root=args.root,
        now=now,
    )
    if result is None:
        msg = (
            "❌ simulate_model_migration — no trigger.\n"
            "   FIX: set MODEL_MIGRATION_REQUESTED=<from>:<to> "
            "OR add a retirement entry within 90 days to "
            "configs/anthropic-retirement-list.yaml.\n"
            "   OVERRIDE: pass --env-var <from>:<to>."
        )
        print(msg, file=sys.stderr)
        return 1

    if args.emit_pr_body:
        print(result.pr_body)
        return 0

    if args.json:
        payload = {
            "plan": asdict(result.plan),
            "verifier_present": result.verifier_present,
            "verifier_findings_count": result.verifier_findings_count,
            "pr_body": result.pr_body,
            "started_at": result.started_at,
            "ok": result.ok,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"✅ simulate_model_migration — {result.plan.from_model} → "
          f"{result.plan.to_model}")
    print(f"   source: {result.plan.source}")
    print(f"   retirement_date: {result.plan.retirement_date}")
    print(f"   deprecation_url: {result.plan.deprecation_url or '—'}")
    print(f"   verify_llm_routing.py: "
          f"{'present' if result.verifier_present else 'absent (fallback regex sweep)'}")
    if result.verifier_present:
        print(f"   call sites detected: {result.verifier_findings_count}")
    for note in result.plan.notes:
        print(f"   - {note}")
    print("\n   PR body draft (use --emit-pr-body to print only the body):")
    print("\n".join(f"     {line}" for line in result.pr_body.splitlines()[:6]))
    print("     ...")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
