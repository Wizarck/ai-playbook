"""Skills materialiser — Phase 2a of RFC-0001 (skills distribution).

Resolves a consumer's `skills_sources` (declared in AGENTS.md frontmatter) into:

1. Submodules under `<consumer>/.skills-sources/<repo-slug>/`, sparse-checkout-ed
   to `skills/`, pinned to the declared semver tag.
2. A merged `<consumer>/skills/` directory (union of every source's `skills/`).
3. Per-LLM mirror copies at `<consumer>/.claude/skills/` and `<consumer>/.gemini/skills/`.

Idempotent: re-invoking with the same state is a no-op.

Used by `scripts/bootstrap.py --refresh-skills` and as the post-bootstrap step.

Reference: rfcs/RFC-0001-skills-distribution.md §2.

Stdlib + pyyaml. Python 3.11+. UTF-8 stdio.

Exit-code contract (when the caller exits on the result):
    0  success / no-op
    1  user-actionable failure (collision, malformed source ref, missing tag)
    2  prerequisite missing (git binary not on PATH)
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Force UTF-8 stdio — sigils in output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


SCRIPT_BASENAME = "_skills_materialiser.py"
SOURCES_SUBDIR = ".skills-sources"
SKILLS_SUBDIR = "skills"
MIRROR_SUBDIRS = (
    Path(".claude") / "skills",
    Path(".gemini") / "skills",
)
SOURCE_RE = re.compile(
    r"^(?:github\.com/)?(?P<owner>[A-Za-z0-9._-]+)/(?P<repo>[A-Za-z0-9._-]+)@(?P<tag>[A-Za-z0-9._+-]+)$"
)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class SkillsMaterialisationResult:
    """Outcome of a single materialise_skills call."""

    skills_total: int = 0
    sources_pinned: int = 0
    mirrors_generated: int = 0
    errors: list[str] = field(default_factory=list)
    noop: bool = False
    # Free-text status, useful for callers that print a one-line summary.
    summary: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# Canonical error emission (mirrors skills_registry.py)
# ---------------------------------------------------------------------------


def _emit_error(*, why: str, where: str, fix: str, override: str | None = None) -> None:
    """Emit the canonical error shape (specs/error-message-standard.md)."""
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(f"   OVERRIDE: {override if override else 'none'}", file=sys.stderr)


# ---------------------------------------------------------------------------
# AGENTS.md frontmatter parsing
# ---------------------------------------------------------------------------


def _read_agents_md_frontmatter(consumer_dir: Path) -> dict[str, Any] | None:
    """Return the YAML frontmatter dict from `<consumer>/AGENTS.md`, or None.

    Returns None when AGENTS.md is missing or has no frontmatter block. Raises
    nothing — callers decide whether absence is fatal.
    """
    agents_md = consumer_dir / "AGENTS.md"
    if not agents_md.is_file():
        return None
    text = agents_md.read_text(encoding="utf-8")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None
    block = "\n".join(lines[1:end])
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _parse_source_ref(ref: str) -> tuple[str, str, str]:
    """Parse `<owner>/<repo>@<tag>` (optionally `github.com/` prefixed).

    Returns `(owner, repo, tag)`. Raises ValueError on malformed input.
    """
    m = SOURCE_RE.match(ref.strip())
    if not m:
        raise ValueError(f"malformed skills source ref: {ref!r}")
    return m.group("owner"), m.group("repo"), m.group("tag")


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git_available() -> bool:
    return shutil.which("git") is not None


def _run_git(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _is_git_repo(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        r = _run_git(
            ["rev-parse", "--is-inside-work-tree"],
            cwd=path,
            check=False,
        )
    except FileNotFoundError:
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def _ensure_consumer_repo(consumer_dir: Path) -> None:
    """Idempotent `git init` so submodule add works on fresh consumers."""
    if _is_git_repo(consumer_dir):
        return
    consumer_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "-C", str(consumer_dir), "init", "--quiet"],
        check=False,
    )


def _submodule_already_added(consumer_dir: Path, submodule_rel: str) -> bool:
    """Check `.gitmodules` for an existing entry pointing at submodule_rel."""
    gm = consumer_dir / ".gitmodules"
    if not gm.is_file():
        return False
    text = gm.read_text(encoding="utf-8")
    # `git submodule` writes path = ... entries; match either forward or
    # back slash forms for Windows safety.
    needle_fwd = f"path = {submodule_rel}"
    needle_back = f"path = {submodule_rel.replace('/', chr(92))}"
    return needle_fwd in text or needle_back in text


def _enable_sparse_checkout(submodule_dir: Path) -> None:
    """Configure the submodule so only `skills/` is checked out.

    Uses `git sparse-checkout set --no-cone skills/` for compatibility with the
    widest range of git versions (≥2.25). On older gits (~2.x without
    sparse-checkout subcommand), this falls back silently — the full repo is
    fetched, which is correct but heavier.
    """
    try:
        _run_git(
            ["sparse-checkout", "init", "--no-cone"],
            cwd=submodule_dir,
            check=False,
        )
        _run_git(
            ["sparse-checkout", "set", f"{SKILLS_SUBDIR}/"],
            cwd=submodule_dir,
            check=False,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        # Sparse-checkout is best-effort; full checkout still satisfies FR-2.
        return


def _add_submodule(
    consumer_dir: Path,
    *,
    url: str,
    relpath: str,
    tag: str,
) -> tuple[bool, str]:
    """Add the submodule (or no-op if already present) and pin to tag.

    Returns `(pinned, message)`. `pinned=False` on failure; `message` carries
    the error detail.
    """
    submodule_dir = consumer_dir / relpath

    if _submodule_already_added(consumer_dir, relpath):
        # Update + re-pin only.
        try:
            _run_git(
                ["submodule", "update", "--init", "--", relpath],
                cwd=consumer_dir,
                check=False,
            )
        except subprocess.CalledProcessError as exc:
            return False, f"submodule update failed: {(exc.stderr or '').strip()[:200]}"
    else:
        # Fresh add.
        submodule_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            _run_git(
                ["submodule", "add", "--force", url, relpath],
                cwd=consumer_dir,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            return False, f"submodule add failed: {(exc.stderr or '').strip()[:200]}"
        _enable_sparse_checkout(submodule_dir)
        # `git submodule add` already checked out HEAD; we re-fetch to make
        # sparse-checkout patterns take effect on the working tree.
        try:
            _run_git(["read-tree", "-mu", "HEAD"], cwd=submodule_dir, check=False)
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

    # Fetch tags so checkout below resolves the requested ref.
    _run_git(["fetch", "--tags", "--quiet", "origin"], cwd=submodule_dir, check=False)

    # Confirm the tag exists in the remote.
    rev = _run_git(
        ["rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"],
        cwd=submodule_dir,
        check=False,
    )
    if rev.returncode != 0:
        return False, f"tag {tag} not found in remote (consumer ref unchanged)"

    # Checkout the tag (detached).
    co = _run_git(
        ["checkout", "--quiet", tag],
        cwd=submodule_dir,
        check=False,
    )
    if co.returncode != 0:
        return False, f"checkout {tag} failed: {(co.stderr or '').strip()[:200]}"

    return True, "ok"


# ---------------------------------------------------------------------------
# Skill merging + mirroring
# ---------------------------------------------------------------------------


def _list_skill_dirs(skills_root: Path) -> list[Path]:
    """Return the immediate children of `skills_root` that are directories.

    Skills are by convention `skills/<skill-name>/SKILL.md`; we surface every
    direct child dir and let the caller verify SKILL.md presence if desired.
    """
    if not skills_root.is_dir():
        return []
    return sorted(p for p in skills_root.iterdir() if p.is_dir())


def _merge_sources(
    consumer_dir: Path,
    source_relpaths: list[str],
) -> tuple[int, list[str]]:
    """Merge each source's `skills/` into `<consumer>/skills/`.

    Returns `(skills_total, errors)`. Collisions across sources are reported
    in errors; the merged dir is left in whatever state the first hit produced
    (last writer wins is **not** the contract; callers must abort on errors).
    """
    merged_dir = consumer_dir / SKILLS_SUBDIR
    # Wipe + recreate to guarantee idempotency. We never preserve hand-edits in
    # `skills/` — that directory is derived state, even if it's git-tracked
    # (it's tracked through the submodule reference itself, not as files).
    if merged_dir.exists():
        shutil.rmtree(merged_dir)
    merged_dir.mkdir(parents=True, exist_ok=True)

    seen: dict[str, str] = {}
    errors: list[str] = []
    skills_total = 0

    for relpath in source_relpaths:
        src_skills = consumer_dir / relpath / SKILLS_SUBDIR
        if not src_skills.is_dir():
            errors.append(
                f"source {relpath} has no `{SKILLS_SUBDIR}/` directory after sparse-checkout"
            )
            continue
        for skill_dir in _list_skill_dirs(src_skills):
            name = skill_dir.name
            if name in seen:
                errors.append(
                    f"❓ CLARIFICATION NEEDED: skill name collision for "
                    f"{name!r}: present in both {seen[name]!r} and {relpath!r}"
                )
                continue
            seen[name] = relpath
            shutil.copytree(skill_dir, merged_dir / name)
            skills_total += 1

    return skills_total, errors


def _regenerate_mirrors(consumer_dir: Path) -> int:
    """Wipe + copy `skills/` into each per-LLM mirror. Returns mirror count."""
    src = consumer_dir / SKILLS_SUBDIR
    if not src.is_dir():
        return 0
    mirrors_done = 0
    for rel in MIRROR_SUBDIRS:
        dst = consumer_dir / rel
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst)
        mirrors_done += 1
    return mirrors_done


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def materialise_skills(
    consumer_dir: Path,
    *,
    dry_run: bool = False,
) -> SkillsMaterialisationResult:
    """Materialise every `skills_sources` entry into the consumer working tree.

    See module docstring for the full algorithm.

    Parameters
    ----------
    consumer_dir : Path
        Root of the consumer project (where AGENTS.md lives).
    dry_run : bool
        Report what would happen without touching the filesystem (other than
        log lines).

    Returns
    -------
    SkillsMaterialisationResult
        Counts + collected error strings. Inspect `.errors` to decide whether
        downstream steps should bail.
    """
    consumer_dir = consumer_dir.resolve()
    result = SkillsMaterialisationResult()

    frontmatter = _read_agents_md_frontmatter(consumer_dir)
    if not frontmatter:
        result.noop = True
        result.summary = (
            f"AGENTS.md missing or has no frontmatter at {consumer_dir}; "
            "skills materialisation skipped (consumer not migrated yet)."
        )
        print(f"ℹ️  {result.summary}")
        return result

    sources = frontmatter.get("skills_sources")
    if not sources:
        result.noop = True
        result.summary = (
            f"AGENTS.md frontmatter has no `skills_sources` at {consumer_dir}; "
            "skills materialisation skipped (consumer not migrated yet)."
        )
        print(f"ℹ️  {result.summary}")
        return result

    if not isinstance(sources, list):
        _emit_error(
            why="`skills_sources` in AGENTS.md frontmatter is not a list",
            where=f"{consumer_dir}/AGENTS.md",
            fix="convert the frontmatter value to a YAML list of "
                "`<owner>/<repo>@<tag>` strings (see RFC-0001 §2).",
        )
        result.errors.append("skills_sources is not a list")
        return result

    # Parse + validate every ref before any side effects.
    parsed: list[tuple[str, str, str, str]] = []
    for ref in sources:
        if not isinstance(ref, str):
            _emit_error(
                why=f"skills_sources entry is not a string: {ref!r}",
                where=f"{consumer_dir}/AGENTS.md frontmatter",
                fix="every entry must be a `<owner>/<repo>@<tag>` string.",
            )
            result.errors.append(f"non-string source: {ref!r}")
            continue
        try:
            owner, repo, tag = _parse_source_ref(ref)
        except ValueError as exc:
            _emit_error(
                why=str(exc),
                where=f"{consumer_dir}/AGENTS.md frontmatter",
                fix="format must be `<owner>/<repo>@<tag>` "
                    "(e.g. `Wizarck/ai-playbook@v0.4.0`).",
            )
            result.errors.append(str(exc))
            continue
        parsed.append((ref, owner, repo, tag))

    if result.errors:
        return result

    if dry_run:
        for ref, owner, repo, tag in parsed:
            print(f"(dry-run) Would add submodule {owner}/{repo}@{tag} → "
                  f".skills-sources/{repo}/")
        print("(dry-run) Would merge sources into skills/.")
        print("(dry-run) Would copy skills/ into .claude/skills/ + .gemini/skills/.")
        result.summary = f"(dry-run) {len(parsed)} source(s) would be materialised."
        return result

    if not _git_available():
        _emit_error(
            why="`git` not found on PATH",
            where=f"{SCRIPT_BASENAME}:git-missing",
            fix="install git ≥2.25 (sparse-checkout support) and re-run.",
        )
        result.errors.append("git not on PATH")
        # Caller (bootstrap) decides whether to map to exit-code 2.
        return result

    _ensure_consumer_repo(consumer_dir)

    # Step 1: submodule add + pin per source.
    submodule_relpaths: list[str] = []
    for ref, owner, repo, tag in parsed:
        url = f"https://github.com/{owner}/{repo}.git"
        relpath = f"{SOURCES_SUBDIR}/{repo}".replace("\\", "/")
        ok, msg = _add_submodule(consumer_dir, url=url, relpath=relpath, tag=tag)
        if not ok:
            _emit_error(
                why=f"failed to materialise skills source {ref}: {msg}",
                where=f"{consumer_dir}/{relpath}",
                fix="check connectivity, the tag exists in the source repo, "
                    "and you have read access; re-run after fixing.",
            )
            result.errors.append(f"{ref}: {msg}")
            continue
        submodule_relpaths.append(relpath)
        result.sources_pinned += 1

    if result.errors:
        # Don't proceed to merge if any source failed; partial state is still
        # better than mixing old + new content silently.
        return result

    # Step 2: merge into <consumer>/skills/.
    skills_total, merge_errors = _merge_sources(consumer_dir, submodule_relpaths)
    result.skills_total = skills_total
    if merge_errors:
        for err in merge_errors:
            print(err, file=sys.stderr)
        result.errors.extend(merge_errors)
        return result

    # Step 3: regenerate per-LLM mirrors.
    result.mirrors_generated = _regenerate_mirrors(consumer_dir)

    result.summary = (
        f"materialised {result.skills_total} skill(s) from "
        f"{result.sources_pinned} source(s); regenerated "
        f"{result.mirrors_generated} mirror(s)."
    )
    print(f"✓ {result.summary}")
    return result


__all__ = [
    "MIRROR_SUBDIRS",
    "SKILLS_SUBDIR",
    "SOURCES_SUBDIR",
    "SOURCE_RE",
    "SkillsMaterialisationResult",
    "materialise_skills",
]
