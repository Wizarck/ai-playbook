"""Scan working tree / staged diff / literal text for plaintext secrets.

This is the *non-overridable* credential-exposure gate per
`docs/concepts/agentic-failures.md` §2.11 and `docs/rules/break-glass.rule.md` §"Scripts that MUST
support break-glass" (where this row is listed with `OVERRIDE: none` ALWAYS).

Modes
-----
    python -m scripts.secrets_scan <path> [<path>...]          # scan paths (files/dirs)
    python -m scripts.secrets_scan --staged                    # scan staged (index) content
    python -m scripts.secrets_scan --text "literal string"     # scan a literal string
    echo "..." | python -m scripts.secrets_scan -              # read text from stdin
    echo "..." | python -m scripts.secrets_scan \
        --sanitise-for hindsight                               # redact & print sanitised

Importable API
--------------
    from scripts.secrets_scan import scan, sanitise, Match

    matches = scan(text)                       # list[Match]
    sanitised_text, kinds = sanitise(text)     # tuple[str, list[str]]

Exit codes (per `docs/rules/error-message-standard.rule.md`)
---------------------------------------------------
    0 = no matches (scan mode), or sanitise-for hindsight finished (always 0)
    2 = environment/setup problem (couldn't read a file, invalid CLI combo,
        --staged outside a git work tree / git failure)
    3 = hard block — at least one secret matched in scan mode
"""
from __future__ import annotations

import argparse
import codecs
import os
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

# Assignment operator between a NAME and its value. A quoted value may sit on a
# later line (YAML `KEY:\n  "v"`, JS `const KEY =\n  "v";`); an unquoted one
# must share the NAME's line, or an empty `API_KEY=` would take the next dotenv
# line (`CLAUDE_MODEL=…`) as its value.
_ASSIGN = r"""(?:\s*[:=]\s*['"]|[ \t]*[:=][ \t]*)"""

# One line-break unit inside a PEM block: real whitespace, an escaped `\n` /
# `\r` (JSON, env values; any escape depth) or a quote from the seam between
# concatenated string literals.
_PEM_BREAK = r"""(?:\s|\\+[nr]|["'])"""

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Anthropic API key. Example: sk-ant-api03-abc...XYZ (>= 50 chars after prefix).
    ("anthropic_api_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{50,}")),
    # OpenAI API key — legacy (sk-<32+ alnum>) and the prefixed project /
    # service-account / admin keys, whose bodies include `_` and `-` (real ones
    # are ~150 chars). The prefixed form must not follow a letter unless that
    # letter ends an escape (`\n`, `%3D`), and its body must pass
    # `_looks_like_secret`, so kebab-case (`task-proj-…`, `helpdesk-admin-…`)
    # and `.env.example` placeholders do not fire.
    # Example: sk-proj-abc...xyz, sk-svcacct-..., sk-admin-...
    (
        "openai_api_key",
        re.compile(
            r"(?:(?<![A-Za-z])|(?<=\\[nrt])|(?<=%[0-9A-Fa-f]{2}))"
            r"sk-(?:proj|svcacct|admin)-(?P<body>[A-Za-z0-9_\-]{40,})"
            r"|sk-[A-Za-z0-9]{32,}"
        ),
    ),
    # GitHub classic tokens (ghp_/gho_/ghu_/ghs_/ghr_) and fine-grained PATs
    # (github_pat_<22>_<59>).
    (
        "github_pat",
        re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,}"),
    ),
    # AWS Access Key ID — long-term (AKIA) and STS temporary (ASIA).
    # Example: AKIAIOSFODNN7EXAMPLE.
    ("aws_access_key", re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}")),
    # AWS Secret Access Key: only when paired with an obvious assignment.
    # Quotes optional (dotenv / ~/.aws/credentials are unquoted); see
    # `_ASSIGN` for why only a quoted value may sit on a later line.
    # Example: aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
    (
        "aws_secret_access_key",
        re.compile(
            r"aws_secret_access_key" + _ASSIGN
            + r"[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])['\"]?",
            re.IGNORECASE,
        ),
    ),
    # PEM / OpenSSH / PGP private key: the BEGIN line, optional armor headers
    # (PGP `Comment:`, encrypted-PEM `Proc-Type:`), then key material whose
    # first line is 40+ base64 chars that pass `_looks_like_secret`. A header
    # alone (prose, a constant, a `MIIE...` placeholder) does not fire. Line
    # breaks may be real, escaped (`\n` in JSON / env values) or the seam
    # between concatenated string literals, and the match runs through the END
    # line so sanitise() redacts the key material, not just the header.
    # Example header: "BEGIN OPENSSH PRIVATE KEY" in dashes.
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----" + _PEM_BREAK + r"*+"
            + r"(?:[A-Za-z][A-Za-z0-9-]{0,40}:[ \t][^\r\n\\]*+" + _PEM_BREAK + r"++){0,10}"
            + r"(?P<body>(?:[A-Za-z0-9+/]|\\/){40,}+)"
            + r"""(?:[A-Za-z0-9+/=\s"']|\\+[nr]|\\/)*+"""
            + r"(?:-----END [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----)?"
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
    # quoted or unquoted (dotenv), terminated by whitespace / a quote / end of
    # text, and contains a mix of classes (lowers/UPPERS/digits). The
    # terminator is checked by `_env_assignments` and the mix-class
    # requirement post-match in `_looks_like_secret`.
    # The name may start anywhere, so `_API_KEY`, `self._API_TOKEN`,
    # `app_SECRET_KEY` and `2FA_SECRET` match from their uppercase tail. Its
    # bounded length keeps this linear on long uppercase runs (an unbounded
    # name restarts from every offset of the run); a longer name still
    # matches from a later offset.
    (
        "generic_env_secret",
        re.compile(
            r"""(?P<prefix>[A-Z][A-Z0-9_]{0,64}(?:SECRET|TOKEN|KEY|PASSWORD|PASS|APIKEY))"""
            + _ASSIGN
            + r"""(?P<val>[A-Za-z0-9/+=_\-]{20,}+)""",
        ),
    ),
]

