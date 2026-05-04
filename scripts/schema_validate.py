"""Validate an AGENTS.md YAML frontmatter against specs/agents-md-v1.schema.json.

Populated in T09. Supersedes the T03a stub.

CLI
---
    python -m scripts.schema_validate <path>... [--autofix] [--force-with-reason TEXT]

Behaviour
---------
- If `<path>` is omitted, validates `AGENTS.md` in the current working directory.
- Reads the frontmatter (delimited by `---` on its own line) and validates it
  against `specs/agents-md-v1.schema.json`.
- On failure: emits a canonical error in WHY / WHERE / FIX / OVERRIDE shape and
  exits 1.
- `--autofix`: applies the "WILL" list from `specs/migration-guide.md`:
    * Missing frontmatter -> inject sensible defaults.
    * `updated` in near-ISO variants -> normalise to YYYY-MM-DD.
    * Invalid `project` slug -> slugify (valid slugs are left alone).
    * Missing `capabilities_map` -> add `false`.
    * Missing `inherits_from` -> add `[github.com/Wizarck/ai-playbook@<pinned>]`
      where `<pinned>` is read from `<cwd>/.ai-playbook/VERSION` (if it exists)
      else `v0.1.0`.
  After a fix the file is re-written in place and a diff-like summary is printed.
- `--force-with-reason="<text>"`: always allowed for this gate. Logs the
  override to `.ai-playbook/overrides.log` and exits 0.

Exit codes
----------
    0 success (or override applied)
    1 validation failure (canonical error was emitted)
    2 environment failure (schema file missing, pyyaml/jsonschema missing)
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

# Force UTF-8 stdio — Windows default cp1252 cannot encode the sigils we emit.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

try:
    import yaml
except ImportError:
    print("❌ PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    raise SystemExit(2) from None

try:
    import jsonschema
except ImportError:
    print("❌ jsonschema is required. Install with: pip install jsonschema", file=sys.stderr)
    raise SystemExit(2) from None

from scripts._break_glass import add_break_glass_flag, apply_break_glass  # noqa: E402

SCRIPT_BASENAME = "schema_validate.py"
GATE_NAME = "agents-md-schema"
DEFAULT_PINNED_VERSION = "v0.1.0"
SCHEMA_RELPATH = Path("specs") / "agents-md-v1.schema.json"
SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Dev-flow cross-ref check (per specs/bootstrap-directive.md v1.2.0).
# AGENTS.md body MUST contain a link to development-flow.md somewhere.
# Warn-only initially; promote to strict after 30d via --strict-dev-flow-cross-ref.
DEV_FLOW_CROSS_REF_RE = re.compile(r"development-flow\.md")

MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ],
        start=1,
    )
}


@dataclass
class Frontmatter:
    """Parsed YAML frontmatter result.

    `present=False` means the file has no `---` fenced frontmatter at all; in
    that case `data` is an empty dict, `raw=""`, `start_line`/`end_line` are
    zero, and `body` is the whole file text (prepended after autofix).
    """

    present: bool
    data: dict[str, Any]
    raw: str
    start_line: int
    end_line: int
    body: str


# ---------------------------------------------------------------------------
# Playbook-repo discovery (to locate the schema file)
# ---------------------------------------------------------------------------


def find_playbook_root() -> Path | None:
    """Locate the ai-playbook repo root (where specs/ lives).

    Checks this script's directory first, then walks up looking for `specs/`.
    """
    here = Path(__file__).resolve().parent
    for candidate in (here.parent, *here.parents):
        if (candidate / SCHEMA_RELPATH).is_file():
            return candidate
    return None


def load_schema() -> dict[str, Any]:
    root = find_playbook_root()
    if root is None:
        print(
            f"❌ schema file not found at <playbook>/{SCHEMA_RELPATH.as_posix()} "
            f"at {SCRIPT_BASENAME}:schema-load",
            file=sys.stderr,
        )
        print(
            "   FIX: run this script from inside an ai-playbook checkout, or "
            "set up the repo via `git submodule add`.",
            file=sys.stderr,
        )
        print("   OVERRIDE: none", file=sys.stderr)
        raise SystemExit(2) from None
    import json

    return json.loads((root / SCHEMA_RELPATH).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> Frontmatter:
    """Split an AGENTS.md into frontmatter + body.

    Line numbers are 1-indexed. `start_line` is the line of the opening `---`,
    `end_line` is the line of the closing `---`.
    """
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return Frontmatter(
            present=False, data={}, raw="", start_line=0, end_line=0, body=text
        )
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return Frontmatter(
            present=False, data={}, raw="", start_line=0, end_line=0, body=text
        )
    raw = "\n".join(lines[1:end])
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    body = "\n".join(lines[end + 1 :])
    return Frontmatter(
        present=True,
        data=data,
        raw=raw,
        start_line=1,
        end_line=end + 1,
        body=body,
    )


# ---------------------------------------------------------------------------
# Canonical error emission
# ---------------------------------------------------------------------------


def _format_path(p: Path) -> str:
    return p.resolve().as_posix()


def emit_error(
    *, why: str, where: str, fix: str, override_invocation: str | None
) -> None:
    """Print the 4-line canonical error."""
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    if override_invocation is None:
        print("   OVERRIDE: none", file=sys.stderr)
    else:
        print(f"   OVERRIDE: {override_invocation}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Autofix helpers
# ---------------------------------------------------------------------------


def read_pinned_version(cwd: Path) -> str:
    """Read pinned playbook version from <cwd>/.ai-playbook/VERSION, fallback v0.1.0."""
    version_file = cwd / ".ai-playbook" / "VERSION"
    if version_file.is_file():
        text = version_file.read_text(encoding="utf-8").strip()
        if text:
            if not text.startswith("v"):
                text = f"v{text}"
            return text
    return DEFAULT_PINNED_VERSION


def slugify(value: str) -> str:
    """Lowercase + replace spaces/underscores with hyphens. Strip invalid chars."""
    out = value.strip().lower().replace("_", "-")
    out = re.sub(r"\s+", "-", out)
    out = re.sub(r"[^a-z0-9\-]", "", out)
    out = re.sub(r"-{2,}", "-", out).strip("-")
    return out or "project"


def normalise_date(value: Any) -> str | None:
    """Coerce common near-ISO variants to YYYY-MM-DD. Return None if unrecognised."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if DATE_RE.match(raw):
        return raw
    # 2026/04/23 or 2026.04.23
    m = re.match(r"^(\d{4})[/.](\d{1,2})[/.](\d{1,2})$", raw)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    # 2026-4-23 (missing zero padding)
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", raw)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    # "April 23 2026" or "April 23, 2026"
    m = re.match(
        r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", raw
    )
    if m:
        month_name, d, y = m.groups()
        mo = MONTHS.get(month_name.lower())
        if mo:
            return f"{int(y):04d}-{mo:02d}-{int(d):02d}"
    # "23 April 2026"
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", raw)
    if m:
        d, month_name, y = m.groups()
        mo = MONTHS.get(month_name.lower())
        if mo:
            return f"{int(y):04d}-{mo:02d}-{int(d):02d}"
    return None


