"""Bootstrap a new consumer project with the ai-playbook submodule + templates.

Populated in T22e. Supersedes the T14a stub that merely printed args.

Responsibilities (per specs/migration-guide.md + templates/new-project/):

1. Resolve target directory (--path or <cwd>/<project-name>). Create if absent;
   error if a non-directory collision exists.
2. Resolve owner email (--owner > $GIT_AUTHOR_EMAIL > `git config user.email` >
   fallback sentinel matching schema_validate._guess_owner_email).
3. Add the playbook as a git submodule at .ai-playbook/ pinned to --playbook-pin.
   Offline fallback: --playbook-path <local> plus --force-with-reason skips
   GitHub and copies from a local clone.
4. Copy templates/new-project/ into the target with placeholder substitution:
      {{TODAY}} → today ISO date
      {{PROJECT_NAME}} → slug
      {{OWNER_EMAIL}} → resolved owner
   Other placeholders ({{ACTIVE_OPENSPEC_CHANGE_OR_NONE}}, …) are left verbatim
   so the dev fills them.
5. Best-effort `pre-commit install`; warn if pre-commit is absent.
6. Run `python -m scripts.doctor` with CWD=project dir; print summary.
7. Run `python -m scripts.discover_projects --add <project-dir>`.
8. If --personal, inject `personal: true` into AGENTS.md frontmatter.
9. Print a "next steps" block.

Exit codes
----------
    0  success (or break-glass override applied)
    1  template / filesystem error
    2  missing prerequisites (git unavailable, playbook URL unreachable
       without --playbook-path + --force-with-reason)
    3  reserved for `OVERRIDE: none` refusal paths (not used by this script
       but honoured via the shared break-glass helper)
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Force UTF-8 stdio — sigils in output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts._break_glass import add_break_glass_flag, apply_break_glass  # noqa: E402

SCRIPT_BASENAME = "bootstrap.py"
GATE_NAME = "submodule-unreachable"
DEFAULT_PLAYBOOK_URL = "https://github.com/Wizarck/ai-playbook.git"
DEFAULT_PIN = "v0.1.0"
SUBMODULE_PATH = ".ai-playbook"
TEMPLATE_SUBDIR = Path("templates") / "new-project"
SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class BootstrapArgs:
    project_name: str
    path: Path
    owner: str
    playbook_pin: str
    playbook_path: Path | None
    personal: bool
    force_reason: str | None
    dry_run: bool


# ---------------------------------------------------------------------------
# Playbook root discovery (same logic as schema_validate.find_playbook_root)
# ---------------------------------------------------------------------------


def find_playbook_root() -> Path:
    """Locate this playbook checkout's root (the directory with specs/ + scripts/)."""
    here = Path(__file__).resolve().parent
    for candidate in (here.parent, *here.parents):
        if (candidate / "specs").is_dir() and (candidate / "scripts").is_dir():
            return candidate
    raise SystemExit("❌ bootstrap.py cannot locate its own playbook root.")


# ---------------------------------------------------------------------------
# Owner resolution
# ---------------------------------------------------------------------------


def resolve_owner(cli_owner: str | None) -> str:
    """CLI > GIT_AUTHOR_EMAIL > git config user.email > sentinel."""
    if cli_owner:
        return cli_owner.strip()
    for env_key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL", "EMAIL"):
        val = os.environ.get(env_key)
        if val:
            return val.strip()
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
# Path / slug handling
# ---------------------------------------------------------------------------


def validate_slug(name: str) -> None:
    if not SLUG_RE.match(name):
        print(
            f"❌ project name {name!r} is not a valid slug at {SCRIPT_BASENAME}:slug",
            file=sys.stderr,
        )
        print(
            "   FIX: use a name matching [a-zA-Z0-9][a-zA-Z0-9_-]*  "
            "(e.g. 'acme-shop' not 'Acme Shop').",
            file=sys.stderr,
        )
        print("   OVERRIDE: none", file=sys.stderr)
        raise SystemExit(1)


