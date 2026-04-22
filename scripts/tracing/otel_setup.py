"""Bootstrap OTel SDK with `gen_ai.*` semantic conventions and dual exporters.

Populated in T07c. v0.1.0 stub.

Design (decided in planning): OTel Collector + Tempo paralelo a Langfuse.
- Langfuse gets prompts/outputs/cost (LLM-native view).
- OTel Collector + Tempo gets infra correlation (logs/metrics/traces join).

REUSES existing eligia-core tracers at `lib/telemetry/{anthropic,gemini,ollama}_tracer.py`
— this helper wraps them rather than duplicating SDK setup.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    print("ai-playbook tracing/otel_setup — stub (populated in T07c).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
