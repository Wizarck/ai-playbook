"""Filter tool outputs / user inputs for prompt-injection patterns.

Populated in T10. v0.1.0 stub.

Two layers:
1. Regex for known injection templates ("Ignore previous instructions", "System:", etc).
2. LLM-as-judge fallback (Haiku) for ambiguous content.

Output: JSON verdict per `specs/verdict-contract.md`. Emits OTel attrs
`ai_playbook.injection.layer1_match` and `.layer2_verdict`.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    print("ai-playbook prompt_injection_filter — stub (populated in T10).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