# Longest name generic_env_secret matches: [A-Z] + {0,64} + "PASSWORD".
_ENV_NAME_MAX = 1 + 64 + len("PASSWORD")
_ENV_VALUE_END = re.compile(r"""[\s'"]""")

# Placeholder markers: a value containing one is documentation, not a secret.
# Key bodies (prefixed OpenAI, PEM material) are checked against the long words
# only: a random ~150-char body contains "xxxx" (any case) about once in 7,000.
_PLACEHOLDER_WORDS = ("example", "changeme", "redacted", "your-")
_PLACEHOLDER_MARKERS = (*_PLACEHOLDER_WORDS, "xxxx", "****", "<", ">")

# kind -> (named group holding the value, placeholder markers) for kinds whose
# matches must also pass `_looks_like_secret`. A group that did not take part
# in the match (the legacy `sk-` branch has no `body`) is not checked.
_VALUE_CHECKS: dict[str, tuple[str, tuple[str, ...]]] = {
    "openai_api_key": ("body", _PLACEHOLDER_WORDS),
    "private_key": ("body", _PLACEHOLDER_WORDS),
    "generic_env_secret": ("val", _PLACEHOLDER_MARKERS),
}


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


def _looks_like_secret(value: str, markers: tuple[str, ...] = _PLACEHOLDER_MARKERS) -> bool:
    """Heuristic: the value looks secret-y (classes mix + no obvious placeholder)."""
    if len(value) < 20:
        return False
    lowered = value.lower()
    if any(ph in lowered for ph in markers):
        return False
    has_lower = any(c.islower() for c in value)
    has_upper = any(c.isupper() for c in value)
    has_digit = any(c.isdigit() for c in value)
    classes = sum([has_lower, has_upper, has_digit])
    return classes >= 2


def _env_assignments(
    pattern: re.Pattern[str], text: str,
) -> Iterator[tuple[int, int, re.Match[str]]]:
    """Yield ``(start, end, match)`` per generic_env_secret hit, in linear time.

    Same hits as ``finditer`` over the pattern plus ``(?=[\\s'"]|\\Z)['"]?``:
    the value must end at whitespace, a quote (kept in the hit) or the end of
    text; otherwise it is part of a longer token (``TOKEN = getToken()``).
    With that check inside the regex, each ``NAME=`` start inside one long run
    of value characters rescanned the run (quadratic). Every later start whose
    name ends before the value's end shares that end and fails too, so the
    search resumes at the first start whose name could end exactly there
    (``…NAME: "v"``).
    """
    n = len(text)
    pos = 0
    while (m := pattern.search(text, pos)) is not None:
        end = m.end("val")
        if end < n and not _ENV_VALUE_END.match(text, end):
            pos = max(m.start() + 1, end - _ENV_NAME_MAX)
            continue
        if end < n and text[end] in "'\"":
            end += 1
        yield m.start(), end, m
        pos = end


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
        check = _VALUE_CHECKS.get(kind)
        if kind == "generic_env_secret":
            hits = _env_assignments(pattern, text)
        else:
            hits = ((m.start(), m.end(), m) for m in pattern.finditer(text))
        for start, end, m in hits:
            if check is not None:
                value = m.group(check[0])
                if value is not None and not _looks_like_secret(value, check[1]):
                    continue
            out.append(
                Match(
                    kind=kind,
                    path=None,
                    line_no=_line_no_of(start),
                    start=start,
                    end=end,
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
    # Patterns overlap (a generic KEY="..." wraps a ghp_/AKIA hit), so merge
    # overlapping spans first — label = the outermost (earliest, widest) match —
    # then rebuild in one left-to-right pass. Applying overlapping spans with
    # stale offsets deletes trailing text or leaks the secret's tail.
    spans: list[list] = []
    for m in sorted(matches, key=lambda x: (x.start, -x.end)):
        if spans and m.start < spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], m.end)
        else:
            spans.append([m.start, m.end, m.kind])
    parts: list[str] = []
    pos = 0
    for start, end, kind in spans:
        parts.append(text[pos:start])
        parts.append(f"[REDACTED:{kind}]")
        pos = end
    parts.append(text[pos:])
    kinds = sorted({m.kind for m in matches})
    return "".join(parts), kinds


