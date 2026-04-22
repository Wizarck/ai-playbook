"""Render consumer-specific MCP configs from the 3-layer yaml merge.

Populated in T08. v0.1.0 stub.

Outputs per target:
- `<repo>/.mcp.json` for Claude Code.
- `<repo>/.gemini/settings.json` for Gemini CLI / Antigravity.
- Printed summary of which layers contributed which server.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    print("ai-playbook mcp/render — stub (populated in T08).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
