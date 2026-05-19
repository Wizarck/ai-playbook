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
    - templates/mcp-servers-personal.yaml.example → kept as-is (already generic)

What it does NOT touch:

    - specs/*.md      — these are universal and should stay org-agnostic
    - templates/rendered/mcp-servers-base.yaml.tmpl — already generic post-v0.3.0
    - scripts/*.py    — scripts are already parametric (read env vars)
    - VERSION + CHANGELOG — keep the upstream history intact

Exit codes:
    0  applied (or dry-run reported the plan)
    1  user-actionable error (missing arg, invalid org-name)
    2  setup error (cwd is not an ai-playbook checkout)
"""
from __future__ import annotations

import argparse
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
        ]
        for f in url_targets:
            plan.append(FileEdit(f, [
                ("https://acme-corp-hindsight.consumer-bfood.com", hindsight_url),
            ]))

    # SOPS path in template settings.json (default points at sibling acme-corp).
    if secrets_env_path:
        plan.append(FileEdit("templates/new-project/AGENTS.md.tmpl", [
            ("../acme-corp/secrets/secrets.env", secrets_env_path),
        ]))

    # Owner email tag in templates.
    plan.append(FileEdit("templates/new-project/AGENTS.md.tmpl", [
        ("23051550+Wizarck@users.noreply.github.com", owner_email),
    ]))

    return plan


def apply_edits(root: Path, plan: list[FileEdit], *, dry_run: bool) -> tuple[int, int]:
    """Apply (or simulate) edits. Returns ``(files_touched, total_replacements)``."""
    files_touched = 0
    total_replacements = 0

    for edit in plan:
        path = root / edit.path
        if not path.is_file():
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

        if new_text == text:
            continue
        files_touched += 1
        total_replacements += local_replacements
        action = "would write" if dry_run else "wrote"
        print(f"  ✏️  {action} {edit.path} ({local_replacements} replacement(s))")
        if not dry_run:
            path.write_text(new_text, encoding="utf-8")

    return files_touched, total_replacements


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.init_org", description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--org-name", required=True,
                   help="Lowercase kebab. Replaces Wizarck/* references.")
    p.add_argument("--owner-email", required=True,
                   help="Owner email for templated AGENTS.md frontmatter.")
    p.add_argument("--hindsight-url",
                   help="Override the Hindsight base URL across docs (optional).")
    p.add_argument("--secrets-env-path",
                   help="Override the SOPS secrets path in SessionStart hook templates "
                        "(default: ../acme-corp/secrets/secrets.env stays).")
    p.add_argument("--upstream-org", default="Wizarck",
                   help="Source org to replace (default: Wizarck).")
    p.add_argument("--root", type=Path, default=Path.cwd(),
                   help="Playbook root (auto-detected by walking up; pass to override).")
    p.add_argument("--dry-run", action="store_true",
                   help="Report the plan without writing.")
    args = p.parse_args(argv)

    _validate_org_name(args.org_name)
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
