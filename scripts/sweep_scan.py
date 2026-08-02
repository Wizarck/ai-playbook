"""Deterministic scanner for code-entropy axis 1, `orphan-file`.

Axis 2 (`dead-symbol`) is in the same undecidable family and is served by the
same skill, but nothing here detects it: `build_ledger` declares `axes_scanned`
as `orphan-file` alone, and an empty ledger must only claim the axis that ran.

Emits a ledger validating against `schemas/schema-sweep-manifest-v1.json`.
Taxonomy: `docs/concepts/code-entropy.md`.

WHAT THIS IS NOT
It is not a rule. It never runs at pre-commit and never blocks a commit — the
cadence for these axes is on-demand and monthly, per the taxonomy. It is also not
an executor: it writes a ledger and stops. Deleting is a separate, explicit human
step, and there is no delete path in this file.

THE PROBE GATE — the reason this scanner is shaped the way it is
Measured against geeplo before this was written: a naive "not imported" scan
produced 779 candidates, of which 17 were real (2.2%). The two failures that
mattered were NOT judgement calls, they were mechanical resolver bugs of mine:

  1. Not reading `tsconfig.json` `compilerOptions.paths`. That project declares
     FOURTEEN aliases (`@auth/`, `@components/`, `@hooks/`, ...). Handling only
     `@/` alone produced 89 false positives — it reported `AuthProvider`,
     `MainLayout` and the shared `data-table` as dead.
  2. Counting references by NAME instead of by PATH, which produced a falsely
     reassuring negative: two directories held same-named files, so references to
     the live one were credited to the dead one.

An adjudicating model fed that output would have written 89 convincing rationales
for 89 wrong findings — laundering a resolver bug into reasoned ledger rows. So
the fidelity of this scanner, not the quality of the adjudication, is where the
value is.

Hence `probes`: the consumer declares files it KNOWS are reachable, and this
scanner REFUSES to emit a ledger if any of them reads as unreachable. That turns
"I should have sanity-checked the resolver" into a structural gate. A reachability
result nobody validated is an opinion with a JSON schema.

ENTRY POINTS COME FROM THE FRAMEWORK, NOT THE PROJECT
`capability-wiring` and `repo-hygiene` put their holes in consumer data, because
*which registry* a project uses is irreducibly its own. That reasoning does not
carry here: that pytest collects `test_*.py`, that Alembic loads `versions/*.py`,
and that Next.js routes `page.tsx` are facts about the FRAMEWORK. Making every
consumer redeclare them would be the duplication this campaign exists to remove.
So conventions ship as presets, and `entrypoints` in the consumer config is only
for what the presets do not cover.

CLI:
    sweep_scan.py scan     [--config P] [--out PATH] [--json]
    sweep_scan.py probe    [--config P]      # run the probe gate alone
    sweep_scan.py validate [--config P]      # config-only lint, no scan

Exit codes:
    0 — scan completed (findings are DATA, not failure: this never gates a commit).
    1 — PROBE FAILURE: a file the consumer declared live read as unreachable, so
        the resolver is wrong and the ledger was NOT written.
    2 — CONFIG ERROR: bad schema, a root matching zero files, an unreadable
        tsconfig, no probes declared.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment guard
    print("FATAL: pyyaml not installed. Run `pip install pyyaml`.", file=sys.stderr)
    raise SystemExit(2) from exc

sys.path.insert(0, str(Path(__file__).resolve().parent / "rules"))

from _rule_kit import (  # noqa: E402  (deliberate: needs the sys.path line above)
    ConfigError,
    emit_error,
    expand_glob,
    find_consumer_root,
    resolve_config,
)

TOOL_VERSION = "0.1.0"
SCHEMA_CONST = "ai-playbook/sweep-config/v1"
CONFIG_NAME = "sweep.yaml"
ENGINE_MAJOR = 1

LANGUAGES = ("python", "typescript")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")

TS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
PY_EXTS = (".py", ".pyi")


# ---------------------------------------------------------------------------
# Framework presets — entry-point conventions
# ---------------------------------------------------------------------------
#
# Each preset is a set of globs whose matches are ENTRY POINTS: reachable by
# definition, because a framework loads them by filename rather than by import.
# Measured on geeplo: these six presets account for 762 of 779 naive candidates.
# They are framework facts, so they ship here rather than in every consumer's
# config.


def _by_ext(stems: tuple[str, ...], exts: tuple[str, ...]) -> list[str]:
    """Every stem × every extension, as `**/`-anchored globs.

    Hand-enumerating this product is how a preset ends up covering `page.tsx`
    but not `page.js`. Measured on geeplo: that exact omission left three live
    Next routes rootless and reported the 10 modals below them — a whole
    directory — as orphans. Generating the product makes "we support this
    extension" a single edit that cannot apply to some stems and not others.
    """
    return [f"**/{stem}{ext}" for stem in stems for ext in exts]


# Next.js resolves route files in any of its four script extensions; so do
# Vitest and Playwright for specs. Neither framework privileges TypeScript.
_JS_TS = (".js", ".jsx", ".ts", ".tsx")

PRESETS: dict[str, dict[str, Any]] = {
    "python-pytest": {
        "why": "pytest COLLECTS these by filename; nothing imports a test module.",
        "entrypoints": ["**/test_*.py", "**/*_test.py", "**/conftest.py"],
    },
    "python-alembic": {
        "why": "Alembic imports migration modules dynamically by revision id.",
        "entrypoints": ["**/alembic/versions/*.py", "**/alembic/env.py"],
    },
    "python-package-init": {
        "why": (
            "`__init__.py` is executed on package import, so it is reachable "
            "whenever anything under its package is. Treating it as a subject "
            "reports every package in the tree."
        ),
        "entrypoints": ["**/__init__.py"],
    },
    "next-app-router": {
        "why": (
            "Next.js App Router routes by FILE SYSTEM: these filenames are "
            "entry points by convention and are never imported. On geeplo this "
            "one preset alone explains 118 candidates."
        ),
        "entrypoints": _by_ext(
            (
                "page", "layout", "route", "loading", "error", "not-found",
                "template", "default", "global-error", "middleware",
                "instrumentation", "sitemap", "robots", "opengraph-image",
                "twitter-image", "icon", "apple-icon",
            ),
            _JS_TS,
        ),
    },
    "node-tooling": {
        "why": "Config files are read by their tool by filename, not imported.",
        "entrypoints": [
            "**/*.config.ts", "**/*.config.js", "**/*.config.mjs",
            "**/vitest.setup.ts", "**/next-env.d.ts", "**/*.d.ts",
        ],
    },
    "js-test": {
        "why": "Vitest/Playwright collect spec files by filename.",
        "entrypoints": _by_ext(("*.spec", "*.test"), _JS_TS)
        + [f"**/tests/**/*{ext}" for ext in _JS_TS],
    },
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_config(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} is not a mapping — not a sweep config")
    if raw.get("schema") != SCHEMA_CONST:
        raise ConfigError(f"{path} is not a sweep config (schema: {raw.get('schema')!r})")

    version = raw.get("schema_version")
    if not isinstance(version, str) or not _SEMVER_RE.match(version):
        raise ConfigError(f"schema_version must be MAJOR.MINOR.PATCH, got {version!r}")
    if int(version.split(".")[0]) > ENGINE_MAJOR:
        raise ConfigError(f"unsupported schema_version {version} (engine supports {ENGINE_MAJOR}.x)")

    for name in raw.get("presets") or []:
        if name not in PRESETS:
            raise ConfigError(
                f"unknown preset {name!r} (known: {', '.join(sorted(PRESETS))})"
            )

    roots = raw.get("roots")
    if not isinstance(roots, list) or not roots:
        raise ConfigError("`roots` must be a non-empty list — a scan with no roots inspects nothing")
    seen: set[str] = set()
    for entry in roots:
        if not isinstance(entry, dict):
            raise ConfigError("each root must be a mapping")
        rid = entry.get("id")
        if not isinstance(rid, str) or not _ID_RE.match(rid):
            raise ConfigError(f"root `id` must be kebab-case, got {rid!r}")
        if rid in seen:
            raise ConfigError(f"duplicate root id {rid!r}")
        seen.add(rid)
        if entry.get("language") not in LANGUAGES:
            raise ConfigError(f"'{rid}': `language` must be one of {', '.join(LANGUAGES)}")
        include = entry.get("include")
        if not include:
            raise ConfigError(f"'{rid}': `include` is required")
        # A list, because a language rarely lives in one extension: the glob
        # grammar has no `{ts,tsx}` alternation on purpose (brackets and braces
        # are literal, so real paths like `app/(ops)/` survive).
        entry["include"] = [include] if isinstance(include, str) else list(include)
        exclude = entry.get("exclude") or []
        # Same normalisation as `include`, and for a sharper reason: a bare string
        # left unwrapped iterates CHARACTER by character, silently excluding
        # nothing, and the generated tree it was meant to suppress lands in the
        # ledger looking like a finding.
        entry["exclude"] = [exclude] if isinstance(exclude, str) else list(exclude)

        bases = {_glob_base(p) for p in entry["include"]}
        if entry["language"] == "python" and len(bases) > 1:
            raise ConfigError(
                f"'{rid}': `include` patterns span more than one package base "
                f"({', '.join(sorted(repr(b) for b in bases))}), but a Python root has a "
                "single dotted-module index. Modules outside the first base would be "
                "indexed under the wrong name and read as unreachable. Declare one root "
                "per base instead."
            )

    probes = raw.get("probes")
    if not isinstance(probes, list) or not probes:
        raise ConfigError(
            "`probes` must be a non-empty list. A reachability scan nobody validated is an "
            "opinion with a schema: declare files you KNOW are live, so a broken resolver "
            "fails loudly instead of reporting the tree as dead."
        )

    raw.setdefault("root", ".")
    raw.setdefault("presets", [])
    raw.setdefault("entrypoints", [])
    return raw


def _glob_base(pattern: str) -> str:
    """The fixed directory prefix of a glob — `src/**/*.py` -> `src`, `**/*.py` -> ``."""
    cut = min([p for p in (pattern.find("*"), pattern.find("?")) if p != -1] or [len(pattern)])
    head = pattern[:cut]
    return head.rsplit("/", 1)[0] if "/" in head else ""


def preset_entrypoints(names: list[str]) -> list[str]:
    out: list[str] = []
    for name in names:
        out.extend(PRESETS[name]["entrypoints"])
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------------------
# Module-specifier extraction (shape shared with repo-hygiene; the RESOLVERS
# below are not — that rule asks "which package", this one asks "which file")
# ---------------------------------------------------------------------------

_TS_SPEC_RE = re.compile(
    r"""(?:\bfrom\b|\bimport\b|\brequire\b)\s*\(?\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)


