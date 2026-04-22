"""Scan working tree for plaintext secrets (regex + gitleaks integration).

Populated in T10 + T09 (pre-commit). v0.1.0 stub.

Checks:
- Regex set for AWS keys, Anthropic keys, GitHub PATs, generic JWT.
- Invokes `gitleaks detect` if installed (via pre-commit's managed binary).
- Refuses to proceed if a match is found, unless `--force-with-reason=<text>`.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    print("ai-playbook secrets_scan — stub (populated in T10).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
