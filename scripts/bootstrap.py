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
from scripts.materialise_skills import materialise_skills  # noqa: E402

SCRIPT_BASENAME = "bootstrap.py"
GATE_NAME = "submodule-unreachable"
DEFAULT_PLAYBOOK_URL = "https://github.com/Wizarck/ai-playbook.git"
DEFAULT_PIN = "v0.3.0"
SUBMODULE_PATH = ".ai-playbook"
TEMPLATE_SUBDIR = Path("templates") / "new-project"
SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
CONSUMERS_FILE = "consumers.yaml"


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
    register_in: Path | None = None  # Path to a playbook checkout whose
                                      # consumers.yaml should be updated with a
                                      # row for this project.
    visibility: str = "private"       # GitHub repo visibility (public|private).
    default_branch: str = "main"      # for consumers.yaml registration.
    refresh_skills: bool = False      # If True, only run skills materialisation
                                      # against the resolved target dir + exit.


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
    if cli_path is not None:  # noqa: SIM108 — ternary equivalent exceeds 120c
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
    # Bank id is the lowercased project slug per specs/memory-hierarchy.md §2.
    bank_id = project_name.lower()
    return (
        text.replace("{{TODAY}}", today_iso)
        .replace("{{PROJECT_NAME}}", project_name)
        .replace("{{OWNER_EMAIL}}", owner)
        .replace("{{PROJECT_BANK}}", bank_id)
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


def print_next_steps(target_dir: Path, project_name: str, *, registered: bool = False) -> None:
    print()
    print("✅ Bootstrap complete. Next steps:")
    print(f"   1. cd {target_dir}")
    print("   2. Fill placeholders in AGENTS.md (§1 identity, §3 active work, §4 rules).")
    print("   3. Review the rendered .mcp.json + .gemini/settings.json; tweak "
          "mcp-servers.project.yaml if you need to override base/personal layers.")
    print("   4. Write your first OpenSpec change: `/opsx:propose <topic>`.")
    print(f"   5. Commit + push the consumer: "
          f"`git add . && git commit -m 'chore: bootstrap {project_name} via ai-playbook' && git push`.")
    if registered:
        print("   6. Commit + push the playbook's consumers.yaml change so the "
              "propagation Action picks up your repo on the next tag.")
    else:
        print("   6. (Optional) Add a row for this project to "
              "<playbook>/consumers.yaml so the propagation Action auto-bumps "
              "the submodule when ai-playbook releases a new tag. Re-run "
              "bootstrap with --register-in <playbook-path> to do this in one "
              "step.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None) -> BootstrapArgs:
    parser = argparse.ArgumentParser(
        prog="bootstrap",
        description="Bootstrap a new consumer project with the ai-playbook submodule + templates.",
    )
    parser.add_argument("project_name", nargs="?", default=None,
                        help="Slug for the new project (must match [a-zA-Z0-9][a-zA-Z0-9_-]*). "
                             "Optional when --refresh-skills is used.")
    parser.add_argument("--owner", default=None,
                        help="Owner email (default: $GIT_AUTHOR_EMAIL or git config user.email).")
    parser.add_argument("--path", type=Path, default=None,
                        help="Target directory (default: <cwd>/<project-name>).")
    parser.add_argument("--playbook-pin", default=DEFAULT_PIN,
                        help="Playbook semver tag to pin (default: %(default)s).")
    parser.add_argument("--playbook-path", type=Path, default=None,
                        help="Offline fallback: copy from a local playbook checkout instead of cloning "
                             "from GitHub. Requires --force-with-reason.")
    parser.add_argument("--personal", action="store_true", help="Mark the new AGENTS.md with `personal: true`.")
    parser.add_argument("--register-in", type=Path, default=None,
                        help="Path to a playbook checkout. If set, append a row for this "
                             "project to <playbook>/consumers.yaml so the propagation "
                             "Action picks it up on the next tag push. The dev still "
                             "needs to commit + push the playbook change.")
    parser.add_argument("--visibility", choices=["public", "private"], default="private",
                        help="Repository visibility for the consumers.yaml entry "
                             "(default: private).")
    parser.add_argument("--default-branch", default="main",
                        help="Default branch name written to consumers.yaml "
                             "(default: main).")
    parser.add_argument("--dry-run", action="store_true", help="Report actions without side effects.")
    parser.add_argument("--refresh-skills", action="store_true",
                        help="Skip the full bootstrap flow and only run "
                             "skills materialisation against --path (or cwd). "
                             "Reads `skills_sources` from the consumer's "
                             "AGENTS.md frontmatter; see RFC-0001 §2.")
    add_break_glass_flag(parser)
    ns = parser.parse_args(argv)
    project_name = ns.project_name
    if not project_name:
        if not ns.refresh_skills:
            parser.error("project_name is required unless --refresh-skills is used")
        # Use a placeholder; --refresh-skills path doesn't validate the slug.
        project_name = "_refresh-skills"
    return BootstrapArgs(
        project_name=project_name,
        path=ns.path,
        owner=ns.owner,
        playbook_pin=ns.playbook_pin,
        playbook_path=ns.playbook_path,
        personal=ns.personal,
        force_reason=ns.force_reason,
        dry_run=ns.dry_run,
        register_in=ns.register_in,
        visibility=ns.visibility,
        default_branch=ns.default_branch,
        refresh_skills=ns.refresh_skills,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # --refresh-skills short-circuit: skip the bootstrap flow entirely and
    # only re-run skills materialisation against the target dir.
    if args.refresh_skills:
        target_dir = (args.path or Path.cwd()).expanduser().resolve()
        if not target_dir.is_dir():
            print(
                f"❌ --refresh-skills target {target_dir} is not a directory "
                f"at {SCRIPT_BASENAME}:refresh-skills",
                file=sys.stderr,
            )
            print("   FIX: pass --path <consumer-root> or run from inside the "
                  "consumer dir.", file=sys.stderr)
            print("   OVERRIDE: none", file=sys.stderr)
            return 1
        result = materialise_skills(target_dir, dry_run=args.dry_run)
        if not result.ok:
            # v0.17.0 single-source materialiser: exit 2 only when the source
            # is missing (consumer needs `git submodule update --init`); any
            # other failure is exit 1.
            return 2 if any(e.startswith("source missing:") for e in result.errors) else 1
        return 0

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

    # Step 4.5: skills materialisation (RFC-0001). Opt-in via AGENTS.md
    # `skills_sources`; consumer pre-Phase-5 will no-op silently. Failures
    # warn but don't abort the bootstrap.
    try:
        skills_result = materialise_skills(target_dir, dry_run=args.dry_run)
        if not skills_result.ok:
            print(
                f"⚠️ skills materialisation failed for {target_dir}; "
                f"bootstrap continues. Errors: "
                f"{'; '.join(skills_result.errors)[:300]}",
                file=sys.stderr,
            )
    except Exception as exc:  # noqa: BLE001 — never abort bootstrap on skills errors
        print(
            f"⚠️ skills materialisation raised {type(exc).__name__}: {exc}; "
            "bootstrap continues.",
            file=sys.stderr,
        )

    # Step 5: render .mcp.json + .gemini/settings.json from the merged layers.
    render_mcp_configs(target_dir, args.project_name, args.dry_run)

    # Step 6: optional registration in playbook's consumers.yaml.
    if args.register_in is not None:
        register_consumer(
            playbook_root=args.register_in,
            project_name=args.project_name,
            owner=owner,
            visibility=args.visibility,
            default_branch=args.default_branch,
            personal=args.personal,
            dry_run=args.dry_run,
        )

    print_next_steps(target_dir, args.project_name, registered=args.register_in is not None)
    return 0


def render_mcp_configs(target_dir: Path, project_name: str, dry_run: bool) -> None:
    """Run scripts/mcp/render.py against the new consumer to produce .mcp.json
    + .gemini/settings.json from the 3-layer merge. Best-effort — failures
    print a warning + leave the consumer with its template files only."""
    if dry_run:
        print(f"(dry-run) Would render .mcp.json + .gemini/settings.json for {project_name}.")
        return
    playbook_root = find_playbook_root()
    cmd = [
        sys.executable, "-m", "scripts.mcp.render",
        "--project", project_name,
        "--playbook-root", str(playbook_root),
        "--consumer-root", str(target_dir),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(playbook_root) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env)
    except FileNotFoundError:
        print(f"⚠️ python not found on PATH; skipping mcp/render for {project_name}.")
        return
    if result.returncode != 0:
        print(
            f"⚠️ mcp/render.py failed for {project_name} "
            f"(exit {result.returncode}); first stderr line: "
            f"{(result.stderr or '').splitlines()[0] if result.stderr else '<empty>'}"
        )
        return
    print(f"✓ rendered .mcp.json + .gemini/settings.json for {project_name}.")


def register_consumer(
    *,
    playbook_root: Path,
    project_name: str,
    owner: str,
    visibility: str,
    default_branch: str,
    personal: bool,
    dry_run: bool,
) -> None:
    """Append a consumer row to <playbook>/consumers.yaml (idempotent: skips if
    the row already exists)."""
    cf = playbook_root / CONSUMERS_FILE
    if not cf.is_file():
        print(
            f"⚠️ {cf} not found — skipping consumers.yaml registration."
        )
        return
    text = cf.read_text(encoding="utf-8")
    if f"\n  {project_name}:\n" in text:
        print(f"✓ {project_name} already in {cf} — no change.")
        return

    # Try to infer the org from existing entries (first repo: <org>/<name>).
    import re as _re
    m = _re.search(r"^\s+repo:\s+(\S+)/", text, _re.MULTILINE)
    org = m.group(1).strip() if m else "Wizarck"

    notes = "Personal infra." if personal else "Project repo."
    row = (
        f"\n  {project_name}:\n"
        f"    repo: {org}/{project_name}\n"
        f"    default_branch: {default_branch}\n"
        f"    visibility: {visibility}\n"
        + ("    personal: true\n" if personal else "")
        + "    status: active\n"
        + f"    notes: {notes}\n"
    )

    if dry_run:
        print(f"(dry-run) Would append to {cf}:\n{row}")
        return

    # Append before the trailing newline-only block.
    new_text = text.rstrip("\n") + row + "\n"
    cf.write_text(new_text, encoding="utf-8")
    print(f"✓ added {project_name} row to {cf}.")
    print(f"  Next: cd {playbook_root} && git add consumers.yaml && git commit && git push")


if __name__ == "__main__":
    raise SystemExit(main())