def resolve_target_path(project_name: str, cli_path: Path | None) -> Path:
    """Return the resolved target directory. Error if a file collides."""
    if cli_path is not None:
        target = cli_path.expanduser().resolve()
    else:
        target = (Path.cwd() / project_name).resolve()

    if target.exists() and not target.is_dir():
        print(
            f"❌ path {target} exists and is not a directory "
            f"at {SCRIPT_BASENAME}:path-collision",
            file=sys.stderr,
        )
        print("   FIX: remove or rename the conflicting file, or pass --path.", file=sys.stderr)
        print("   OVERRIDE: none", file=sys.stderr)
        raise SystemExit(1)
    return target


# ---------------------------------------------------------------------------
# Submodule step
# ---------------------------------------------------------------------------


def _git_available() -> bool:
    return shutil.which("git") is not None


def add_submodule(
    *,
    target_dir: Path,
    playbook_url: str,
    pin: str,
    dry_run: bool,
) -> int:
    """Attempt `git submodule add` + checkout pin. Returns 0 on success, non-zero on failure.

    Callers decide whether the failure is recoverable (e.g. via --playbook-path
    + break-glass) or fatal.
    """
    submodule_dir = target_dir / SUBMODULE_PATH
    if submodule_dir.exists() and any(submodule_dir.iterdir()):
        print(f"ℹ️  {submodule_dir} already populated; skipping submodule add.")
        return 0

    if dry_run:
        print(f"(dry-run) Would `git -C {target_dir} init` if not already a repo.")
        print(f"(dry-run) Would `git -C {target_dir} submodule add {playbook_url} {SUBMODULE_PATH}`.")
        print(f"(dry-run) Would `git -C {submodule_dir} checkout {pin}`.")
        return 0

    if not _git_available():
        return 127  # prereq missing

    # Make sure target_dir is a git repo (fresh `git init` is fine; no side effect on existing).
    subprocess.run(["git", "-C", str(target_dir), "init", "--quiet"], check=False)
    result = subprocess.run(
        ["git", "-C", str(target_dir), "submodule", "add", playbook_url, SUBMODULE_PATH],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return result.returncode
    result = subprocess.run(
        ["git", "-C", str(submodule_dir), "checkout", pin],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode


def copy_local_playbook(*, target_dir: Path, playbook_path: Path, dry_run: bool) -> None:
    """Offline fallback: copy a local playbook checkout to .ai-playbook/ verbatim.

    Used when --playbook-path is provided alongside --force-with-reason because
    github.com is unreachable. The copy is NOT a git submodule; it's a plain
    directory. The caller is responsible for reminding the dev to wire it up as
    a submodule when connectivity returns (see next-steps output).
    """
    submodule_dir = target_dir / SUBMODULE_PATH
    if dry_run:
        print(f"(dry-run) Would copy {playbook_path} → {submodule_dir}.")
        return
    # Detect a real prior bootstrap by looking for the tell-tale specs/ dir.
    # The overrides.log from break-glass itself may have created .ai-playbook/
    # already; treat that as empty for copy purposes.
    if (submodule_dir / "specs").is_dir():
        print(f"ℹ️  {submodule_dir} already populated; skipping local copy.")
        return
    shutil.copytree(playbook_path, submodule_dir, dirs_exist_ok=True)


# ---------------------------------------------------------------------------
# Template copy + substitution
# ---------------------------------------------------------------------------


def _substitute(
    text: str,
    *,
    project_name: str,
    owner: str,
    today_iso: str,
) -> str:
    return (
        text.replace("{{TODAY}}", today_iso)
        .replace("{{PROJECT_NAME}}", project_name)
        .replace("{{OWNER_EMAIL}}", owner)
    )


def copy_templates(
    *,
    playbook_root: Path,
    target_dir: Path,
    project_name: str,
    owner: str,
    dry_run: bool,
) -> list[Path]:
    """Copy templates/new-project/ into target_dir with {{PLACEHOLDER}} substitution.

    Returns the list of files written (or "would write" in dry-run).
    """
    src_root = playbook_root / TEMPLATE_SUBDIR
    if not src_root.is_dir():
        print(
            f"❌ templates directory missing at {src_root} "
            f"at {SCRIPT_BASENAME}:templates-missing",
            file=sys.stderr,
        )
        print(
            "   FIX: re-clone the playbook; templates/new-project/ is required.",
            file=sys.stderr,
        )
        print("   OVERRIDE: none", file=sys.stderr)
        raise SystemExit(1)

    today_iso = date.today().isoformat()
    written: list[Path] = []

    for src in src_root.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(src_root)
        # Strip .tmpl suffix if present (so AGENTS.md.tmpl → AGENTS.md).
        rel_out = rel.with_suffix("") if rel.suffix == ".tmpl" else rel
        dst = target_dir / rel_out

        if dry_run:
            print(f"(dry-run) Would write {dst}.")
            written.append(dst)
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        raw = src.read_text(encoding="utf-8")
        new = _substitute(raw, project_name=project_name, owner=owner, today_iso=today_iso)
        dst.write_text(new, encoding="utf-8", newline="\n")
        written.append(dst)

    return written


# ---------------------------------------------------------------------------
# Personal flag injection
# ---------------------------------------------------------------------------


def inject_personal_flag(agents_md: Path, dry_run: bool) -> None:
    """Add `personal: true` to the AGENTS.md frontmatter if not already present."""
    if dry_run:
        print(f"(dry-run) Would inject `personal: true` into {agents_md}.")
        return
    if not agents_md.is_file():
        return
    text = agents_md.read_text(encoding="utf-8")
    # Narrow the edit to the first `---`-fenced block.
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return
    block = lines[1:end]
    if any(ln.strip().startswith("personal:") for ln in block):
        return  # already set (idempotent)
    block.append("personal: true")
    new = "---\n" + "\n".join(block) + "\n---\n" + "\n".join(lines[end + 1 :])
    agents_md.write_text(new, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# pre-commit + doctor + discover integrations
# ---------------------------------------------------------------------------


def install_pre_commit(target_dir: Path, dry_run: bool) -> None:
    if dry_run:
        print(f"(dry-run) Would `pre-commit install` in {target_dir}.")
        return
    if shutil.which("pre-commit") is None:
        print("⚠️  pre-commit not installed; skipping hook setup.")
        return
    subprocess.run(
        ["pre-commit", "install"],
        cwd=str(target_dir),
        capture_output=True,
        text=True,
        check=False,
    )


def run_doctor(target_dir: Path, dry_run: bool) -> None:
    if dry_run:
        print(f"(dry-run) Would run `python -m scripts.doctor` with CWD={target_dir}.")
        return
    subprocess.run(
        [sys.executable, "-m", "scripts.doctor"],
        cwd=str(target_dir),
        check=False,
    )


def run_discover(target_dir: Path, dry_run: bool) -> None:
    if dry_run:
        print(f"(dry-run) Would run `python -m scripts.discover_projects --add {target_dir}`.")
        return
    subprocess.run(
        [sys.executable, "-m", "scripts.discover_projects", "--add", str(target_dir)],
        check=False,
    )


# ---------------------------------------------------------------------------
# Next-steps banner
# ---------------------------------------------------------------------------


def print_next_steps(target_dir: Path, project_name: str) -> None:
    print()
    print("✅ Bootstrap complete. Next steps:")
    print(f"   1. cd {target_dir}")
    print("   2. Fill placeholders in AGENTS.md (§1 identity, §3 active work, §4 rules).")
    print("   3. Write your first OpenSpec change: `/opsx:propose <topic>`.")
    print(f"   4. Commit: `git add . && git commit -m 'chore: bootstrap {project_name} via ai-playbook'`.")
    print("   5. Push to your remote when ready.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None) -> BootstrapArgs:
    parser = argparse.ArgumentParser(
        prog="bootstrap",
        description="Bootstrap a new consumer project with the ai-playbook submodule + templates.",
    )
    parser.add_argument("project_name", help="Slug for the new project (must match [a-zA-Z0-9][a-zA-Z0-9_-]*).")
    parser.add_argument("--owner", default=None, help="Owner email (default: $GIT_AUTHOR_EMAIL or git config user.email).")
    parser.add_argument("--path", type=Path, default=None, help="Target directory (default: <cwd>/<project-name>).")
    parser.add_argument("--playbook-pin", default=DEFAULT_PIN, help="Playbook semver tag to pin (default: %(default)s).")
    parser.add_argument("--playbook-path", type=Path, default=None,
                        help="Offline fallback: copy from a local playbook checkout instead of cloning from GitHub. Requires --force-with-reason.")
    parser.add_argument("--personal", action="store_true", help="Mark the new AGENTS.md with `personal: true`.")
    parser.add_argument("--dry-run", action="store_true", help="Report actions without side effects.")
    add_break_glass_flag(parser)
    ns = parser.parse_args(argv)
    return BootstrapArgs(
        project_name=ns.project_name,
        path=ns.path,
        owner=ns.owner,
        playbook_pin=ns.playbook_pin,
        playbook_path=ns.playbook_path,
        personal=ns.personal,
        force_reason=ns.force_reason,
        dry_run=ns.dry_run,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    validate_slug(args.project_name)

    target_dir = resolve_target_path(args.project_name, args.path)
    owner = resolve_owner(args.owner)
    playbook_root = find_playbook_root()

    print(f"→ Bootstrapping project '{args.project_name}'")
    print(f"   target : {target_dir}")
    print(f"   owner  : {owner}")
    print(f"   pin    : {args.playbook_pin}")
    print(f"   mode   : {'dry-run' if args.dry_run else 'live'}")

    if not args.dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: submodule.
    if args.playbook_path is not None:
        # Offline fallback requires a break-glass reason.
        if args.force_reason is None:
            print(
                f"❌ --playbook-path requires --force-with-reason at {SCRIPT_BASENAME}:{GATE_NAME}",
                file=sys.stderr,
            )
            print(
                "   FIX: pass --force-with-reason explaining why GitHub can't be reached.",
                file=sys.stderr,
            )
            print(
                f'   OVERRIDE: python -m scripts.bootstrap {args.project_name} '
                '--playbook-path <path> --force-with-reason="<>=10 char reason"',
                file=sys.stderr,
            )
            return 2
        result = apply_break_glass(
            gate=GATE_NAME,
            script=SCRIPT_BASENAME,
            reason=args.force_reason,
            override_allowed=True,
            repo_root=target_dir if target_dir.exists() else playbook_root,
        )
        if result.applied:
            print(f"⚠️ OVERRIDE APPLIED: {result.reason}")
            copy_local_playbook(
                target_dir=target_dir,
                playbook_path=args.playbook_path,
                dry_run=args.dry_run,
            )
    else:
        rc = add_submodule(
            target_dir=target_dir,
            playbook_url=DEFAULT_PLAYBOOK_URL,
            pin=args.playbook_pin,
            dry_run=args.dry_run,
        )
        if rc == 127:
            print(
                f"❌ `git` not found on PATH at {SCRIPT_BASENAME}:git-missing",
                file=sys.stderr,
            )
            print("   FIX: install git and re-run.", file=sys.stderr)
            print("   OVERRIDE: none", file=sys.stderr)
            return 2
        if rc != 0:
            print(
                f"❌ submodule add failed (exit {rc}) at {SCRIPT_BASENAME}:{GATE_NAME}",
                file=sys.stderr,
            )
            print(
                "   FIX: check connectivity, or pass --playbook-path <local> with "
                "--force-with-reason to use a local copy.",
                file=sys.stderr,
            )
            print(
                f'   OVERRIDE: python -m scripts.bootstrap {args.project_name} '
                '--playbook-path <path> --force-with-reason="<>=10 char reason"',
                file=sys.stderr,
            )
            return 2

    # Step 2: templates.
    copy_templates(
        playbook_root=playbook_root,
        target_dir=target_dir,
        project_name=args.project_name,
        owner=owner,
        dry_run=args.dry_run,
    )

    # Step 3: personal flag.
    if args.personal:
        inject_personal_flag(target_dir / "AGENTS.md", dry_run=args.dry_run)

    # Step 4: pre-commit / doctor / discover.
    install_pre_commit(target_dir, dry_run=args.dry_run)
    run_doctor(target_dir, dry_run=args.dry_run)
    run_discover(target_dir, dry_run=args.dry_run)

    print_next_steps(target_dir, args.project_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
