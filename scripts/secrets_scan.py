"""Scan working tree / staged diff / literal text for plaintext secrets.

This is the *non-overridable* credential-exposure gate per
`specs/agentic-failures.md` §2.11 and `specs/break-glass.md` §"Scripts that MUST
support break-glass" (where this row is listed with `OVERRIDE: none` ALWAYS).

Modes
-----
    python -m scripts.secrets_scan <path> [<path>...]          # scan paths (files/dirs)
    python -m scripts.secrets_scan --staged                    # scan git-staged files
    python -m scripts.secrets_scan --text "literal string"     # scan a literal string
    echo "..." | python -m scripts.secrets_scan -              # read text from stdin
    echo "..." | python -m scripts.secrets_scan \
        --sanitise-for hindsight                               # redact & print sanitised

Importable API
--------------
    from scripts.secrets_scan import scan, sanitise, Match

    matches = scan(text)                       # list[Match]
    sanitised_text, kinds = sanitise(text)     # tuple[str, list[str]]

Exit codes (per `specs/error-message-standard.md`)
---------------------------------------------------
    0 = no matches (scan mode), or sanitise-for hindsight finished (always 0)
    2 = environment/setup problem (couldn't read a file, invalid CLI combo)
    3 = hard block — at least one secret matched in scan mode
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

# Force UTF-8 stdio — Windows default cp1252 cannot encode the ❌/⚠️/✅ sigils
# we emit, and secrets-scan output on Windows CI is routinely piped into UTF-8
# sinks (gh-actions log, pre-commit aggregator).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


# ---------------------------------------------------------------------------
# Regex catalogue. Each entry is (kind, compiled-pattern). Kinds are stable
# strings used in error output, sanitised placeholders `[REDACTED:<kind>]`,
# and OTel attributes. NEVER print the matched group text.
#
# Patterns are designed to be:
#   - precise enough to avoid flagging obvious non-secrets (e.g. `sk-`
#     followed by a short word)
#   - permissive enough to catch real keys even if future provider rotations
#     change the exact suffix length
#
# New patterns must include at least one docstring example and land with a
# test in `tests/test_secrets_scan.py`.
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Anthropic API key. Example: sk-ant-api03-abc...XYZ (>= 50 chars after prefix).
    ("anthropic_api_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{50,}")),
    # OpenAI API key — legacy and "proj-" project keys.
    # Example: sk-proj-abc...xyz (>= 32 chars after prefix).
    ("openai_api_key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9]{32,}")),
    # GitHub personal access token / fine-grained / server-to-server.
    # Example: ghp_abc..., ghs_..., gho_..., ghu_..., ghr_...
    ("github_pat", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    # AWS Access Key ID. Example: AKIAIOSFODNN7EXAMPLE.
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    # AWS Secret Access Key: only when paired with an obvious assignment.
    # Example: aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY".
    (
        "aws_secret_access_key",
        re.compile(
            r"aws_secret_access_key\s*[:=]\s*['\"][A-Za-z0-9/+=]{40}['\"]",
            re.IGNORECASE,
        ),
    ),
    # Langfuse observability keys.
    ("langfuse_public_key", re.compile(r"pk-lf-[A-Za-z0-9\-]{20,}")),
    ("langfuse_secret_key", re.compile(r"sk-lf-[A-Za-z0-9\-]{20,}")),
    # Generic JWT: three base64url chunks separated by dots, first starts "eyJ".
    # Example: eyJhbGciOi...eyJzdWIiOi....abc-def.
    (
        "jwt",
        re.compile(
            r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"
        ),
    ),
    # Generic SECRET/TOKEN/KEY=value envs. Only fires when RHS is >=20 chars,
    # quoted, and contains a mix of classes (lowers/UPPERS/digits). The
    # mix-class requirement is asserted post-match in `_generic_env_is_secret`.
    (
        "generic_env_secret",
        re.compile(
            r"""(?P<prefix>[A-Z][A-Z0-9_]*(?:SECRET|TOKEN|KEY|PASSWORD|PASS|APIKEY))"""
            r"""\s*[:=]\s*['\"](?P<val>[A-Za-z0-9/+=_\-]{20,})['\"]""",
        ),
    ),
]


