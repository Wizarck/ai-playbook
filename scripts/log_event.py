"""Emit a structured event to `<repo>/.ai-playbook/events.jsonl` + OTel span.

This is the thin, dependency-free entry point every playbook script calls when
it needs to record a machine-readable event (verdicts, gate decisions, routing
fallbacks, override applications). The JSONL log is always written; the OTel
span is emitted only when tracing is available and not disabled
(see ``scripts/tracing/otel_setup.py``).

Usage
-----
CLI::

    python -m scripts.log_event \\
        --name "qa.verdict" \\
        --attrs '{"severity":"S1","verdict":"issues-found"}'

    python -m scripts.log_event --name "router.fallback" \\
        --attrs '{"ai_playbook.routing.fallback_depth":2}' \\
        --trace-id 0196f34a8c7e7b2f9d013e8a9b4c2f11 --pretty

Programmatic::

    from scripts.log_event import main
    rc = main(["--name", "qa.verdict", "--attrs", '{"severity":"S1"}'])

Exit codes
----------
- ``0`` on success.
- ``1`` on malformed ``--attrs`` JSON.
- ``2`` on filesystem error or missing ``--name`` (argparse emits SystemExit(2)
  on required-arg violation, which we deliberately let through so CLI misuse
  surfaces as exit 2).

The JSONL payload shape::

    {
      "ts": "2026-04-22T10:15:30+00:00",
      "name": "qa.verdict",
      "trace_id": "0196f34a...",   # absent if not provided and no active span
      "attrs": { ... }
    }
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Force UTF-8 stdio — the event attrs may carry ✅/⚠️/❌ verdict sigils.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_EVENTS_PATH = _REPO_ROOT / ".ai-playbook" / "events.jsonl"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="log_event",
        description=(
            "Append a structured event to .ai-playbook/events.jsonl and "
            "optionally emit an OTel span."
        ),
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Event name (e.g. 'qa.verdict', 'router.fallback', 'override.applied').",
    )
    parser.add_argument(
        "--attrs",
        default="{}",
        help="JSON object of event attributes. Default: '{}'.",
    )
    parser.add_argument(
        "--trace-id",
        default=None,
        help=(
            "Optional 32-char hex trace id to stamp into the event "
            "(correlation with a parent span)."
        ),
    )
    parser.add_argument(
        "--events-file",
        type=Path,
        default=None,
        help=f"Override events JSONL path (default: {_DEFAULT_EVENTS_PATH}).",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Also pretty-print the written payload to stdout (human testing).",
    )
    return parser


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _emit_otel_span(name: str, attrs: dict[str, Any]) -> None:
    """Best-effort emit an OTel span. Never crashes the caller."""
    try:
        from scripts.tracing.trace_emit import span  # local import; optional dep

        with span(name, attrs):
            pass
    except Exception:  # noqa: BLE001 — tracing is always optional
        return


def main(argv: list[str] | None = None) -> int:
    # argparse raises SystemExit(2) on missing required args; that matches our
    # "filesystem / usage error" exit code, which is convenient.
    parser = _build_parser()
    args = parser.parse_args(argv)

    raw_attrs: str = args.attrs or "{}"
    try:
        attrs_obj = json.loads(raw_attrs)
    except json.JSONDecodeError as exc:
        print(f"[log_event] malformed --attrs JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(attrs_obj, dict):
        print("[log_event] --attrs must be a JSON object", file=sys.stderr)
        return 1

    events_path: Path = args.events_file or _DEFAULT_EVENTS_PATH
    payload: dict[str, Any] = {
        "ts": _utc_now_iso(),
        "name": args.name,
        "attrs": attrs_obj,
    }

    trace_id: str | None = args.trace_id
    match trace_id:
        case None:
            # Try to pick up an active span's trace id silently.
            try:
                from scripts.tracing.trace_emit import current_trace_id

                tid = current_trace_id()
                if tid:
                    payload["trace_id"] = tid
            except Exception:  # noqa: BLE001
                pass
        case "":
            pass
        case _:
            payload["trace_id"] = trace_id

    try:
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            f.write("\n")
    except OSError as exc:
        print(f"[log_event] filesystem error writing {events_path}: {exc}", file=sys.stderr)
        return 2

    # Best-effort OTel span emission — never blocks success.
    _emit_otel_span(args.name, attrs_obj)

    if args.pretty:
        try:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        except OSError:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
