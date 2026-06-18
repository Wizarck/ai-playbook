"""Bootstrap a new consumer project with the ai-playbook submodule + templates.

Populated in T22e. Supersedes the T14a stub that merely printed args.

Responsibilities (per docs/concepts/migration-guide.md + templates/new-project/):

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
      {{PLAYBOOK_PIN}} → the tag from --playbook-pin (DEFAULT_PIN, read
                        lazily from the playbook's VERSION file)
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
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

# Force UTF-8 stdio — sigils in output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

# Make sibling-script imports work whether invoked via `-m scripts.bootstrap`
# or by direct path (`python .ai-playbook/scripts/bootstrap.py …`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._backup_helper import backup_base  # noqa: E402
from scripts._break_glass import add_break_glass_flag, apply_break_glass  # noqa: E402
from scripts.materialise_skills import materialise_skills  # noqa: E402
from scripts.tracing import trace_emit  # noqa: E402

SCRIPT_BASENAME = "bootstrap.py"
GATE_NAME = "submodule-unreachable"
DEFAULT_PLAYBOOK_URL = "https://github.com/Wizarck/ai-playbook.git"
SUBMODULE_PATH = ".ai-playbook"
TEMPLATE_SUBDIR = Path("templates") / "new-project"
SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")

# Single source of truth for the playbook's current version is the VERSION
# file at the repo root. Read lazily so bumps don't require touching code.
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _default_pin() -> str:
    """Return the current playbook tag (``v{VERSION}``) read from VERSION.

    Falls back to ``v0.0.0`` if the file is missing or unreadable — this only
    matters for the ``--help`` text; runtime callers can override with
    ``--playbook-pin``.
    """
    try:
        raw = (_REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "v0.0.0"
    return f"v{raw}" if raw and not raw.startswith("v") else (raw or "v0.0.0")


DEFAULT_PIN = _default_pin()


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
    refresh_skills: bool = False      # If True, only run skills materialisation
                                      # against the resolved target dir + exit.
    no_caveman: bool = False          # If True, omit caveman from the synthesised
                                      # defaults bundle so the door's apply_caveman
                                      # no-ops (see _synthesize_defaults_bundle).
    no_ponytail: bool = False         # If True, omit ponytail from the synthesised
                                      # defaults bundle so the door's apply_ponytail
                                      # no-ops (mirrors no_caveman; ponytail is
                                      # default-on like caveman).
    from_config: Path | None = None   # If set, apply an ai-playbook-config/v1 bundle
                                      # after the base bootstrap flow completes.
                                      # See scripts/apply_config.py.
    no_check: bool = False            # If True, skip the post-bootstrap
                                      # ai-playbook-check validate pass (see
                                      # run_playbook_check). Default behaviour
                                      # surfaces rule drift (bare-layout,
                                      # missing dispatchers, gitignore entries,
                                      # …) right before the "Next steps" banner.
    update: bool = False              # If True, run the update flow against an
                                      # already-bootstrapped consumer: skip
                                      # submodule-add + copy_templates (those
                                      # would clobber consumer customisations);
                                      # instead reconcile through the single
                                      # apply_config door against the existing
                                      # applied-config.json (or the one produced
                                      # by migrate_to_bundle if absent).
    check: bool = False               # If True, run a read-only reconcile
                                      # (apply --dry-run) against an existing
                                      # consumer and exit non-zero when any
                                      # section reports drift. This is the
                                      # drift-CI gate: same code path as apply,
                                      # report-only. Implies no writes.


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
    playbook_pin: str,
) -> str:
    # Bank id is the lowercased project slug per docs/concepts/memory-hierarchy.md §2.
    bank_id = project_name.lower()
    return (
        text.replace("{{TODAY}}", today_iso)
        .replace("{{PROJECT_NAME}}", project_name)
        .replace("{{OWNER_EMAIL}}", owner)
        .replace("{{PROJECT_BANK}}", bank_id)
        .replace("{{PLAYBOOK_PIN}}", playbook_pin)
    )


def copy_templates(
    *,
    playbook_root: Path,
    target_dir: Path,
    project_name: str,
    owner: str,
    playbook_pin: str,
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
    backed_up: list[str] = []  # pre-existing consumer files captured as BASE snapshots

    for src in src_root.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(src_root)
        # Strip .tmpl suffix if present (so AGENTS.md.tmpl → AGENTS.md).
        rel_out = rel.with_suffix("") if rel.suffix == ".tmpl" else rel
        dst = target_dir / rel_out
        rel_str = str(rel_out).replace(os.sep, "/")

        if dry_run:
            if dst.is_file():
                print(f"(dry-run) Would back up pre-existing {rel_str} (BASE snapshot) before overwrite.")
                backed_up.append(rel_str)
            print(f"(dry-run) Would write {dst}.")
            written.append(dst)
            continue

        # Lossless adoption: capture the consumer's pre-playbook content ONCE as a
        # restorable BASE snapshot before the template overwrites it. No-op when the
        # file is new or already has a base record (idempotent).
        if backup_base(target_dir, dst) is not None:
            backed_up.append(rel_str)

        dst.parent.mkdir(parents=True, exist_ok=True)
        raw = src.read_text(encoding="utf-8")
        new = _substitute(
            raw,
            project_name=project_name,
            owner=owner,
            today_iso=today_iso,
            playbook_pin=playbook_pin,
        )
        dst.write_text(new, encoding="utf-8", newline="\n")
        written.append(dst)

    if backed_up:
        _report_adoption_backups(backed_up)

    return written


_DISPATCHER_FILES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")


def _report_adoption_backups(rel_paths: list[str]) -> None:
    """Tell the operator which pre-existing files were preserved on adoption.

    The originals are stored as BASE snapshots (``.ai-playbook-state/backups/``)
    and are restorable via ``restore_base``. For dispatcher files we additionally
    point at the human-gated ``curate`` pass that re-absorbs their prose into
    ``AGENTS.md`` (the renderer is template-authoritative, so prose is preserved
    through extraction, not in place — see the lossless-adoption design D2).
    """
    print(
        f"📦 Lossless adoption: backed up {len(rel_paths)} pre-existing file(s) "
        f"as restorable BASE snapshots: {', '.join(rel_paths)}"
    )
    if any(r in _DISPATCHER_FILES for r in rel_paths):
        print(
            "   Your prior CLAUDE.md/AGENTS.md prose is in the BASE snapshot. To "
            "absorb it into AGENTS.md §1/§4/§8, run: "
            "python -m scripts.curate --dry-run  (then --yes to apply)."
        )


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


# Components the first reconcile turns on by default (the "everything ON"
# defaults synthesised when no user bundle exists). response_style materialises
# the AGENTS.md ruleset block, mcp_shrink wraps the rendered .mcp.json +
# .gemini/settings.json via the post-render hook in scripts/mcp/render.py, and
# the remaining flags advertise the related skills. Consumers opt-out with
# `--no-caveman` at bootstrap time (omits caveman from the synthesised bundle)
# or run `python -m scripts.caveman off` later. The actual activation now
# happens inside the door (apply_config.apply_caveman), not here.
DEFAULT_CAVEMAN_COMPONENTS = (
    "response_style",
    "compress_docs",
    "subagents_cavecrew",
    "commit_caveman",
    "review_caveman",
    "mcp_shrink",
)

# Ponytail is the code-minimalism twin of caveman and ships default-on at
# bootstrap, just like caveman: the synthesised bundle turns it ON with every
# component (see _synthesize_defaults_bundle). Consumers opt out with
# `--no-ponytail` (omits the ponytail section so the door's apply_ponytail
# no-ops) or run `python -m scripts.ponytail off` later.
DEFAULT_PONYTAIL_COMPONENTS = (
    "code_style",
    "review_ponytail",
    "audit_ponytail",
    "debt_ponytail",
)


def run_discover(target_dir: Path, dry_run: bool) -> None:
    if dry_run:
        print(f"(dry-run) Would run `python -m scripts.discover_projects --add {target_dir}`.")
        return
    subprocess.run(
        [sys.executable, "-m", "scripts.discover_projects", "--add", str(target_dir)],
        check=False,
    )


def run_playbook_check(target_dir: Path, dry_run: bool) -> None:
    """Invoke `python -m scripts.ai_playbook_check <target> --check` post-bootstrap.

    Validate-only by design: bootstrap surfaces rule drift (bare-layout,
    missing dispatchers, gitignore entries, etc.) so the operator sees what
    manual follow-up is needed, but never offers `apply` and never aborts
    bootstrap. The orchestrator's ``--check`` flag suppresses the interactive
    prompt; remediation stays operator-driven via ``/ai-playbook-check`` or
    the runbook referenced by each failing rule.

    Best-effort — any failure (missing python, orchestrator crash, exit≥2)
    prints a warning and lets bootstrap continue. Non-zero exit 1 (drift
    detected) is the EXPECTED outcome on a fresh single-tree consumer and
    is also handled as "report and continue".
    """
    if dry_run:
        print(
            f"(dry-run) Would run `python -m scripts.ai_playbook_check "
            f"{target_dir} --check`."
        )
        return
    playbook_root = find_playbook_root()
    cmd = [
        sys.executable, "-m", "scripts.ai_playbook_check",
        str(target_dir),
        "--check",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(playbook_root) + os.pathsep + env.get("PYTHONPATH", "")
    env["PLAYBOOK_NO_PROMPT"] = "1"  # belt-and-suspenders against any prompt
    print()
    print("→ ai-playbook-check: post-bootstrap drift report (validate-only)")
    try:
        result = subprocess.run(cmd, text=True, encoding="utf-8", env=env)
    except FileNotFoundError:
        print(
            "⚠️ python not found on PATH; skipping ai-playbook-check. "
            "Run `python -m scripts.ai_playbook_check` manually once env is ready."
        )
        return
    if result.returncode not in (0, 1):
        print(
            f"⚠️ ai-playbook-check exited {result.returncode}; bootstrap continues. "
            "Re-run `python -m scripts.ai_playbook_check` from the consumer root for details."
        )


# ---------------------------------------------------------------------------
# Next-steps banner
# ---------------------------------------------------------------------------

def print_next_steps(target_dir: Path, project_name: str) -> None:
    print()
    print("✅ Bootstrap complete. Next steps:")
    print(f"   1. cd {target_dir}")
    print("   2. Fill placeholders in AGENTS.md (§1 identity, §3 active work, §4 rules).")
    print("   3. Review the rendered .mcp.json + .gemini/settings.json; tweak "
          "mcp-servers.project.yaml if you need to override base/personal layers.")
    print("   4. Check caveman status: `python -m scripts.caveman status` "
          "(default-on unless --no-caveman was passed; see docs/runbooks/caveman-toggle.md).")
    print("      Ponytail (lazy/minimal code mode) is default-on too; check with "
          "`python -m scripts.ponytail status` (skip at bootstrap with --no-ponytail; "
          "see docs/runbooks/ponytail-toggle.md).")
    print("   5. If you applied a config bundle (--from-config), source the env file in your shell init: "
          "`set -a; source .ai-playbook/feature-flags.env; set +a` (or via direnv .envrc).")
    print("      Re-apply changes anytime with: `python -m scripts.apply_config <bundle.json>`. "
          "Build a new bundle in the HTML UI at `.ai-playbook/config-ui/index.html`.")
    print("   6. Write your first OpenSpec change: `/opsx:propose <topic>`.")
    print(f"   7. Commit + push the consumer: "
          f"`git add . && git commit -m 'chore: bootstrap {project_name} via ai-playbook' && git push`.")

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
    parser.add_argument("--dry-run", action="store_true", help="Report actions without side effects.")
    parser.add_argument("--refresh-skills", action="store_true",
                        help="Skip the full bootstrap flow and only run "
                             "skills materialisation against --path (or cwd). "
                             "Reads `skills_sources` from the consumer's "
                             "AGENTS.md frontmatter; see RFC-0001 §2.")
    parser.add_argument("--no-caveman", action="store_true",
                        help="Skip the default-on caveman activation step "
                             "(see scripts/caveman/). Without this flag, "
                             "bootstrap runs `caveman on --mode full --components <all>` "
                             "against the new project. Opt-out only; the "
                             "consumer can still flip it on later.")
    parser.add_argument("--no-ponytail", action="store_true",
                        help="Skip the default-on ponytail (lazy/minimal code mode) "
                             "activation step (see scripts/ponytail/). Without this "
                             "flag, bootstrap runs `ponytail on --mode full "
                             "--components <all>` against the new project. Opt-out "
                             "only; the consumer can still flip it on later.")
    parser.add_argument("--no-check", action="store_true",
                        help="Skip the post-bootstrap ai-playbook-check drift "
                             "report (validate-only). Without this flag, "
                             "bootstrap runs `python -m scripts.ai_playbook_check "
                             "<target> --check` at the end so the operator sees "
                             "any rule drift (bare-layout, dispatchers, "
                             "gitignore-entries, …). Never offers apply or aborts.")
    parser.add_argument("--update", action="store_true",
                        help="Update an existing consumer: skip submodule-add + "
                             "copy_templates (those would clobber consumer "
                             "customisations). Instead invokes apply_config on "
                             "<target>/.ai-playbook/applied-config.json (or "
                             "produces one via migrate_to_bundle if absent), "
                             "then re-runs skills materialisation + MCP render "
                             "+ advisory drift check. project_name argument is "
                             "optional under --update (taken from AGENTS.md).")
    parser.add_argument("--from-config", dest="from_config", type=Path, default=None,
                        help="Apply an ai-playbook-config/v1 bundle JSON (exported from "
                             "config-ui/) after the base bootstrap flow. Mutates "
                             "rules-toggle.json + caveman.json (via its CLI) + "
                             "feature-flags.env. See scripts/apply_config.py.")
    parser.add_argument("--check", action="store_true",
                        help="Read-only reconcile (apply --dry-run) against an "
                             "existing consumer at --path (or cwd): report drift "
                             "without writing, and exit non-zero when any section "
                             "differs. This is the drift-CI gate — same code path "
                             "as a real apply. project_name is optional under "
                             "--check (taken from the consumer).")
    add_break_glass_flag(parser)
    ns = parser.parse_args(argv)
    project_name = ns.project_name
    if not project_name:
        if not ns.refresh_skills and not ns.update and not ns.check:
            parser.error(
                "project_name is required unless --refresh-skills, --update, or "
                "--check is used"
            )
        # Use a placeholder; --refresh-skills / --update / --check don't validate
        # the slug (they operate on an existing consumer tree).
        if ns.update:
            project_name = "_update"
        elif ns.check:
            project_name = "_check"
        else:
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
        refresh_skills=ns.refresh_skills,
        no_caveman=ns.no_caveman,
        no_ponytail=ns.no_ponytail,
        from_config=ns.from_config,
        no_check=ns.no_check,
        update=ns.update,
        check=ns.check,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # --check short-circuit: read-only reconcile (apply --dry-run) against an
    # already-bootstrapped consumer. This is the drift-CI gate — same code path
    # as a real apply, but it writes nothing and exits non-zero when any section
    # reports drift. No submodule-add, no template copy, no advisory check
    # (the dry-run report IS the check).
    if args.check:
        target_dir = (args.path or Path.cwd()).expanduser().resolve()
        if not target_dir.is_dir():
            print(
                f"❌ --check target {target_dir} is not a directory",
                file=sys.stderr,
            )
            return 1
        return reconcile(target_dir, args, first_run=False)

    # --update short-circuit: skip submodule-add + copy_templates (which would
    # clobber consumer customisations) and reconcile through the single door:
    #   1. resolve the bundle (applied-config.json, or migrate_to_bundle)
    #   2. apply_config.apply — which itself re-materialises skills + re-renders
    #      MCP configs + re-applies caveman intent as its own sections
    #   3. ai_playbook_check --check (advisory)
    if args.update:
        target_dir = (args.path or Path.cwd()).expanduser().resolve()
        if not target_dir.is_dir():
            print(
                f"❌ --update target {target_dir} is not a directory",
                file=sys.stderr,
            )
            return 1
        return run_update(target_dir, args)

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
        playbook_pin=args.playbook_pin,
        dry_run=args.dry_run,
    )

    # Step 3: personal flag.
    if args.personal:
        inject_personal_flag(target_dir / "AGENTS.md", dry_run=args.dry_run)

    # Step 4: pre-commit / doctor / discover.
    install_pre_commit(target_dir, dry_run=args.dry_run)
    run_doctor(target_dir, dry_run=args.dry_run)
    run_discover(target_dir, dry_run=args.dry_run)

    # Steps 4.5–6 collapsed into the single reconcile door.
    #
    # Skills materialisation, MCP render, and caveman default-on used to run
    # here as separate inline calls. They are now SECTIONS of the one operation
    # (apply_config.apply); bootstrap is the *first reconcile*. On a fresh
    # install with no --from-config bundle we synthesise the defaults (every
    # feature ON; caveman omitted iff --no-caveman) and apply them. Section
    # ordering inside the door keeps caveman before MCP render (so the
    # post-render shrink hook sees caveman.json) and managed-files last; a
    # synthesised defaults bundle carries no managed-file trigger sections, so
    # the freshly-copied templates are left untouched. See SECTION_ORDER in
    # scripts/apply_config.py.
    reconcile(target_dir, args, first_run=True)

    # Step 7: post-bootstrap drift report (advisory). Runs ai-playbook-check
    # in validate-only mode so the operator sees any rule drift (bare-layout,
    # missing dispatchers, gitignore entries, etc.) before the "Next steps"
    # banner. Never aborts bootstrap and never offers apply — those stay
    # operator-driven via `/ai-playbook-check` or the runbook listed against
    # the failing rule.
    if args.no_check:
        print("→ ai-playbook-check: skipped (--no-check).")
    else:
        run_playbook_check(target_dir, dry_run=args.dry_run)

    print_next_steps(target_dir, args.project_name)
    return 0


# ---------------------------------------------------------------------------
# The single reconcile door
#
# bootstrap (the first reconcile), --update, and --check all funnel through
# scripts.apply_config.apply. The door owns caveman activation, skills
# materialisation, MCP render, and managed-file rendering as ordered sections
# (see SECTION_ORDER in scripts/apply_config.py). There is no second
# file-writing path: CHECK = apply --dry-run, REMEDY = apply.
# ---------------------------------------------------------------------------


def _synthesize_defaults_bundle(args: BootstrapArgs) -> dict[str, Any]:
    """Build the "everything ON" defaults bundle for a consumer with no config.

    The first reconcile has nothing on disk to read, so it materialises the
    playbook's defaults: all skills + MCP servers enforced (empty opt-out
    lists), and caveman + ponytail default-on with every component — unless
    --no-caveman / --no-ponytail, which omit that feature's section entirely (so
    the door's apply_caveman / apply_ponytail no-ops rather than running `off`
    against a never-activated tree).

    Carries NO content-bearing managed-file trigger sections (gitignore_extras,
    project_meta, …) so those stay no-ops and the freshly-copied templates are
    left exactly as bootstrap wrote them. The ONE exception is ``settings: {}``,
    which makes the door own ``.claude/settings.json`` from the first reconcile:
    its renderer only re-serialises on a real merge, so against the just-copied
    template (which already carries the PreToolUse invariant) it is a byte-level
    no-op — but it guarantees the enforce hook on every subsequent reconcile.
    """
    bundle: dict[str, Any] = {
        "schema": "ai-playbook-config/v1",
        "generated_by": "bootstrap-reconcile",
        "skills_enforce": {"disabled": []},
        "mcps_enforce": {"disabled": []},
        "settings": {},
    }
    features: dict[str, Any] = {}
    if not args.no_caveman:
        features["caveman"] = {
            "enabled": True,
            "mode": "full",
            "components": {c: True for c in DEFAULT_CAVEMAN_COMPONENTS},
        }
    if not args.no_ponytail:
        features["ponytail"] = {
            "enabled": True,
            "mode": "full",
            "components": {c: True for c in DEFAULT_PONYTAIL_COMPONENTS},
        }
    if features:
        bundle["features"] = features
    return bundle


def _write_temp_bundle(bundle: dict[str, Any]) -> Path:
    """Serialise a synthesised/derived bundle to a tempfile apply() can read.

    apply() takes a path, not an in-memory dict, so the synthesised defaults
    are written to a throwaway tempfile (outside the consumer tree, so even a
    dry-run reconcile leaves no consumer-visible artifact). The caller unlinks
    it once apply() has read it.
    """
    fd, name = tempfile.mkstemp(prefix="ai-playbook-reconcile-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, ensure_ascii=False, indent=2)
    return Path(name)


def _resolve_bundle_path(
    target_dir: Path, args: BootstrapArgs, *, first_run: bool
) -> tuple[Path | None, bool]:
    """Resolve the bundle the door should consume. Returns (path, is_temp).

    Precedence:
      --from-config <path>          → that bundle (never temp)
      applied-config.json present   → reuse the last-applied state
      first_run OR dry-run          → synthesise defaults (temp file)
      live update, no prior state   → migrate_to_bundle to derive desired state

    ``(None, False)`` signals a fatal resolution error (caller returns non-zero).
    """
    if args.from_config is not None:
        return args.from_config.expanduser().resolve(), False

    applied = target_dir / ".ai-playbook" / "applied-config.json"
    if applied.is_file():
        return applied, False

    dry = args.dry_run or args.check
    if first_run or dry:
        # Nothing on disk to read: synthesise the "everything ON" defaults.
        # For a dry-run check this yields a meaningful "what the playbook would
        # set" report without writing migrate output to the consumer tree.
        return _write_temp_bundle(_synthesize_defaults_bundle(args)), True

    # Live update with no applied-config.json: derive desired state via migrate.
    print("→ no applied-config.json — invoking migrate_to_bundle to extract state")
    playbook_root = find_playbook_root()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(playbook_root) + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [sys.executable, "-m", "scripts.migrate_to_bundle", "--target", str(target_dir)]
    try:
        rc = subprocess.run(cmd, env=env, check=False).returncode
    except FileNotFoundError:
        print("⚠️ python not found on PATH; cannot run migrate_to_bundle", file=sys.stderr)
        return None, False
    if rc != 0:
        print(f"⚠️ migrate_to_bundle exited {rc}; aborting reconcile", file=sys.stderr)
        return None, False
    migrated = target_dir / ".ai-playbook-state" / "migrated-bundle.json"
    if not migrated.is_file():
        print(f"❌ expected bundle not produced at {migrated}", file=sys.stderr)
        return None, False
    return migrated, False


def _apply_through_door(target_dir: Path, bundle_path: Path, *, dry_run: bool):
    """Invoke the one door (apply_config.apply) in-process. None on fatal error."""
    from scripts import apply_config as ac
    try:
        return ac.apply(bundle_path, target=target_dir, dry_run=dry_run)
    except (FileNotFoundError, ValueError) as exc:
        print(f"❌ reconcile/apply failed: {exc}", file=sys.stderr)
        return None


def reconcile(target_dir: Path, args: BootstrapArgs, *, first_run: bool) -> int:
    """The single write door — bootstrap, --update, and --check all funnel here.

    - first_run / fresh install: synthesise the "everything ON" defaults (or use
      --from-config) and apply. Best-effort — section failures warn but do not
      change the exit code (submodule/template errors already gated the
      fresh-install path before reaching here).
    - --update: resolve the consumer's bundle (applied-config.json or migrate)
      and apply. Best-effort.
    - --check: dry-run apply; exit non-zero when any section reports drift —
      this is the drift-CI gate, same code path as a real apply, report-only.
    """
    dry = args.dry_run or args.check
    # One slug ("bootstrap"); the mode is a span attribute, not a separate slug,
    # so first-reconcile / update / check stay distinguishable in telemetry
    # without breaking metric continuity. Nests under the entry span created by
    # script_emit("bootstrap", main).
    mode = "check" if args.check else ("first_run" if first_run else "update")
    if not first_run:
        label = "check (dry-run reconcile)" if args.check else "update"
        print(f"→ ai-playbook {label} for {target_dir}")
        print(f"   mode: {'dry-run' if dry else 'live'}")

    with trace_emit.span(
        "reconcile",
        {
            "ai_playbook.reconcile.mode": mode,
            "ai_playbook.reconcile.dry_run": dry,
        },
    ) as rspan:
        bundle_path, is_temp = _resolve_bundle_path(target_dir, args, first_run=first_run)
        if bundle_path is None:
            return 1
        try:
            report = _apply_through_door(target_dir, bundle_path, dry_run=dry)
        finally:
            if is_temp:
                try:
                    bundle_path.unlink()
                except OSError:
                    pass
        if rspan is not None and report is not None:
            try:
                rspan.set_attribute("ai_playbook.reconcile.ok", bool(report.ok))
                rspan.set_attribute("ai_playbook.reconcile.sections", len(report.sections))
            except Exception:  # noqa: BLE001 — telemetry must never break reconcile
                pass

    if report is None:
        return 1
    print(report.to_markdown())

    if args.check:
        # CI gate: any section drift / failure → non-zero exit.
        return 0 if report.ok else 1
    if not report.ok:
        print(
            "⚠️ reconcile: one or more sections reported issues; see report above. "
            "Re-run `python -m scripts.apply_config <bundle> --target <root>` after "
            "fixing the issue.",
            file=sys.stderr,
        )
    return 0


def run_update(target_dir: Path, args: BootstrapArgs) -> int:
    """Update an already-bootstrapped consumer through the single reconcile door.

    No submodule-add, no copy_templates (those would clobber consumer
    customisations). Reconcile resolves the consumer's bundle
    (.ai-playbook/applied-config.json, or migrate_to_bundle when absent) and
    funnels it through apply_config.apply — which re-applies caveman intent,
    re-materialises skills, re-renders MCP configs, and re-renders managed files
    as its own ordered sections. The advisory drift check runs last.

    Returns 0 on success (best-effort, matching the fresh-install discipline);
    non-zero only when the bundle could not be resolved.
    """
    rc = reconcile(target_dir, args, first_run=False)
    if rc != 0:
        return rc

    if not args.no_check:
        run_playbook_check(target_dir, dry_run=args.dry_run)

    print()
    print("✅ Update complete.")
    print("   - Managed files, skills + MCP configs reconciled from the bundle "
          "via the single door. Backups in .bak (configured location).")
    print("   - Restart Claude Code / Gemini CLI sessions if AGENTS.md or .claude/* changed.")
    return 0


if __name__ == "__main__":
    from scripts.rules._telemetry import script_emit
    raise SystemExit(script_emit("bootstrap", main))