# Directory names we will not recurse into when scanning a tree.
_IGNORE_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", ".env",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "dist", "build", ".next", ".turbo", "target",
})


@dataclass(frozen=True)
class Match:
    """A single secret-like hit."""

    kind: str
    path: Path | None  # None when scanning literal text
    line_no: int  # 1-indexed; 1 for literal-text scans
    start: int
    end: int

    def location(self) -> str:
        if self.path is None:
            return f"<stdin>:{self.line_no}"
        # Use forward slashes per error-message-standard.md (piped output).
        return f"{self.path.as_posix()}:{self.line_no}"


def _generic_env_is_secret(value: str) -> bool:
    """Heuristic: the RHS looks secret-y (classes mix + no obvious placeholder)."""
    if len(value) < 20:
        return False
    lowered = value.lower()
    if any(ph in lowered for ph in (
        "example", "changeme", "redacted", "xxxx", "****", "your-", "<", ">",
    )):
        return False
    has_lower = any(c.islower() for c in value)
    has_upper = any(c.isupper() for c in value)
    has_digit = any(c.isdigit() for c in value)
    classes = sum([has_lower, has_upper, has_digit])
    return classes >= 2


def scan(text: str, *, kinds: list[str] | None = None) -> list[Match]:
    """Scan a literal string. Return all matches (possibly empty).

    `kinds` restricts to a subset of pattern names; `None` means all.
    Line numbers are 1-indexed relative to `text`.
    """
    if not text:
        return []

    selected = _PATTERNS if kinds is None else [p for p in _PATTERNS if p[0] in kinds]

    # Pre-compute line offsets so we can map a byte offset -> line number in O(log n).
    line_starts: list[int] = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            line_starts.append(i + 1)

    def _line_no_of(offset: int) -> int:
        # bisect without importing bisect — small N.
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    out: list[Match] = []
    for kind, pattern in selected:
        for m in pattern.finditer(text):
            if kind == "generic_env_secret":
                val = m.group("val")
                if not _generic_env_is_secret(val):
                    continue
            out.append(
                Match(
                    kind=kind,
                    path=None,
                    line_no=_line_no_of(m.start()),
                    start=m.start(),
                    end=m.end(),
                )
            )
    # Stable ordering by offset.
    out.sort(key=lambda x: (x.start, x.kind))
    return out


def sanitise(text: str) -> tuple[str, list[str]]:
    """Return `(redacted_text, list_of_kinds)` with matches replaced in-place.

    Replacement token is `[REDACTED:<kind>]`. Deduplicated kinds returned (sorted).
    """
    matches = scan(text)
    if not matches:
        return text, []
    # Replace from right to left so earlier indices stay valid.
    redacted = text
    for m in sorted(matches, key=lambda x: x.start, reverse=True):
        redacted = redacted[: m.start] + f"[REDACTED:{m.kind}]" + redacted[m.end :]
    kinds = sorted({m.kind for m in matches})
    return redacted, kinds


# ---------------------------------------------------------------------------
# File / directory walking
# ---------------------------------------------------------------------------


def _is_probably_binary(path: Path, sample_size: int = 2048) -> bool:
    try:
        chunk = path.read_bytes()[:sample_size]
    except OSError:
        return True
    if not chunk:
        return False
    # Null byte ⇒ binary; high ratio of non-printables likewise.
    if b"\x00" in chunk:
        return True
    # Try decoding as UTF-8; anything that fails is considered binary for our
    # purposes (we don't want to false-positive on compiled artefacts).
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _walk_paths(paths: Iterable[Path]) -> Iterator[Path]:
    """Yield every scan-eligible file under the given paths (files/dirs)."""
    for p in paths:
        if p.is_file():
            yield p
            continue
        if not p.is_dir():
            continue
        for child in p.rglob("*"):
            try:
                if any(part in _IGNORE_DIRS for part in child.parts):
                    continue
                if not child.is_file():
                    continue
            except OSError:
                continue
            yield child