# ---------------------------------------------------------------------------
# File / directory walking
# ---------------------------------------------------------------------------


def _is_binary_sample(chunk: bytes) -> bool:
    if not chunk:
        return False
    # Null byte ⇒ binary.
    if b"\x00" in chunk:
        return True
    # Try decoding as UTF-8; anything that fails is considered binary for our
    # purposes (we don't want to false-positive on compiled artefacts). The
    # incremental decoder with final=False tolerates a multibyte character
    # split by the sample boundary.
    try:
        codecs.getincrementaldecoder("utf-8")().decode(chunk, final=False)
    except UnicodeDecodeError:
        return True
    return False


def _is_probably_binary(path: Path, sample_size: int = 2048) -> bool:
    try:
        with path.open("rb") as fh:
            chunk = fh.read(sample_size)
    except OSError:
        return True
    return _is_binary_sample(chunk)


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
        # Non-0/1 code so the caller surfaces it as a warning. Still advisory:
        # gitleaks is optional and its own findings (rc 1) do not block either.
        return -1, f"gitleaks invocation failed: {exc}\n"
    return proc.returncode, proc.stderr or ""


# ---------------------------------------------------------------------------
# `--staged` support
# ---------------------------------------------------------------------------


class _GitError(Exception):
    pass


def _git(*args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        detail = getattr(exc, "stderr", b"") or b""
        raise _GitError(
            f"git {' '.join(args[:2])} failed: {exc} {detail.decode(errors='replace').strip()}"
        ) from exc


def _staged_blobs() -> list[tuple[str, str]]:
    """Return ``(toplevel-relative path, blob sha)`` for every staged file.

    Reads the INDEX (what will be committed), not the working tree. ``-z``
    avoids C-quoting of non-ASCII paths; gitlinks (submodule bumps, mode
    160000) are skipped. Raises ``_GitError`` when git fails (not a repo, …).
    """
    raw = _git(
        "diff", "--cached", "--raw", "-z", "--no-renames", "--no-abbrev",
        "--diff-filter=ACMR",
    )
    fields = raw.split(b"\0")
    out: list[tuple[str, str]] = []
    # Records: ":<old mode> <new mode> <old sha> <new sha> <status>\0<path>\0"
    for meta, path in zip(fields[0::2], fields[1::2], strict=False):
        if not meta.startswith(b":"):
            continue
        _, new_mode, _, new_sha, _ = meta[1:].decode().split(" ")
        if new_mode == "160000":
            continue
        out.append((os.fsdecode(path), new_sha))
    return out


# ---------------------------------------------------------------------------
# Error output (per `docs/rules/error-message-standard.rule.md`)
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
    try:
        blobs = _staged_blobs()
        if not blobs:
            # Nothing staged → nothing to scan.
            return 0
        top = Path(os.fsdecode(_git("rev-parse", "--show-toplevel").strip()))
        matches: list[Match] = []
        for name, sha in blobs:
            data = _git("cat-file", "blob", sha)
            if _is_binary_sample(data[:2048]):
                continue
            path = Path(name)
            matches.extend(
                Match(kind=m.kind, path=path, line_no=m.line_no, start=m.start, end=m.end)
                for m in scan(data.decode("utf-8", errors="replace"))
            )
    except _GitError as exc:
        # Fail closed: a vacuous pass here would let the commit through unscanned.
        print(f"❌ --staged could not read the git index: {exc} "
              "at scripts/secrets_scan.py", file=sys.stderr)
        print("   FIX: run from inside a git work tree with git on PATH.", file=sys.stderr)
        print("   OVERRIDE: none", file=sys.stderr)
        return 2
    worktree = [top / n for n, _ in blobs if (top / n).exists()]
    return _run_paths_mode(worktree, invoked_via_staged=True, matches=matches)


def _run_paths_mode(
    paths: list[Path],
    *,
    invoked_via_staged: bool = False,
    matches: list[Match] | None = None,
) -> int:
    all_matches: list[Match] = []
    if matches is not None:
        all_matches = matches  # --staged: already scanned from the index
    else:
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


# Make `from scripts...` resolve when run by path (`python .ai-playbook/scripts/...`), not just via -m.
_PLAYBOOK_ROOT = str(Path(__file__).resolve().parents[1])
if _PLAYBOOK_ROOT not in sys.path:
    sys.path.insert(0, _PLAYBOOK_ROOT)


if __name__ == "__main__":
    from scripts.rules._telemetry import script_emit
    raise SystemExit(script_emit("secrets-scan", main))
