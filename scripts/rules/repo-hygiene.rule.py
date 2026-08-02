"""L1 hardrule: repo-hygiene.

Paired with docs/rules/repo-hygiene.rule.md.
Contract: specs/repo-hygiene.schema.yaml (field-by-field).
Taxonomy: docs/concepts/code-entropy.md, axes 3 `unused-dependency` and
5 `disk-residue`.

WHAT THIS DETECTS
  axis 3 — a package declared in a manifest that nothing in the tree uses.
  axis 5 — a generated artefact that is STALE, or COMMITTABLE (untracked and
           unignored, so the next `git add -A` sweeps it into the repo).

WHY THE OBVIOUS DETECTOR IS THE WRONG ONE
Both were measured against geeplo before this engine was written, and both
naive detectors failed:

  `declared − imported` gave 16 candidates, all 16 false positives — five ways a
  package is legitimately used without being imported by name. The dangerous one
  was `scikit-learn`: no line imports it; it loads when `joblib.load()`
  deserialises the vendored pipeline in the piracy detector, so deleting it
  would have broken piracy detection only when that path ran.

  The artefact's own mtime gave a PERMANENT false STALE. `graphify update .`
  re-reads 3810 files, finds no topology change, and deliberately leaves
  `graph.json` untouched; only `manifest.json` moves.

So "used" is a DISJUNCTION OF DECLARED CHANNELS and "fresh" is a DECLARED
SIGNAL. Both are consumer data. The engine ships once; adding a detector is
YAML, never code.

THIS RULE NEVER DELETES ANYTHING.
No delete path exists, not even behind a flag. The verdicts are `unused`,
`stale`, `committable`, `tracked` — never `deletable`. The ledger is the
deliverable and a human decides. Precedent: `cleanup-zombies` v0.19.29 shipped a
Tier-1 auto-delete and destroyed 623 lines of live code.

CLI:
    repo-hygiene.rule.py check   [--config P] [--json] [--changed-only] [--check ID] [--max N]
    repo-hygiene.rule.py explain <check-id> [--config P]
    repo-hygiene.rule.py validate [--config P]

Exit codes:
    0 — clean (or no `repo-hygiene.yaml` in this consumer).
    1 — at least one S1/S2 finding from an `enforced` check.
    2 — CONFIG ERROR: bad schema_version, missing manifest, empty corpus,
        unknown format, stale `allow`, unparseable regex. Distinct from 1 on
        purpose — a broken contract must never be reported as a clean repo.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment guard
    print("FATAL: pyyaml not installed. Run `pip install pyyaml`.", file=sys.stderr)
    raise SystemExit(2) from exc

# Executed by path (pre-commit, CI) and loaded by `spec_from_file_location`
# (tests). Neither puts the playbook root on `sys.path`, so make the sibling
# helper importable by its own directory. See capability-wiring.rule.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _rule_kit import (  # noqa: E402  (deliberate: needs the sys.path line above)
    BLOCKING,
    SEVERITIES,
    ConfigError,
    allow_matches,
    changed_files,
    compile_flags,
    emit_error,
    expand_glob,
    find_consumer_root,
    interpolate,
    resolve_config,
    skip_directive,
    used_tokens,
)

SKIP_ENV = "AIPLAYBOOK_HYGIENE_SKIP"
SCHEMA_CONST = "ai-playbook/repo-hygiene/v1"
ENGINE_MAJOR = 1
CONFIG_NAME = "repo-hygiene.yaml"

FORMATS = ("requirements-txt", "package-json", "pyproject")
CHANNEL_KINDS = ("import", "search")
LANGUAGES = ("python", "typescript")

# Closed set, as in capability-wiring: an unknown `{token}` is a config error,
# never an empty substitution. Substituting empty would widen the regex
# enormously and report a permanent, silent green.
TOKENS = ("dist", "module")

_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_PY_SUFFIXES = (".py", ".pyi")


# ---------------------------------------------------------------------------
# Manifest parsing — the POPULATION
# ---------------------------------------------------------------------------


def _strip_requirement(line: str) -> str:
    """Reduce one requirements.txt line to its distribution name, or ''.

    Handles comments, `-r`/`-c`/`-e` directives, environment markers, extras,
    version specifiers, and PEP 508 direct references (`pkg @ https://...`).
    """
    line = line.split("#", 1)[0].strip()
    if not line or line.startswith("-"):
        return ""
    line = line.split(";", 1)[0].strip()      # environment marker
    line = line.split(" @ ", 1)[0].strip()    # PEP 508 direct reference
    name = re.split(r"[<>=!~\[(\s]", line, maxsplit=1)[0].strip()
    return name


def parse_manifest(path: Path, fmt: str, sections: list[str]) -> list[str]:
    """Return the declared distribution names, in declaration order."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read manifest {path}: {exc}") from exc

    names: list[str] = []
    if fmt == "requirements-txt":
        for raw in text.splitlines():
            name = _strip_requirement(raw)
            if name:
                names.append(name)
    elif fmt == "package-json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
        for section in sections:
            names.extend(data.get(section, {}) or {})
    elif fmt == "pyproject":
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
        project = data.get("project", {}) or {}
        for section in sections:
            if section == "dependencies":
                names.extend(_strip_requirement(r) for r in project.get("dependencies", []) or [])
            else:
                extra = (project.get("optional-dependencies", {}) or {}).get(section, []) or []
                names.extend(_strip_requirement(r) for r in extra)
    else:  # pragma: no cover - guarded at validation
        raise ConfigError(f"unknown manifest format {fmt!r}")

    # Order-preserving dedup: a dist may legitimately appear in two sections.
    return list(dict.fromkeys(n for n in names if n))


