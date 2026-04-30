"""Validate the 3-layer ``mcp-servers*.yaml`` stack and detect drift vs rendered configs.

Three layers — each a YAML file, same v1 schema:

1. **Base**     — ``<playbook>/mcp-servers-base.yaml`` (well-known templates).
2. **Project**  — ``<consumer>/mcp-servers.yaml`` (project-scoped servers).
3. **Personal** — ``$AIPLAYBOOK_PERSONAL_MCP_FILE`` if set, else
                  ``~/.config/mcp-servers.yaml``, else
                  ``<HOME>/Projects/consumer-d/mcp-servers.yaml`` (legacy convention).

Merge precedence: **personal > project > base**, field-by-field deep merge.

Validations (every failure emits a canonical error per
``specs/error-message-standard.md``: ``❌ WHY / FIX / OVERRIDE``):

- each YAML file parses and matches ``schema: mcp-servers/v1`` shape
- no ``scope: personal`` server appears at base or project layer
- no duplicate canonical IDs within a single layer
- merged result declares no missing ``env.required`` in the process environment
- drift: if ``<consumer>/.mcp.json`` or ``<consumer>/.gemini/settings.json``
  exists, recompute its rendered form in-memory and refuse on any diff.

Exit codes (see ``specs/error-message-standard.md``):

- ``0`` — all validations pass
- ``1`` — user-actionable validation error
- ``2`` — environment / setup error (missing file, bad YAML, unreadable path)
- ``3`` — hard block with ``OVERRIDE: none`` (e.g. secret-like value leaked)

Usage::

    python -m scripts.mcp.validate [--project <name>] \\
        [--playbook-root <path>] [--consumer-root <path>] \\
        [--personal-file <path>] [--force-with-reason "..."]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Force UTF-8 stdio — the canonical error sigil is ❌.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

try:
    import yaml
except ImportError:  # pragma: no cover - dep bootstrap
    print("❌ PyYAML required at mcp/validate startup", file=sys.stderr)
    print("   FIX: pip install pyyaml", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)
    raise SystemExit(2) from None


SCHEMA = "mcp-servers/v1"
LAYER_BASE = "base"
LAYER_PROJECT = "project"
LAYER_PERSONAL = "personal"
VALID_LAYERS = {LAYER_BASE, LAYER_PROJECT, LAYER_PERSONAL}
VALID_TRANSPORTS = {"stdio", "http", "sse", "streamable-http"}
VALID_SCOPES = {"personal", "project", "universal"}
MIN_OVERRIDE_REASON_LEN = 10

# Fields that the renderer emits per server — the drift check compares these.
_RENDER_KEYS = ("id", "description", "transport", "endpoint", "command", "env", "auth",
                "scope", "capabilities_hint")


# ---------------------------------------------------------------------------
# Canonical error emission
# ---------------------------------------------------------------------------
@dataclass
class CanonicalError:
    why: str
    where: str
    fix: str
    override: str = "none"
    detail: str | None = None

    def render(self) -> str:
        out = [f"❌ {self.why} at {self.where}",
               f"   FIX: {self.fix}",
               f"   OVERRIDE: {self.override}"]
        if self.detail:
            out.append("")
            out.append("Detail:")
            out.append(self.detail)
        return "\n".join(out)


def _emit(err: CanonicalError) -> None:
    print(err.render(), file=sys.stderr)


# ---------------------------------------------------------------------------
# Break-glass — delegates to scripts/_break_glass.py when available, with an
# inline fallback for the (rare) case where the shared helper isn't importable
# (e.g. when this script is vendored into a consumer without the full playbook).
# ---------------------------------------------------------------------------
def _apply_break_glass(*, gate: str, script: str, reason: str | None,
                       repo_root: Path) -> bool:
    """Return True if the override was accepted and logged, False if no override supplied.

    Exits with code 1 if the reason is present but below MIN_OVERRIDE_REASON_LEN.
    """
    try:
        from scripts._break_glass import (  # type: ignore[import-not-found]
            apply_break_glass as _shared,
        )
    except Exception:
        _shared = None

    if _shared is not None:
        try:
            result = _shared(
                gate=gate, script=script, reason=reason,
                override_allowed=True, repo_root=repo_root,
            )
            if result.applied:
                # The shared helper logs + validates but leaves the banner to callers.
                print(f"⚠️  OVERRIDE APPLIED: {result.reason}", file=sys.stderr)
                print(f"   logged: {repo_root / '.ai-playbook' / 'overrides.log'}",
                      file=sys.stderr)
                return True
            return False
        except SystemExit:
            raise
        except Exception:  # noqa: BLE001 — fall through to inline fallback
            pass

    if reason is None:
        return False
    stripped = reason.strip()
    if len(stripped) < MIN_OVERRIDE_REASON_LEN:
        print(
            f"❌ --force-with-reason must be ≥{MIN_OVERRIDE_REASON_LEN} non-whitespace "
            f"chars. Got: {len(stripped)}.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    log_path = repo_root / ".ai-playbook" / "overrides.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
        actor = os.environ.get("GIT_AUTHOR_EMAIL") or os.environ.get("USER") or "unknown"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f'{ts} {actor} {script} {gate} "{stripped}"\n')
    except OSError:
        # Logging failure must not silently cancel the override — surface it.
        print(f"⚠️  OVERRIDE APPLIED (log write failed at {log_path}): {stripped}",
              file=sys.stderr)
        return True
    print(f"⚠️  OVERRIDE APPLIED: {stripped}", file=sys.stderr)
    print(f"   logged: {log_path}", file=sys.stderr)
    return True


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
def resolve_playbook_root(explicit: Path | None, cwd: Path) -> Path:
    """Locate the ai-playbook repo root.

    Order:
    1. --playbook-root CLI arg.
    2. $AIPLAYBOOK_ROOT env var.
    3. ``<cwd>/.ai-playbook`` (submodule convention).
    4. ``<cwd>`` when it contains ``mcp-servers-base.yaml`` (running inside playbook itself).
    5. The dir containing this script (fallback for test-from-source).
    """
    if explicit is not None:
        return explicit.expanduser().resolve()
    env = os.environ.get("AIPLAYBOOK_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    submodule = cwd / ".ai-playbook"
    if (submodule / "mcp-servers-base.yaml").is_file():
        return submodule.resolve()
    if (cwd / "mcp-servers-base.yaml").is_file():
        return cwd.resolve()
    return Path(__file__).resolve().parent.parent.parent


def resolve_personal_file(explicit: Path | None) -> Path | None:
    """Resolve the personal-layer YAML path (may not exist — returns the candidate).

    Search order:
        1. ``--personal-file`` CLI arg.
        2. ``$AIPLAYBOOK_PERSONAL_MCP_FILE`` env var.
        3. ``~/.config/mcp-servers.yaml`` (XDG convention).
        4. ``~/Projects/consumer-d/mcp-servers.yaml`` (legacy fallback;
           emits a stderr notice so the dev sees the cross-project read).
        5. ``C:/Projects/consumer-d/mcp-servers.yaml`` (Windows legacy
           fallback; same notice).
    """
    if explicit is not None:
        return explicit.expanduser().resolve()
    env = os.environ.get("AIPLAYBOOK_PERSONAL_MCP_FILE")
    if env:
        return Path(env).expanduser().resolve()
    xdg = Path.home() / ".config" / "mcp-servers.yaml"
    if xdg.is_file():
        return xdg.resolve()

    def _legacy_notice(path: Path) -> None:
        print(
            f"ℹ️  mcp-validate: using legacy personal-layer fallback at {path} "
            f"(no ~/.config/mcp-servers.yaml found). Set $AIPLAYBOOK_PERSONAL_MCP_FILE "
            f"or create ~/.config/mcp-servers.yaml to override.",
            file=sys.stderr,
        )

    legacy = Path.home() / "Projects" / "consumer-d" / "mcp-servers.yaml"
    if legacy.is_file():
        _legacy_notice(legacy)
        return legacy.resolve()
    win_legacy = Path("C:/Projects/consumer-d/mcp-servers.yaml")
    if win_legacy.is_file():
        _legacy_notice(win_legacy)
        return win_legacy.resolve()
    return None


# ---------------------------------------------------------------------------
# Layer loading
# ---------------------------------------------------------------------------
@dataclass
class Layer:
    name: str
    path: Path | None
    data: dict[str, Any] = field(default_factory=dict)
    present: bool = False


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"cannot read {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise RuntimeError(f"malformed YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"top-level YAML in {path} must be a mapping, got {type(data).__name__}")
    return data


def _resolve_project_layer_file(consumer_root: Path) -> Path:
    """Resolve the v1 project-layer YAML for a consumer.

    A consumer may ship its own legacy ``mcp-servers.yaml`` as SSOT for other
    tooling (e.g. consumer-d's helm chart + desktop-stack scripts predate the
    playbook v1 layer schema). Those files declare ``metadata:`` rather than
    ``schema: mcp-servers/v1`` and would fail playbook validation.

    Resolution order:
      1. ``<consumer>/mcp-servers.project.yaml`` — explicit v1 file. Use as-is.
      2. ``<consumer>/mcp-servers.yaml`` — only when the file declares
         ``schema: mcp-servers/v1`` (otherwise treated as legacy + skipped).
    """
    explicit = consumer_root / "mcp-servers.project.yaml"
    if explicit.is_file():
        return explicit
    default = consumer_root / "mcp-servers.yaml"
    if not default.is_file():
        return default  # treated as not-present by caller
    try:
        head = _load_yaml(default)
    except RuntimeError:
        return default
    if head.get("schema") == SCHEMA:
        return default
    # Legacy shape — point at the explicit-file location so callers see "absent"
    # for the v1 surface without erroring on the legacy file.
    return explicit


def load_layers(*, playbook_root: Path, consumer_root: Path,
                personal_file: Path | None) -> tuple[Layer, Layer, Layer]:
    base_path = playbook_root / "mcp-servers-base.yaml"
    project_path = _resolve_project_layer_file(consumer_root)

    base = Layer(name=LAYER_BASE, path=base_path, present=base_path.is_file())
    if base.present:
        base.data = _load_yaml(base_path)

    project = Layer(name=LAYER_PROJECT, path=project_path, present=project_path.is_file())
    if project.present:
        project.data = _load_yaml(project_path)

    personal = Layer(name=LAYER_PERSONAL, path=personal_file,
                     present=bool(personal_file and personal_file.is_file()))
    if personal.present and personal.path is not None:
        personal.data = _load_yaml(personal.path)

    return base, project, personal


# ---------------------------------------------------------------------------
# Schema validation (lightweight — no jsonschema dep needed for v1 shape)
# ---------------------------------------------------------------------------
def validate_layer_shape(layer: Layer, errors: list[CanonicalError]) -> None:
    if not layer.present:
        return
    data = layer.data
    path_str = _path_str(layer.path)

    schema = data.get("schema")
    if schema != SCHEMA:
        errors.append(CanonicalError(
            why=f"{layer.name} layer schema must be '{SCHEMA}'; got {schema!r}",
            where=f"{path_str}:schema",
            fix=f"set `schema: {SCHEMA}` at the top of {path_str}",
        ))

    declared = data.get("layer")
    if declared not in VALID_LAYERS:
        errors.append(CanonicalError(
            why=f"{layer.name} layer file declares unknown `layer: {declared!r}`",
            where=f"{path_str}:layer",
            fix=f"set `layer: {layer.name}` at the top of {path_str}",
        ))
    elif declared != layer.name:
        errors.append(CanonicalError(
            why=f"{layer.name} file declares `layer: {declared}`, expected `{layer.name}`",
            where=f"{path_str}:layer",
            fix=f"change the `layer:` field in {path_str} to `{layer.name}`",
        ))

    servers = data.get("servers")
    if servers is not None and not isinstance(servers, dict):
        errors.append(CanonicalError(
            why=f"{layer.name} layer `servers` must be a mapping; got {type(servers).__name__}",
            where=f"{path_str}:servers",
            fix="rewrite `servers:` as a YAML mapping of id → server entry",
        ))
        return

    servers_map: dict[str, Any] = servers or {}
    seen: set[str] = set()
    for sid, entry in servers_map.items():
        if sid in seen:
            errors.append(CanonicalError(
                why=f"duplicate canonical server id `{sid}` in {layer.name} layer",
                where=f"{path_str}:servers.{sid}",
                fix="rename one of the duplicates or merge them field-by-field",
            ))
            continue
        seen.add(sid)
        _validate_server_entry(sid, entry, layer, path_str, errors)


def _validate_server_entry(sid: str, entry: Any, layer: Layer, path_str: str,
                           errors: list[CanonicalError]) -> None:
    if not isinstance(entry, dict):
        errors.append(CanonicalError(
            why=f"server `{sid}` must be a YAML mapping; got {type(entry).__name__}",
            where=f"{path_str}:servers.{sid}",
            fix="rewrite the entry as a mapping with id/description/transport/env/auth/scope",
        ))
        return
    declared_id = entry.get("id")
    if declared_id is not None and declared_id != sid:
        errors.append(CanonicalError(
            why=f"server entry `{sid}` declares inner `id: {declared_id!r}` which differs from its key",
            where=f"{path_str}:servers.{sid}.id",
            fix=f"set `id: {sid}` inside the entry or rename the map key to `{declared_id}`",
        ))
    transport = entry.get("transport")
    if transport is not None and transport not in VALID_TRANSPORTS:
        errors.append(CanonicalError(
            why=f"server `{sid}` has unknown transport `{transport}`",
            where=f"{path_str}:servers.{sid}.transport",
            fix=f"set transport to one of {sorted(VALID_TRANSPORTS)}",
        ))
    scope = entry.get("scope")
    if scope is not None and scope not in VALID_SCOPES:
        errors.append(CanonicalError(
            why=f"server `{sid}` has unknown scope `{scope}`",
            where=f"{path_str}:servers.{sid}.scope",
            fix=f"set scope to one of {sorted(VALID_SCOPES)}",
        ))
    if scope == "personal" and layer.name in (LAYER_BASE, LAYER_PROJECT):
        errors.append(CanonicalError(
            why=(f"server `{sid}` declares `scope: personal` in the {layer.name} layer; "
                 "personal scope is personal-layer-only"),
            where=f"{path_str}:servers.{sid}.scope",
            fix=(f"move this entry to the personal layer (e.g. ~/.config/mcp-servers.yaml) "
                 f"or change its scope to `universal`/`project` in {path_str}"),
        ))
    env = entry.get("env")
    if env is not None:
        if not isinstance(env, dict):
            errors.append(CanonicalError(
                why=f"server `{sid}` `env` must be a mapping with `required`/`optional` lists",
                where=f"{path_str}:servers.{sid}.env",
                fix="rewrite `env:` as `env: {required: [...], optional: [...]}`",
            ))
        else:
            for key in ("required", "optional"):
                value = env.get(key)
                if value is None:
                    continue
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    errors.append(CanonicalError(
                        why=(f"server `{sid}` `env.{key}` must be a list of env var name strings"),
                        where=f"{path_str}:servers.{sid}.env.{key}",
                        fix=f"rewrite `env.{key}` as a YAML list of uppercase env-var names",
                    ))


# ---------------------------------------------------------------------------
# Deep merge
# ---------------------------------------------------------------------------
def deep_merge(base: Any, override: Any) -> Any:
    """Recursively merge override into base. Override scalars replace, override lists replace.

    Dicts are merged field-by-field. `None` in override is treated as "leave base untouched"
    so that templates in the base layer with `endpoint: null` are not overridden by accident
    (the project layer must explicitly set a value to override).
    """
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            if v is None and k in out:
                continue
            if k in out:
                out[k] = deep_merge(out[k], v)
            else:
                out[k] = v
        return out
    if override is None:
        return base
    return override


def merge_servers(base: Layer, project: Layer, personal: Layer
                  ) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    """Return (merged_servers, layer_provenance_per_id).

    Provenance lists which layers contributed fields to each server id, in precedence order.
    """
    merged: dict[str, dict[str, Any]] = {}
    provenance: dict[str, list[str]] = {}
    for layer in (base, project, personal):
        servers = (layer.data or {}).get("servers") or {}
        if not isinstance(servers, dict):
            continue
        for sid, entry in servers.items():
            if not isinstance(entry, dict):
                continue
            provenance.setdefault(sid, []).append(layer.name)
            if sid in merged:
                merged[sid] = deep_merge(merged[sid], entry)
            else:
                merged[sid] = dict(entry)
    # Ensure each merged entry carries its canonical id.
    for sid, entry in merged.items():
        entry.setdefault("id", sid)
    return merged, provenance


# ---------------------------------------------------------------------------
# Env required check
# ---------------------------------------------------------------------------
def collect_missing_env(merged: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Return {server_id: [missing_vars]} for every required env var unset in os.environ."""
    missing: dict[str, list[str]] = {}
    for sid, entry in merged.items():
        env = entry.get("env") or {}
        required = env.get("required") or []
        if not isinstance(required, list):
            continue
        holes = [v for v in required if isinstance(v, str) and not os.environ.get(v)]
        if holes:
            missing[sid] = holes
    return missing


