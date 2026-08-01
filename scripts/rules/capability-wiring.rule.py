"""L1 hardrule: capability-wiring.

Paired with docs/rules/capability-wiring.rule.md.
Contract: specs/wiring-assertions.schema.yaml (field-by-field).
Taxonomy: docs/concepts/code-entropy.md, axis 4 `unwired-capability`.

WHAT THIS DETECTS
A capability that was BUILT but never WIRED into the registry that makes it
reachable. The code exists, imports cleanly, type-checks, and is dead.

Precedent (geeplo `47717de3`): `app.tasks.heartbeat_tasks.emit_liveness_heartbeat`
existed, was imported, and had a `beat_schedule` entry — but no `task_routes`
entry, so Beat published it to `default` instead of `scheduled`. Nothing was
missing; nothing was broken; one line of registry was absent.

THE GENERALISATION
Every assertion of that class is the same sentence with different holes:

    "every <file-or-symbol matching X> must be referenced in <registry Z>
     by <pattern Y>"

The engine ships once, here. The holes are per-consumer data and live in the
consumer's `wiring.yaml`. Adding a detector is six lines of YAML, never code.

The engine is STATIC — glob + `ast` + regex. It never imports the code under
inspection, because an unwired capability is frequently one that cannot be
imported in isolation. It needs no venv, no broker and no database, so it runs
identically in pre-commit, in CI, and in an agent self-check.

CLI:
    capability-wiring.rule.py check   [--config P] [--json] [--changed-only] [--assertion ID]
    capability-wiring.rule.py explain <assertion-id> [--config P]
    capability-wiring.rule.py validate [--config P]

Exit codes:
    0 — clean (or no `wiring.yaml` in this consumer).
    1 — at least one S1/S2 finding from an `enforced` assertion.
    2 — CONFIG ERROR: bad schema_version, glob matching zero items, missing
        registry, unknown interpolation token, unparseable regex, stale `allow`.
        Distinct from 1 on purpose — a broken contract must never be reported
        as a clean repo.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment guard
    print("FATAL: pyyaml not installed. Run `pip install pyyaml`.", file=sys.stderr)
    raise SystemExit(2) from exc

# This file is executed by PATH (pre-commit, CI) and loaded by
# `spec_from_file_location` (tests). Neither puts the playbook root on
# `sys.path`, so make the sibling helper importable by its own directory rather
# than by package path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _rule_kit import (  # noqa: E402  (deliberate: needs the sys.path line above)
    BLOCKING,
    SEVERITIES,
    TOKEN_RE as _TOKEN_RE,
    ConfigError,
    allow_matches as _allow_matches,
    changed_files as _changed_files,
    compile_flags,
    emit_error as _emit_error,
    expand_glob,
    find_consumer_root as _find_consumer_root,
    interpolate,
    line_of,
    resolve_config as _resolve_config,
    skip_directive as _skip_directive,
    used_tokens,
)

SKIP_ENV = "AIPLAYBOOK_WIRING_SKIP"
SCHEMA_CONST = "ai-playbook/wiring-assertions/v1"
ENGINE_MAJOR = 1
CONFIG_NAME = "wiring.yaml"

# Interpolation tokens. Deliberately a closed set: an unknown `{token}` is a
# config error, never an empty substitution. Substituting empty would widen the
# regex enormously and report a permanent, silent green — the exact failure this
# rule exists to prevent.
TOKENS = ("path", "name", "stem", "dir", "symbol", "capture")


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolPattern:
    decorator: str | None
    kind: str
    name: str  # a name-glob, except for `member` where it is the CONTAINER name


KINDS = ("def", "class", "const", "member", "export", "any")


def parse_symbol_pattern(raw: str) -> SymbolPattern:
    """`[ "@" <decorator-glob> WS ] <kind> ":" <name-glob>`."""
    text = raw.strip()
    decorator = None
    if text.startswith("@"):
        deco, _, rest = text.partition(" ")
        decorator = deco[1:]
        text = rest.strip()
        if not text:
            raise ConfigError(f"symbol pattern {raw!r} has a decorator but no <kind>:<name>")
    kind, sep, name = text.partition(":")
    if not sep:
        raise ConfigError(f"symbol pattern {raw!r} is missing the `<kind>:<name>` colon")
    kind, name = kind.strip(), name.strip()
    if kind not in KINDS:
        raise ConfigError(f"symbol pattern {raw!r}: unknown kind {kind!r} (expected one of {', '.join(KINDS)})")
    if not name:
        raise ConfigError(f"symbol pattern {raw!r} has an empty name")
    return SymbolPattern(decorator, kind, name)


def _decorator_source(node: ast.expr) -> str:
    try:
        text = ast.unparse(node)
    except Exception:  # noqa: BLE001 - unparse is best-effort on exotic nodes
        return ""
    return " ".join(text.split())


def _decorator_matches(node: ast.AST, glob: str) -> bool:
    decorators = getattr(node, "decorator_list", [])
    return any(fnmatch(_decorator_source(d), glob) for d in decorators)


def _literal_members(value: ast.expr) -> list[str]:
    if isinstance(value, (ast.Tuple, ast.List, ast.Set)):
        return [e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    if isinstance(value, ast.Dict):
        return [k.value for k in value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    return []


def _python_symbols(text: str, pat: SymbolPattern) -> list[str]:
    tree = ast.parse(text)

    if pat.kind == "member":
        for node in tree.body:
            targets = (
                node.targets if isinstance(node, ast.Assign)
                else [node.target] if isinstance(node, ast.AnnAssign)
                else []
            )
            if any(isinstance(t, ast.Name) and t.id == pat.name for t in targets) and node.value is not None:
                return _literal_members(node.value)
            # An Enum class: each member contributes its string value when it
            # has one, else its attribute name.
            if isinstance(node, ast.ClassDef) and node.name == pat.name:
                out: list[str] = []
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                        val = stmt.value
                        out.append(
                            val.value if isinstance(val, ast.Constant) and isinstance(val.value, str)
                            else stmt.targets[0].id
                        )
                return out
        return []

    names: list[str] = []
    for node in tree.body:
        if pat.kind in ("def", "any") and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if pat.decorator is None or _decorator_matches(node, pat.decorator):
                names.append(node.name)
        elif pat.kind in ("class", "any") and isinstance(node, ast.ClassDef):
            if pat.decorator is None or _decorator_matches(node, pat.decorator):
                names.append(node.name)
        elif pat.kind in ("const", "any"):
            if isinstance(node, ast.Assign):
                names.extend(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.append(node.target.id)
    return [n for n in names if fnmatch(n, pat.name)]


_TS_EXPORT_RE = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:async\s+)?(?:const|let|var|function\*?|class|interface|type|enum)\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)
_TS_EXPORT_LIST_RE = re.compile(r"^\s*export\s*\{([^}]*)\}", re.MULTILINE)
_TS_DECL_RE = {
    "def": re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\*?\s+([A-Za-z_$][\w$]*)", re.MULTILINE),
    "class": re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)", re.MULTILINE),
    "const": re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)", re.MULTILINE),
}


def _ts_symbols(text: str, pat: SymbolPattern) -> list[str]:
    """Line-shaped declaration scan. No TS parser is available in this runtime,
    and shelling out to one would break the "runs anywhere, no toolchain"
    property that makes this rule usable in pre-commit."""
    names: list[str] = []
    if pat.kind in ("export", "any"):
        names.extend(_TS_EXPORT_RE.findall(text))
        for group in _TS_EXPORT_LIST_RE.findall(text):
            for part in group.split(","):
                token = part.strip().split(" as ")[-1].strip()
                if token and token != "default":
                    names.append(token)
    if pat.kind == "member":
        # `const NAME = [...]` / `{...}` — string literals inside the named
        # container, matched textually because there is no AST here.
        block = re.search(
            rf"\b{re.escape(pat.name)}\b[^=]*=\s*([\[\{{])",
            text,
        )
        if block is None:
            return []
        opener = block.group(1)
        closer = "]" if opener == "[" else "}"
        depth, start = 0, block.end() - 1
        end = len(text)
        for idx in range(start, len(text)):
            if text[idx] == opener:
                depth += 1
            elif text[idx] == closer:
                depth -= 1
                if depth == 0:
                    end = idx
                    break
        return re.findall(r"['\"]([^'\"]+)['\"]", text[start:end])
    for kind, rx in _TS_DECL_RE.items():
        if pat.kind in (kind, "any"):
            names.extend(rx.findall(text))
    return [n for n in dict.fromkeys(names) if fnmatch(n, pat.name)]


def extract_symbols(path: Path, rel: str, pat: SymbolPattern) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if rel.endswith(".py"):
        try:
            return _python_symbols(text, pat)
        except SyntaxError:
            return []
    if pat.decorator is not None:
        print(f"⚠ wiring: decorator filter ignored for non-Python file {rel}", file=sys.stderr)
    return _ts_symbols(text, pat)


# ---------------------------------------------------------------------------
# Items and interpolation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    path: str
    symbol: str | None = None
    capture: str | None = None

    @property
    def item_id(self) -> str:
        return f"{self.path}::{self.symbol}" if self.symbol is not None else self.path

    def bindings(self) -> dict[str, str]:
        name = self.path.rsplit("/", 1)[-1]
        stem = name.rsplit(".", 1)[0] if "." in name else name
        parent = self.path.rsplit("/", 2)[-2] if "/" in self.path else ""
        out = {"path": self.path, "name": name, "stem": stem, "dir": parent}
        if self.symbol is not None:
            out["symbol"] = self.symbol
        if self.capture is not None:
            out["capture"] = self.capture
        return out


# ---------------------------------------------------------------------------
# Config loading + validation
# ---------------------------------------------------------------------------

_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_ASSERTION_DEFAULTS: dict[str, Any] = {
    "exclude": [],
    "flags": "m",
    "expect": "at_least_one",
    "unreferenced_max": 0,
    "exclude_self": True,
    "orphan_direction": "forward",
    "status": "enforced",
    "allow": [],
}

# Defaulting `by` or `every` globally is refused: a silent global pattern is
# unreviewable, and these two fields are the whole meaning of an assertion.
_UNDEFAULTABLE = ("by", "every", "id", "description", "referenced_in", "capture")


def load_config(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} is not a mapping — not a wiring-assertions file")
    if raw.get("schema") != SCHEMA_CONST:
        raise ConfigError(f"{path}: not a wiring-assertions file (schema != {SCHEMA_CONST})")

    version = raw.get("schema_version")
    if not isinstance(version, str) or not _SEMVER_RE.match(version):
        raise ConfigError(f"{path}: schema_version must be MAJOR.MINOR.PATCH, got {version!r}")
    if int(version.split(".")[0]) > ENGINE_MAJOR:
        raise ConfigError(
            f"unsupported schema_version {version} (engine supports {ENGINE_MAJOR}.x)"
        )

    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError(f"{path}: `defaults` must be a mapping")
    for key in _UNDEFAULTABLE:
        if key in defaults:
            raise ConfigError(f"{path}: `{key}` may not be set in `defaults`")

    assertions = raw.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        # An empty list is a broken adoption, not a clean repo.
        raise ConfigError(f"{path}: `assertions` must be a non-empty list")

    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for index, entry in enumerate(assertions):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: assertion #{index} is not a mapping")
        item = {**_ASSERTION_DEFAULTS, **defaults, **entry}
        _validate_assertion(item, index, seen)
        merged.append(item)

    raw["assertions"] = merged
    raw.setdefault("root", ".")
    return raw


def _validate_assertion(entry: dict[str, Any], index: int, seen: set[str]) -> None:
    aid = entry.get("id")
    if not isinstance(aid, str) or not _ID_RE.match(aid):
        raise ConfigError(f"assertion #{index}: `id` must match {_ID_RE.pattern}, got {aid!r}")
    if aid in seen:
        raise ConfigError(f"duplicate assertion id {aid!r}")
    seen.add(aid)

    for required in ("description", "every", "referenced_in", "by", "severity"):
        if not entry.get(required):
            raise ConfigError(f"assertion '{aid}': `{required}` is required")

    severity = entry["severity"]
    if severity not in SEVERITIES:
        # S0 is retro-only, exactly as verdict-contract rejects it outside --audit.
        raise ConfigError(f"assertion '{aid}': severity {severity!r} not in {SEVERITIES}")
    if entry["status"] not in ("enforced", "advisory"):
        raise ConfigError(f"assertion '{aid}': status must be enforced|advisory")
    if entry["expect"] not in ("at_least_one", "exactly_one"):
        raise ConfigError(f"assertion '{aid}': expect must be at_least_one|exactly_one")
    if entry["orphan_direction"] not in ("forward", "both"):
        raise ConfigError(f"assertion '{aid}': orphan_direction must be forward|both")
    if not isinstance(entry["unreferenced_max"], int) or entry["unreferenced_max"] < 0:
        raise ConfigError(f"assertion '{aid}': unreferenced_max must be a non-negative integer")

    compile_flags(entry["flags"])

    has_symbol = "::" in entry["every"]
    if has_symbol:
        parse_symbol_pattern(entry["every"].split("::", 1)[1])
    for token in used_tokens(entry["by"]):
        if token not in TOKENS:
            raise ConfigError(f"assertion '{aid}': unknown interpolation token {{{token}}} in `by`")
        if token == "symbol" and not has_symbol:
            raise ConfigError(f"assertion '{aid}': `by` uses {{symbol}} but `every` has no `::` suffix")
        if token == "capture" and not entry.get("capture"):
            raise ConfigError(f"assertion '{aid}': `by` uses {{capture}} but no `capture` regex is set")

    if entry.get("capture"):
        try:
            captured = re.compile(entry["capture"], compile_flags(entry["flags"]))
        except re.error as exc:
            raise ConfigError(f"assertion '{aid}': `capture` is not a valid regex: {exc}") from exc
        if "value" not in captured.groupindex:
            raise ConfigError(f"assertion '{aid}': `capture` must define the named group `value`")

    for allow in entry["allow"]:
        if not isinstance(allow, dict) or not allow.get("match") or not allow.get("reason"):
            raise ConfigError(f"assertion '{aid}': every `allow` entry needs `match` and `reason`")
        expires = allow.get("expires")
        if expires is not None and not _DATE_RE.match(str(expires)):
            raise ConfigError(f"assertion '{aid}': allow `expires` must be YYYY-MM-DD, got {expires!r}")


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    assertion: str
    item: str
    severity: str
    status: str
    kind: str  # unreferenced | capture-failed | symbol-selector-empty |
               # duplicate-reference | orphan-registry-entry | expired-exemption
    detail: str

    def render(self, registry: str, description: str) -> str:
        # Path first so editors linkify it; one greppable line per finding.
        return f"{self.item}: {self.severity} [{self.assertion}] {self.detail} {registry} — {description}"


@dataclass
class AssertionResult:
    assertion_id: str
    severity: str
    status: str
    population: int
    referenced: int
    unreferenced: list[str] = field(default_factory=list)
    allowed: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def build_population(
    root: Path, entry: dict[str, Any], changed: set[str] | None
) -> tuple[list[Item], list[Finding], int]:
    """Expand `every` (minus `exclude`) into items. Returns (items, findings, raw_file_count)."""
    aid = entry["id"]
    spec = entry["every"]
    glob, _, symbol_spec = spec.partition("::")
    files = expand_glob(root, glob)
    for pattern in entry["exclude"]:
        excluded = set(expand_glob(root, pattern))
        files = [f for f in files if f not in excluded]

    raw_count = len(files)
    if changed is not None:
        files = [f for f in files if f in changed]

    capture_rx = (
        re.compile(entry["capture"], compile_flags(entry["flags"])) if entry.get("capture") else None
    )
    pattern = parse_symbol_pattern(symbol_spec) if symbol_spec else None

    items: list[Item] = []
    findings: list[Finding] = []
    for rel in files:
        path = root / rel
        captured: str | None = None
        if capture_rx is not None:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                text = ""
            match = capture_rx.search(text)
            if match is None:
                # Never skipped: a file whose identity cannot be read is exactly
                # the file most likely to be unwired.
                findings.append(Finding(
                    aid, rel, entry["severity"], entry["status"], "capture-failed",
                    "capture regex found no `value` group in this file",
                ))
                continue
            captured = match.group("value")

        if pattern is None:
            items.append(Item(rel, None, captured))
            continue

        symbols = extract_symbols(path, rel, pattern)
        if not symbols and pattern.kind == "member":
            findings.append(Finding(
                aid, rel, entry["severity"], entry["status"], "symbol-selector-empty",
                f"container `{pattern.name}` is absent or holds no string literals",
            ))
            continue
        items.extend(Item(rel, sym, captured) for sym in symbols)

    return items, findings, raw_count


def evaluate(
    root: Path,
    entry: dict[str, Any],
    changed: set[str] | None = None,
    today: date | None = None,
) -> AssertionResult:
    aid = entry["id"]
    flags = compile_flags(entry["flags"])
    today = today or date.today()

    registries = expand_glob(root, entry["referenced_in"])
    if not registries:
        # A missing registry would make every item unreferenced and fire the
        # whole population at once. That is a config error, not N findings.
        raise ConfigError(
            f"assertion '{aid}': referenced_in {entry['referenced_in']!r} matched no file"
        )

    items, findings, raw_count = build_population(root, entry, changed)
    if changed is None and raw_count == 0:
        # A detector that silently inspects nothing reports green forever.
        raise ConfigError(f"assertion '{aid}' matched 0 items — dead assertion")

    texts = {}
    for rel in registries:
        try:
            texts[rel] = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            texts[rel] = ""

    result = AssertionResult(aid, entry["severity"], entry["status"], len(items), 0)
    result.findings.extend(findings)

    unreferenced: list[Item] = []
    for item in items:
        rx = re.compile(interpolate(entry["by"], item.bindings()), flags)
        hits = 0
        for rel, text in texts.items():
            if entry["exclude_self"] and rel == item.path:
                continue
            hits += sum(1 for _ in rx.finditer(text))
        if hits == 0:
            unreferenced.append(item)
        elif entry["expect"] == "exactly_one" and hits != 1:
            result.referenced += 1
            result.findings.append(Finding(
                aid, item.item_id, entry["severity"], entry["status"], "duplicate-reference",
                f"expected exactly one reference, found {hits}",
            ))
        else:
            result.referenced += 1

    # `allow` — reviewed exceptions, subtracted before the tolerance.
    used: set[int] = set()
    survivors: list[Item] = []
    for item in unreferenced:
        exempt = False
        for index, allow in enumerate(entry["allow"]):
            if not _allow_matches(str(allow["match"]), item.item_id):
                continue
            used.add(index)
            expires = allow.get("expires")
            if expires and str(expires) < today.isoformat():
                result.findings.append(Finding(
                    aid, item.item_id, entry["severity"], entry["status"], "expired-exemption",
                    f"not referenced — expired exemption (expired {expires})",
                ))
                exempt = True
                break
            result.allowed.append(item.item_id)
            exempt = True
            break
        if not exempt:
            survivors.append(item)

    for index, allow in enumerate(entry["allow"]):
        if index in used:
            continue
        # An allow may legitimately point at an item that got wired since. Only
        # an entry matching NOTHING in the population is stale — a rotting
        # exception must break the build, or the ruleset drifts into fiction.
        if not any(_allow_matches(str(allow["match"]), i.item_id) for i in items):
            if changed is not None:
                continue  # --changed-only sees a partial population; not evidence
            raise ConfigError(
                f"assertion '{aid}': stale allow entry {allow['match']!r} — matches no item"
            )
        result.notes.append(f"allow entry {allow['match']!r} is now referenced (exemption unnecessary)")

    result.unreferenced = [i.item_id for i in survivors]
    tolerance = entry["unreferenced_max"]
    excess = len(survivors) - tolerance
    if excess > 0:
        # Every unreferenced item is listed as a finding, not just the `excess`
        # of them: with a tolerance in play (a chain tip) you cannot tell which
        # item is the legitimate one without seeing them all. `excess` is what
        # drives the exit code; the lines are what make it fixable.
        for item in survivors:
            result.findings.append(Finding(
                aid, item.item_id, entry["severity"], entry["status"], "unreferenced",
                "not referenced in",
            ))
    elif survivors:
        result.notes.append(
            f"{len(survivors)} unreferenced within tolerance {tolerance}: {', '.join(result.unreferenced)}"
        )

    if entry["orphan_direction"] == "both":
        result.findings.extend(_orphan_registry_entries(entry, items, texts, flags))

    return result


def _orphan_registry_entries(
    entry: dict[str, Any], items: list[Item], texts: dict[str, str], flags: int
) -> list[Finding]:
    """Reverse direction: a registry entry whose capability no longer exists."""
    probe_src = _TOKEN_RE.sub(lambda m: r"[A-Za-z0-9_.-]+", entry["by"])
    try:
        probe = re.compile(probe_src, flags)
    except re.error as exc:
        raise ConfigError(f"assertion '{entry['id']}': orphan probe is not a valid regex: {exc}") from exc

    live = [re.compile(interpolate(entry["by"], i.bindings()), flags) for i in items]
    out: list[Finding] = []
    for rel, text in texts.items():
        for match in probe.finditer(text):
            span = match.group(0)
            if any(rx.search(span) for rx in live):
                continue
            out.append(Finding(
                entry["id"], f"{rel}:{line_of(text, match.start())}", entry["severity"],
                entry["status"], "orphan-registry-entry",
                f"registry entry {span.strip()!r} matches no capability in the population",
            ))
    return out


# ---------------------------------------------------------------------------
# Config discovery + git
# ---------------------------------------------------------------------------


def find_consumer_root(start: Path) -> Path:
    return _find_consumer_root(start, CONFIG_NAME)


def resolve_config(explicit: str | None) -> Path | None:
    return _resolve_config(explicit, CONFIG_NAME)


def changed_files(root: Path) -> set[str]:
    return _changed_files(root)


def _skipped_ids() -> tuple[bool, set[str]]:
    return _skip_directive(SKIP_ENV)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def _load(explicit: str | None) -> tuple[Path, Path, dict[str, Any]] | None:
    config_path = resolve_config(explicit)
    if config_path is None:
        print("ℹ wiring: no wiring.yaml in this consumer — nothing to check.")
        return None
    if not config_path.is_file():
        raise ConfigError(f"config {config_path} does not exist")
    config = load_config(config_path)
    root = (config_path.parent / config["root"]).resolve()
    if not root.is_dir():
        raise ConfigError(f"root {config['root']!r} does not exist (resolved to {root})")
    return config_path, root, config


def cmd_check(args: argparse.Namespace) -> int:
    skip_all, skip_ids = _skipped_ids()
    if skip_all:
        print(f"⚠ capability_wiring: entire run skipped via {SKIP_ENV}", file=sys.stderr)
        return 0

    loaded = _load(args.config)
    if loaded is None:
        return 0
    config_path, root, config = loaded

    changed = changed_files(root) if args.changed_only else None
    results: list[AssertionResult] = []
    registries: dict[str, str] = {}
    descriptions: dict[str, str] = {}

    for entry in config["assertions"]:
        if args.assertion and entry["id"] != args.assertion:
            continue
        if entry["id"] in skip_ids:
            print(f"⚠ capability_wiring: assertion '{entry['id']}' skipped via {SKIP_ENV}", file=sys.stderr)
            continue
        registries[entry["id"]] = entry["referenced_in"]
        descriptions[entry["id"]] = " ".join(str(entry["description"]).split())
        results.append(evaluate(root, entry, changed))

    if args.assertion and not results and args.assertion not in skip_ids:
        raise ConfigError(f"no assertion with id {args.assertion!r} in {config_path}")

    blocking = [
        f for r in results for f in r.findings
        if f.status == "enforced" and f.severity in BLOCKING
    ]

    if args.as_json:
        print(json.dumps({
            "config": str(config_path),
            "assertions": [
                {
                    "id": r.assertion_id, "severity": r.severity, "status": r.status,
                    "population": r.population, "referenced": r.referenced,
                    "unreferenced": r.unreferenced, "allowed": r.allowed,
                    "notes": r.notes,
                    "findings": [
                        {"item": f.item, "kind": f.kind, "severity": f.severity,
                         "status": f.status, "detail": f.detail}
                        for f in r.findings
                    ],
                }
                for r in results
            ],
            "blocking": len(blocking),
        }, indent=2))
    else:
        # Findings are data and go to stdout uniformly, so one grep catches them
        # all regardless of severity. Only the diagnostic block goes to stderr —
        # and it names the blocking items, so a log that captured stderr alone is
        # still actionable.
        for result in results:
            for note in result.notes:
                print(f"ℹ [{result.assertion_id}] {note}")
            for finding in result.findings:
                print(finding.render(registries[finding.assertion], descriptions[finding.assertion]))

    if blocking:
        items = ", ".join(sorted({f.item for f in blocking}))
        noun = "capability" if len(blocking) == 1 else "capabilities"
        _emit_error(
            why=f"{len(blocking)} {noun} built but never wired: {items}",
            where=str(config_path),
            fix=(
                "add the missing registry entry in this same commit, or — if the item is "
                "correctly absent — add an `allow` entry naming the alternative wiring. "
                "Run `capability-wiring.rule.py explain <id>` to see the exact regex and "
                "the registry lines it matched."
            ),
            override=f"{SKIP_ENV}=1 or {SKIP_ENV}=<assertion-id>",
        )
        return 1

    if not args.as_json:
        total = sum(r.population for r in results)
        print(f"capability-wiring: OK — {len(results)} assertion(s), {total} item(s) checked")
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    loaded = _load(args.config)
    if loaded is None:
        return 0
    config_path, root, config = loaded

    entry = next((a for a in config["assertions"] if a["id"] == args.assertion_id), None)
    if entry is None:
        raise ConfigError(f"no assertion with id {args.assertion_id!r} in {config_path}")

    flags = compile_flags(entry["flags"])
    registries = expand_glob(root, entry["referenced_in"])
    if not registries:
        raise ConfigError(f"assertion '{entry['id']}': referenced_in matched no file")
    texts = {rel: (root / rel).read_text(encoding="utf-8", errors="replace") for rel in registries}
    items, findings, _ = build_population(root, entry, None)

    print(f"# {entry['id']}  [{entry['severity']}/{entry['status']}]")
    print(f"  every        : {entry['every']}")
    print(f"  referenced_in: {entry['referenced_in']}  ({len(registries)} file(s))")
    print(f"  by           : {' '.join(str(entry['by']).split())}")
    print(f"  population   : {len(items)} item(s)")
    print()

    allowed = {
        i.item_id for i in items
        for a in entry["allow"] if _allow_matches(str(a["match"]), i.item_id)
    }
    unproven = 0
    for item in items:
        rendered = interpolate(entry["by"], item.bindings())
        rx = re.compile(rendered, flags)
        proof: str | None = None
        for rel, text in texts.items():
            if entry["exclude_self"] and rel == item.path:
                continue
            match = rx.search(text)
            if match:
                first = line_of(text, match.start())
                last = line_of(text, max(match.start(), match.end() - 1))
                lines = text.splitlines()
                # Quote the LAST line of the match, not the first. A `by` is
                # typically anchored on the registry construct and ends on the
                # entry itself, so the closing line is the one that proves the
                # item is registered; the opening line proves only that the
                # registry exists.
                where = f"{rel}:{first}" if first == last else f"{rel}:{first}-{last}"
                proof = f"{where}: {lines[last - 1].strip()}"
                break
        if proof:
            print(f"✓ {item.item_id}\n    {proof}")
        elif item.item_id in allowed:
            print(f"· {item.item_id}\n    (allowed) no match for: {' '.join(rendered.split())}")
        else:
            unproven += 1
            print(f"✗ {item.item_id}\n    NO MATCH for: {' '.join(rendered.split())}")

    for finding in findings:
        print(f"! {finding.item}\n    {finding.kind}: {finding.detail}")

    print()
    print(f"authoring gate: {len(items) - unproven - len(allowed)} proven, {len(allowed)} allowed, {unproven} unproven")
    if unproven:
        print(
            "  A `by` merged without a real matched line is unreviewable — the reviewer "
            "cannot tell a working regex from one that matches nothing forever.",
        )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    loaded = _load(args.config)
    if loaded is None:
        return 0
    config_path, _, config = loaded
    print(f"capability-wiring: {config_path} OK — {len(config['assertions'])} assertion(s), "
          f"schema_version {config['schema_version']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="capability-wiring")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    check = sub.add_parser("check", help="evaluate every assertion against the tree")
    check.add_argument("--config", default=None)
    check.add_argument("--json", action="store_true", dest="as_json")
    check.add_argument(
        "--changed-only", action="store_true",
        help=(
            "restrict the POPULATION to changed files. Registries are always read in "
            "full — a run that only read changed registries would miss the case where "
            "the capability is the changed file and the registry is untouched, which "
            "is the entire bug class."
        ),
    )
    check.add_argument("--assertion", default=None)
    check.set_defaults(func=cmd_check)

    explain = sub.add_parser("explain", help="print the interpolated regex and its proof per item")
    explain.add_argument("assertion_id")
    explain.add_argument("--config", default=None)
    explain.set_defaults(func=cmd_explain)

    validate = sub.add_parser("validate", help="lint the config only; no repo scan")
    validate.add_argument("--config", default=None)
    validate.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        _emit_error(
            why=f"wiring config error: {exc}",
            where=str(args.config or "wiring.yaml"),
            fix="fix the contract. An unevaluable contract must never be reported as a clean repo.",
            override=f"{SKIP_ENV}=1",
        )
        return 2


if __name__ == "__main__":
    from pathlib import Path as _Path

    sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit

    raise SystemExit(cli_emit("capability-wiring", main))