def _scan_file(path: Path) -> list[Match]:
    if _is_probably_binary(path):
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(
            f"⚠️  Could not read {path.as_posix()}: {exc}", file=sys.stderr,
        )
        return []
    matches = scan(text)
    # Rehydrate `path` on each match.
    return [
        Match(kind=m.kind, path=path, line_no=m.line_no, start=m.start, end=m.end)
        for m in matches
    ]


# ---------------------------------------------------------------------------
# Gitleaks integration (optional)
# ---------------------------------------------------------------------------


def _gitleaks_available() -> bool:
    return shutil.which("gitleaks") is not None


def _run_gitleaks_on(paths: list[Path]) -> tuple[int, str]:
    """Run `gitleaks detect` on the given paths (non-blocking — we aggregate).

    Returns (returncode, stderr_capture). Gitleaks exits 1 when it finds leaks.
    We never require it — failure to invoke is reported via stderr but not fatal.
    """
    if not paths:
        return 0, ""
    # Prefer `gitleaks detect --no-git --source <dir>` for each unique dir,
    # or `--source <file>` for individual files. Keep invocation minimal.
    try:
        proc = subprocess.run(
            ["gitleaks", "detect", "--no-banner", "--redact", "--no-git",
             "--source", str(paths[0])],
            capture_output=True, text=True, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 0, f"gitleaks invocation failed: {exc}\n"
    return proc.returncode, proc.stderr or ""


# ---------------------------------------------------------------------------
# `--staged` support
# ---------------------------------------------------------------------------


def _staged_files() -> list[Path]:
    """Return paths currently staged for commit (git diff --cached --name-only).

    Filters to tracked, still-existing paths (git may list deletions too).
    """
    try:
        proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.SubprocessError, subprocess.CalledProcessError):
        return []
    out: list[Path] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        p = Path(line)
        if p.exists():
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# Error output (per `specs/error-message-standard.md`)
# ---------------------------------------------------------------------------


def _emit_match_error(m: Match) -> None:
    """Emit the canonical WHY/WHERE/FIX/OVERRIDE error block for one match."""
    print(
        f"❌ Secret-like pattern matched ({m.kind}) at {m.location()}",
        file=sys.stderr,
    )
    print(
        "   FIX: move the secret to an encrypted store (SOPS / .env.local / "
        "secrets manager) and replace the literal with an env-var reference.",
        file=sys.stderr,
    )
    print("   OVERRIDE: none", file=sys.stderr)


def _emit_otel_failure_event(count: int) -> None:
    """Best-effort OTel span event on a non-zero match count."""
    try:
        from scripts.tracing import trace_emit  # type: ignore[import-not-found]
    except ImportError:
        return
    try:
        with trace_emit.span("secrets_scan.match", {
            "ai_playbook.failure.kind": "credential_exposure",
            "ai_playbook.failure.severity": "S1",
            "ai_playbook.failure.detector": "pre_commit",
            "ai_playbook.secrets.match_count": int(count),
        }):
            pass
    except Exception:  # noqa: BLE001 — tracing must never crash the gate
        return


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="secrets_scan",
        description=(
            "Scan files / staged diff / literal text for plaintext secrets. "
            "OVERRIDE: none — this gate never accepts --force-with-reason."
        ),
    )
    parser.add_argument(
        "paths", nargs="*", type=Path,
        help="Files or directories to scan. Use '-' to read text from stdin.",
    )
    parser.add_argument(
        "--staged", action="store_true",
        help="Scan files currently staged for commit (git diff --cached).",
    )
    parser.add_argument(
        "--text", metavar="STR", default=None,
        help="Scan this literal string instead of any path.",
    )
    parser.add_argument(
        "--sanitise-for", metavar="TARGET", default=None,
        choices=["hindsight"],
        help=(
            "Read text from stdin, redact matches with [REDACTED:<kind>], "
            "print to stdout, exit 0. Intended for inject_context.py before "
            "persisting to Hindsight."
        ),
    )
    # No --force-with-reason: this gate is non-overridable by spec.
    return parser