# ---------------------------------------------------------------------------
# Render-equivalence (drift detection)
# ---------------------------------------------------------------------------
def _normalize_env(env: Any) -> dict[str, Any]:
    if not isinstance(env, dict):
        return {"required": [], "optional": []}
    return {
        "required": sorted(env.get("required") or []),
        "optional": sorted(env.get("optional") or []),
    }


def normalize_server_for_compare(entry: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in _RENDER_KEYS:
        v = entry.get(k)
        if k == "env":
            out[k] = _normalize_env(v)
        elif k == "capabilities_hint" and isinstance(v, list):
            out[k] = sorted(v)
        else:
            out[k] = v
    return out


def render_claude_code(merged: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Claude Code ``.mcp.json`` shape."""
    servers: dict[str, Any] = {}
    for sid in sorted(merged):
        entry = merged[sid]
        item: dict[str, Any] = {"transport": entry.get("transport")}
        if entry.get("transport") == "stdio":
            if entry.get("command"):
                item["command"] = entry["command"]
        else:
            if entry.get("endpoint"):
                item["url"] = entry["endpoint"]
        env = entry.get("env") or {}
        if isinstance(env, dict):
            if env.get("required"):
                item["env_required"] = list(env["required"])
            if env.get("optional"):
                item["env_optional"] = list(env["optional"])
        if entry.get("auth"):
            item["auth"] = entry["auth"]
        servers[sid] = item
    return {"mcpServers": servers}


def render_gemini(merged: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Gemini CLI / Antigravity ``.gemini/settings.json`` shape.

    TODO: verify against Gemini CLI docs — using a conservative shape with a
    top-level ``mcpServers`` map mirroring Claude Code, since Gemini's
    settings.json accepts an ``mcpServers`` key per the public CLI reference.
    """
    servers: dict[str, Any] = {}
    for sid in sorted(merged):
        entry = merged[sid]
        item: dict[str, Any] = {}
        transport = entry.get("transport")
        if transport == "stdio":
            if entry.get("command"):
                item["command"] = entry["command"]
        else:
            if entry.get("endpoint"):
                item["httpUrl"] = entry["endpoint"]
        env = entry.get("env") or {}
        if isinstance(env, dict) and env.get("required"):
            item["env"] = {v: f"${{{v}}}" for v in env["required"]}
        servers[sid] = item
    return {"mcpServers": servers}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{path}: {exc}") from exc


def detect_drift(*, merged: dict[str, dict[str, Any]], consumer_root: Path,
                 errors: list[CanonicalError]) -> None:
    claude_path = consumer_root / ".mcp.json"
    gemini_path = consumer_root / ".gemini" / "settings.json"
    if claude_path.is_file():
        try:
            committed = _load_json(claude_path)
        except RuntimeError as exc:
            errors.append(CanonicalError(
                why=f"cannot parse committed Claude Code MCP config: {exc}",
                where=_path_str(claude_path),
                fix=f"fix the JSON syntax in {_path_str(claude_path)} or delete and re-render",
            ))
        else:
            fresh = render_claude_code(merged)
            if committed != fresh:
                errors.append(CanonicalError(
                    why="mcp-servers.yaml rendered output diverges from committed .mcp.json",
                    where=_path_str(claude_path),
                    fix=("run `python .ai-playbook/scripts/mcp/render.py --project <name>` "
                         "and commit the regenerated file"),
                    detail=_diff_summary(committed, fresh),
                ))
    if gemini_path.is_file():
        try:
            committed = _load_json(gemini_path)
        except RuntimeError as exc:
            errors.append(CanonicalError(
                why=f"cannot parse committed Gemini settings: {exc}",
                where=_path_str(gemini_path),
                fix=f"fix the JSON syntax in {_path_str(gemini_path)} or delete and re-render",
            ))
        else:
            fresh = render_gemini(merged)
            if committed != fresh:
                errors.append(CanonicalError(
                    why="mcp-servers.yaml rendered output diverges from committed .gemini/settings.json",
                    where=_path_str(gemini_path),
                    fix=("run `python .ai-playbook/scripts/mcp/render.py --project <name>` "
                         "and commit the regenerated file"),
                    detail=_diff_summary(committed, fresh),
                ))


def _diff_summary(committed: Any, fresh: Any) -> str:
    try:
        import difflib
        left = json.dumps(committed, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
        right = json.dumps(fresh, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
        diff = list(difflib.unified_diff(left, right, fromfile="committed", tofile="rendered",
                                         lineterm=""))
        return "\n".join(diff[:40]) or "(empty diff)"
    except Exception:  # noqa: BLE001
        return "(diff unavailable)"


def _path_str(path: Path | None) -> str:
    if path is None:
        return "<unset>"
    return str(path).replace("\\", "/")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts.mcp.validate",
        description="Validate the 3-layer MCP SSOT stack and detect drift vs rendered configs.",
    )
    parser.add_argument("--project", default=None,
                        help="Consumer project name (informational, used in logs).")
    parser.add_argument("--playbook-root", type=Path, default=None,
                        help="Override path to the ai-playbook repo root.")
    parser.add_argument("--consumer-root", type=Path, default=None,
                        help="Override path to the consumer repo root (default: cwd).")
    parser.add_argument("--personal-file", type=Path, default=None,
                        help="Override personal layer YAML path.")
    parser.add_argument("--skip-drift", action="store_true",
                        help="Skip drift check against committed .mcp.json / .gemini/settings.json.")
    parser.add_argument("--skip-env-check", action="store_true",
                        help="Skip the env.required check (useful for offline CI).")
    parser.add_argument("--force-with-reason", dest="force_reason", default=None,
                        metavar="TEXT",
                        help="Break-glass: bypass validation with an audit trail (≥10 chars).")
    return parser


def run(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    consumer_root = (args.consumer_root or cwd).expanduser().resolve()
    playbook_root = resolve_playbook_root(args.playbook_root, consumer_root)
    personal_file = resolve_personal_file(args.personal_file)

    try:
        base, project, personal = load_layers(
            playbook_root=playbook_root,
            consumer_root=consumer_root,
            personal_file=personal_file,
        )
    except RuntimeError as exc:
        _emit(CanonicalError(
            why=f"could not load MCP YAML layers: {exc}",
            where=f"playbook={_path_str(playbook_root)} consumer={_path_str(consumer_root)}",
            fix="fix the YAML file named above or correct the --playbook-root / --consumer-root path",
        ))
        return 2

    if not base.present:
        _emit(CanonicalError(
            why="base layer `mcp-servers-base.yaml` not found",
            where=_path_str(playbook_root / "mcp-servers-base.yaml"),
            fix=("set --playbook-root to the ai-playbook checkout, set $AIPLAYBOOK_ROOT, "
                 "or ensure .ai-playbook/ is submoduled under the consumer repo"),
        ))
        return 2

    errors: list[CanonicalError] = []
    validate_layer_shape(base, errors)
    validate_layer_shape(project, errors)
    validate_layer_shape(personal, errors)

    # If any layer failed shape validation we still attempt merge to surface more issues,
    # but skip env+drift to avoid false cascades when the yaml is unparseable.
    merged, provenance = merge_servers(base, project, personal)

    # Pre-commit auto-skips env-check: PRE_COMMIT=1 is set by pre-commit when
    # running hooks. Required env vars (ATLASSIAN_*, GOOGLE_*, etc.) live in
    # SOPS-encrypted dotenv files and aren't sourced before `git commit`,
    # so the env-check gives false positives in pre-commit context. CI and
    # explicit invocations still hard-fail (drop --skip-env-check).
    in_pre_commit = bool(os.environ.get("PRE_COMMIT"))
    if not args.skip_env_check and not in_pre_commit:
        missing = collect_missing_env(merged)
        for sid, vars_ in sorted(missing.items()):
            errors.append(CanonicalError(
                why=(f"merged server `{sid}` declares {len(vars_)} required env var(s) "
                     f"unset in the current environment"),
                where=f"mcp-servers(merged):servers.{sid}.env.required",
                fix=(f"export {', '.join(vars_)} (or source your SOPS-decrypted env file) "
                     "before re-running"),
            ))
    elif in_pre_commit and not args.skip_env_check:
        # Soft notice so the dev sees what was skipped.
        missing = collect_missing_env(merged)
        if missing:
            count = sum(len(v) for v in missing.values())
            print(
                f"ℹ️  mcp-validate: skipped env-check in pre-commit context "
                f"({count} env var(s) across {len(missing)} server(s) would have "
                "fired; run `python .ai-playbook/scripts/mcp/validate.py` directly "
                "with envs sourced for the full check)",
                file=sys.stderr,
            )

    if not args.skip_drift and not any("YAML" in e.why or "shape" in e.why for e in errors):
        detect_drift(merged=merged, consumer_root=consumer_root, errors=errors)

    if not errors:
        print(f"✅ MCP SSOT validation passed ({len(merged)} merged servers "
              f"across base={base.present} project={project.present} personal={personal.present}).",
              file=sys.stderr)
        if args.project:
            print(f"   project: {args.project}", file=sys.stderr)
        return 0

    # Emit every error block.
    for err in errors:
        _emit(err)
        print("", file=sys.stderr)

    # Break-glass bypass
    applied = _apply_break_glass(
        gate="mcp.validate",
        script="scripts/mcp/validate.py",
        reason=args.force_reason,
        repo_root=consumer_root,
    )
    if applied:
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — turn any internal crash into canonical err
        _emit(CanonicalError(
            why=f"unexpected failure during mcp.validate: {type(exc).__name__}: {exc}",
            where="scripts/mcp/validate.py",
            fix="report with full stacktrace to FEEDBACK.md",
        ))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
