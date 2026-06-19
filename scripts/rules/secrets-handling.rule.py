"""L1 hardrule: secrets-handling (paired with docs/rules/secrets-handling.rule.md).

Thin wrapper around `scripts/secrets_scan.py`. Per the rule contract,
this gate declares `OVERRIDE: none` — break-glass is refused.

CLI:
    python scripts/rules/secrets-handling.rule.py validate

Exit codes:
    0 — no secrets detected in staged content.
    1 — likely secret hit (violation).
    2 — schema break / fatal (scanner missing).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCANNER = REPO_ROOT / "scripts" / "secrets_scan.py"


def validate() -> int:
    if not SCANNER.is_file():
        print(f"error: secrets_scan.py missing at {SCANNER}", file=sys.stderr)
        return 2
    # Default scope = `--staged` (matches the rule's docstring: "no secrets
    # detected in staged content"). Without an explicit scope, scripts/
    # secrets_scan.py prints CLI usage and exits non-zero, which the
    # orchestrator (correctly) reads as drift even though there's nothing
    # actually to scan. `--staged` makes the rule a no-op on a clean tree
    # and a real check during PR review / commit hooks.
    rc = subprocess.call([sys.executable, str(SCANNER), "--staged"])
    return 1 if rc != 0 else 0


def pretooluse(event: dict):
    """In-process L1 hook: refuse an Edit/Write/MultiEdit that introduces a secret.

    Scans the NEW content of the event (not the staged tree — this fires before
    the write lands). Fail-open if the scanner is unavailable; CI/pre-commit
    ``validate`` remains the backstop. OVERRIDE: none (per the rule contract).
    """
    from scripts.rules._hook_contract import allow, block, edited_path, edited_text, tool_name

    if tool_name(event) not in ("Edit", "Write", "MultiEdit"):
        return None
    text = edited_text(event)
    if not text:
        return None
    try:
        from scripts import secrets_scan
        matches = secrets_scan.scan(text)
    except Exception:  # noqa: BLE001 — scanner missing → fail open.
        return None
    if matches:
        kinds = ", ".join(sorted({m.kind for m in matches}))
        where = edited_path(event) or "the edited content"
        return block(
            f"likely secret(s) detected in {where}: {kinds}. Remove the secret or move "
            "it to a SOPS-encrypted env file before writing. OVERRIDE: none."
        )
    return allow()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="secrets-handling")
    parser.add_argument("subcommand", choices=["validate"])
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    return 2


if __name__ == "__main__":
    # File-path invocation from a consumer root: put the playbook root on
    # sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("secrets-handling", main))
