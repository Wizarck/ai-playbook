"""Prerequisite + context-budget + env-var + registry health checks.

Populated in T14a. Emits an OTel-friendly report so it can run both interactively
(pretty output, stderr) and headless (JSON mode, stdout).

Checks (each emits a :class:`CheckResult`):

- ``python``              — ``sys.version_info >= (3, 11)``.
- ``git``                 — ``shutil.which("git")``.
- ``gh``                  — ``shutil.which("gh")`` (warn if missing; optional).
- ``npx``                 — ``shutil.which("npx")``/``npx.cmd`` (warn if missing).
- ``pre-commit``          — ``shutil.which("pre-commit")`` (warn if missing).
- ``pyyaml``              — import-check; fail if missing (hard dep).
- ``jsonschema``          — import-check; fail if missing (hard dep).
- ``sops``                — ``shutil.which("sops")`` (warn if missing).
- ``gitleaks``            — ``shutil.which("gitleaks")`` (warn if missing).
- ``playbook-submodule``  — confirm ``<cwd>/.ai-playbook/`` has ``specs/`` + ``scripts/``.
- ``projects-registry``   — parse ``~/.ai-playbook/projects.yaml``.
- ``env-vars-required``   — parse ``docs/concepts/env-vars.md`` for ``Required? | yes`` rows.
- ``env-vars-alias-warning`` — warn when only the ``ANTHROPIC_CACHE_TOKENS_MIN``
  alias is set without the canonical ``AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN``.
- ``context-budget``      — sum of ``specs/*.md`` bytes; warn if >100KB.

CLI
---
    python -m scripts.doctor [--json] [--strict] [--install-deps]

``--install-deps`` editable-installs the playbook (``pip install -e <root>``,
with an ``ensurepip`` fallback) so the hard deps (pyyaml, jsonschema, …) resolve,
then runs the checks. Self-heal for the common "venv lacks jsonschema" failure.

Exit codes
----------
    0  all green or only warnings (non-strict)
    1  any ``fail`` (or any ``warn`` when ``--strict``)
    2  setup error (cannot read cwd, etc.)

The report shape is stable — JSON mode emits an array of CheckResult objects
(``{name, status, detail}``) so downstream tooling (T07c OTel span emission,
T19 dashboards) can ingest without re-parsing pretty output.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

# Force UTF-8 stdio — Windows default cp1252 cannot encode the ✅/⚠️/❌ sigils.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"

CONTEXT_BUDGET_BYTES = 100 * 1024  # 100 KB cumulative across specs/*.md

# Playbook root — discovered by walking up from this file until we see ``specs/``.
def _discover_playbook_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        if (parent / "specs").is_dir() and (parent / "scripts").is_dir():
            return parent
    return here.parent.parent


PLAYBOOK_ROOT = _discover_playbook_root()


@dataclass
class CheckResult:
    """One doctor check outcome. Stable shape for OTel + JSON consumers."""

    name: str
    status: str  # "ok" | "warn" | "fail"
    detail: str


# ---------------------------------------------------------------------------
# Individual checks — each returns exactly one CheckResult.
# ---------------------------------------------------------------------------


def check_python() -> CheckResult:
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 11):
        return CheckResult("python", STATUS_OK, f"Python {major}.{minor} (>= 3.11)")
    return CheckResult(
        "python",
        STATUS_FAIL,
        f"Python {major}.{minor} < 3.11 — playbook requires 3.11+",
    )


def _which(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def check_git() -> CheckResult:
    path = _which("git")
    if path:
        return CheckResult("git", STATUS_OK, f"git found at {path}")
    return CheckResult(
        "git",
        STATUS_FAIL,
        "git not on PATH — install from https://git-scm.com/",
    )


def check_gh() -> CheckResult:
    path = _which("gh")
    if path:
        return CheckResult("gh", STATUS_OK, f"gh found at {path}")
    return CheckResult(
        "gh",
        STATUS_WARN,
        "gh (GitHub CLI) not on PATH — optional, used by OpenSpec/PR flows.",
    )


def check_npx() -> CheckResult:
    path = _which("npx", "npx.cmd")
    if path:
        return CheckResult("npx", STATUS_OK, f"npx found at {path}")
    return CheckResult(
        "npx",
        STATUS_WARN,
        "npx not on PATH — required by scripts/openspec_validate.py.",
    )


def check_precommit() -> CheckResult:
    path = _which("pre-commit")
    if path:
        return CheckResult("pre-commit", STATUS_OK, f"pre-commit found at {path}")
    return CheckResult(
        "pre-commit",
        STATUS_WARN,
        "pre-commit not on PATH — install with `pip install pre-commit`.",
    )


def _import_check(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def check_pyyaml() -> CheckResult:
    if _import_check("yaml"):
        return CheckResult("pyyaml", STATUS_OK, "pyyaml importable")
    return CheckResult(
        "pyyaml",
        STATUS_FAIL,
        "PyYAML not importable — install with `pip install pyyaml`.",
    )


def check_jsonschema() -> CheckResult:
    if _import_check("jsonschema"):
        return CheckResult("jsonschema", STATUS_OK, "jsonschema importable")
    return CheckResult(
        "jsonschema",
        STATUS_FAIL,
        "jsonschema not importable — install with `pip install jsonschema`.",
    )


def check_sops() -> CheckResult:
    path = _which("sops")
    if path:
        return CheckResult("sops", STATUS_OK, f"sops found at {path}")
    return CheckResult(
        "sops",
        STATUS_WARN,
        "sops not on PATH — required by session-start hook for secrets decrypt.",
    )


def check_gitleaks() -> CheckResult:
    path = _which("gitleaks")
    if path:
        return CheckResult("gitleaks", STATUS_OK, f"gitleaks found at {path}")
    return CheckResult(
        "gitleaks",
        STATUS_WARN,
        "gitleaks not on PATH — pre-commit installs it lazily on first run.",
    )


def check_playbook_submodule(cwd: Path | None = None) -> CheckResult:
    """Confirm consumer repo has ``.ai-playbook/`` submodule with ``specs/`` + ``scripts/``."""
    cwd = cwd or Path.cwd()
    sub = cwd / ".ai-playbook"
    if not sub.is_dir():
        return CheckResult(
            "playbook-submodule",
            STATUS_WARN,
            f"{sub} missing — consumer repo lacks ai-playbook submodule "
            "(expected when running inside the playbook repo itself).",
        )
    missing = [d for d in ("specs", "scripts") if not (sub / d).is_dir()]
    if missing:
        return CheckResult(
            "playbook-submodule",
            STATUS_FAIL,
            f"{sub} exists but is missing: {', '.join(missing)}",
        )
    return CheckResult("playbook-submodule", STATUS_OK, f"submodule healthy at {sub}")


def _registry_path() -> Path:
    env = os.environ.get("AIPLAYBOOK_PROJECTS_FILE")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".ai-playbook" / "projects.yaml"


def check_projects_registry() -> CheckResult:
    path = _registry_path()
    if not path.exists():
        return CheckResult(
            "projects-registry",
            STATUS_WARN,
            f"{path} missing — run `python -m scripts.discover_projects` to populate.",
        )
    try:
        import yaml  # local import; pyyaml check covers the hard-dep case.

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — parse error is the signal.
        return CheckResult(
            "projects-registry",
            STATUS_FAIL,
            f"{path} unparseable: {exc}",
        )
    if not isinstance(data, dict):
        return CheckResult(
            "projects-registry",
            STATUS_FAIL,
            f"{path} is not a YAML mapping.",
        )
    projects = data.get("projects")
    if not isinstance(projects, dict) or not projects:
        return CheckResult(
            "projects-registry",
            STATUS_WARN,
            f"{path} has no project entries — run discover_projects to populate.",
        )
    return CheckResult(
        "projects-registry",
        STATUS_OK,
        f"{len(projects)} project(s) registered at {path}",
    )


# Matches a markdown row whose cells contain at least a Var in the first column
# and `yes` in the "Required?" column. Robust to small formatting variations
# (extra spaces, surrounding backticks on the var name, parenthetical annotations).
_VAR_RE = re.compile(r"`?([A-Z][A-Z0-9_]+)`?")


def _parse_required_env_vars(spec_text: str) -> list[str]:
    """Return a list of canonical env-var names flagged ``Required? | yes``.

    The env-vars.md contract is a markdown table with columns
    ``Var | Prefix | Purpose | Required? | Default | Where read``.
    We scan data rows (skip header + separator) and emit the Var-cell name
    whenever the Required? cell contains the word ``yes`` (case-insensitive,
    allowing annotations like ``yes (if acme-corp consumer)``).
    """
    out: list[str] = []
    for line in spec_text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        # Skip header row and separator row.
        if cells[0].lower() == "var" or set(cells[0]) <= {"-", ":", " "}:
            continue
        required_cell = cells[3].lower()
        if "yes" not in required_cell:
            continue
        # Skip alias rows — their Var cell is *(alias)* or similar; only canonical
        # names we can export from a shell matter here.
        raw = cells[0]
        if raw.startswith("*") or raw.lower().startswith("(alias"):
            continue
        m = _VAR_RE.search(raw)
        if not m:
            continue
        name = m.group(1)
        # Only probe vars that live in a prefix a playbook consumer would set
        # from their shell/SOPS env. Cross-prefix vars (acme-corp_, consumer-c_)
        # flow through CLI args per env-vars.md Rules; doctor doesn't probe them.
        if name not in out:
            out.append(name)
    return out


def check_env_vars_required(playbook_root: Path | None = None) -> CheckResult:
    playbook_root = playbook_root or PLAYBOOK_ROOT
    spec = playbook_root / "specs" / "env-vars.md"
    if not spec.is_file():
        return CheckResult(
            "env-vars-required",
            STATUS_WARN,
            f"{spec} not found — cannot enumerate required env vars.",
        )
    text = spec.read_text(encoding="utf-8")
    required = _parse_required_env_vars(text)
    missing = [name for name in required if not os.environ.get(name)]
    if not missing:
        return CheckResult(
            "env-vars-required",
            STATUS_OK,
            f"all {len(required)} required env var(s) set (per docs/concepts/env-vars.md).",
        )
    return CheckResult(
        "env-vars-required",
        STATUS_WARN,
        f"missing required env var(s): {', '.join(missing)} — see docs/concepts/env-vars.md.",
    )


def check_env_vars_alias_warning() -> CheckResult:
    """Warn when the deprecated ``ANTHROPIC_CACHE_TOKENS_MIN`` alias is set
    without the canonical ``AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN``.

    Rule source: ``docs/concepts/env-vars.md`` §Resolution order.
    """
    alias = os.environ.get("ANTHROPIC_CACHE_TOKENS_MIN")
    canonical = os.environ.get("AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN")
    if alias and not canonical:
        return CheckResult(
            "env-vars-alias-warning",
            STATUS_WARN,
            "ANTHROPIC_CACHE_TOKENS_MIN is deprecated; "
            "rename to AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN.",
        )
    return CheckResult(
        "env-vars-alias-warning",
        STATUS_OK,
        "no deprecated env-var aliases in use.",
    )


def check_context_budget(playbook_root: Path | None = None) -> CheckResult:
    playbook_root = playbook_root or PLAYBOOK_ROOT
    specs_dir = playbook_root / "specs"
    if not specs_dir.is_dir():
        return CheckResult(
            "context-budget",
            STATUS_WARN,
            f"{specs_dir} not a directory — cannot compute context budget.",
        )
    total = 0
    count = 0
    for md in sorted(specs_dir.glob("*.md")):
        try:
            total += md.stat().st_size
            count += 1
        except OSError:
            continue
    kb = total / 1024
    if total > CONTEXT_BUDGET_BYTES:
        return CheckResult(
            "context-budget",
            STATUS_WARN,
            f"{count} specs/*.md files = {kb:.1f} KB (>100 KB threshold); "
            "prune per docs/concepts/taxonomy.md `Framework files lean` principle.",
        )
    return CheckResult(
        "context-budget",
        STATUS_OK,
        f"{count} specs/*.md files = {kb:.1f} KB (<100 KB budget).",
    )


# ---------------------------------------------------------------------------
# Aggregation + CLI surface
# ---------------------------------------------------------------------------


ALL_CHECKS: tuple[Callable[[], CheckResult], ...] = (
    check_python,
    check_git,
    check_gh,
    check_npx,
    check_precommit,
    check_pyyaml,
    check_jsonschema,
    check_sops,
    check_gitleaks,
    check_playbook_submodule,
    check_projects_registry,
    check_env_vars_required,
    check_env_vars_alias_warning,
    check_context_budget,
)


def _ensure_pip() -> bool:
    """Return True once ``pip`` is importable, bootstrapping via ``ensurepip``."""
    if _import_check("pip"):
        return True
    try:
        subprocess.run(
            [sys.executable, "-m", "ensurepip", "--upgrade"],
            capture_output=True, text=True, timeout=120, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return _import_check("pip")


def install_deps(root: Path | None = None) -> CheckResult:
    """Editable-install the playbook so its hard deps resolve in this interpreter.

    Self-heal for the common consumer failure where the active venv lacks
    ``jsonschema``/``pyyaml`` (they are not in every consumer's pyproject).
    Reuses ``PLAYBOOK_ROOT`` (the pyproject that declares the deps + console
    scripts). Best-effort: returns a single ``install-deps`` CheckResult.
    """
    root = root or PLAYBOOK_ROOT
    # Fast path for uv-managed venvs (no pip, no ensurepip): install the hard
    # deps straight into this interpreter. Covers the common "uv venv lacks
    # jsonschema" failure without needing pip at all.
    if shutil.which("uv"):
        try:
            proc = subprocess.run(
                ["uv", "pip", "install", "--python", sys.executable, "pyyaml", "jsonschema"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=600, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            proc = None
        if proc is not None and proc.returncode == 0 and _import_check("jsonschema") and _import_check("yaml"):
            return CheckResult("install-deps", STATUS_OK, "installed pyyaml+jsonschema via uv")
    if not _ensure_pip():
        return CheckResult(
            "install-deps", STATUS_FAIL,
            "pip/uv unavailable and `ensurepip` failed — create a venv with pip "
            "(`python -m venv .venv`) or install uv, then re-run; or install "
            "pyyaml+jsonschema manually.",
        )
    cmd = [sys.executable, "-m", "pip", "install", "-e", str(root)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=600, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult("install-deps", STATUS_FAIL, f"`pip install -e` failed to start: {exc}")
    if proc.returncode != 0:
        tail = " ".join((proc.stderr or proc.stdout or "").strip().splitlines()[-3:])
        return CheckResult(
            "install-deps", STATUS_FAIL,
            f"`pip install -e {root}` exited {proc.returncode}: {tail[:300]}",
        )
    return CheckResult("install-deps", STATUS_OK, f"installed playbook (editable) from {root}")


def run_all() -> list[CheckResult]:
    """Run every check and return the collected results."""
    results: list[CheckResult] = []
    for fn in ALL_CHECKS:
        try:
            results.append(fn())
        except Exception as exc:  # noqa: BLE001 — individual check should never crash the doctor.
            results.append(CheckResult(fn.__name__, STATUS_FAIL, f"check raised: {exc}"))
    return results


def _sigil(status: str) -> str:
    if status == STATUS_OK:
        return "✅"
    if status == STATUS_WARN:
        return "⚠️"
    return "❌"


def _render_pretty(results: Iterable[CheckResult]) -> str:
    lines: list[str] = []
    lines.append("ai-playbook doctor")
    lines.append("")
    ok = warn = fail = 0
    for r in results:
        lines.append(f"{_sigil(r.status)} {r.name}: {r.detail}")
        if r.status == STATUS_OK:
            ok += 1
        elif r.status == STATUS_WARN:
            warn += 1
        else:
            fail += 1
    lines.append("")
    lines.append(f"Summary: {ok} ok, {warn} warn, {fail} fail.")
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doctor",
        description="Run ai-playbook prerequisite + health checks.",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit JSON array to stdout (machine-readable).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as failures (exit 1 on any warn).",
    )
    parser.add_argument(
        "--install-deps",
        dest="install_deps",
        action="store_true",
        help="Editable-install the playbook (pip install -e) to resolve missing "
             "hard deps (pyyaml, jsonschema) before running the checks.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:  # argparse error
        return int(exc.code or 2)

    pre: list[CheckResult] = []
    if getattr(args, "install_deps", False):
        pre.append(install_deps())

    try:
        results = pre + run_all()
    except OSError as exc:
        print(f"❌ doctor setup error: {exc}", file=sys.stderr)
        print("   FIX: verify cwd is readable and the playbook checkout is intact.",
              file=sys.stderr)
        print("   OVERRIDE: none", file=sys.stderr)
        return 2

    if args.as_json:
        sys.stdout.write(json.dumps([asdict(r) for r in results], indent=2) + "\n")
    else:
        sys.stderr.write(_render_pretty(results))

    has_fail = any(r.status == STATUS_FAIL for r in results)
    has_warn = any(r.status == STATUS_WARN for r in results)
    if has_fail:
        return 1
    if args.strict and has_warn:
        return 1
    return 0


if __name__ == "__main__":
    from scripts.rules._telemetry import script_emit
    raise SystemExit(script_emit("doctor", main))
