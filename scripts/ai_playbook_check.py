"""ai-playbook-check — cross-cutting advisory orchestrator (v0.20.0, PR-B).

Reads every `docs/rules/<slug>.rule.md` via `hook_dispatcher.load_rules()`,
invokes each paired `.rule.py validate` against the consumer repo, and reports
a unified drift summary. Optionally offers opt-in remediation via the
`.rule.py apply` subcommand (when the rule implements it).

This is the **L4 advisor** layer — it never blocks, never mutates without user
opt-in, and reuses every existing L1/L2/L3 invariant. The contract for the
`.rule.py apply` extension is documented in
`docs/concepts/enforcement-layers.md` §"Rule .rule.py contract".

CLI:

    python scripts/ai_playbook_check.py [TARGET] [flags]

Default TARGET is the consumer root discovered by walking up from cwd until
a `.gitmodules` file mentioning `.ai-playbook` is found. Pass an explicit
path to target a different consumer.

Flags:
    --check                 Report only; never offer to apply.
    --json                  Machine-readable output (skill / CI consumption).
    --yes                   Auto-approve all remediations (per-rule fences
                            inside `apply` still fire — type-path prompts etc.).
    --select SLUGS          Comma-separated allow-list of slugs to consider.
    --skip SLUGS            Comma-separated deny-list to subtract from the set.
    --upgrade-only          Skip rule validation; check submodule pin freshness only.
    --exit-on-drift         Exit 1 instead of 0 when drift is detected
                            (opt-in for consumer CI). Default exit is always 0.

Exit codes:
    0   default; or user completed flow (incl. declining to apply).
    1   only under --exit-on-drift: drift detected.
    2   orchestrator internal error (rule loader crashed, etc.).
    3   usage error.

Environment:
    PLAYBOOK_PROJECT_ROOT   Equivalent to TARGET positional argument.
    PLAYBOOK_NO_PROMPT      If "1", fail with exit 3 when interactive prompt
                            would be needed. CI-safe.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# Status literals — keep in sync with the JSON output schema.
STATUS_OK = "ok"
STATUS_DRIFT = "drift"
STATUS_NOT_APPLICABLE = "not_applicable"
STATUS_MANUAL_ONLY = "manual_fix_only"
STATUS_ERROR = "error"


@dataclass
class RuleResult:
    slug: str
    status: str
    detail: str = ""
    apply_available: bool = False
    runbook: str | None = None  # for manual_fix_only rules
    stderr_excerpt: str = ""


@dataclass
class CheckReport:
    target: Path
    playbook_root: Path
    rules: list[RuleResult] = field(default_factory=list)
    pinned_tag: str | None = None
    latest_tag: str | None = None
    upgrade_available: bool = False

    def actionable_rules(self) -> list[RuleResult]:
        return [r for r in self.rules if r.status == STATUS_DRIFT and r.apply_available]

    def manual_only(self) -> list[RuleResult]:
        return [r for r in self.rules if r.status == STATUS_MANUAL_ONLY]

    def has_drift(self) -> bool:
        return any(r.status == STATUS_DRIFT for r in self.rules)


# --- Consumer-root discovery ---------------------------------------------------

def discover_consumer_root(start: Path) -> Path | None:
    """Walk up from `start` until a `.gitmodules` referencing `.ai-playbook` is found.

    Returns the directory containing that `.gitmodules`, or None if not found.
    Also accepts a path that IS the playbook itself (start == REPO_ROOT) for
    dogfooding — in that case the playbook IS the target.
    """
    cur = start.resolve()
    for p in [cur, *cur.parents]:
        gm = p / ".gitmodules"
        if gm.is_file():
            try:
                if ".ai-playbook" in gm.read_text(encoding="utf-8", errors="replace"):
                    return p
            except OSError:
                continue
    # Dogfood case: running inside the playbook itself, no consumer above us.
    if (start / "AGENTS.md").is_file() and (start / "docs" / "rules").is_dir():
        return start
    return None


# --- Rule introspection --------------------------------------------------------

def _rule_supports_apply(hardrule_path: Path, python_exe: str = sys.executable) -> bool:
    """Detect whether a `.rule.py` exposes the `apply` subcommand.

    Strategy: invoke `<rule.py> apply --dry-run`. If argparse rejects with exit
    code 2 AND stderr contains "invalid choice", the rule is validate-only.
    Any other outcome (including a successful dry-run, or a runtime failure)
    indicates `apply` is at least declared in the choices list.
    """
    try:
        proc = subprocess.run(
            [python_exe, str(hardrule_path), "apply", "--dry-run"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    stderr = (proc.stderr or "").lower()
    return not (proc.returncode == 2 and "invalid choice" in stderr)


def _invoke_validate(
    hardrule_path: Path,
    target: Path,
    python_exe: str = sys.executable,
) -> tuple[int, str, str]:
    """Run `<rule.py> validate` from inside `target`. Returns (rc, stdout, stderr)."""
    try:
        proc = subprocess.run(
            [python_exe, str(hardrule_path), "validate"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(target),
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"timeout after 30s: {exc}"
    except OSError as exc:
        return 2, "", f"OSError: {exc}"
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _invoke_apply(
    hardrule_path: Path,
    target: Path,
    *,
    dry_run: bool,
    python_exe: str = sys.executable,
) -> int:
    """Run `<rule.py> apply [--dry-run]` from inside `target`. Stream output live."""
    cmd = [python_exe, str(hardrule_path), "apply"]
    if dry_run:
        cmd.append("--dry-run")
    try:
        return subprocess.call(cmd, cwd=str(target))
    except OSError as exc:
        print(f"error: invoking {hardrule_path.name}: {exc}", file=sys.stderr)
        return 2


# --- Submodule freshness -------------------------------------------------------

def _submodule_pin(consumer_root: Path) -> str | None:
    submodule = consumer_root / ".ai-playbook"
    if not submodule.is_dir():
        return None
    try:
        out = subprocess.check_output(
            ["git", "-C", str(submodule), "describe", "--tags", "--exact-match"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        ).strip()
        return out or None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None


def _latest_remote_tag(playbook_root: Path) -> str | None:
    try:
        subprocess.check_call(
            ["git", "-C", str(playbook_root), "fetch", "--tags", "--quiet"],
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        pass  # best-effort
    try:
        out = subprocess.check_output(
            ["git", "-C", str(playbook_root), "tag", "--list", "v*", "--sort=-v:refname"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        ).strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    for line in out.splitlines():
        line = line.strip()
        if line:
            return line
    return None


def _version_tuple(tag: str) -> tuple[int, ...] | None:
    if not tag.startswith("v"):
        return None
    try:
        return tuple(int(part) for part in tag[1:].split("."))
    except ValueError:
        return None


# --- Core: run the checks ------------------------------------------------------

def run_checks(
    target: Path,
    playbook_root: Path,
    *,
    select: set[str] | None = None,
    skip: set[str] | None = None,
    skip_validation: bool = False,
) -> CheckReport:
    """Load rules and run validate against target. Returns CheckReport."""
    # Import lazily to keep `--help` fast and avoid yaml import at top level.
    sys.path.insert(0, str(playbook_root))
    try:
        from scripts.hook_dispatcher import load_rules  # type: ignore
    finally:
        sys.path.pop(0)

    rules = load_rules(playbook_root)
    report = CheckReport(target=target, playbook_root=playbook_root)

    if not skip_validation:
        for rule in rules:
            slug = rule.slug
            if select and slug not in select:
                continue
            if skip and slug in skip:
                continue
            if rule.hardrule_path is None:
                # Advisory-only rule — manual-fix only (no .rule.py to run).
                report.rules.append(RuleResult(
                    slug=slug,
                    status=STATUS_MANUAL_ONLY,
                    detail="advisory-only (no paired_hardrule)",
                    runbook=str(rule.doc_path.relative_to(playbook_root)),
                ))
                continue
            if not rule.hardrule_path.is_file():
                report.rules.append(RuleResult(
                    slug=slug,
                    status=STATUS_ERROR,
                    detail=f"paired_hardrule not found: {rule.hardrule_path}",
                ))
                continue
            rc, _stdout, stderr = _invoke_validate(rule.hardrule_path, target)
            apply_avail = _rule_supports_apply(rule.hardrule_path)
            if rc == 0:
                report.rules.append(RuleResult(slug=slug, status=STATUS_OK, apply_available=apply_avail))
            elif rc == 1:
                report.rules.append(RuleResult(
                    slug=slug,
                    status=STATUS_DRIFT,
                    detail="invariant violation",
                    apply_available=apply_avail,
                    stderr_excerpt=_truncate(stderr, 240),
                ))
            elif rc == 2:
                # Schema break / not-applicable for this target.
                report.rules.append(RuleResult(
                    slug=slug,
                    status=STATUS_NOT_APPLICABLE,
                    detail="rule reported schema break (not applicable here)",
                    apply_available=apply_avail,
                    stderr_excerpt=_truncate(stderr, 240),
                ))
            else:
                report.rules.append(RuleResult(
                    slug=slug,
                    status=STATUS_ERROR,
                    detail=f"unexpected exit code {rc}",
                    apply_available=apply_avail,
                    stderr_excerpt=_truncate(stderr, 240),
                ))

    # Submodule freshness — informational, always attempted.
    report.pinned_tag = _submodule_pin(target)
    report.latest_tag = _latest_remote_tag(playbook_root)
    pinned = _version_tuple(report.pinned_tag) if report.pinned_tag else None
    latest = _version_tuple(report.latest_tag) if report.latest_tag else None
    if pinned and latest and latest > pinned:
        report.upgrade_available = True

    return report


def _truncate(s: str, n: int) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    return s[: n - 3].rstrip() + "..."


# --- Rendering -----------------------------------------------------------------

def render_text(report: CheckReport) -> str:
    lines: list[str] = []
    sep = "═" * 65
    lines.append(sep)
    lines.append("  ai-playbook-check")
    lines.append(f"  target:   {report.target}")
    pin = report.pinned_tag or "<unknown>"
    lines.append(f"  playbook: {report.playbook_root}  •  pinned: {pin}")
    lines.append(sep)
    if not report.rules:
        lines.append("  (no rules evaluated — empty selection or --upgrade-only)")
    else:
        ok = sum(1 for r in report.rules if r.status == STATUS_OK)
        drift = sum(1 for r in report.rules if r.status == STATUS_DRIFT)
        manual = sum(1 for r in report.rules if r.status == STATUS_MANUAL_ONLY)
        na = sum(1 for r in report.rules if r.status == STATUS_NOT_APPLICABLE)
        err = sum(1 for r in report.rules if r.status == STATUS_ERROR)
        lines.append(f"  {len(report.rules)} rules: ok={ok} drift={drift} manual-only={manual} n/a={na} error={err}")
        lines.append("-" * 65)
        for r in sorted(report.rules, key=lambda x: (_status_order(x.status), x.slug)):
            icon = _status_icon(r.status)
            tag = " [auto-apply available]" if (r.status == STATUS_DRIFT and r.apply_available) else ""
            if r.status == STATUS_MANUAL_ONLY:
                tag = " [manual fix only]"
            lines.append(f"  {icon} {r.slug:<32} {r.detail}{tag}")
    if report.upgrade_available:
        lines.append("")
        lines.append(f"  ℹ playbook upgrade available: {report.pinned_tag} → {report.latest_tag}")
    return "\n".join(lines) + "\n"


def render_json(report: CheckReport) -> str:
    payload: dict[str, Any] = {
        "target": str(report.target),
        "playbook_root": str(report.playbook_root),
        "pinned_tag": report.pinned_tag,
        "latest_tag": report.latest_tag,
        "upgrade_available": report.upgrade_available,
        "rules": [
            {
                "slug": r.slug,
                "status": r.status,
                "detail": r.detail,
                "apply_available": r.apply_available,
                "runbook": r.runbook,
                "stderr_excerpt": r.stderr_excerpt,
            }
            for r in report.rules
        ],
    }
    return json.dumps(payload, indent=2)


_STATUS_ORDER = {
    STATUS_DRIFT: 0,
    STATUS_ERROR: 1,
    STATUS_MANUAL_ONLY: 2,
    STATUS_NOT_APPLICABLE: 3,
    STATUS_OK: 4,
}


def _status_order(status: str) -> int:
    return _STATUS_ORDER.get(status, 99)


def _status_icon(status: str) -> str:
    return {
        STATUS_OK: "ok ",
        STATUS_DRIFT: "!! ",
        STATUS_MANUAL_ONLY: "ⓘ ",
        STATUS_NOT_APPLICABLE: "-- ",
        STATUS_ERROR: "✗  ",
    }.get(status, "?  ")


# --- Interactive apply ---------------------------------------------------------

def interactive_apply(report: CheckReport, *, auto_yes: bool = False) -> int:
    """Prompt the user (or auto-yes) to select which rules to remediate.

    Returns the count of rules whose `apply` was invoked. Each rule's exit
    code is printed; the orchestrator's return is the number of attempts.
    """
    candidates = report.actionable_rules()
    if not candidates:
        return 0

    if auto_yes:
        selected = candidates
    else:
        if os.environ.get("PLAYBOOK_NO_PROMPT") == "1":
            print("error: drift requires apply but PLAYBOOK_NO_PROMPT=1", file=sys.stderr)
            return 0
        print("\nDrift detected with auto-apply available:")
        for i, r in enumerate(candidates, 1):
            print(f"  [{i}] {r.slug:<32} {r.detail}")
        print()
        print("Enter comma-separated numbers, 'all', or empty to skip:")
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not raw:
            return 0
        if raw.lower() == "all":
            selected = candidates
        else:
            indices: list[int] = []
            for chunk in raw.split(","):
                chunk = chunk.strip()
                if chunk.isdigit():
                    n = int(chunk)
                    if 1 <= n <= len(candidates):
                        indices.append(n - 1)
            selected = [candidates[i] for i in indices]

    if not selected:
        return 0

    # Load rules once for hardrule_path lookup.
    sys.path.insert(0, str(report.playbook_root))
    try:
        from scripts.hook_dispatcher import load_rules  # type: ignore
    finally:
        sys.path.pop(0)
    rules_by_slug = {r.slug: r for r in load_rules(report.playbook_root)}

    invoked = 0
    for r in selected:
        rule = rules_by_slug.get(r.slug)
        if rule is None or rule.hardrule_path is None:
            continue
        print(f"\n--- apply {r.slug} ---")
        rc = _invoke_apply(rule.hardrule_path, report.target, dry_run=False)
        print(f"--- {r.slug}: exit {rc} ---")
        invoked += 1
    return invoked


# --- Argparse + entrypoint -----------------------------------------------------

def _parse_csv(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {s.strip() for s in value.split(",") if s.strip()}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ai-playbook-check",
        description="Advisory orchestrator across all playbook rules (L4).",
    )
    p.add_argument("target", nargs="?", help="Consumer root (default: discovered from cwd).")
    p.add_argument("--check", action="store_true", help="Report only; do not offer to apply.")
    p.add_argument("--json", action="store_true", help="Machine-readable output.")
    p.add_argument("--yes", action="store_true", help="Auto-approve all auto-apply remediations.")
    p.add_argument("--select", help="Comma-separated slug allow-list.")
    p.add_argument("--skip", help="Comma-separated slug deny-list.")
    p.add_argument("--upgrade-only", action="store_true", help="Skip rule validation; check pin only.")
    p.add_argument(
        "--exit-on-drift",
        action="store_true",
        help="Exit 1 instead of 0 when drift detected (opt-in for CI).",
    )
    p.add_argument("--playbook-root", default=str(REPO_ROOT), help=argparse.SUPPRESS)
    return p


def main(argv: list[str] | None = None) -> int:
    # Ensure UTF-8 output on Windows terminals (cp1252 default can't encode
    # the box-drawing + status icons we emit). Best-effort: older Pythons
    # without reconfigure() lose the icons but never crash on the encode.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
            except (AttributeError, OSError):
                pass

    parser = build_parser()
    args = parser.parse_args(argv)

    target_arg = args.target or os.environ.get("PLAYBOOK_PROJECT_ROOT")
    target_path = Path(target_arg).resolve() if target_arg else Path.cwd()
    consumer_root = discover_consumer_root(target_path)
    if consumer_root is None:
        print(
            f"error: no consumer root with .ai-playbook submodule found from {target_path}",
            file=sys.stderr,
        )
        return 3

    playbook_root = Path(args.playbook_root).resolve()
    if not (playbook_root / "docs" / "rules").is_dir():
        print(f"error: --playbook-root {playbook_root} does not contain docs/rules/", file=sys.stderr)
        return 3

    try:
        report = run_checks(
            target=consumer_root,
            playbook_root=playbook_root,
            select=_parse_csv(args.select),
            skip=_parse_csv(args.skip),
            skip_validation=args.upgrade_only,
        )
    except Exception as exc:  # noqa: BLE001 — orchestrator-internal failure
        print(f"error: orchestrator failure: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(render_json(report))
    else:
        print(render_text(report), end="")

    if not args.check and not args.upgrade_only and not args.json:
        interactive_apply(report, auto_yes=args.yes)

    if args.exit_on_drift and report.has_drift():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
