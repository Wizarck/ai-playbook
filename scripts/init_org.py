"""Parametrise an ai-playbook fork for a new org / personal stack.

When you fork ai-playbook to create your own playbook for a different org,
you'd normally have to find-and-replace `Wizarck/<repo>` references,
`https://acme-corp-hindsight.consumer-bfood.com` placeholders, and tenant-named
entries in 6+ files. This script walks the worktree, applies a single set
of substitutions, and reports what changed.

Usage:

    python -m scripts.init_org \\
        --org-name acme \\
        --owner-email ops@acme.example \\
        --hindsight-url https://hindsight.acme.example \\
        --secrets-env-path acme-core/secrets/secrets.env \\
        [--dry-run]

What it touches:

    - README.md       → replaces "Wizarck" + "ai-playbook" branding refs
    - runbooks/*.md   → replaces "Wizarck/<repo>" examples
    - docs/*.md       → replaces "Wizarck" + endpoint examples
    - templates/new-project/.claude/settings.json.tmpl → SOPS path placeholder
    - templates/new-project/mcp-servers.project.yaml.tmpl → Hindsight endpoint
    - AGENTS.md + templates/projects.yaml.example → owner email
    - templates/mcp-servers-personal.yaml.example → kept as-is (already generic)

An explicitly passed flag whose upstream literals match nothing, and whose
value is not already in place (a re-run), exits 1 before any file is written
(it would otherwise be a silent no-op).

What it does NOT touch:

    - specs/*.md      — these are universal and should stay org-agnostic
    - templates/rendered/mcp-servers-base.yaml.tmpl — already generic post-v0.3.0
    - scripts/*.py    — scripts are already parametric (read env vars)
    - VERSION + CHANGELOG — keep the upstream history intact

Exit codes:
    0  applied (or dry-run reported the plan)
    1  user-actionable error (missing arg, invalid org-name, flag matched nothing)
    2  setup error (cwd is not an ai-playbook checkout)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


# Files we touch + the substitutions applied.
@dataclass
class FileEdit:
    path: str
    replacements: list[tuple[str, str]] = field(default_factory=list)
    flag: str | None = None  # CLI flag this edit serves (zero-hit check)


# Upstream literals each flag rewrites. Keep in sync with the files: a flag
# whose literals match nothing makes main() exit 1 rather than silently no-op.
HINDSIGHT_URLS = (
    "https://acme-corp-hindsight.consumer-bfood.com",
    "https://consumer-d-hindsight.consumer-bfood.com",
)
SECRETS_ENV_PATHS = (
    "../acme-corp/secrets/secrets.env",
    "../consumer-a/secrets/secrets.env",
    "../consumer-d/secrets/secrets.env",
)
UPSTREAM_OWNER_EMAIL = "23051550+Wizarck@users.noreply.github.com"


def _detect_playbook_root(path: Path) -> Path:
    """Walk up from `path` until we find the playbook root.

    Heuristic: presence of ``templates/rendered/mcp-servers-base.yaml.tmpl``
    + ``AGENTS.md``. (Pre-v0.19.0 also checked for ``consumers.yaml`` — that
    central registry was removed when the push pipeline was retired.)
    """
    cur = path.resolve()
    while True:
        base_tmpl = cur / "templates" / "rendered" / "mcp-servers-base.yaml.tmpl"
        if base_tmpl.is_file() and (cur / "AGENTS.md").is_file():
            return cur
        if cur == cur.parent:
            print(
                "❌ not inside an ai-playbook checkout (no templates/rendered/"
                "mcp-servers-base.yaml.tmpl + AGENTS.md found walking up)",
                file=sys.stderr,
            )
            print("   FIX: cd into your ai-playbook fork and rerun.", file=sys.stderr)
            print("   OVERRIDE: none", file=sys.stderr)
            sys.exit(2)
        cur = cur.parent


def _validate_org_name(name: str) -> None:
    if not re.match(r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$", name):
        print(
            f"❌ org-name must be lowercase kebab, 3-32 chars, [a-z0-9-]: got {name!r}",
            file=sys.stderr,
        )
        print("   OVERRIDE: none", file=sys.stderr)
        sys.exit(1)


def build_edit_plan(
    *,
    root: Path,
    org_name: str,
    owner_email: str,
    hindsight_url: str | None,
    secrets_env_path: str | None,
    upstream_org: str = "Wizarck",
) -> list[FileEdit]:
    """Build the substitution plan. Each FileEdit is a path + a list of
    (find, replace) tuples applied in order."""
    plan: list[FileEdit] = []

    # README.md → swap upstream branding.
    plan.append(FileEdit("README.md", [
        (f"github.com/{upstream_org}/", f"github.com/{org_name}/"),
        (f"{upstream_org}/", f"{org_name}/"),
    ]))

    # Runbooks reference upstream repos in examples.
    for run in ("docs/runbooks/release.md", "docs/runbooks/rotate-secrets.md",
                "docs/runbooks/hindsight-retain.md"):
        plan.append(FileEdit(run, [
            (f"{upstream_org}/", f"{org_name}/"),
        ]))

    # Hindsight URL across docs (only when explicit).
    if hindsight_url:
        url_targets = [
            "docs/concepts/env-vars.md", "docs/concepts/session-start-hook.md",
            "docs/runbooks/hindsight-retain.md",
            "templates/new-project/AGENTS.md.tmpl",
            "templates/new-project/mcp-servers.project.yaml.tmpl",
        ]
        for f in url_targets:
            plan.append(FileEdit(f, [(u, hindsight_url) for u in HINDSIGHT_URLS],
                                 flag="--hindsight-url"))

    # SOPS path: the SessionStart hook in the template settings.json (sibling
    # consumer-a) + the runbooks' sops exec-env examples. Inside a JSON string
    # the value is escaped: a Windows path's backslashes are JSON escapes.
    if secrets_env_path:
        for f in ("templates/new-project/.claude/settings.json.tmpl",
                  "templates/new-project/AGENTS.md.tmpl",
                  "docs/runbooks/hindsight-retain.md",
                  "docs/runbooks/onboard-new-project.md"):
            value = json.dumps(secrets_env_path, ensure_ascii=False)[1:-1] if _is_json(f) else secrets_env_path
            plan.append(FileEdit(f, [(s, value) for s in SECRETS_ENV_PATHS],
                                 flag="--secrets-env-path"))

    # Owner email: the fork's own AGENTS.md frontmatter + the registry example.
    # (templates/new-project/AGENTS.md.tmpl uses {{OWNER_EMAIL}}, set at bootstrap.)
    for f in ("AGENTS.md", "templates/projects.yaml.example",
              "templates/new-project/AGENTS.md.tmpl"):
        plan.append(FileEdit(f, [(UPSTREAM_OWNER_EMAIL, owner_email)], flag="--owner-email"))

    return plan


def _is_json(rel: str) -> bool:
    return rel.endswith((".json", ".json.tmpl"))


def apply_edits(
    root: Path, plan: list[FileEdit], *, dry_run: bool,
    flag_hits: dict[str, int] | None = None,
    quiet: bool = False,
) -> tuple[int, int]:
    """Apply (or simulate) edits. Returns ``(files_touched, total_replacements)``.

    When ``flag_hits`` is given, it receives the replacement count per
    ``FileEdit.flag`` (0 for a flag whose literals matched nothing).

    Raises ``ValueError`` when an edit would turn a valid JSON file invalid.
    """
    files_touched = 0
    total_replacements = 0

    for edit in plan:
        path = root / edit.path
        if not path.is_file():
            if not quiet:
                print(f"  ⚠️  skip (file not found): {edit.path}", file=sys.stderr)
            continue
        text = path.read_text(encoding="utf-8")
        new_text = text
        local_replacements = 0
        for find, replace in edit.replacements:
            count = new_text.count(find)
            if count > 0:
                new_text = new_text.replace(find, replace)
                local_replacements += count
        if flag_hits is not None and edit.flag:
            flag_hits[edit.flag] = flag_hits.get(edit.flag, 0) + local_replacements

        if new_text == text:
            continue
        if _is_json(edit.path):
            try:
                json.loads(text)
            except ValueError:
                pass  # not plain JSON to begin with; nothing to keep valid
            else:
                try:
                    json.loads(new_text)
                except ValueError as exc:
                    raise ValueError(f"{edit.path} would become invalid JSON ({exc})") from exc
        files_touched += 1
        total_replacements += local_replacements
        action = "would write" if dry_run else "wrote"
        if not quiet:
            print(f"  ✏️  {action} {edit.path} ({local_replacements} replacement(s))")
        if not dry_run:
            path.write_text(new_text, encoding="utf-8")

    return files_touched, total_replacements


def _already_applied(root: Path, plan: list[FileEdit], flag: str) -> bool:
    """True when ``flag``'s value already sits in one of its target files, i.e.
    an earlier run rewrote the upstream literal (a re-run adding a flag later)."""
    for edit in plan:
        path = root / edit.path
        if edit.flag != flag or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if any(replace in text for _find, replace in edit.replacements):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.init_org", description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--org-name", required=True,
                   help="Lowercase kebab. Replaces Wizarck/* references.")
    p.add_argument("--owner-email", required=True,
                   help="Owner email for the fork's AGENTS.md frontmatter + registry example.")
    p.add_argument("--hindsight-url",
                   help="Override the Hindsight base URL across docs (optional).")
    p.add_argument("--secrets-env-path",
                   help="Override the SOPS secrets path in SessionStart hook templates "
                        "(default: ../consumer-a/secrets/secrets.env stays).")
    p.add_argument("--upstream-org", default="Wizarck",
                   help="Source org to replace (default: Wizarck).")
    p.add_argument("--root", type=Path, default=Path.cwd(),
                   help="Playbook root (auto-detected by walking up; pass to override).")
    p.add_argument("--dry-run", action="store_true",
                   help="Report the plan without writing.")
    args = p.parse_args(argv)

    _validate_org_name(args.org_name)
    if args.secrets_env_path and any(c in args.secrets_env_path for c in '"\r\n'):
        # The template puts it inside a double-quoted shell arg of a JSON string.
        print(f"❌ --secrets-env-path must not contain a double quote or a line break: "
              f"got {args.secrets_env_path!r}", file=sys.stderr)
        print("   OVERRIDE: none", file=sys.stderr)
        return 1
    root = _detect_playbook_root(args.root)
    print(f"playbook root: {root}")
    print(f"target org   : {args.org_name}")
    print(f"upstream org : {args.upstream_org}")
    if args.hindsight_url:
        print(f"hindsight URL: {args.hindsight_url}")
    if args.secrets_env_path:
        print(f"SOPS path    : {args.secrets_env_path}")
    print()

    plan = build_edit_plan(
        root=root,
        org_name=args.org_name,
        owner_email=args.owner_email,
        hindsight_url=args.hindsight_url,
        secrets_env_path=args.secrets_env_path,
        upstream_org=args.upstream_org,
    )
    # Silent dry pass first: nothing is written unless every flag passed either
    # rewrites an upstream literal or already holds its value (a re-run).
    flag_hits: dict[str, int] = {}
    try:
        apply_edits(root, plan, dry_run=True, flag_hits=flag_hits, quiet=True)
    except ValueError as exc:
        print(f"❌ {exc}; nothing was written at scripts/init_org.py:apply_edits", file=sys.stderr)
        print("   FIX: pass a value that is valid inside a JSON string, then rerun.", file=sys.stderr)
        print("   OVERRIDE: none", file=sys.stderr)
        return 1
    passed = ["--owner-email"]
    if args.hindsight_url:
        passed.append("--hindsight-url")
    if args.secrets_env_path:
        passed.append("--secrets-env-path")
    no_ops: list[str] = []
    for flag in passed:
        if flag_hits.get(flag, 0):
            continue
        if _already_applied(root, plan, flag):
            print(f"ℹ️  {flag}: already applied (its value is in place; nothing to replace).")
        else:
            no_ops.append(flag)
    if no_ops:
        print(
            f"❌ {', '.join(no_ops)} matched no upstream literal and the value is not in "
            "place either, so nothing was written at scripts/init_org.py:build_edit_plan",
            file=sys.stderr,
        )
        print(
            "   FIX: if an earlier run set a different value, edit it by hand (or "
            "`git checkout -- .` and rerun once with every flag); otherwise the files "
            "drifted: update the literal tuples at the top of scripts/init_org.py, then rerun.",
            file=sys.stderr,
        )
        print("   OVERRIDE: none", file=sys.stderr)
        return 1

    files, replacements = apply_edits(root, plan, dry_run=args.dry_run)
    print()
    verb = "Would touch" if args.dry_run else "Touched"
    print(f"{verb} {files} file(s); {replacements} total replacement(s).")

    if not args.dry_run:
        print()
        print("Next steps:")
        print("  1. Review the diff: git diff")
        print("  2. Set up your Hindsight instance (or skip if you don't want memory layer).")
        print("  3. Create your first consumer: copy templates/new-project/ → "
              "<org>/<repo>/, customise its AGENTS.md frontmatter (tracker_kind, "
              "jira_project if applicable), commit.")
        print("  4. Cut your first tag: see docs/runbooks/release.md.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