def _run_sanitise_mode() -> int:
    text = sys.stdin.read()
    redacted, kinds = sanitise(text)
    if kinds:
        print(
            f"⚠️  secrets_scan: redacted {len(kinds)} kind(s): {', '.join(kinds)}",
            file=sys.stderr,
        )
    sys.stdout.write(redacted)
    return 0


def _run_text_mode(text: str) -> int:
    matches = scan(text)
    for m in matches:
        _emit_match_error(m)
    if matches:
        _emit_otel_failure_event(len(matches))
        return 3
    return 0


def _run_staged_mode() -> int:
    files = _staged_files()
    if not files:
        # Nothing staged → nothing to scan.
        return 0
    return _run_paths_mode(files, invoked_via_staged=True)


def _run_paths_mode(
    paths: list[Path],
    *,
    invoked_via_staged: bool = False,
) -> int:
    all_matches: list[Match] = []
    for f in _walk_paths(paths):
        all_matches.extend(_scan_file(f))

    # Gitleaks is advisory — if present and we have a directory root, run it.
    if not _gitleaks_available():
        if not invoked_via_staged:
            print(
                "ℹ️  gitleaks not found on PATH; running regex-only detection. "
                "Install from https://github.com/gitleaks/gitleaks for deeper coverage.",
                file=sys.stderr,
            )
    else:
        rc, gl_stderr = _run_gitleaks_on(paths)
        if rc not in (0, 1):
            # Unknown exit — surface so user knows gitleaks misbehaved, but
            # don't block purely on that.
            print(
                f"⚠️  gitleaks exited with code {rc}: {gl_stderr.strip()}",
                file=sys.stderr,
            )
        elif rc == 1:
            # Gitleaks found something. Our regex pass SHOULD also flag it,
            # but emit a summary line so the user knows gitleaks contributed.
            print(
                "⚠️  gitleaks reported additional findings (see its own output).",
                file=sys.stderr,
            )

    for m in all_matches:
        _emit_match_error(m)

    if all_matches:
        _emit_otel_failure_event(len(all_matches))
        return 3
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Sanitise mode: stdin → sanitised stdout, exit 0.
    if args.sanitise_for == "hindsight":
        if args.paths or args.staged or args.text is not None:
            print(
                "❌ --sanitise-for is mutually exclusive with paths/--staged/--text "
                "at scripts/secrets_scan.py",
                file=sys.stderr,
            )
            print(
                "   FIX: pipe the text on stdin; do not pass other inputs.",
                file=sys.stderr,
            )
            print("   OVERRIDE: none", file=sys.stderr)
            return 2
        return _run_sanitise_mode()

    # Literal text mode.
    if args.text is not None:
        return _run_text_mode(args.text)

    # --staged mode.
    if args.staged:
        if args.paths:
            print(
                "❌ --staged is mutually exclusive with explicit paths "
                "at scripts/secrets_scan.py",
                file=sys.stderr,
            )
            print("   FIX: pass --staged OR paths, not both.", file=sys.stderr)
            print("   OVERRIDE: none", file=sys.stderr)
            return 2
        return _run_staged_mode()

    # Path(s) mode. Accept '-' as shorthand for stdin-as-text.
    if args.paths and len(args.paths) == 1 and str(args.paths[0]) == "-":
        return _run_text_mode(sys.stdin.read())

    if not args.paths:
        parser.print_help(sys.stderr)
        print(
            "\n❌ No inputs: pass paths, --staged, --text STR, or --sanitise-for "
            "hindsight with stdin at scripts/secrets_scan.py",
            file=sys.stderr,
        )
        print("   FIX: see --help.", file=sys.stderr)
        print("   OVERRIDE: none", file=sys.stderr)
        return 2

    return _run_paths_mode(list(args.paths))


__all__ = [
    "Match",
    "scan",
    "sanitise",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