# ---------------------------------------------------------------------------
# Import extraction — the `import` channel
# ---------------------------------------------------------------------------


def _dotted_prefixes(module: str) -> set[str]:
    """`a.b.c` -> {`a`, `a.b`, `a.b.c`}.

    Namespace packages need every prefix, not just the root. Four distributions
    in geeplo's backend ship into the single `opentelemetry` namespace
    (`opentelemetry-sdk` -> `opentelemetry.sdk`,
    `opentelemetry-instrumentation-celery` -> `opentelemetry.instrumentation.celery`,
    ...). Recording only the root would make importing any ONE of them prove all
    four used — a false green that hides a genuinely unused instrumentor, which
    is exactly what this measurement found.
    """
    parts = module.split(".")
    return {".".join(parts[: i + 1]) for i in range(len(parts))}


def python_imports(text: str) -> set[str]:
    """Module names imported by `text`, each with all of its dotted prefixes.

    `ast`, not regex, on purpose: a package name inside a comment, a docstring
    or a log message is not an import, and counting it would prove use that does
    not exist. `ast.walk` rather than `tree.body` on purpose too: a lazily
    imported optional dependency lives inside a function, and that is still a
    use — several of geeplo's are exactly that shape.
    """
    tree = ast.parse(text)  # SyntaxError propagates: the caller notes it, never silently skips
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out |= _dotted_prefixes(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            # Only the module path — the imported names may be symbols, not modules.
            out |= _dotted_prefixes(node.module)
    return out


# Covers `from 'x'`, bare `import 'x'`, `require('x')` and dynamic `import('x')`.
# The `\b` matters: without it `requireAuth("...")` would read as a `require`.
_TS_SPEC_RE = re.compile(
    r"""(?:\bfrom\b|\bimport\b|\brequire\b)\s*\(?\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)


def _ts_package_of(spec: str) -> str | None:
    """Package name of a TS/JS module specifier, or None if it is not a package.

    `@/app/x` is a tsconfig path alias, NOT a scoped package — treating it as
    one would invent a dependency named `@/app` on nearly every file in a Next.js
    tree. Relative and absolute specifiers are likewise not packages.
    """
    if not spec or spec.startswith((".", "/", "@/")):
        return None
    parts = spec.split("/")
    if spec.startswith("@"):
        return "/".join(parts[:2]) if len(parts) >= 2 else None
    return parts[0]


def typescript_imports(text: str) -> set[str]:
    out: set[str] = set()
    for match in _TS_SPEC_RE.finditer(text):
        pkg = _ts_package_of(match.group(1))
        if pkg:
            out.add(pkg)
    return out


def module_candidates(dist: str, aliases: dict[str, list[str]]) -> list[str]:
    """Import names a distribution might present as.

    The declared alias wins outright. Otherwise four mechanical guesses cover the
    regular cases; genuinely irregular names (`beautifulsoup4` -> `bs4`) need an
    alias entry.

    The `-` -> `.` guess is what resolves namespace packages without an alias
    table: `opentelemetry-sdk` -> `opentelemetry.sdk`,
    `google-cloud-kms` -> `google.cloud.kms`. It is also PRECISE where an alias
    to the bare root would not be — mapping `google-auth` to `google` would let
    any `google.*` import prove it used.
    """
    declared = aliases.get(dist) or aliases.get(dist.casefold())
    if declared:
        return [a.casefold() for a in declared]
    low = dist.casefold()
    return list(dict.fromkeys([
        low,
        low.replace("-", "_"),
        low.replace("-", ""),
        low.replace("-", "."),
    ]))


# ---------------------------------------------------------------------------
# Config loading + validation
# ---------------------------------------------------------------------------

_DEFAULTABLE = ("severity", "status")

_DEP_DEFAULTS: dict[str, Any] = {
    "sections": ["dependencies"],
    "aliases": {},
    "allow": [],
    "status": "enforced",
}

_ART_DEFAULTS: dict[str, Any] = {
    "must_be_ignored": True,
    "allow": [],
    "status": "enforced",
}


def load_config(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} is not a mapping — not a repo-hygiene file")
    if raw.get("schema") != SCHEMA_CONST:
        raise ConfigError(f"{path} is not a repo-hygiene file (schema: {raw.get('schema')!r})")

    version = raw.get("schema_version")
    if not isinstance(version, str) or not _SEMVER_RE.match(version):
        raise ConfigError(f"schema_version must be MAJOR.MINOR.PATCH, got {version!r}")
    if int(version.split(".")[0]) > ENGINE_MAJOR:
        raise ConfigError(
            f"unsupported schema_version {version} (engine supports {ENGINE_MAJOR}.x)"
        )

    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError("`defaults` must be a mapping")
    for key in defaults:
        if key not in _DEFAULTABLE:
            raise ConfigError(
                f"`defaults.{key}` is not defaultable — a silent global for a field that "
                f"carries meaning is unreviewable (defaultable: {', '.join(_DEFAULTABLE)})"
            )

    deps = raw.get("dependencies") or []
    arts = raw.get("artifacts") or []
    if not isinstance(deps, list) or not isinstance(arts, list):
        raise ConfigError("`dependencies` and `artifacts` must be lists")
    if not deps and not arts:
        raise ConfigError(
            "contract declares no checks — a consumer that wired the engine and declared "
            "nothing has a broken adoption, not a clean repo"
        )

    seen: set[str] = set()
    raw["dependencies"] = [_merge(e, _DEP_DEFAULTS, defaults) for e in deps]
    raw["artifacts"] = [_merge(e, _ART_DEFAULTS, defaults) for e in arts]
    for index, entry in enumerate(raw["dependencies"]):
        _validate_dependency(entry, index, seen)
    for index, entry in enumerate(raw["artifacts"]):
        _validate_artifact(entry, index, seen)
    raw.setdefault("root", ".")
    return raw


def _merge(entry: Any, hard: dict[str, Any], soft: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ConfigError(f"each check must be a mapping, got {type(entry).__name__}")
    out = {**hard, **soft, **entry}
    return out


def _validate_common(entry: dict[str, Any], index: int, seen: set[str], kind: str) -> str:
    cid = entry.get("id")
    if not isinstance(cid, str) or not _ID_RE.match(cid):
        raise ConfigError(f"{kind}[{index}]: `id` must be kebab-case, 3-64 chars, got {cid!r}")
    if cid in seen:
        raise ConfigError(f"duplicate check id {cid!r} — ids must be unique across the contract")
    seen.add(cid)
    if not isinstance(entry.get("description"), str) or not entry["description"].strip():
        raise ConfigError(f"'{cid}': `description` is required — reviewers read it, not the regex")
    severity = entry.get("severity")
    if severity not in SEVERITIES:
        raise ConfigError(f"'{cid}': `severity` must be one of {', '.join(SEVERITIES)}, got {severity!r}")
    if entry.get("status") not in ("enforced", "advisory"):
        raise ConfigError(f"'{cid}': `status` must be `enforced` or `advisory`, got {entry.get('status')!r}")
    _validate_allow(entry, cid)
    return cid


def _validate_allow(entry: dict[str, Any], cid: str) -> None:
    allow = entry.get("allow") or []
    if not isinstance(allow, list):
        raise ConfigError(f"'{cid}': `allow` must be a list")
    for item in allow:
        if not isinstance(item, dict):
            raise ConfigError(f"'{cid}': each `allow` entry must be a mapping")
        if not isinstance(item.get("match"), str) or not item["match"]:
            raise ConfigError(f"'{cid}': every `allow` entry needs a `match`")
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise ConfigError(
                f"'{cid}': allow entry {item['match']!r} needs a `reason` naming the mechanism — "
                "without one the exemption list becomes a graveyard nobody can prune"
            )
        expires = item.get("expires")
        if expires is not None and (not isinstance(expires, str) or not _DATE_RE.match(expires)):
            raise ConfigError(f"'{cid}': allow entry {item['match']!r} has a non-ISO `expires`: {expires!r}")


def _validate_dependency(entry: dict[str, Any], index: int, seen: set[str]) -> None:
    cid = _validate_common(entry, index, seen, "dependencies")
    if not isinstance(entry.get("manifest"), str) or not entry["manifest"]:
        raise ConfigError(f"'{cid}': `manifest` is required")
    if entry.get("format") not in FORMATS:
        raise ConfigError(f"'{cid}': `format` must be one of {', '.join(FORMATS)}, got {entry.get('format')!r}")
    if not isinstance(entry.get("sections"), list):
        raise ConfigError(f"'{cid}': `sections` must be a list")
    aliases = entry.get("aliases") or {}
    if not isinstance(aliases, dict):
        raise ConfigError(f"'{cid}': `aliases` must be a mapping of dist -> [module, ...]")
    for dist, mods in aliases.items():
        if not isinstance(mods, list) or not all(isinstance(m, str) for m in mods):
            raise ConfigError(f"'{cid}': alias {dist!r} must map to a list of module names")

    channels = entry.get("channels")
    if not isinstance(channels, list) or not channels:
        raise ConfigError(
            f"'{cid}': `channels` must be a non-empty list — a check with no channels "
            "marks every declared dependency unused"
        )
    ids: set[str] = set()
    for chan in channels:
        if not isinstance(chan, dict):
            raise ConfigError(f"'{cid}': each channel must be a mapping")
        chid = chan.get("id")
        if not isinstance(chid, str) or not _ID_RE.match(chid):
            raise ConfigError(f"'{cid}': channel `id` must be kebab-case, got {chid!r}")
        if chid in ids:
            raise ConfigError(f"'{cid}': duplicate channel id {chid!r}")
        ids.add(chid)
        if chan.get("kind") not in CHANNEL_KINDS:
            raise ConfigError(f"'{cid}/{chid}': `kind` must be one of {', '.join(CHANNEL_KINDS)}")
        if not chan.get("corpus"):
            raise ConfigError(f"'{cid}/{chid}': `corpus` is required")
        chan.setdefault("language", "python")
        chan.setdefault("flags", "m")
        if chan["kind"] == "import":
            if chan["language"] not in LANGUAGES:
                raise ConfigError(f"'{cid}/{chid}': `language` must be one of {', '.join(LANGUAGES)}")
        else:
            by = chan.get("by")
            if not isinstance(by, str) or not by:
                raise ConfigError(f"'{cid}/{chid}': a `search` channel requires `by`")
            present = used_tokens(by)
            if not present:
                raise ConfigError(
                    f"'{cid}/{chid}': `by` contains no interpolation token, so it evaluates "
                    f"identically for every declaration — one match would mark the WHOLE "
                    f"manifest used. Anchor it on {{dist}} or {{module}}."
                )
            unknown = [t for t in present if t not in TOKENS]
            if unknown:
                raise ConfigError(
                    f"'{cid}/{chid}': unknown interpolation token(s) {', '.join(unknown)} "
                    f"(known: {', '.join(TOKENS)})"
                )
            try:
                re.compile(interpolate(by, {"dist": "probe", "module": "probe"}), compile_flags(chan["flags"]))
            except re.error as exc:
                raise ConfigError(f"'{cid}/{chid}': `by` is not a valid regex: {exc}") from exc


def _validate_artifact(entry: dict[str, Any], index: int, seen: set[str]) -> None:
    cid = _validate_common(entry, index, seen, "artifacts")
    if not isinstance(entry.get("path"), str) or not entry["path"]:
        raise ConfigError(f"'{cid}': `path` is required")
    if not isinstance(entry.get("must_be_ignored"), bool):
        raise ConfigError(f"'{cid}': `must_be_ignored` must be a boolean")
    fresh = entry.get("freshness")
    if fresh is None:
        return
    if not isinstance(fresh, dict):
        raise ConfigError(f"'{cid}': `freshness` must be a mapping")
    if not isinstance(fresh.get("signal"), str) or not fresh["signal"]:
        raise ConfigError(
            f"'{cid}': `freshness.signal` is required — point it at the file the generator "
            "rewrites unconditionally, never at one it skips when nothing changed"
        )
    inputs = fresh.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise ConfigError(f"'{cid}': `freshness.inputs` must be a non-empty list of globs")
    grace = fresh.setdefault("grace", 0)
    if not isinstance(grace, int) or isinstance(grace, bool) or grace < 0:
        raise ConfigError(f"'{cid}': `freshness.grace` must be a non-negative integer, got {grace!r}")


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    check: str
    item: str
    severity: str
    status: str
    # unused | stale | signal-missing | committable | tracked | expired-exemption
    verdict: str
    detail: str

    def render(self) -> str:
        # Item first so editors linkify a path; one greppable line per finding.
        return f"{self.item}: {self.severity} [{self.check}] {self.verdict} — {self.detail}"


@dataclass
class CheckResult:
    check_id: str
    severity: str
    status: str
    population: int
    clean: int = 0
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # dist -> channel id that proved it; used by `explain`.
    proof: dict[str, str] = field(default_factory=dict)
    skipped: bool = False


# ---------------------------------------------------------------------------
# Axis 3 evaluation
# ---------------------------------------------------------------------------


def _corpus_files(root: Path, spec: Any, cid: str, chid: str) -> list[str]:
    patterns = [spec] if isinstance(spec, str) else list(spec)
    files: list[str] = []
    for pattern in patterns:
        files.extend(expand_glob(root, pattern))
    files = sorted(dict.fromkeys(files))
    if not files:
        raise ConfigError(
            f"'{cid}/{chid}': corpus matched 0 files — a channel that reads nothing proves "
            "nothing, and would push every dependency toward `unused`"
        )
    return files


def _read(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def evaluate_dependency(root: Path, entry: dict[str, Any]) -> CheckResult:
    cid = entry["id"]
    manifest = root / entry["manifest"]
    if not manifest.is_file():
        raise ConfigError(f"'{cid}': manifest {entry['manifest']} does not exist")
    declared = parse_manifest(manifest, entry["format"], entry["sections"])
    if not declared:
        raise ConfigError(
            f"'{cid}': manifest {entry['manifest']} parsed to 0 declarations — dead check"
        )

    aliases: dict[str, list[str]] = entry.get("aliases") or {}
    result = CheckResult(cid, entry["severity"], entry["status"], len(declared))

    # Collect every channel's evidence once, not per dependency: the corpus is
    # read a single time regardless of how many packages are declared.
    imported: dict[str, set[str]] = {}      # channel id -> module names seen
    searches: list[tuple[str, list[str], str, int]] = []   # id, files, `by`, flags
    for chan in entry["channels"]:
        chid = chan["id"]
        files = _corpus_files(root, chan["corpus"], cid, chid)
        if chan["kind"] == "import":
            seen: set[str] = set()
            for rel in files:
                text = _read(root, rel)
                if chan["language"] == "python":
                    if not rel.endswith(_PY_SUFFIXES):
                        continue
                    try:
                        seen |= python_imports(text)
                    except SyntaxError as exc:
                        # Never silent: a file we could not parse is a file whose
                        # imports we cannot see, which biases toward false unused.
                        result.notes.append(f"{rel}: unparseable, imports not counted ({exc.msg})")
                else:
                    seen |= typescript_imports(text)
            imported[chid] = {s.casefold() for s in seen}
        else:
            searches.append((chid, files, chan["by"], compile_flags(chan["flags"])))

    texts = {rel: _read(root, rel) for _, files, _, _ in searches for rel in files}

    allow_list = entry.get("allow") or []
    used_allow: set[str] = set()
    today = date.today().isoformat()

    for dist in declared:
        candidates = module_candidates(dist, aliases)
        proof: str | None = None

        for chid, seen in imported.items():
            if any(c in seen for c in candidates):
                proof = chid
                break

        if proof is None:
            for chid, files, by, flags in searches:
                for binding in [{"dist": dist, "module": dist}] + [
                    {"dist": dist, "module": c} for c in candidates
                ]:
                    try:
                        rx = re.compile(interpolate(by, binding), flags)
                    except re.error as exc:  # pragma: no cover - guarded at validation
                        raise ConfigError(f"'{cid}/{chid}': {exc}") from exc
                    if any(rx.search(texts[rel]) for rel in files):
                        proof = chid
                        break
                if proof:
                    break

        if proof is not None:
            result.clean += 1
            result.proof[dist] = proof
            continue

        exemption = next((a for a in allow_list if allow_matches(str(a["match"]), dist)), None)
        if exemption is not None:
            used_allow.add(str(exemption["match"]))
            expires = exemption.get("expires")
            if expires and expires < today:
                result.findings.append(
                    Finding(cid, dist, entry["severity"], entry["status"], "expired-exemption",
                            f"exemption expired {expires}: {exemption['reason']}")
                )
            else:
                result.clean += 1
                result.proof[dist] = f"allow: {exemption['reason']}"
            continue

        channels = ", ".join(c["id"] for c in entry["channels"])
        result.findings.append(
            Finding(cid, dist, entry["severity"], entry["status"], "unused",
                    f"declared in {entry['manifest']} but proved by no channel ({channels})")
        )

    _assert_no_stale_allow(allow_list, used_allow, declared, cid)
    return result


def _assert_no_stale_allow(
    allow_list: list[dict[str, Any]], used: set[str], population: list[str], cid: str
) -> None:
    """A rotting exception must break the build, or the contract drifts into fiction."""
    for item in allow_list:
        match = str(item["match"])
        if match in used:
            continue
        if any(allow_matches(match, name) for name in population):
            continue
        raise ConfigError(
            f"'{cid}': stale allow entry {match!r} — it matches nothing in the population; "
            "delete it, or the exemption list becomes fiction"
        )


# ---------------------------------------------------------------------------
# Axis 5 evaluation
# ---------------------------------------------------------------------------


def _git(root: Path, args: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(root), capture_output=True, text=True, check=False, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return 128, ""
    return proc.returncode, proc.stdout


def _newest(root: Path, patterns: list[str], cid: str) -> tuple[float, str]:
    newest_mtime, newest_rel = 0.0, ""
    total = 0
    for pattern in patterns:
        for rel in expand_glob(root, pattern):
            total += 1
            try:
                mtime = (root / rel).stat().st_mtime
            except OSError:
                continue
            if mtime > newest_mtime:
                newest_mtime, newest_rel = mtime, rel
    if total == 0:
        raise ConfigError(f"'{cid}': `freshness.inputs` matched 0 files — the check would never fire")
    return newest_mtime, newest_rel


def evaluate_artifact(root: Path, entry: dict[str, Any]) -> CheckResult:
    cid = entry["id"]
    target = root / entry["path"]
    result = CheckResult(cid, entry["severity"], entry["status"], 1)

    if not target.exists():
        # A fresh clone has not built its artefacts yet. That is not a hygiene
        # problem, and reporting it would train readers to ignore this rule.
        result.skipped = True
        result.notes.append(f"{entry['path']}: not present — nothing to assess")
        return result

    allow_list = entry.get("allow") or []
    exemption = next((a for a in allow_list if allow_matches(str(a["match"]), cid)), None)
    today = date.today().isoformat()
    exempt = exemption is not None and not (
        exemption.get("expires") and str(exemption["expires"]) < today
    )
    if allow_list and exemption is None:
        raise ConfigError(
            f"'{cid}': stale allow entry — an artefact `allow` must match the check id {cid!r}"
        )

    if entry["must_be_ignored"]:
        code, out = _git(root, ["ls-files", "--", entry["path"]])
        tracked = code == 0 and bool(out.strip())
        if tracked:
            count = len(out.strip().splitlines())
            result.findings.append(
                Finding(cid, entry["path"], entry["severity"], entry["status"], "tracked",
                        f"{count} generated file(s) already in the index — `git rm --cached` them "
                        "before .gitignore can take effect")
            )
        else:
            code, _ = _git(root, ["check-ignore", "-q", entry["path"]])
            if code == 1:
                result.findings.append(
                    Finding(cid, entry["path"], entry["severity"], entry["status"], "committable",
                            "untracked and not ignored — the next `git add -A` commits it")
                )

    fresh = entry.get("freshness")
    if fresh:
        signal = root / fresh["signal"]
        if not signal.is_file():
            result.findings.append(
                Finding(cid, fresh["signal"], entry["severity"], entry["status"], "signal-missing",
                        f"{entry['path']} exists but its freshness signal does not — the artefact "
                        "is present and its currency is unknowable")
            )
        else:
            newest_mtime, newest_rel = _newest(root, fresh["inputs"], cid)
            lag = newest_mtime - signal.stat().st_mtime
            if lag > fresh["grace"]:
                result.findings.append(
                    Finding(cid, entry["path"], entry["severity"], entry["status"], "stale",
                            f"{newest_rel} is {int(lag)}s newer than {fresh['signal']} — regenerate; "
                            "a stale map is worse than no map, because it is consulted with confidence")
                )

    if exempt:
        for finding in result.findings:
            result.notes.append(f"exempt ({exemption['reason']}): {finding.render()}")
        result.findings = []
    if not result.findings:
        result.clean = 1
    return result


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def _load(explicit: str | None) -> tuple[Path, Path, dict[str, Any]] | None:
    config_path = resolve_config(explicit, CONFIG_NAME)
    if config_path is None or not config_path.is_file():
        return None
    root = find_consumer_root(config_path.parent, CONFIG_NAME)
    config = load_config(config_path)
    base = (root / config["root"]).resolve()
    if not base.is_dir():
        raise ConfigError(f"`root` {config['root']!r} does not exist — every glob would match nothing")
    return config_path, base, config


def _entries(config: dict[str, Any], only: str | None) -> list[tuple[str, dict[str, Any]]]:
    pairs = [("dependency", e) for e in config["dependencies"]]
    pairs += [("artifact", e) for e in config["artifacts"]]
    if only:
        pairs = [p for p in pairs if p[1]["id"] == only]
        if not pairs:
            raise ConfigError(f"no check with id {only!r}")
    return pairs


def cmd_check(args: argparse.Namespace) -> int:
    skip_all, skip_ids = skip_directive(SKIP_ENV)
    if skip_all:
        print(f"⚠ repo-hygiene: SKIPPED entirely via {SKIP_ENV}", file=sys.stderr)
        return 0

    loaded = _load(args.config)
    if loaded is None:
        return 0
    config_path, root, config = loaded

    changed = changed_files(root) if args.changed_only else None
    results: list[CheckResult] = []

    for kind, entry in _entries(config, args.check):
        cid = entry["id"]
        if cid in skip_ids:
            print(f"⚠ repo-hygiene: check '{cid}' SKIPPED via {SKIP_ENV}", file=sys.stderr)
            continue
        if changed is not None and kind == "dependency" and entry["manifest"] not in changed:
            # `--changed-only` narrows on the MANIFEST, never on the corpus. A
            # source edit can only make a dependency MORE used, and re-reading
            # the whole corpus on every commit is the cost this flag exists to
            # avoid. Artefact checks always run — they are a few stat calls.
            continue
        results.append(
            evaluate_dependency(root, entry) if kind == "dependency" else evaluate_artifact(root, entry)
        )

    findings = [f for r in results for f in r.findings]

    if args.as_json:
        print(json.dumps({
            "config": str(config_path),
            "checks": [
                {"id": r.check_id, "severity": r.severity, "status": r.status,
                 "population": r.population, "clean": r.clean, "skipped": r.skipped,
                 "notes": r.notes,
                 "findings": [{"item": f.item, "verdict": f.verdict, "detail": f.detail} for f in r.findings]}
                for r in results
            ],
        }, indent=2))
    else:
        for result in results:
            for note in result.notes:
                print(f"ℹ [{result.check_id}] {note}")
        # Every finding goes to stdout regardless of severity, so one grep
        # catches them all. Only the ❌ block goes to stderr.
        for finding in findings:
            print(finding.render())

    blocking = [f for f in findings if f.severity in BLOCKING and f.status == "enforced"]
    if blocking:
        items = ", ".join(sorted({f.item for f in blocking}))
        emit_error(
            why=f"{len(blocking)} hygiene finding(s) at a blocking severity: {items}",
            where=str(config_path),
            fix=(
                "remove the dependency, or declare the channel that proves it is used; "
                "regenerate the stale artefact, or ignore the committable one. Run "
                "`repo-hygiene.rule.py explain <id>` to see what each channel proved. "
                "This rule never deletes anything — the decision is yours."
            ),
            override=f"{SKIP_ENV}=1 or {SKIP_ENV}=<check-id>",
        )
        return 1

    # The ratchet, and it is deliberately NOT the severity mechanism above.
    #
    # Every check here is S3 on the merits: an unused dependency widens the CVE
    # surface and a stale graph misleads a reader, but neither is a correctness
    # defect. Relabelling them S2 so the step fails would buy a gate at the cost
    # of the severity scale meaning anything — and a scale nobody trusts is how
    # the S2s that DO matter start getting waved through.
    #
    # "How bad is this finding" and "has this got worse" are separate questions.
    # Severity answers the first and only the first; this answers the second,
    # and a finding can legitimately be S3 forever while still never being
    # allowed to grow.
    if args.max is not None:
        if args.max < 0:
            raise ConfigError(
                f"`--max {args.max}` is negative; a baseline is a count, and counts start at 0"
            )
        if len(findings) > args.max:
            emit_error(
                why=(
                    f"{len(findings)} hygiene finding(s), baseline {args.max} — this got WORSE. "
                    "Severity says how bad a finding is; the baseline says whether it grew, "
                    "and these are S3 precisely so that this number is the thing that gates"
                ),
                where=str(config_path),
                fix=(
                    "remove the dependency, declare the channel that proves it is used, or "
                    "regenerate the stale artefact. `explain <id>` shows what each channel "
                    "proved. Raising the baseline is not on this list."
                ),
                override="none",
            )
            return 1

    if not args.as_json:
        total = sum(r.population for r in results)
        print(f"repo-hygiene: OK — {len(results)} check(s), {total} item(s), {len(findings)} finding(s)")
        if args.max is not None and len(findings) < args.max:
            # Ratchets only ratchet if somebody lowers them, and nobody lowers a
            # number they were never told had slack.
            print(f"repo-hygiene: below the baseline of {args.max} — LOWER IT to "
                  f"{len(findings)} in this same PR; that is what locks the improvement in.")
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    loaded = _load(args.config)
    if loaded is None:
        print("no repo-hygiene.yaml in this consumer", file=sys.stderr)
        return 2
    _, root, config = loaded

    for kind, entry in _entries(config, args.check_id):
        cid = entry["id"]
        print(f"=== {cid} ({kind}) — {entry['severity']}/{entry['status']}")
        print(f"    {entry['description']}")
        if kind == "dependency":
            result = evaluate_dependency(root, entry)
            print(f"    manifest: {entry['manifest']} — {result.population} declaration(s)")
            for dist in sorted(result.proof):
                print(f"      ✓ {dist:32} proved by {result.proof[dist]}")
            for finding in result.findings:
                print(f"      ✗ {finding.item:32} {finding.verdict}: {finding.detail}")
        else:
            target = root / entry["path"]
            print(f"    path: {entry['path']} — {'present' if target.exists() else 'absent'}")
            fresh = entry.get("freshness")
            if fresh and target.exists():
                signal = root / fresh["signal"]
                if signal.is_file():
                    newest_mtime, newest_rel = _newest(root, fresh["inputs"], cid)
                    delta = int(newest_mtime - signal.stat().st_mtime)
                    print(f"      signal  {fresh['signal']} mtime={int(signal.stat().st_mtime)}")
                    print(f"      newest  {newest_rel} mtime={int(newest_mtime)}")
                    print(f"      lag     {delta}s (grace {fresh['grace']}s) -> "
                          f"{'STALE' if delta > fresh['grace'] else 'fresh'}")
            result = evaluate_artifact(root, entry)
            for finding in result.findings:
                print(f"      ✗ {finding.verdict}: {finding.detail}")
        for note in result.notes:
            print(f"      ℹ {note}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    loaded = _load(args.config)
    if loaded is None:
        print("no repo-hygiene.yaml in this consumer — nothing to validate")
        return 0
    config_path, _, config = loaded
    total = len(config["dependencies"]) + len(config["artifacts"])
    print(f"repo-hygiene: {config_path} is valid — {total} check(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="repo-hygiene")
    sub = parser.add_subparsers(dest="cmd", required=True)

    check = sub.add_parser("check", help="Evaluate every check.")
    check.add_argument("--config")
    check.add_argument("--json", dest="as_json", action="store_true")
    check.add_argument("--changed-only", action="store_true",
                       help="Only run dependency checks whose manifest changed.")
    check.add_argument("--check", help="Limit to one check id.")
    check.add_argument("--max", type=int, default=None,
                       help="Ratchet: fail if the finding count exceeds this. Only goes DOWN.")
    check.set_defaults(func=cmd_check)

    explain = sub.add_parser("explain", help="Show what each channel proved.")
    explain.add_argument("check_id", nargs="?")
    explain.add_argument("--config")
    explain.set_defaults(func=cmd_explain)

    validate = sub.add_parser("validate", help="Parse and validate the contract only.")
    validate.add_argument("--config")
    validate.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        emit_error(
            why=f"repo-hygiene config error: {exc}",
            where=str(args.config or CONFIG_NAME),
            fix="fix the contract. An unevaluable contract must never be reported as a clean repo.",
            override=f"{SKIP_ENV}=1",
        )
        return 2


if __name__ == "__main__":
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("repo-hygiene", main))
