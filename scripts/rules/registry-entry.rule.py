"""L1 hardrule: registry-entry (paired with docs/rules/registry-entry.rule.md).

Verifies the consumer repository is registered in the developer's local
playbook registry at ``~/.ai-playbook/projects.yaml`` — the per-developer
file populated by ``scripts/discover_projects.py``.

The registry is gitignored and per-machine state. On machines where the
registry file is absent (typically CI runners), the rule reports
``not-applicable`` (exit 2) rather than failing.

CLI:
    python scripts/rules/registry-entry.rule.py validate
    python scripts/rules/registry-entry.rule.py apply [--dry-run]

Exit codes:
    0 — consumer path is registered.
    1 — registry exists but consumer path is missing.
    2 — registry not initialised here (file absent) OR fatal (no consumer root).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SKIP_ENV = "AIPLAYBOOK_REGISTRY_ENTRY_SKIP"
REGISTRY_PATH = Path.home() / ".ai-playbook" / "projects.yaml"


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: AIPLAYBOOK_REGISTRY_ENTRY_SKIP=1", file=sys.stderr)


def _consumer_root(cwd: Path | None = None) -> Path | None:
    """Locate the consumer root: directory containing AGENTS.md."""
    cur = (cwd or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / "AGENTS.md").is_file():
            return p
    return None


def _playbook_root(consumer_root: Path) -> Path | None:
    """Find the playbook submodule root inside the consumer.

    Returns the path to `<consumer>/.ai-playbook` if it exists, else the
    current script's playbook root (when running directly out of the playbook
    repo for tests/dev).
    """
    submodule = consumer_root / ".ai-playbook"
    if (submodule / "scripts" / "discover_projects.py").is_file():
        return submodule
    # Fallback: walk up from this script.
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "scripts" / "discover_projects.py").is_file():
            return p
    return None


def _path_in_registry(registry_text: str, target: Path) -> bool:
    """Return True iff `target` appears as a `path:` value in the registry.

    Uses a forgiving line-based match: any line whose stripped form is
    ``path: <target-form>`` (with `target-form` matching either the POSIX
    or native-separator representation) counts as a hit. We intentionally
    avoid a full YAML parse here so the rule does not hard-depend on PyYAML
    at validate time.
    """
    target_resolved = target.resolve()
    candidates = {
        str(target_resolved),
        target_resolved.as_posix(),
        str(target_resolved).replace("\\", "/"),
    }
    for raw in registry_text.splitlines():
        line = raw.strip()
        if not line.startswith("path:"):
            continue
        value = line[len("path:"):].strip().strip("'\"")
        # Normalise both sides.
        value_norm = value.replace("\\", "/").rstrip("/")
        for c in candidates:
            if value_norm == c.replace("\\", "/").rstrip("/"):
                return True
    return False


def validate(cwd: Path | None = None) -> int:
    if os.environ.get(SKIP_ENV):
        return 0
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2

    if not REGISTRY_PATH.is_file():
        # Not applicable: registry not initialised on this machine (e.g. CI).
        print(
            f"not-applicable: {REGISTRY_PATH} does not exist on this machine "
            "(registry is per-developer / not present on CI)",
            file=sys.stderr,
        )
        return 2

    try:
        text = REGISTRY_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"error: cannot read {REGISTRY_PATH}: {exc}", file=sys.stderr)
        return 2

    if not _path_in_registry(text, root):
        _emit_error(
            why=f"consumer path {root} not registered in {REGISTRY_PATH}",
            where=str(REGISTRY_PATH),
            fix="run `python .ai-playbook/scripts/rules/registry-entry.rule.py apply`.",
        )
        return 1

    return 0


def apply(*, dry_run: bool, cwd: Path | None = None) -> int:
    """Refresh the registry by invoking `scripts/discover_projects.py`.

    Idempotent: the discover script rescans the filesystem and rewrites the
    registry; running twice on a converged state produces the same content.
    """
    root = _consumer_root(cwd)
    if root is None:
        print("error: no consumer root (AGENTS.md) found from cwd", file=sys.stderr)
        return 2
    playbook = _playbook_root(root)
    if playbook is None:
        print(
            "error: cannot locate scripts/discover_projects.py "
            "(neither in consumer's .ai-playbook/ nor relative to this script)",
            file=sys.stderr,
        )
        return 2
    script = playbook / "scripts" / "discover_projects.py"

    cmd: list[str] = [sys.executable, str(script)]
    if dry_run:
        cmd.append("--dry-run")
        print(f"[dry-run] would invoke: {' '.join(cmd)}")
    else:
        print(f"invoking: {' '.join(cmd)}")

    try:
        completed = subprocess.run(  # noqa: S603 — args constructed locally
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        print(f"error: cannot invoke discover_projects.py: {exc}", file=sys.stderr)
        return 2

    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    return 0 if completed.returncode == 0 else completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="registry-entry")
    parser.add_argument("subcommand", choices=["validate", "apply"])
    parser.add_argument("--dry-run", action="store_true", help="With 'apply': print plan, mutate nothing.")
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    if args.subcommand == "apply":
        return apply(dry_run=args.dry_run)
    return 2


if __name__ == "__main__":
    # File-path invocation from a consumer root: put the playbook root on
    # sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("registry-entry", main))
