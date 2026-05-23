"""Validate the slug-based pairing convention (D3 + D12).

Enforces 4 defense signals per rule:

1. Filename slug — `scripts/rules/<slug>.rule.py` ⇔ `docs/rules/<slug>.rule.md`
   ⇔ `tests/test_<slug>.py` ⇔ `.github/workflows/<slug>.rule.yml`
2. Frontmatter `slug:` in `docs/rules/<slug>.rule.md` matches filename
3. `paired_hardrule:` cross-reference points to the existing `.rule.py`
4. AGENTS.md Rule Map entry mentions the slug

CLI:

    python -m scripts.validate_pairing            # default: STRICT (Slice 5.F)
    python -m scripts.validate_pairing --lenient  # legacy Slice-4 lifeline mode
    python -m scripts.validate_pairing --include-local  # D13 local-rules/

Exit codes:
    0 — all signals consistent
    2 — drift detected (prints offending paths)

Default mode flipped to STRICT in Slice 5.F (v0.18.1). The lenient mode is
preserved as `--lenient` for legacy CI callers that still need the Slice-4
window where frontmatter / paired_hardrule paths could be absent.

Deferred hardrules: rules whose `paired_hardrule:` names a `.rule.py` that
ships in a later slice can be listed in `scripts/rules/deferred-hardrules.txt`
(one slug per line, `#` comments allowed). The "not found on disk" check is
downgraded to a no-op for listed slugs. Every entry is mirrored in
`openspec/changes/slice-5f-harmonization/deferred-strict-failures.md` for
audit-trail discoverability.

Self-test fixtures live in `tests/test_validate_pairing.py` (≥30 cases per
D12 defense-in-depth). A parallel shell oracle
`scripts/validate_pairing_oracle.sh` re-implements signal #1 as a tripwire.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

# Stdlib YAML
try:
    import yaml
except ImportError as exc:  # pragma: no cover
    print(
        "FATAL: pyyaml not installed. Run `pip install pyyaml` or `pip install -e .`",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

REPO_ROOT = Path(__file__).resolve().parent.parent
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


class PairingError(NamedTuple):
    slug: str
    signal: str  # "filename" | "frontmatter" | "hardrule" | "rulemap"
    detail: str


def _parse_frontmatter(md_path: Path) -> dict | None:
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


def _discover_rule_docs(root: Path, include_local: bool = False) -> list[Path]:
    paths = sorted((root / "docs" / "rules").glob("*.rule.md"))
    if include_local:
        local = root / "local-rules"
        if local.is_dir():
            paths.extend(sorted(local.glob("*.rule.md")))
    return paths


def _discover_rule_scripts(root: Path) -> list[Path]:
    return sorted((root / "scripts" / "rules").glob("*.rule.py"))


def _slug_from_filename(p: Path) -> str:
    # Strip trailing `.rule.md` or `.rule.py` or `.rule.yml`.
    name = p.name
    for suffix in (".rule.md", ".rule.py", ".rule.yml", ".rule.yaml"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return p.stem


def _load_deferred_hardrules(root: Path) -> set[str]:
    """Load slugs whose paired_hardrule .py is acknowledged as deferred.

    The Slice 5 rewrite landed 38 rule docs but only 9 paired hardrule scripts.
    The remaining ~25 rules name a `paired_hardrule:` that ships in a future
    slice. Listing the slug here downgrades the "not found on disk" strict
    check to a no-op so CI can run strict-by-default without faking either
    side of the contract.
    """
    deferred_path = root / "scripts" / "rules" / "deferred-hardrules.txt"
    if not deferred_path.is_file():
        return set()
    slugs: set[str] = set()
    for line in deferred_path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            slugs.add(line)
    return slugs


def validate(root: Path = REPO_ROOT, *, strict: bool = True, include_local: bool = False) -> list[PairingError]:
    errors: list[PairingError] = []

    # Index slugs known via each signal.
    doc_paths = _discover_rule_docs(root, include_local=include_local)
    script_paths = _discover_rule_scripts(root)

    doc_slugs: dict[str, Path] = {}
    for p in doc_paths:
        slug = _slug_from_filename(p)
        if not SLUG_RE.match(slug):
            errors.append(PairingError(slug, "filename", f"slug {slug!r} from {p} fails regex"))
            continue
        if slug in doc_slugs:
            errors.append(PairingError(slug, "filename", f"duplicate doc slug at {p} and {doc_slugs[slug]}"))
        doc_slugs[slug] = p

    script_slugs: dict[str, Path] = {}
    for p in script_paths:
        slug = _slug_from_filename(p)
        if not SLUG_RE.match(slug):
            errors.append(PairingError(slug, "filename", f"slug {slug!r} from {p} fails regex"))
            continue
        script_slugs[slug] = p

    # AGENTS.md Rule Map text (signal #4).
    agents_path = root / "AGENTS.md"
    agents_text = agents_path.read_text(encoding="utf-8") if agents_path.is_file() else ""

    # Slugs whose paired_hardrule .py ships in a later slice.
    deferred_slugs = _load_deferred_hardrules(root)

    # Cross-validate each doc.
    for slug, doc in doc_slugs.items():
        fm = _parse_frontmatter(doc)
        if fm is None:
            # Slice 5 rewrites legacy content to add frontmatter. Until then,
            # missing frontmatter is a WARN (only fail under --strict).
            if strict:
                errors.append(PairingError(slug, "frontmatter", f"missing or invalid frontmatter at {doc}"))
            continue

        # Signal #2: frontmatter slug matches filename.
        fm_slug = fm.get("slug")
        if fm_slug is not None and fm_slug != slug:
            errors.append(PairingError(
                slug, "frontmatter",
                f"frontmatter slug={fm_slug!r} != filename slug={slug!r} at {doc}",
            ))

        # Signal #3: paired_hardrule cross-reference. Treat as null (advisory)
        # when the field is absent — Slice 5 backfills the field.
        ph = fm.get("paired_hardrule", None) if "paired_hardrule" in fm else None
        if ph is None:
            # Advisory-only — require exception justification.
            exc_doc = root / "docs" / "concepts" / "enforcement-pairing-exceptions.md"
            if strict and exc_doc.is_file():
                exc_text = exc_doc.read_text(encoding="utf-8")
                if slug not in exc_text:
                    errors.append(PairingError(
                        slug, "hardrule",
                        f"advisory rule {slug!r} not justified in "
                        f"enforcement-pairing-exceptions.md",
                    ))
        elif isinstance(ph, str):
            ph_path = root / ph
            if not ph_path.is_file():
                # Slice 5 declares paired_hardrule paths ahead of the .rule.py
                # implementation (the hardrules ship in a later slice). Strict
                # mode (default since 5.F) flags this unless the slug appears
                # in scripts/rules/deferred-hardrules.txt — the audit-trail
                # allowlist for known-deferred hardrules.
                if strict and slug not in deferred_slugs:
                    errors.append(PairingError(
                        slug, "hardrule",
                        f"paired_hardrule {ph!r} not found on disk",
                    ))
            else:
                expected_script_slug = _slug_from_filename(ph_path)
                if expected_script_slug != slug:
                    errors.append(PairingError(
                        slug, "hardrule",
                        f"paired_hardrule slug {expected_script_slug!r} != "
                        f"doc slug {slug!r}",
                    ))
        else:
            errors.append(PairingError(
                slug, "hardrule",
                f"paired_hardrule must be string or null, got {type(ph).__name__}",
            ))

        # Signal #4: AGENTS.md mentions the slug (best-effort lint; not strict
        # by default because AGENTS.md is regenerated by gen_indexes.py).
        if strict and agents_text and slug not in agents_text:
            errors.append(PairingError(
                slug, "rulemap",
                f"slug {slug!r} not present in AGENTS.md Rule Map",
            ))

    # Reverse direction: script has no doc.
    for slug, script in script_slugs.items():
        if slug not in doc_slugs:
            errors.append(PairingError(
                slug, "filename",
                f"orphan hardrule {script} (no matching docs/rules/{slug}.rule.md)",
            ))

    return errors


def _format_errors(errors: Iterable[PairingError]) -> str:
    lines = []
    for e in errors:
        lines.append(f"[{e.signal}] {e.slug}: {e.detail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate ai-playbook rule pairing (D3 + D12).",
    )
    parser.add_argument(
        "--lenient",
        action="store_true",
        help=(
            "Run in legacy Slice-4 mode — skip frontmatter, hardrule-on-disk, "
            "and AGENTS.md Rule Map gates. Default is strict (Slice 5.F)."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Deprecated no-op — strict is the default since Slice 5.F. Kept "
            "for backward compatibility with older CI workflows; ignored."
        ),
    )
    parser.add_argument(
        "--include-local",
        action="store_true",
        help="Also validate consumer-side local-rules/ (D13).",
    )
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repo root.")
    args = parser.parse_args(argv)

    strict = not args.lenient  # default strict, --lenient opts back to legacy
    errors = validate(Path(args.root), strict=strict, include_local=args.include_local)
    if errors:
        print(_format_errors(errors), file=sys.stderr)
        return 2
    print("validate_pairing: OK")
    return 0


if __name__ == "__main__":
    from scripts.rules._telemetry import script_emit
    sys.exit(script_emit("validate-pairing", main))