def build_default_frontmatter(
    project_slug: str, owner_email: str, pinned_version: str
) -> dict[str, Any]:
    """Return the full default block per migration-guide.md."""
    return {
        "schema": "agents-md/v1",
        "version": "0.1.0",
        "inherits_from": [f"github.com/Wizarck/ai-playbook@{pinned_version}"],
        "updated": date.today().isoformat(),
        "project": project_slug,
        "owner": owner_email,
        "capabilities_map": False,
    }


def serialise_frontmatter(fm: dict[str, Any]) -> str:
    """Render a frontmatter dict back to YAML with stable field order."""
    field_order = [
        "schema",
        "version",
        "inherits_from",
        "updated",
        "project",
        "owner",
        "capabilities_map",
        "personal",
        "personal_addon",
    ]
    ordered: dict[str, Any] = {}
    for key in field_order:
        if key in fm:
            ordered[key] = fm[key]
    for key in fm:
        if key not in ordered:
            ordered[key] = fm[key]
    return yaml.safe_dump(
        ordered,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


def apply_autofix(
    fm: Frontmatter, *, file_path: Path
) -> tuple[Frontmatter, list[str]]:
    """Apply the migration-guide.md WILL list to the frontmatter.

    Returns (new_frontmatter, applied_fixes). `applied_fixes` is a list of
    human-readable strings suitable for printing as a diff-like summary.
    """
    fixes: list[str] = []
    pinned = read_pinned_version(file_path.parent)

    if not fm.present:
        owner = _guess_owner_email()
        slug = slugify(file_path.parent.name)
        data = build_default_frontmatter(slug, owner, pinned)
        fixes.append(
            f"injected full default frontmatter (project={slug}, owner={owner}, "
            f"pinned={pinned})"
        )
        new_fm = Frontmatter(
            present=True,
            data=data,
            raw=serialise_frontmatter(data),
            start_line=1,
            end_line=0,
            body=fm.body,
        )
        return new_fm, fixes

    data = dict(fm.data)

    if "schema" not in data:
        data["schema"] = "agents-md/v1"
        fixes.append("added `schema: agents-md/v1`")

    if "updated" in data:
        normalised = normalise_date(data["updated"])
        if normalised and normalised != str(data["updated"]):
            fixes.append(
                f"normalised `updated: {data['updated']!r}` -> `{normalised}`"
            )
            data["updated"] = normalised
        elif isinstance(data["updated"], (date, datetime)):
            # PyYAML loads dates as date objects; serialise back to ISO string.
            normalised = normalise_date(data["updated"])
            if normalised:
                data["updated"] = normalised

    if "project" in data:
        raw_project = data["project"]
        if isinstance(raw_project, str) and not SLUG_RE.match(raw_project):
            new_slug = slugify(raw_project)
            fixes.append(
                f"slugified `project: {raw_project!r}` -> `{new_slug}`"
            )
            data["project"] = new_slug

    if "capabilities_map" not in data:
        data["capabilities_map"] = False
        fixes.append("added `capabilities_map: false`")

    if "inherits_from" not in data or not data.get("inherits_from"):
        data["inherits_from"] = [f"github.com/Wizarck/ai-playbook@{pinned}"]
        fixes.append(
            f"added `inherits_from: [github.com/Wizarck/ai-playbook@{pinned}]`"
        )

    new_fm = Frontmatter(
        present=True,
        data=data,
        raw=serialise_frontmatter(data),
        start_line=fm.start_line,
        end_line=fm.end_line,
        body=fm.body,
    )
    return new_fm, fixes


def write_frontmatter(file_path: Path, fm: Frontmatter) -> None:
    """Rewrite file with updated frontmatter, preserving the body verbatim."""
    raw = fm.raw
    if not raw.endswith("\n"):
        raw += "\n"
    body = fm.body
    text = f"---\n{raw}---\n"
    if body and not body.startswith("\n"):
        text += "\n" + body
    else:
        text += body
    file_path.write_text(text, encoding="utf-8", newline="\n")


def _guess_owner_email() -> str:
    """Best-effort owner email lookup. Falls back to `unknown@example.com`."""
    import os
    import subprocess

    for env_key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL", "EMAIL"):
        val = os.environ.get(env_key)
        if val:
            return val
    try:
        out = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "unknown@example.com"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _coerce_for_validation(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce YAML-native types to JSON-Schema-friendly strings where relevant.

    PyYAML loads `updated: 2026-04-23` as `datetime.date`. JSON Schema's
    `format: date` expects a string. Coerce before validation so unquoted ISO
    dates still pass. Non-date fields are passed through unchanged.
    """
    coerced = dict(data)
    upd = coerced.get("updated")
    if isinstance(upd, datetime):
        coerced["updated"] = upd.date().isoformat()
    elif isinstance(upd, date):
        coerced["updated"] = upd.isoformat()
    return coerced


def validate_frontmatter(
    data: dict[str, Any], schema: dict[str, Any]
) -> list[str]:
    """Return a list of human-readable error strings. Empty = valid."""
    validator = jsonschema.Draft202012Validator(schema)
    coerced = _coerce_for_validation(data)
    errors: list[str] = []
    for err in sorted(validator.iter_errors(coerced), key=lambda e: list(e.absolute_path)):
        loc = ".".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"{loc}: {err.message}")
    return errors


def check_dev_flow_cross_ref(body: str) -> bool:
    """Return True if the AGENTS.md body references development-flow.md.

    Body is the post-frontmatter content; a single occurrence anywhere is
    sufficient (consumers SHOULD put it as the first row of §2 Dispatcher
    index, but the check is permissive — link presence is the contract).

    Per specs/bootstrap-directive.md v1.2.0.
    """
    return bool(DEV_FLOW_CROSS_REF_RE.search(body))


def validate_one(
    file_path: Path,
    *,
    schema: dict[str, Any],
    autofix: bool,
    strict_dev_flow_cross_ref: bool = False,
) -> int:
    """Validate a single file. Returns exit code for this file."""
    if not file_path.is_file():
        emit_error(
            why="AGENTS.md not found",
            where=f"{_format_path(file_path)}",
            fix=(
                f"create {file_path.name} with the default frontmatter, or re-run "
                f"with --autofix to inject it."
            ),
            override_invocation=(
                f"python -m scripts.schema_validate {file_path} "
                f"--force-with-reason=\"<>=10 char reason\""
            ),
        )
        return 1
    text = file_path.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)

    if autofix:
        new_fm, fixes = apply_autofix(fm, file_path=file_path)
        if fixes:
            write_frontmatter(file_path, new_fm)
            print(f"✅ autofix applied to {_format_path(file_path)}:")
            for f in fixes:
                print(f"  - {f}")
        fm = new_fm

    if not fm.present:
        emit_error(
            why="AGENTS.md has no YAML frontmatter block",
            where=f"{_format_path(file_path)}:1",
            fix=(
                "add a `---` fenced frontmatter at the top of the file per "
                "specs/agents-md-v1.schema.json; or run with --autofix."
            ),
            override_invocation=(
                f"python -m scripts.schema_validate {file_path} "
                f"--force-with-reason=\"<>=10 char reason\""
            ),
        )
        return 1

    errors = validate_frontmatter(fm.data, schema)

    # Dev-flow cross-ref check (specs/bootstrap-directive.md v1.2.0).
    # Always evaluated; warn-only by default, error when --strict-dev-flow-cross-ref.
    cross_ref_ok = check_dev_flow_cross_ref(fm.body)
    cross_ref_failed = not cross_ref_ok

    if not errors and not (strict_dev_flow_cross_ref and cross_ref_failed):
        print(f"✅ {_format_path(file_path)} frontmatter valid (agents-md/v1).")
        if cross_ref_failed:
            # Warn-only path: print to stderr but exit 0.
            print(
                f"⚠️  {_format_path(file_path)} body lacks a link to "
                f"development-flow.md (specs/bootstrap-directive.md v1.2.0). "
                f"Add it to §2 Dispatcher index. Will become an error in a "
                f"future version (currently warn-only).",
                file=sys.stderr,
            )
        return 0

    for err in errors:
        emit_error(
            why=f"AGENTS.md frontmatter invalid: {err}",
            where=f"{_format_path(file_path)}:{fm.start_line}",
            fix=(
                "see specs/agents-md-v1.schema.json for the contract; "
                "`--autofix` repairs the common cases."
            ),
            override_invocation=(
                f"python -m scripts.schema_validate {file_path} "
                f"--force-with-reason=\"<>=10 char reason\""
            ),
        )

    if strict_dev_flow_cross_ref and cross_ref_failed:
        emit_error(
            why=(
                "AGENTS.md §2 Dispatcher index lacks the canonical "
                "development-flow.md cross-reference"
            ),
            where=f"{_format_path(file_path)}",
            fix=(
                "add the row `| **How to make a change in this project (canonical "
                "entry point)** | [.ai-playbook/docs/development-flow.md]"
                "(.ai-playbook/docs/development-flow.md) |` to §2 Dispatcher "
                "index. See specs/bootstrap-directive.md v1.2.0."
            ),
            override_invocation=(
                f"python -m scripts.schema_validate {file_path} "
                f"--force-with-reason=\"<>=10 char reason\""
            ),
        )
    return 1


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="schema_validate",
        description=(
            "Validate AGENTS.md frontmatter against the v1 JSON schema. "
            "See specs/agents-md-v1.schema.json and specs/migration-guide.md."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="AGENTS.md file(s) to validate. Defaults to ./AGENTS.md.",
    )
    parser.add_argument(
        "--autofix",
        action="store_true",
        help="Apply migration-guide.md WILL list fixes in-place.",
    )
    parser.add_argument(
        "--strict-dev-flow-cross-ref",
        action="store_true",
        help=(
            "Promote the development-flow.md cross-ref check from warn-only "
            "to error. Defaults to off during the v0.9.3+ rollout window; "
            "flip on after 30 days of green builds (per "
            "specs/bootstrap-directive.md v1.2.0)."
        ),
    )
    add_break_glass_flag(parser)
    args = parser.parse_args(argv)

    schema = load_schema()

    paths: list[Path] = args.paths or [Path.cwd() / "AGENTS.md"]

    overall: int = 0
    for p in paths:
        rc = validate_one(
            p,
            schema=schema,
            autofix=args.autofix,
            strict_dev_flow_cross_ref=args.strict_dev_flow_cross_ref,
        )
        if rc != 0:
            overall = rc

    if overall == 0:
        return 0

    # Break-glass: this gate is always overridable.
    result = apply_break_glass(
        gate=GATE_NAME,
        script=SCRIPT_BASENAME,
        reason=args.force_reason,
        override_allowed=True,
        repo_root=Path.cwd(),
    )
    if result.applied:
        print(f"⚠️ OVERRIDE APPLIED: {result.reason}")
        print("   actor: logged")
        print(f"   logged: {(Path.cwd() / '.ai-playbook' / 'overrides.log').as_posix()}")
        return 0
    return overall


if __name__ == "__main__":
    raise SystemExit(main())
