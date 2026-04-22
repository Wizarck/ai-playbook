"""Discover ai-playbook consumer projects on the local filesystem and populate
the projects registry (~/.ai-playbook/projects.yaml by default).

The registry decouples dispatchers from hardcoded paths. Moving a project from
C:\\OpenTrattOS to C:\\Projects\\openTrattOS only requires re-running this script —
no markdown edits.

See `specs/projects-registry.md` for the registry format and resolution rules.

Usage
-----
    python -m scripts.discover_projects                    # scan defaults, refresh registry
    python -m scripts.discover_projects --dry-run          # preview without writing
    python -m scripts.discover_projects --list             # print current registry
    python -m scripts.discover_projects --add <PATH>       # add one project by path
    python -m scripts.discover_projects --roots C:/Projects ~/work
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# Force UTF-8 I/O — Windows default cp1252 cannot encode the ✅/⚠️/❌ sigils we emit.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

try:
    import yaml
except ImportError:
    print("❌ PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    raise SystemExit(2)


DEFAULT_REGISTRY_PATH = Path.home() / ".ai-playbook" / "projects.yaml"
REGISTRY_SCHEMA = "ai-playbook/projects-registry/v1"

IGNORE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__",
    ".idea", ".vscode", "dist", "build", ".next", ".turbo",
    "target", ".cache", ".pytest_cache", ".ruff_cache",
    "Library", "Applications", "Windows", "AppData",
}


@dataclass
class ProjectEntry:
    name: str
    path: Path
    owner: str = ""
    personal: bool = False
    personal_addon: str | None = None
    version: str = ""
    inherits_from: list[str] = field(default_factory=list)


def get_default_roots() -> list[Path]:
    """Return conventional scan roots that exist on this machine."""
    roots: list[Path] = []
    env = os.environ.get("AIPLAYBOOK_PROJECTS_ROOTS", "")
    for p in env.replace(",", os.pathsep).split(os.pathsep):
        p = p.strip()
        if p:
            candidate = Path(p).expanduser()
            if candidate.exists() and candidate not in roots:
                roots.append(candidate)

    conventional = [
        Path.home() / "Projects",
        Path.home() / "projects",
        Path("C:/Projects"),
        Path("/opt"),
        Path("/srv"),
    ]
    for candidate in conventional:
        if candidate.exists() and candidate not in roots:
            roots.append(candidate)
    return roots


def parse_frontmatter(agents_md: Path) -> dict | None:
    """Parse YAML frontmatter from an AGENTS.md file. Return None if absent/invalid."""
    try:
        text = agents_md.read_text(encoding="utf-8")
    except OSError:
        return None
    # Normalize CRLF
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return None
    rest = text[4:]
    end = rest.find("\n---\n")
    if end == -1:
        # allow trailing '---' at end-of-file
        end = rest.find("\n---")
        if end == -1:
            return None
    fm_text = rest[:end]
    try:
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError:
        return None
    return fm if isinstance(fm, dict) else None


def scan(root: Path, max_depth: int = 3) -> Iterable[tuple[Path, dict]]:
    """Yield (project_dir, frontmatter) for every v1 AGENTS.md under `root`."""
    root = root.resolve()
    if not root.is_dir():
        return
    q: deque[tuple[Path, int]] = deque([(root, 0)])
    while q:
        d, depth = q.popleft()
        if depth > max_depth:
            continue
        agents = d / "AGENTS.md"
        if agents.is_file():
            fm = parse_frontmatter(agents)
            if fm and fm.get("schema") == "agents-md/v1":
                yield d, fm
                continue  # don't recurse into a matched project
        if depth == max_depth:
            continue
        try:
            entries = list(d.iterdir())
        except (PermissionError, OSError):
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            name = entry.name
            if name in IGNORE_DIRS or name.startswith("."):
                continue
            q.append((entry, depth + 1))


def build_entry(project_dir: Path, fm: dict) -> ProjectEntry:
    name = str(fm.get("project") or project_dir.name)
    owner = str(fm.get("owner", ""))
    personal = bool(fm.get("personal", False))
    version = str(fm.get("version", ""))
    inherits_from = list(fm.get("inherits_from", []))
    addon_abs: str | None = None
    addon_file = fm.get("personal_addon")
    if isinstance(addon_file, str):
        candidate = (project_dir / addon_file).resolve()
        if candidate.is_file():
            addon_abs = str(candidate)
    return ProjectEntry(
        name=name,
        path=project_dir.resolve(),
        owner=owner,
        personal=personal,
        personal_addon=addon_abs,
        version=version,
        inherits_from=inherits_from,
    )


def entry_to_dict(entry: ProjectEntry) -> dict:
    d: dict = {"path": str(entry.path)}
    if entry.owner:
        d["owner"] = entry.owner
    if entry.version:
        d["version"] = entry.version
    if entry.inherits_from:
        d["inherits_from"] = entry.inherits_from
    if entry.personal:
        d["personal"] = True
    if entry.personal_addon:
        d["personal_addon"] = entry.personal_addon
    return d


def load_registry(path: Path) -> dict:
    if not path.exists():
        return {"schema": REGISTRY_SCHEMA, "projects": {}}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {"schema": REGISTRY_SCHEMA, "projects": {}}
    if not isinstance(data, dict):
        return {"schema": REGISTRY_SCHEMA, "projects": {}}
    data.setdefault("schema", REGISTRY_SCHEMA)
    projects = data.get("projects")
    if not isinstance(projects, dict):
        data["projects"] = {}
    return data


def write_registry(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(
            "# ai-playbook projects registry.\n"
            "# Generated by scripts/discover_projects.py. Per-dev, gitignored.\n"
            "# See specs/projects-registry.md in ai-playbook.\n"
        )
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=True, allow_unicode=True)


def resolve_registry_path(cli_arg: Path | None) -> Path:
    if cli_arg:
        return cli_arg.expanduser()
    env = os.environ.get("AIPLAYBOOK_PROJECTS_FILE")
    if env:
        return Path(env).expanduser()
    return DEFAULT_REGISTRY_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="discover_projects",
        description="Discover ai-playbook consumer projects and populate the registry.",
    )
    parser.add_argument("--roots", nargs="*", type=Path,
                        help="Scan roots (default: AIPLAYBOOK_PROJECTS_ROOTS + conventional dirs).")
    parser.add_argument("--registry", type=Path, default=None,
                        help="Registry YAML path (default: AIPLAYBOOK_PROJECTS_FILE or ~/.ai-playbook/projects.yaml).")
    parser.add_argument("--dry-run", action="store_true", help="Scan/print, don't write.")
    parser.add_argument("--list", action="store_true", help="Print current registry and exit.")
    parser.add_argument("--add", type=Path, metavar="PATH",
                        help="Register a specific project path without scanning.")
    parser.add_argument("--depth", type=int, default=3, help="Max scan depth (default 3).")
    parser.add_argument("--refresh", action="store_true",
                        help="Rescan and rewrite (default behavior; flag is accepted for clarity).")
    args = parser.parse_args(argv)

    registry_path = resolve_registry_path(args.registry)

    if args.list:
        data = load_registry(registry_path)
        print(f"# {registry_path}")
        yaml.safe_dump(data, sys.stdout, default_flow_style=False, sort_keys=True, allow_unicode=True)
        return 0

    data = load_registry(registry_path)
    projects = data.setdefault("projects", {})

    if args.add is not None:
        target = args.add.expanduser().resolve()
        agents = target / "AGENTS.md"
        if not agents.is_file():
            print(f"❌ No AGENTS.md at {target}", file=sys.stderr)
            return 1
        fm = parse_frontmatter(agents)
        if not fm or fm.get("schema") != "agents-md/v1":
            print(f"❌ {agents} does not declare `schema: agents-md/v1`", file=sys.stderr)
            return 1
        entry = build_entry(target, fm)
        projects[entry.name] = entry_to_dict(entry)
        if args.dry_run:
            print("(dry-run) Would add:")
            yaml.safe_dump({entry.name: entry_to_dict(entry)}, sys.stdout, default_flow_style=False)
        else:
            write_registry(registry_path, data)
            print(f"✅ Added {entry.name} → {entry.path}  ({registry_path})")
        return 0

    # Default: refresh
    roots: list[Path] = list(args.roots) if args.roots else get_default_roots()
    if not roots:
        print("❌ No scan roots. Set AIPLAYBOOK_PROJECTS_ROOTS or pass --roots.", file=sys.stderr)
        return 1

    found: dict[str, ProjectEntry] = {}
    for root in roots:
        root = root.expanduser()
        if not root.exists():
            print(f"⚠️  Skipping non-existent root: {root}", file=sys.stderr)
            continue
        for project_dir, fm in scan(root, max_depth=args.depth):
            entry = build_entry(project_dir, fm)
            existing = found.get(entry.name)
            if existing is not None and existing.path != entry.path:
                print(
                    f"⚠️  Duplicate project name '{entry.name}': keeping {existing.path}, "
                    f"ignoring {entry.path}",
                    file=sys.stderr,
                )
                continue
            found[entry.name] = entry

    new_projects = {name: entry_to_dict(entry) for name, entry in sorted(found.items())}
    data["projects"] = new_projects

    if args.dry_run:
        print(f"(dry-run) Would write to {registry_path}:")
        yaml.safe_dump(data, sys.stdout, default_flow_style=False, sort_keys=True, allow_unicode=True)
        return 0

    write_registry(registry_path, data)
    print(f"✅ Wrote {len(new_projects)} project(s) to {registry_path}")
    for name, entry in sorted(found.items()):
        tags = " [personal]" if entry.personal else ""
        print(f"  - {name}: {entry.path}{tags}")
    if not found:
        print(
            "ℹ️  No consumer projects found. A project qualifies when its AGENTS.md "
            "carries `schema: agents-md/v1` in its YAML frontmatter.",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