def ts_specifiers(text: str) -> list[str]:
    return [m.group(1) for m in _TS_SPEC_RE.finditer(text)]


def py_imported_modules(text: str) -> list[tuple[str, int]]:
    """`(dotted module, relative level)` for every import in `text`.

    `ast.walk`, not `tree.body`: a lazily imported module inside a function still
    makes its target reachable.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        raise
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((a.name, 0) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.append((node.module, node.level))
            for alias in node.names:
                # `from . import sibling` — the sibling is the reachable module.
                base = f"{node.module}.{alias.name}" if node.module else alias.name
                out.append((base, node.level))
    return out


# ---------------------------------------------------------------------------
# Resolvers — specifier -> repo-relative file path
# ---------------------------------------------------------------------------


@dataclass
class Root:
    rid: str
    language: str
    files: list[str]
    base: str                       # longest literal prefix of `include`
    aliases: list[tuple[str, str]] = field(default_factory=list)


def _strip_comments(text: str) -> str:
    """Drop `//` line comments so a tsconfig with comments still parses as JSON."""
    return re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)


def _read_tsconfig(path: Path, seen: set[Path]) -> tuple[dict[str, list[str]], Path]:
    """One tsconfig's `paths`, merged through its `extends` chain.

    TypeScript resolves `extends` before `paths`, and a great many projects keep
    aliases in a shared `tsconfig.base.json`. Reading only the named file makes
    `paths` come back empty in that layout — and an empty alias table is the
    89-false-positive bug this scanner was built around, just arriving by a
    different door.

    Returns the merged table and the directory `paths` is relative to: TypeScript
    anchors on `baseUrl`, which is itself relative to the file that declares it,
    so the anchor travels with the config that won.
    """
    if path in seen:                       # a cyclic `extends` is the user's bug, not ours
        return {}, path.parent
    seen.add(path)
    try:
        data = json.loads(_strip_comments(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot parse {path.name}: {exc}") from exc

    merged: dict[str, list[str]] = {}
    anchor = path.parent
    parent = data.get("extends")
    if isinstance(parent, str) and not parent.startswith("@"):
        base = (path.parent / parent).resolve()
        if base.suffix != ".json":
            base = base.with_suffix(".json")
        if base.is_file():
            merged, anchor = _read_tsconfig(base, seen)

    opts = data.get("compilerOptions") or {}
    own = opts.get("paths")
    if own:
        merged = {**merged, **own}         # the nearer config wins, key by key
        anchor = path.parent
    if opts.get("baseUrl"):
        anchor = (anchor / opts["baseUrl"]).resolve()
    return merged, anchor


def load_ts_aliases(root: Path, tsconfig_rel: str) -> list[tuple[str, str]]:
    """`compilerOptions.paths` -> [(prefix, target), ...], longest prefix first.

    This is THE field whose absence produced 89 false positives on geeplo. The
    project's own module-resolution config is the ground truth for what an import
    specifier means; a resolver that guesses instead of reading it will report a
    live component tree as dead.

    A key may map to SEVERAL targets and TypeScript tries them in order, so every
    target is emitted. Keeping only the first would leave any import that resolves
    through a fallback reading as unresolved — the same false-orphan outcome,
    one layer down.
    """
    path = root / tsconfig_rel
    if not path.is_file():
        raise ConfigError(
            f"`resolve_from` {tsconfig_rel} does not exist — without the project's own "
            "path aliases every aliased import resolves to nothing and the whole tree "
            "reads as unreachable"
        )
    paths, anchor = _read_tsconfig(path, set())
    try:
        base_dir = anchor.relative_to(root).as_posix()
    except ValueError:                     # `baseUrl` escaping the root resolves nothing
        base_dir = "."
    prefix = "" if base_dir == "." else base_dir + "/"

    out: list[tuple[str, str]] = []
    for key, targets in paths.items():
        src = key[:-1] if key.endswith("*") else key
        for target in targets or []:
            dst = target[:-1] if target.endswith("*") else target
            if dst.startswith("./"):
                dst = dst[2:]
            out.append((src, (prefix + dst).replace("//", "/")))
    # Longest prefix wins, so `@components/` is tried before a bare `@`. Ties keep
    # declaration order, which is the order TypeScript itself tries the targets.
    out.sort(key=lambda kv: -len(kv[0]))
    return out


def resolve_ts(spec: str, importer: str, root_obj: Root, known: set[str]) -> str | None:
    """Resolve one TS/JS specifier to a repo-relative file, or None if external."""
    if spec.startswith("."):
        target = (Path(importer).parent / spec).as_posix()
        target = str(Path(target)).replace("\\", "/")
        # Normalise `a/./b` and `a/b/../c` without touching the filesystem.
        parts: list[str] = []
        for part in target.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        candidates = ["/".join(parts)]
    else:
        # One key can map to several targets and TypeScript tries them in order,
        # so gather every match and let the extension probe below pick the first
        # that exists. Stopping at the first PREFIX would resolve nothing whenever
        # the file lives behind a fallback target.
        candidates = [
            (dst + spec[len(prefix):]).replace("//", "/")
            for prefix, dst in root_obj.aliases
            if spec.startswith(prefix)
        ]
        if not candidates:
            return None          # bare package name — external, not our problem

    for candidate in candidates:
        for ext in ("",) + TS_EXTS:
            if candidate + ext in known:
                return candidate + ext
        for ext in TS_EXTS:                  # directory with an index file
            if f"{candidate}/index{ext}" in known:
                return f"{candidate}/index{ext}"
    return None


def build_py_index(files: list[str], base: str) -> dict[str, str]:
    """Dotted module name -> file, relative to the root's own base directory."""
    index: dict[str, str] = {}
    prefix = base + "/" if base else ""
    for rel in files:
        inner = rel[len(prefix):] if prefix and rel.startswith(prefix) else rel
        parts = list(Path(inner).with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            index[".".join(parts)] = rel
    return index


def resolve_py(module: str, level: int, importer: str, index: dict[str, str], base: str) -> str | None:
    if level:
        prefix = base + "/" if base else ""
        inner = importer[len(prefix):] if prefix and importer.startswith(prefix) else importer
        pkg = list(Path(inner).parent.parts)
        pkg = pkg[: len(pkg) - (level - 1)] if level > 1 else pkg
        module = ".".join([*pkg, module]) if module else ".".join(pkg)
    return index.get(module)


# ---------------------------------------------------------------------------
# Reachability
# ---------------------------------------------------------------------------


@dataclass
class ScanResult:
    reachable: set[str]
    edges: dict[str, set[str]]
    all_files: set[str]
    unparseable: list[str]
    ignored: int = 0


def git_versioned(root: Path) -> set[str] | None:
    """Paths git tracks, or would track — `None` when this is not a git tree.

    A file git ignores cannot be repo entropy: it is a local build artifact
    that regenerates. Measured on geeplo: two gitignored Playwright report
    directories contributed 10 of 24 candidates, all of them bundled vendor
    JavaScript. Reporting them is worse than noise — it invites someone to
    "clean up" a directory that comes back on the next test run.

    `--cached --others --exclude-standard` is tracked files plus untracked ones
    that are NOT ignored, which is exactly "everything a commit could contain".
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            capture_output=True, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return {p for p in out.stdout.decode("utf-8", "replace").split("\0") if p}


def scan_root(root: Path, spec: dict[str, Any], entry_globs: list[str]) -> tuple[Root, ScanResult]:
    files: list[str] = []
    for pattern in spec["include"]:
        files.extend(expand_glob(root, pattern))
    files = sorted(dict.fromkeys(files))
    for pattern in spec["exclude"]:
        excluded = set(expand_glob(root, pattern))
        files = [f for f in files if f not in excluded]

    ignored = 0
    versioned = git_versioned(root)
    if versioned is not None:
        kept = [f for f in files if f in versioned]
        ignored = len(files) - len(kept)
        files = kept

    if not files:
        raise ConfigError(
            f"'{spec['id']}': `include` matched 0 files — a root that inspects nothing "
            "reports a clean repo forever"
        )

    base = _glob_base(spec["include"][0])

    aliases: list[tuple[str, str]] = []
    if spec["language"] == "typescript" and spec.get("resolve_from"):
        aliases = load_ts_aliases(root, spec["resolve_from"])

    root_obj = Root(spec["id"], spec["language"], files, base, aliases)
    known = set(files)
    edges: dict[str, set[str]] = {f: set() for f in files}
    unparseable: list[str] = []

    py_index = build_py_index(files, base) if spec["language"] == "python" else {}

    for rel in files:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if spec["language"] == "python":
            try:
                for module, level in py_imported_modules(text):
                    hit = resolve_py(module, level, rel, py_index, base)
                    if hit and hit != rel:
                        edges[rel].add(hit)
            except SyntaxError:
                unparseable.append(rel)
        else:
            for s in ts_specifiers(text):
                hit = resolve_ts(s, rel, root_obj, known)
                if hit and hit != rel:
                    edges[rel].add(hit)

    roots_set: set[str] = set()
    for pattern in entry_globs:
        roots_set.update(f for f in expand_glob(root, pattern) if f in known)

    reachable = set(roots_set)
    stack = list(roots_set)
    while stack:
        cur = stack.pop()
        for nxt in edges.get(cur, ()):
            if nxt not in reachable:
                reachable.add(nxt)
                stack.append(nxt)

    return root_obj, ScanResult(reachable, edges, known, unparseable, ignored)


# ---------------------------------------------------------------------------
# Ledger emission
# ---------------------------------------------------------------------------


def _git(root: Path, args: list[str]) -> str:
    try:
        proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                              text=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _finding_id(rel: str) -> str:
    """A stable, collision-free id for one path.

    The slug alone is neither: it collapses every non-alphanumeric run to `-`
    (`app/b.ts` and `app-b.ts` both become `app-b-ts`) and it is truncated, so
    two deep paths sharing a prefix converge. Ids drive suppression and
    `seen_count` downstream, and a collision there silences the wrong file.
    The digest is of the FULL path, so truncation cannot reach it.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", rel.lower()).strip("-")
    digest = hashlib.sha256(rel.encode("utf-8")).hexdigest()[:8]
    return f"orphan-{slug}"[:72] + f"-{digest}"


def build_ledger(
    root: Path, config: dict[str, Any], results: dict[str, tuple[Root, ScanResult]],
    entry_globs: list[str], started: datetime, duration_ms: int,
) -> dict[str, Any]:
    commit = _git(root, ["rev-parse", "HEAD"])[:40] or "0000000"
    dirty = bool(_git(root, ["status", "--porcelain"]))
    now = datetime.now(UTC)

    findings: list[dict[str, Any]] = []
    for rid, (_root_obj, res) in results.items():
        scope = list(next(s["include"] for s in config["roots"] if s["id"] == rid))
        for rel in sorted(res.all_files - res.reachable):
            findings.append({
                "id": _finding_id(rel),
                "axis": "orphan-file",
                "path": rel,
                # Tier 3 / report / report_only, unconditionally. This scanner has
                # no delete path; execution is a separate human decision.
                "action": "report",
                "safety": "report_only",
                "reason": (
                    f"No path from any declared entry point reaches {rel}. The scan resolved "
                    f"imports using the project's own module-resolution config, and applied the "
                    f"entry-point conventions of the declared framework presets. This is a "
                    f"CANDIDATE, not a verdict: confirm it is not loaded dynamically, by "
                    f"reflection, or by a convention no preset covers before removing anything."
                ),
                "evidence": {
                    "detector": "reachability-scan",
                    "detector_version": TOOL_VERSION,
                    "verdict": "unreachable",
                    "detector_tier": 3,
                    "consumers_found": 0,
                    "search_scope": scope,
                    "locations": [{"path": rel, "role": "subject"}],
                },
                "adjudication": {
                    "decided_by": "detector",
                    "decision": "confirm",
                    "tier": 3,
                    "decided_at": now.isoformat().replace("+00:00", "Z"),
                },
            })

    return {
        "schema": "sweep-manifest/v1",
        "version": 1,
        "manifest_version": f"{now:%Y-%m-%d}.1",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "scan": {
            "tool_version": TOOL_VERSION,
            "commit": commit,
            "dirty_worktree": dirty,
            "axes_scanned": ["orphan-file"],
            "excluded_globs": sorted({e for s in config["roots"] for e in s["exclude"]}),
            "started_at": started.isoformat().replace("+00:00", "Z"),
            "duration_ms": duration_ms,
            "detectors": [
                {"name": "reachability-scan", "axis": "orphan-file", "version": TOOL_VERSION}
            ],
        },
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# Probe gate
# ---------------------------------------------------------------------------


def run_probes(config: dict[str, Any], results: dict[str, tuple[Root, ScanResult]]) -> list[str]:
    """Return the probes that read as unreachable — i.e. the resolver is wrong."""
    failed: list[str] = []
    for probe in config["probes"]:
        seen_anywhere = False
        ok = False
        for _rid, (_root_obj, res) in results.items():
            if probe in res.all_files:
                seen_anywhere = True
                if probe in res.reachable:
                    ok = True
        if not seen_anywhere:
            failed.append(f"{probe} (not matched by any root's `include`)")
        elif not ok:
            failed.append(f"{probe} (in scope but read as UNREACHABLE)")
    return failed


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def _load(explicit: str | None) -> tuple[Path, Path, dict[str, Any]] | None:
    config_path = resolve_config(explicit, CONFIG_NAME)
    if config_path is None or not config_path.is_file():
        return None
    consumer = find_consumer_root(config_path.parent, CONFIG_NAME)
    config = load_config(config_path)
    base = (consumer / config["root"]).resolve()
    if not base.is_dir():
        raise ConfigError(f"`root` {config['root']!r} does not exist")
    return config_path, base, config


def _scan_all(root: Path, config: dict[str, Any]) -> tuple[dict[str, tuple[Root, ScanResult]], list[str]]:
    entry_globs = preset_entrypoints(config["presets"]) + list(config["entrypoints"])
    results: dict[str, tuple[Root, ScanResult]] = {}
    for spec in config["roots"]:
        results[spec["id"]] = scan_root(root, spec, entry_globs)
    return results, entry_globs


def cmd_scan(args: argparse.Namespace) -> int:
    loaded = _load(args.config)
    if loaded is None:
        print("no sweep.yaml in this consumer — nothing to scan")
        return 0
    config_path, root, config = loaded

    started = datetime.now(UTC)
    results, entry_globs = _scan_all(root, config)
    duration_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)

    failed = run_probes(config, results)
    if failed:
        emit_error(
            why=f"{len(failed)} probe(s) declared live read as unreachable: {'; '.join(failed)}",
            where=str(config_path),
            fix=(
                "the RESOLVER is wrong, not the repo. Check that every root declares "
                "`resolve_from` pointing at the project's tsconfig (its `paths` aliases are "
                "the ground truth for what an import means), and that the presets cover this "
                "framework's entry points. No ledger was written — a scan that cannot see a "
                "file you know is live cannot be trusted about the ones you do not."
            ),
            override="none (fix the resolver; a skipped probe gate is a scan nobody validated)",
        )
        return 1

    ledger = build_ledger(root, config, results, entry_globs, started, duration_ms)

    if args.out:
        out = Path(args.out)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            # Loud, and exit 2: a scan whose ledger never landed must not read as
            # a completed scan to whatever runs next.
            emit_error(
                what=f"cannot write the ledger to {args.out}",
                why=str(exc),
                where=str(args.out),
                fix="choose a writable path, or drop --out to print the summary only.",
                override="none",
            )
            return 2
    if args.as_json:
        print(json.dumps(ledger, indent=2))
    else:
        total = sum(len(r.all_files) for _, r in results.values())
        unparseable = [f for _, r in results.values() for f in r.unparseable]
        print(f"sweep: {len(config['probes'])} probe(s) OK — resolver validated")
        for rid, (_ro, res) in results.items():
            orphans = len(res.all_files - res.reachable)
            skipped = f"  ({res.ignored} gitignored)" if res.ignored else ""
            print(f"  {rid:12} {len(res.all_files):5} files  {len(res.reachable):5} reachable  "
                  f"{orphans:4} candidate(s){skipped}")
        for rel in unparseable:
            print(f"  ℹ unparseable, imports not counted: {rel}")
        print(f"sweep: {len(ledger['findings'])} candidate(s) over {total} file(s) "
              f"in {duration_ms} ms")
        if args.out:
            print(f"sweep: ledger written to {args.out}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    loaded = _load(args.config)
    if loaded is None:
        print("no sweep.yaml in this consumer")
        return 0
    config_path, root, config = loaded
    results, _ = _scan_all(root, config)
    failed = run_probes(config, results)
    if failed:
        emit_error(
            why=f"{len(failed)} probe(s) failed: {'; '.join(failed)}",
            where=str(config_path),
            fix="fix the resolver or the presets before trusting any finding.",
            override="none",
        )
        return 1
    print(f"sweep: {len(config['probes'])} probe(s) OK — resolver sees every known-live file")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    loaded = _load(args.config)
    if loaded is None:
        print("no sweep.yaml in this consumer — nothing to validate")
        return 0
    config_path, _, config = loaded
    print(f"sweep: {config_path} is valid — {len(config['roots'])} root(s), "
          f"{len(config['presets'])} preset(s), {len(config['probes'])} probe(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sweep-scan")
    sub = parser.add_subparsers(dest="cmd", required=True)

    scan = sub.add_parser("scan", help="Scan and emit the ledger.")
    scan.add_argument("--config")
    scan.add_argument("--out", help="Write the sweep-manifest JSON here.")
    scan.add_argument("--json", dest="as_json", action="store_true")
    scan.set_defaults(func=cmd_scan)

    probe = sub.add_parser("probe", help="Run the probe gate alone.")
    probe.add_argument("--config")
    probe.set_defaults(func=cmd_probe)

    validate = sub.add_parser("validate", help="Validate the config only.")
    validate.add_argument("--config")
    validate.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        emit_error(
            why=f"sweep config error: {exc}",
            where=str(args.config or CONFIG_NAME),
            fix="fix the contract. An unevaluable config must never be reported as a clean repo.",
            # `none`, deliberately: this scanner never gates a commit, so there is
            # nothing for a skip switch to unblock. Advertising one that no code
            # reads is worse than having none — the user sets it and sees exit 2.
            override="none",
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
