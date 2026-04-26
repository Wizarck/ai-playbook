"""Scan the playbook and consumer repos for known deprecations.

Populated in T22i. Surfaces the following deprecation signals:

1. **AGENTS.md v0 frontmatter** — `schema: agents-md/v0` or missing schema
   (v0→v1 migration pending per ``specs/migration-guide.md``).
2. **Env-var aliases without their canonical counterparts** — currently
   ``ANTHROPIC_CACHE_TOKENS_MIN`` without ``AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN``
   (see ``specs/env-vars.md`` resolution order).
3. **Deprecated MCP server IDs** in consumer ``mcp-servers.yaml`` / ``.mcp.json``
   — first entry: ``opentrattos-guardrails-mcp`` → canonical ``guardrails-mcp``.
   Configurable via ``specs/deprecations.yaml``; falls back to a hardcoded
   minimal list if that file is absent.
4. **Stale retro-archive entries** flagged by ``scripts/lifecycle_check.py``
   under ``reports/lifecycle/*.md`` (older than 180 days).

CLI
---
    python -m scripts.deprecation_watcher [--strict] [--json] [--registry PATH]
                                          [--playbook-root PATH]

Exit codes
----------
    0  default (even with findings); or strict + no findings
    1  ``--strict`` and at least one finding
    2  setup error (unreadable registry / missing playbook root)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Force UTF-8 stdio.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

try:
    import yaml
except ImportError:  # pragma: no cover - optional import guard
    print("❌ PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    raise SystemExit(2) from None


# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------


DEFAULT_REGISTRY_PATH = Path.home() / ".ai-playbook" / "projects.yaml"
STALE_RETRO_DAYS = 180

DEFAULT_MCP_DEPRECATIONS: dict[str, str] = {
    # deprecated_id → canonical_id
    "opentrattos-guardrails-mcp": "guardrails-mcp",
}

DEFAULT_ENV_ALIASES: dict[str, str] = {
    # alias → canonical
    "ANTHROPIC_CACHE_TOKENS_MIN": "AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    kind: str  # "v0_schema" | "env_alias" | "mcp_deprecated_id" | "stale_retro"
    subject: str  # file path, env var, or retro id
    detail: str
    project: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WatcherConfig:
    registry_path: Path
    playbook_root: Path
    mcp_deprecations: dict[str, str] = field(default_factory=dict)
    env_aliases: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_deprecations_yaml(playbook_root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Load the optional specs/deprecations.yaml.

    Schema:
        mcp_servers:
          <deprecated_id>: <canonical_id>
        env_aliases:
          <alias>: <canonical>

    Returns (mcp_map, env_map) — either may be empty. Falls back to the hardcoded
    defaults if the file is missing or malformed.
    """
    candidate = playbook_root / "specs" / "deprecations.yaml"
    if not candidate.is_file():
        return dict(DEFAULT_MCP_DEPRECATIONS), dict(DEFAULT_ENV_ALIASES)
    try:
        data = yaml.safe_load(candidate.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return dict(DEFAULT_MCP_DEPRECATIONS), dict(DEFAULT_ENV_ALIASES)
    if not isinstance(data, dict):
        return dict(DEFAULT_MCP_DEPRECATIONS), dict(DEFAULT_ENV_ALIASES)
    mcp = data.get("mcp_servers") or {}
    env = data.get("env_aliases") or {}
    if not isinstance(mcp, dict):
        mcp = {}
    if not isinstance(env, dict):
        env = {}
    # Merge with hardcoded defaults so removing an entry from yaml doesn't silently
    # drop coverage of a canonical deprecation.
    merged_mcp = dict(DEFAULT_MCP_DEPRECATIONS)
    merged_mcp.update({str(k): str(v) for k, v in mcp.items()})
    merged_env = dict(DEFAULT_ENV_ALIASES)
    merged_env.update({str(k): str(v) for k, v in env.items()})
    return merged_mcp, merged_env


# ---------------------------------------------------------------------------
# Registry / project enumeration
# ---------------------------------------------------------------------------


def load_registry(path: Path) -> dict[str, dict[str, Any]]:
    """Return the `projects` mapping from the registry, or empty if absent."""
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    projects = data.get("projects")
    return projects if isinstance(projects, dict) else {}


def enumerate_project_paths(registry: dict[str, dict[str, Any]]) -> list[tuple[str, Path]]:
    """Return [(name, path), ...] for registry entries with resolvable paths."""
    out: list[tuple[str, Path]] = []
    for name, entry in registry.items():
        if not isinstance(entry, dict):
            continue
        raw = entry.get("path")
        if not isinstance(raw, str):
            continue
        p = Path(raw)
        if p.is_dir():
            out.append((str(name), p))
    return out


# ---------------------------------------------------------------------------
# v0 schema detection (AGENTS.md)
# ---------------------------------------------------------------------------


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _parse_frontmatter(text: str) -> dict[str, Any] | None:
    text = text.replace("\r\n", "\n")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def scan_agents_md_schema(root: Path, project_name: str) -> list[Finding]:
    """Flag AGENTS.md files whose frontmatter is missing or on v0."""
    findings: list[Finding] = []
    agents_md = root / "AGENTS.md"
    if not agents_md.is_file():
        return findings
    try:
        text = agents_md.read_text(encoding="utf-8")
    except OSError:
        return findings
    fm = _parse_frontmatter(text)
    if fm is None:
        findings.append(
            Finding(
                kind="v0_schema",
                subject=str(agents_md),
                detail="no frontmatter block found (treated as v0)",
                project=project_name,
            )
        )
        return findings
    schema = fm.get("schema")
    if schema != "agents-md/v1":
        findings.append(
            Finding(
                kind="v0_schema",
                subject=str(agents_md),
                detail=f"schema={schema!r} (expected 'agents-md/v1')",
                project=project_name,
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Env-var alias detection
# ---------------------------------------------------------------------------


def scan_env_aliases(env: dict[str, str], aliases: dict[str, str]) -> list[Finding]:
    """Flag alias vars set without their canonical counterpart."""
    findings: list[Finding] = []
    for alias, canonical in aliases.items():
        if alias in env and canonical not in env:
            findings.append(
                Finding(
                    kind="env_alias",
                    subject=alias,
                    detail=(
                        f"{alias} is set but {canonical} is not; export the canonical "
                        "name (per specs/env-vars.md) and drop the alias before v2.0."
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Deprecated MCP IDs
# ---------------------------------------------------------------------------


def _iter_mcp_config_files(root: Path) -> Iterable[Path]:
    for name in ("mcp-servers.yaml", "mcp-servers.yml", ".mcp.json"):
        candidate = root / name
        if candidate.is_file():
            yield candidate


def scan_mcp_deprecations(
    root: Path, project_name: str, deprecations: dict[str, str]
) -> list[Finding]:
    findings: list[Finding] = []
    for cfg in _iter_mcp_config_files(root):
        try:
            text = cfg.read_text(encoding="utf-8")
        except OSError:
            continue
        for deprecated_id, canonical in deprecations.items():
            # Look for either a YAML key form or a JSON string literal form.
            pattern = re.compile(rf"[\"']?{re.escape(deprecated_id)}[\"']?\s*:")
            if pattern.search(text):
                findings.append(
                    Finding(
                        kind="mcp_deprecated_id",
                        subject=f"{cfg}:{deprecated_id}",
                        detail=f"rename '{deprecated_id}' → '{canonical}'",
                        project=project_name,
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Stale retro archives
# ---------------------------------------------------------------------------


_ISO_DATE_IN_NAME = re.compile(r"(\d{4})-(\d{2})(?:-(\d{2}))?")


def _lifecycle_dir(root: Path) -> Path:
    return root / "reports" / "lifecycle"


def scan_stale_retros(
    root: Path, project_name: str, *, now: datetime | None = None
) -> list[Finding]:
    """Flag retro-archive entries older than STALE_RETRO_DAYS.

    Reads ``reports/lifecycle/*.md`` and treats each file's `YYYY-MM` filename
    stem as its logical month; files older than the cutoff produce a finding.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=STALE_RETRO_DAYS)
    lifecycle_dir = _lifecycle_dir(root)
    if not lifecycle_dir.is_dir():
        return []

    findings: list[Finding] = []
    for md in lifecycle_dir.glob("*.md"):
        stem = md.stem
        m = _ISO_DATE_IN_NAME.match(stem)
        if not m:
            continue
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3) or 1)
        try:
            file_dt = datetime(year, month, day, tzinfo=UTC)
        except ValueError:
            continue
        if file_dt < cutoff:
            findings.append(
                Finding(
                    kind="stale_retro",
                    subject=str(md),
                    detail=(
                        f"lifecycle report {stem} is older than {STALE_RETRO_DAYS} days "
                        f"(file_dt={file_dt.date()})"
                    ),
                    project=project_name,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def collect_findings(
    config: WatcherConfig,
    *,
    env: dict[str, str] | None = None,
    now: datetime | None = None,
) -> list[Finding]:
    env = os.environ if env is None else env
    projects = load_registry(config.registry_path)
    project_paths = enumerate_project_paths(projects)
    # Always include the playbook itself under a sentinel project name.
    project_paths.append(("ai-playbook", config.playbook_root))

    findings: list[Finding] = []

    for name, path in project_paths:
        findings.extend(scan_agents_md_schema(path, name))
        findings.extend(scan_mcp_deprecations(path, name, config.mcp_deprecations))
        findings.extend(scan_stale_retros(path, name, now=now))

    findings.extend(scan_env_aliases(dict(env), config.env_aliases))

    return findings


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_markdown(findings: list[Finding]) -> str:
    lines = ["# Deprecation watcher report", ""]
    if not findings:
        lines.append("✅ No deprecations detected.")
        return "\n".join(lines) + "\n"
    lines.append(f"Total findings: {len(findings)}")
    lines.append("")
    lines.append("| Kind | Project | Subject | Detail |")
    lines.append("|---|---|---|---|")
    for f in findings:
        subj = f.subject.replace("|", "\\|")
        detail = f.detail.replace("|", "\\|")
        lines.append(f"| {f.kind} | {f.project or '-'} | {subj} | {detail} |")
    return "\n".join(lines) + "\n"


def render_json(findings: list[Finding]) -> str:
    return json.dumps([f.as_dict() for f in findings], indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _find_playbook_root() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here.parent, *here.parents):
        if (candidate / "specs").is_dir() and (candidate / "scripts").is_dir():
            return candidate
    return Path.cwd()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="deprecation_watcher",
        description="Scan the playbook + consumer repos for known deprecations.",
    )
    parser.add_argument("--strict", action="store_true",
                        help="Exit 1 if any deprecation found (default: exit 0).")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON on stdout instead of the markdown table.")
    parser.add_argument("--registry", type=Path, default=None,
                        help="Projects-registry YAML path "
                        "(default: $AIPLAYBOOK_PROJECTS_FILE or ~/.ai-playbook/projects.yaml).")
    parser.add_argument("--playbook-root", type=Path, default=None,
                        help="Playbook root (default: autodetected).")
    args = parser.parse_args(argv)

    registry_path = args.registry or Path(
        os.environ.get("AIPLAYBOOK_PROJECTS_FILE", str(DEFAULT_REGISTRY_PATH))
    ).expanduser()
    playbook_root = args.playbook_root or _find_playbook_root()

    mcp_map, env_map = load_deprecations_yaml(playbook_root)
    config = WatcherConfig(
        registry_path=registry_path,
        playbook_root=playbook_root,
        mcp_deprecations=mcp_map,
        env_aliases=env_map,
    )

    findings = collect_findings(config)

    if args.json:
        print(render_json(findings))
    else:
        sys.stdout.write(render_markdown(findings))

    if args.strict and findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
