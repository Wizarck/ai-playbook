"""Rules toggle CLI + per-consumer state IO.

State lives at ``<project>/.ai-playbook/rules-toggle.json`` (gitignored).
Sparse representation: only rules that diverge from the all-ON default are
persisted. Rules absent from the file are treated as fully ON.

Side effects of ``on``/``off``:
    - Mutate the JSON via atomic temp+rename (schema-validated first).
    - Append one line to ``<project>/.ai-playbook/rules-toggle-audit.jsonl``.

The CLI mirrors ``scripts/caveman/cli.py`` shape for consistency. State IO
mirrors ``scripts/caveman/toggle.py``.

Subcommands
-----------
    python -m scripts.rules_toggle list   [--json]
    python -m scripts.rules_toggle status --slug SLUG [--layer L1|L2|L3] [--exit-code] [--json]
    python -m scripts.rules_toggle on     SLUG [--layer L1|L2|L3]
    python -m scripts.rules_toggle off    SLUG [--layer L1|L2|L3] [--reason TEXT]
    python -m scripts.rules_toggle inventory [--output PATH]
    python -m scripts.rules_toggle init   [--from PATH]

Exit codes (per docs/rules/error-message-standard.rule.md):
    0   ok
    1   user-actionable error (unknown slug, missing reason, etc.)
    2   environment/setup error (schema missing, jsonschema absent)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

try:
    import jsonschema
except ImportError:
    print(
        "❌ jsonschema is required for scripts.rules_toggle. "
        "Install with: pip install jsonschema",
        file=sys.stderr,
    )
    raise SystemExit(2) from None

try:
    import yaml
except ImportError:
    print(
        "❌ pyyaml is required for scripts.rules_toggle (frontmatter parsing). "
        "Install with: pip install pyyaml",
        file=sys.stderr,
    )
    raise SystemExit(2) from None


SCHEMA_VERSION = "rules-toggle/v1"
STATE_DIR_NAME = ".ai-playbook"
STATE_FILENAME = "rules-toggle.json"
AUDIT_FILENAME = "rules-toggle-audit.jsonl"
VALID_LAYERS = ("L1", "L2", "L3")
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")

# Per-rule advanced sub-toggles. Hardcoded today because only one rule has
# them; promote to a YAML manifest if the catalogue grows beyond ~5 entries.
# Each entry projects to an env var written into .ai-playbook/feature-flags.env
# by scripts/apply_config.py.
ADVANCED_SUB_TOGGLES: dict[str, list[dict[str, Any]]] = {
    "apply-skill-enforcement": [
        {
            "key": "bash_inspection",
            "label": "Bash command inspection",
            "description": (
                "Inspect Bash commands for write_path mutations "
                "(POSIX redirects + sed -i + python -c + PowerShell Out-File/Set-Content/...)."
            ),
            "env_var": "AIPLAYBOOK_BASH_INSPECTION",
            "default": True,
            "value_on": "1",
            "value_off": "0",
        }
    ],
}


# ---------------------------------------------------------------------------
# Project / playbook discovery (mirrors scripts/caveman/toggle.py)
# ---------------------------------------------------------------------------


def find_playbook_root(start: Path | None = None) -> Path | None:
    """Locate the ai-playbook repo root (contains ``specs/`` + ``scripts/`` + ``schemas/``)."""
    here = (start or Path(__file__)).resolve()
    if here.is_file():
        here = here.parent
    for candidate in (here, *here.parents):
        if (
            (candidate / "specs").is_dir()
            and (candidate / "scripts").is_dir()
            and (candidate / "schemas").is_dir()
        ):
            return candidate
    return None


def find_project_root(start: Path | None = None) -> Path | None:
    """Find the consumer project root (directory containing ``AGENTS.md``)."""
    here = (start or Path.cwd()).resolve()
    if here.is_file():
        here = here.parent
    for candidate in (here, *here.parents):
        if (candidate / "AGENTS.md").is_file():
            return candidate
    return None


def _load_schema() -> dict[str, Any]:
    root = find_playbook_root()
    if root is None:
        raise FileNotFoundError(
            "ai-playbook root not found (need specs/ + scripts/ + schemas/ on parent chain)."
        )
    schema_path = root / "schemas" / "schema-rules-toggle-v1.json"
    if not schema_path.is_file():
        raise FileNotFoundError(f"Schema not found: {schema_path}")
    return json.loads(schema_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# State file IO
# ---------------------------------------------------------------------------


def state_path(project_root: Path) -> Path:
    return project_root / STATE_DIR_NAME / STATE_FILENAME


def audit_path(project_root: Path) -> Path:
    return project_root / STATE_DIR_NAME / AUDIT_FILENAME


def default_state() -> dict[str, Any]:
    """Fresh empty state — all rules implicitly ON."""
    return {
        "schema": SCHEMA_VERSION,
        "applied_at": datetime.now(UTC).isoformat(),
        "rules": {},
    }


def read_state(project_root: Path) -> dict[str, Any]:
    """Read state from disk; return ``default_state()`` if missing.

    Validates against schema either way. Raises ``ValueError`` on malformed
    JSON or schema violation.
    """
    p = state_path(project_root)
    schema = _load_schema()
    if not p.is_file():
        state = default_state()
        jsonschema.validate(state, schema)
        return state
    raw = p.read_text(encoding="utf-8")
    try:
        state = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON in {p}: {e}") from e
    try:
        jsonschema.validate(state, schema)
    except jsonschema.ValidationError as e:
        raise ValueError(f"schema validation failed for {p}: {e.message}") from e
    return state


def write_state(project_root: Path, state: dict[str, Any]) -> None:
    """Validate ``state`` against the schema, then atomic temp+rename write."""
    schema = _load_schema()
    jsonschema.validate(state, schema)
    p = state_path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    fd, tmp_path_str = tempfile.mkstemp(prefix=".rules-toggle-", suffix=".tmp", dir=str(p.parent))
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        if os.name != "nt":
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
        os.replace(tmp_path, p)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def audit_append(project_root: Path, entry: dict[str, Any]) -> None:
    """Append one JSONL line to the audit log. Best-effort — swallows OSError."""
    p = audit_path(project_root)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
        with p.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Toggle resolution (used by L1 hook + scripts/rules/_telemetry.py)
# ---------------------------------------------------------------------------


def is_rule_disabled(
    project_root: Path,
    slug: str,
    *,
    layer: str = "L1",
) -> bool:
    """Return True if ``slug`` is OFF at ``layer`` in the consumer's state.

    Resolution cascade (rule absent or file absent → ON):
        1. No state file or no entry for slug → False (rule ON).
        2. Entry has ``enabled=False`` → True (whole rule OFF).
        3. Entry has ``layers.<layer>=False`` → True (only this layer OFF).
        4. Otherwise → False (rule ON at this layer).

    This function is intentionally small and side-effect-free so it can be
    duplicated verbatim into ``.claude/hooks/openspec-apply-enforce.py``
    (which runs as a PreToolUse subprocess and avoids ``sys.path`` injection).
    """
    if layer not in VALID_LAYERS:
        raise ValueError(f"invalid layer {layer!r}; valid: {VALID_LAYERS}")
    p = state_path(project_root)
    if not p.is_file():
        return False
    try:
        raw = p.read_text(encoding="utf-8")
        state = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        # Fail-safe: corrupt file = treat as absent.
        return False
    entry = (state.get("rules") or {}).get(slug)
    if entry is None:
        return False
    if entry.get("enabled") is False:
        return True
    layers = entry.get("layers") or {}
    return layers.get(layer) is False


# ---------------------------------------------------------------------------
# Inventory generation (consumed by tools/config-ui/)
# ---------------------------------------------------------------------------


def _parse_rule_frontmatter(md_path: Path) -> dict[str, Any] | None:
    """Parse YAML frontmatter from a rule doc; return None on absence/malform."""
    try:
        text = md_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    block = text[3:end].strip()
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _slug_from_filename(p: Path) -> str:
    name = p.name
    for suffix in (".rule.md", ".rule.py", ".rule.yml", ".rule.yaml"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return p.stem


def _extract_description(text: str, max_chars: int = 200) -> str:
    """Take the first non-blank paragraph after the H1 heading; truncate."""
    in_body = False
    paragraph: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not in_body:
            if stripped.startswith("# "):
                in_body = True
            continue
        if not stripped:
            if paragraph:
                break
            continue
        if stripped.startswith(">") or stripped.startswith("#"):
            # Skip blockquotes (META banner) and sub-headings.
            if paragraph:
                break
            continue
        paragraph.append(stripped)
    text_out = " ".join(paragraph).strip()
    if len(text_out) > max_chars:
        text_out = text_out[: max_chars - 1].rstrip() + "…"
    return text_out


def build_rules_inventory(playbook_root: Path | None = None) -> dict[str, Any]:
    """Scan docs/rules/, scripts/rules/, .github/workflows/ → inventory dict."""
    root = playbook_root or find_playbook_root()
    if root is None:
        raise FileNotFoundError("ai-playbook root not found for inventory scan.")

    doc_paths = sorted((root / "docs" / "rules").glob("*.rule.md"))
    script_slugs = {
        _slug_from_filename(p) for p in (root / "scripts" / "rules").glob("*.rule.py")
    }
    workflow_slugs = {
        _slug_from_filename(p) for p in (root / ".github" / "workflows").glob("*.rule.yml")
    }

    rules: list[dict[str, Any]] = []
    for doc in doc_paths:
        slug = _slug_from_filename(doc)
        if not SLUG_RE.match(slug):
            continue
        fm = _parse_rule_frontmatter(doc) or {}
        try:
            body = doc.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            body = ""
        description = fm.get("description") or _extract_description(body)

        break_glass = fm.get("break_glass")
        break_glass_env: str | None = None
        if isinstance(break_glass, dict):
            v = break_glass.get("env")
            if isinstance(v, str):
                break_glass_env = v

        triggers_raw = fm.get("triggers")
        triggers: list[str] = []
        if isinstance(triggers_raw, list):
            triggers = [str(t) for t in triggers_raw if isinstance(t, str)]

        entry = {
            "slug": slug,
            "status": fm.get("status") or "unknown",
            "paired_hardrule": fm.get("paired_hardrule"),
            "has_l1": slug in script_slugs,
            "has_l3": slug in workflow_slugs,
            "break_glass_env": break_glass_env,
            "triggers": triggers,
            "description": description,
            "doc_path": doc.relative_to(root).as_posix(),
        }
        if slug in ADVANCED_SUB_TOGGLES:
            entry["advanced"] = list(ADVANCED_SUB_TOGGLES[slug])
        rules.append(entry)

    rules.sort(key=lambda r: r["slug"])
    return {
        "schema": "rules-inventory/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "rules": rules,
    }


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _emit_error(*, why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def _resolve_project_root(arg_project: Path | None) -> Path | None:
    if arg_project is not None:
        return arg_project.expanduser().resolve()
    return find_project_root()


def _actor() -> str:
    return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


def _rule_known(slug: str, inventory_rules: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    for r in inventory_rules:
        if r["slug"] == slug:
            return r
    return None


def _merge_view(state: dict[str, Any], inventory: dict[str, Any]) -> list[dict[str, Any]]:
    """Project (inventory ∪ state) into a list of per-rule view rows for `list`."""
    overrides = state.get("rules", {})
    rows: list[dict[str, Any]] = []
    for inv in inventory["rules"]:
        slug = inv["slug"]
        override = overrides.get(slug)
        if override is None:
            row = {
                "slug": slug,
                "status": inv["status"],
                "enabled": True,
                "layers": {"L1": True, "L2": True, "L3": True},
                "has_l1": inv["has_l1"],
                "has_l3": inv["has_l3"],
                "advanced": {},
                "reason": None,
                "modified": False,
            }
        else:
            layers = override.get("layers", {}) or {}
            row = {
                "slug": slug,
                "status": inv["status"],
                "enabled": override.get("enabled", True),
                "layers": {
                    "L1": layers.get("L1", override.get("enabled", True)),
                    "L2": layers.get("L2", override.get("enabled", True)),
                    "L3": layers.get("L3", override.get("enabled", True)),
                },
                "has_l1": inv["has_l1"],
                "has_l3": inv["has_l3"],
                "advanced": override.get("advanced", {}) or {},
                "reason": override.get("reason"),
                "modified": True,
            }
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    inventory = build_rules_inventory()
    project = _resolve_project_root(getattr(args, "project", None))
    if project is None:
        # Showing inventory only is still useful; treat all as ON.
        rows = _merge_view(default_state(), inventory)
        if getattr(args, "json", False):
            print(json.dumps({"project_root": None, "rules": rows}, indent=2, ensure_ascii=False))
        else:
            _print_list(rows, project=None)
        return 0
    try:
        state = read_state(project)
    except (ValueError, FileNotFoundError) as e:
        _emit_error(
            why=str(e),
            where=f"rules_toggle:list:{project.as_posix()}",
            fix="repair or delete the corrupt state file and re-run.",
        )
        return 1
    rows = _merge_view(state, inventory)
    if getattr(args, "json", False):
        print(json.dumps({"project_root": project.as_posix(), "rules": rows}, indent=2, ensure_ascii=False))
    else:
        _print_list(rows, project=project)
    return 0


def _print_list(rows: list[dict[str, Any]], project: Path | None) -> None:
    if project is not None:
        print(f"project: {project}")
        print(f"state:   {state_path(project)}")
    print(f"rules:   {len(rows)} total\n")
    for r in rows:
        marker = "·" if not r["modified"] else "⚠"
        on_off = "ON " if r["enabled"] else "OFF"
        l1 = "L1✓" if r["layers"]["L1"] and r["has_l1"] else ("L1·" if r["has_l1"] else "   ")
        l3 = "L3✓" if r["layers"]["L3"] and r["has_l3"] else ("L3·" if r["has_l3"] else "   ")
        if not r["layers"]["L1"] and r["has_l1"]:
            l1 = "L1✗"
        if not r["layers"]["L3"] and r["has_l3"]:
            l3 = "L3✗"
        print(f"  {marker} {on_off}  {l1} {l3}  {r['slug']}  ({r['status']})")
        if r["reason"]:
            print(f"        reason: {r['reason']}")
        if r["advanced"]:
            for k, v in r["advanced"].items():
                print(f"        advanced.{k} = {v}")


def cmd_status(args: argparse.Namespace) -> int:
    slug = args.slug
    layer = args.layer or "L1"
    if layer not in VALID_LAYERS:
        _emit_error(
            why=f"invalid layer {layer!r}",
            where="rules_toggle:status:layer",
            fix=f"--layer must be one of: {', '.join(VALID_LAYERS)}",
        )
        return 1
    project = _resolve_project_root(getattr(args, "project", None))
    if project is None:
        # No project context → treat as ON.
        disabled = False
        state_obj = None
    else:
        try:
            state_obj = read_state(project)
        except (ValueError, FileNotFoundError) as e:
            _emit_error(
                why=str(e),
                where=f"rules_toggle:status:{project.as_posix()}",
                fix="repair or delete the corrupt state file and re-run.",
            )
            return 1
        disabled = is_rule_disabled(project, slug, layer=layer)
    out = {
        "slug": slug,
        "layer": layer,
        "enabled": not disabled,
        "project_root": project.as_posix() if project else None,
    }
    if state_obj is not None:
        out["entry"] = state_obj.get("rules", {}).get(slug)
    if getattr(args, "json", False):
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        on_off = "ON" if out["enabled"] else "OFF"
        print(f"{slug} @ {layer}: {on_off}")
        if out.get("entry"):
            print(f"  entry: {json.dumps(out['entry'], ensure_ascii=False)}")
    if getattr(args, "exit_code", False):
        return 0 if out["enabled"] else 1
    return 0


def _require_known_slug(slug: str) -> tuple[int, dict[str, Any] | None]:
    inventory = build_rules_inventory()
    rule = _rule_known(slug, inventory["rules"])
    if rule is None:
        _emit_error(
            why=f"unknown rule slug {slug!r}",
            where="rules_toggle:slug",
            fix="run `python -m scripts.rules_toggle list` to see available slugs.",
        )
        return 1, None
    return 0, rule


def cmd_on(args: argparse.Namespace) -> int:
    rc, rule = _require_known_slug(args.slug)
    if rc != 0 or rule is None:
        return rc
    project = _resolve_project_root(getattr(args, "project", None))
    if project is None:
        _emit_error(
            why="cannot resolve project root",
            where="rules_toggle:on",
            fix="run from inside a project (AGENTS.md present) or pass --project PATH.",
        )
        return 2
    layer = args.layer
    if layer is not None and layer not in VALID_LAYERS:
        _emit_error(
            why=f"invalid layer {layer!r}",
            where="rules_toggle:on:layer",
            fix=f"--layer must be one of: {', '.join(VALID_LAYERS)}",
        )
        return 1
    try:
        state = read_state(project)
    except (ValueError, FileNotFoundError) as e:
        _emit_error(why=str(e), where="rules_toggle:on:read", fix="repair state file.")
        return 1
    prev_entry = (state.get("rules") or {}).get(args.slug)
    if layer is None:
        # Full re-enable: remove the entire override.
        if "rules" in state and args.slug in state["rules"]:
            del state["rules"][args.slug]
    else:
        # Layer-only: flip a single layer to True; keep others.
        entry = dict(prev_entry) if prev_entry else {"enabled": True}
        layers = dict(entry.get("layers") or {})
        layers[layer] = True
        entry["layers"] = layers
        # If all three layers are now True AND enabled is True, drop the override entirely.
        if entry.get("enabled", True) and all(layers.get(L, True) for L in VALID_LAYERS):
            if "rules" in state and args.slug in state["rules"]:
                del state["rules"][args.slug]
        else:
            state.setdefault("rules", {})[args.slug] = entry
    state["applied_at"] = datetime.now(UTC).isoformat()
    state["applied_by"] = _actor()
    try:
        write_state(project, state)
    except Exception as e:  # noqa: BLE001
        _emit_error(why=f"failed to write state: {e}", where="rules_toggle:on:write", fix="check perms.")
        return 2
    audit_append(project, {
        "ts": state["applied_at"],
        "actor": state["applied_by"],
        "action": "on",
        "slug": args.slug,
        "layer": layer,
        "reason": None,
        "prev_state": prev_entry,
        "new_state": (state.get("rules") or {}).get(args.slug),
    })
    if getattr(args, "json", False):
        print(json.dumps({"ok": True, "slug": args.slug, "layer": layer, "state": state}, indent=2, ensure_ascii=False))
    else:
        scope = layer or "all layers"
        print(f"✅ {args.slug} ON ({scope}) at {project}")
    return 0


def cmd_off(args: argparse.Namespace) -> int:
    rc, rule = _require_known_slug(args.slug)
    if rc != 0 or rule is None:
        return rc
    project = _resolve_project_root(getattr(args, "project", None))
    if project is None:
        _emit_error(
            why="cannot resolve project root",
            where="rules_toggle:off",
            fix="run from inside a project (AGENTS.md present) or pass --project PATH.",
        )
        return 2
    layer = args.layer
    if layer is not None and layer not in VALID_LAYERS:
        _emit_error(
            why=f"invalid layer {layer!r}",
            where="rules_toggle:off:layer",
            fix=f"--layer must be one of: {', '.join(VALID_LAYERS)}",
        )
        return 1
    reason = (args.reason or "").strip() or None
    # If the rule has a break_glass.env declared, persistent disable requires
    # a reason ≥10 chars — same shape as the env-var override contract.
    if rule.get("break_glass_env") and (reason is None or len(reason) < 10):
        _emit_error(
            why=(
                f"rule {args.slug!r} has break_glass_env={rule['break_glass_env']!r}; "
                "persistent disable requires --reason (>=10 chars)"
            ),
            where="rules_toggle:off:reason",
            fix=f"re-run with --reason '<>=10 chars explaining why>'.",
        )
        return 1
    try:
        state = read_state(project)
    except (ValueError, FileNotFoundError) as e:
        _emit_error(why=str(e), where="rules_toggle:off:read", fix="repair state file.")
        return 1
    prev_entry = (state.get("rules") or {}).get(args.slug)
    now_iso = datetime.now(UTC).isoformat()
    if layer is None:
        entry = {
            "enabled": False,
            "reason": reason,
            "disabled_at": now_iso,
        }
        # Preserve advanced sub-toggles across full disable.
        if prev_entry and prev_entry.get("advanced"):
            entry["advanced"] = prev_entry["advanced"]
    else:
        entry = dict(prev_entry) if prev_entry else {"enabled": True}
        layers = dict(entry.get("layers") or {})
        layers[layer] = False
        entry["layers"] = layers
        if reason is not None:
            entry["reason"] = reason
        entry["disabled_at"] = now_iso
    state.setdefault("rules", {})[args.slug] = entry
    state["applied_at"] = now_iso
    state["applied_by"] = _actor()
    try:
        write_state(project, state)
    except Exception as e:  # noqa: BLE001
        _emit_error(why=f"failed to write state: {e}", where="rules_toggle:off:write", fix="check perms.")
        return 2
    audit_append(project, {
        "ts": now_iso,
        "actor": state["applied_by"],
        "action": "off",
        "slug": args.slug,
        "layer": layer,
        "reason": reason,
        "prev_state": prev_entry,
        "new_state": entry,
    })
    if getattr(args, "json", False):
        print(json.dumps({"ok": True, "slug": args.slug, "layer": layer, "state": state}, indent=2, ensure_ascii=False))
    else:
        scope = layer or "all layers"
        print(f"✅ {args.slug} OFF ({scope}) at {project}")
        if reason:
            print(f"   reason: {reason}")
    return 0


def cmd_inventory(args: argparse.Namespace) -> int:
    try:
        inv = build_rules_inventory()
    except FileNotFoundError as e:
        _emit_error(why=str(e), where="rules_toggle:inventory", fix="run from inside ai-playbook checkout.")
        return 2
    out_arg = getattr(args, "output", None)
    if out_arg is None:
        # Default location: tools/config-ui/rules-inventory.json relative to playbook root.
        root = find_playbook_root()
        if root is None:
            _emit_error(why="ai-playbook root not found", where="rules_toggle:inventory:output", fix="pass --output PATH.")
            return 2
        out_path = root / "tools" / "config-ui" / "rules-inventory.json"
    else:
        out_path = Path(out_arg).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(inv, indent=2, sort_keys=False, ensure_ascii=False) + "\n"
    out_path.write_text(body, encoding="utf-8")
    if getattr(args, "json", False):
        print(json.dumps({"ok": True, "output": out_path.as_posix(), "rules_count": len(inv["rules"])}, indent=2, ensure_ascii=False))
    else:
        print(f"✅ wrote {len(inv['rules'])} rules to {out_path}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    project = _resolve_project_root(getattr(args, "project", None))
    if project is None:
        _emit_error(
            why="cannot resolve project root",
            where="rules_toggle:init",
            fix="run from inside a project (AGENTS.md present) or pass --project PATH.",
        )
        return 2
    p = state_path(project)
    if p.is_file() and not args.force:
        _emit_error(
            why=f"state file already exists: {p}",
            where="rules_toggle:init",
            fix="re-run with --force to overwrite, or edit the existing file directly.",
        )
        return 1
    if args.from_path is not None:
        src = Path(args.from_path).expanduser().resolve()
        if not src.is_file():
            _emit_error(why=f"--from path not found: {src}", where="rules_toggle:init:from", fix="check the path.")
            return 1
        try:
            raw = src.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as e:
            _emit_error(why=f"failed to read --from {src}: {e}", where="rules_toggle:init:from", fix="provide valid JSON.")
            return 1
        # Accept either a rules-toggle/v1 state file directly, or an
        # ai-playbook-config/v1 bundle whose `rules{}` field is extracted.
        if data.get("schema") == "ai-playbook-config/v1":
            state = default_state()
            state["rules"] = data.get("rules", {}) or {}
        else:
            state = data
    else:
        state = default_state()
    state["applied_at"] = datetime.now(UTC).isoformat()
    state["applied_by"] = _actor()
    try:
        write_state(project, state)
    except Exception as e:  # noqa: BLE001
        _emit_error(why=f"failed to write state: {e}", where="rules_toggle:init:write", fix="check perms.")
        return 2
    if getattr(args, "json", False):
        print(json.dumps({"ok": True, "state_path": p.as_posix(), "rules_count": len(state.get("rules") or {})}, indent=2, ensure_ascii=False))
    else:
        print(f"✅ initialized {p}")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Toggle ai-playbook rules per-consumer (state at .ai-playbook/rules-toggle.json).",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Project root override (default: auto-discover by walking up for AGENTS.md).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List all rules + current state.")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_status = sub.add_parser("status", help="Show state for one rule.")
    p_status.add_argument("--slug", required=True)
    p_status.add_argument("--layer", choices=VALID_LAYERS, default="L1")
    p_status.add_argument("--exit-code", action="store_true", help="Exit 0 if ON, 1 if OFF (for CI gates).")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_on = sub.add_parser("on", help="Enable a rule (optionally one layer).")
    p_on.add_argument("slug")
    p_on.add_argument("--layer", choices=VALID_LAYERS, default=None)
    p_on.add_argument("--json", action="store_true")
    p_on.set_defaults(func=cmd_on)

    p_off = sub.add_parser("off", help="Disable a rule (optionally one layer).")
    p_off.add_argument("slug")
    p_off.add_argument("--layer", choices=VALID_LAYERS, default=None)
    p_off.add_argument("--reason", default=None, help="Required for rules with break_glass.env (>=10 chars).")
    p_off.add_argument("--json", action="store_true")
    p_off.set_defaults(func=cmd_off)

    p_inv = sub.add_parser("inventory", help="Re-scan rules and write rules-inventory.json.")
    p_inv.add_argument("--output", default=None, help="Override default tools/config-ui/rules-inventory.json path.")
    p_inv.add_argument("--json", action="store_true")
    p_inv.set_defaults(func=cmd_inventory)

    p_init = sub.add_parser("init", help="Initialise an empty rules-toggle.json (or import from a bundle).")
    p_init.add_argument("--from", dest="from_path", default=None, help="Import from an existing state file or bundle JSON.")
    p_init.add_argument("--force", action="store_true", help="Overwrite an existing state file.")
    p_init.add_argument("--json", action="store_true")
    p_init.set_defaults(func=cmd_init)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
