"""scripts.telemetry — unified telemetry pipeline (Slice 6, v0.18.2).

This package absorbs five formerly-standalone CLIs:

- scripts/cost_report.py
- scripts/lifecycle_check.py
- scripts/budget_disable_check.py
- scripts/deprecation_watcher.py
- scripts/simulate_model_migration.py

Their logic now lives as internal subroutines of `report.py`. The package
also emits per-rule-fire events via `rule_event_logger.log_event(...)`
(called by `scripts/hook_dispatcher.py` on every L1 hook fire).

Public entry points:

    python -m scripts.telemetry.report monthly
    python -m scripts.telemetry.report weekly --json
    python -m scripts.telemetry.report custom --window-days 14

Privacy guarantees: see `docs/concepts/telemetry-design.md`.
Event schema: see `schemas/schema-rule-event-v1.json`.
"""
from __future__ import annotations

from .anonymize import hash_session_id, scrub_event
from .rule_event_logger import log_event

__all__ = ["log_event", "hash_session_id", "scrub_event"]
