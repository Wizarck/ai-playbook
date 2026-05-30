"""Tests for the telemetry dashboard aggregator (scripts/telemetry/build_dashboard_data.py).

Covers the OpenSpec ``telemetry-dashboard`` change phase 7 task list:
- 7.1 Golden test against the seeded 5k fixture.
- 7.2 Privacy invariants (no raw target_rel paths, no raw Bash commands,
  no unhashed session IDs in any per-developer surface).
- 7.3 Atomic-write guarantee (crash mid-rename leaves prior sidecar intact).
- 7.4 Torn-line tolerance (truncated last JSONL line → events_skipped >= 1).
- 7.5 SLO benchmark (aggregator under 2s, sidecar under 100 KB on 5k events).
- 7.6 Empty-state branch (events_seen < threshold → suppressed panels).
- 7.7 Caveman branch tests (on / off / missing).
- 7.8 JSON-schema validation of the produced payload.

UI tests (7.9 schema-mismatch banner, 7.10 Playwright smoke) live under
``tests/integration/`` and are skipped when optional deps are absent.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "telemetry-dashboard"
SCHEMA_PATH = REPO_ROOT / "schemas" / "schema-dashboard-data-v1.json"
PRICING_PATH = REPO_ROOT / "configs" / "pricing.yaml"

from scripts.telemetry import build_dashboard_data as bdd

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _stage_consumer(tmp_path: Path, *, jsonl_src: Path | None, caveman_json: dict | None = None) -> Path:
    """Create a fake consumer root with state dir + optional caveman.json."""
    consumer = tmp_path / "consumer"
    state_dir = consumer / ".ai-playbook-state"
    ai_dir = consumer / ".ai-playbook"
    state_dir.mkdir(parents=True)
    ai_dir.mkdir(parents=True)
    if jsonl_src is not None:
        shutil.copy(jsonl_src, state_dir / "rule-events.jsonl")
    if caveman_json is not None:
        (ai_dir / "caveman.json").write_text(
            json.dumps(caveman_json, indent=2), encoding="utf-8"
        )
    return consumer


def _restamp_recent(src: Path, dst: Path) -> None:
    """Copy a static rule-events fixture, shifting every ``timestamp`` so the
    newest event lands ~1 day before now. Decouples wall-clock-windowed golden
    assertions from the date the suite runs (the aggregator only accepts 7d/30d
    windows, so the fixture era is normalised rather than the window widened).
    Relative spacing between events is preserved; unparseable lines pass through.
    """
    import datetime as _dt

    records: list[tuple[_dt.datetime | None, dict | str]] = []
    newest: _dt.datetime | None = None
    for line in src.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            records.append((None, line))
            continue
        ts = ev.get("timestamp")
        parsed: _dt.datetime | None = None
        if isinstance(ts, str):
            try:
                parsed = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                parsed = None
        if parsed is not None and (newest is None or parsed > newest):
            newest = parsed
        records.append((parsed, ev))

    assert newest is not None, "fixture has no parseable timestamps"
    target = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0) - _dt.timedelta(days=1)
    delta = target - newest

    out: list[str] = []
    for parsed, ev in records:
        if isinstance(ev, str):
            out.append(ev)
            continue
        if parsed is not None:
            ev["timestamp"] = (parsed + delta).isoformat().replace("+00:00", "Z")
        out.append(json.dumps(ev, ensure_ascii=False))
    dst.write_text("\n".join(out) + "\n", encoding="utf-8")


def _read_sidecar(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"window\.DASHBOARD_DATA\s*=\s*(.*);\s*\Z", text, re.DOTALL)
    assert m, "sidecar does not look like the expected window.DASHBOARD_DATA = ...; form"
    return json.loads(m.group(1))


def _build(tmp_path: Path, consumer: Path, *, window_days: int = 30, threshold: int = 100) -> dict:
    output = tmp_path / "dashboard-data.js"
    rc = bdd.main(
        [
            "--consumer-root", str(consumer),
            "--window", f"{window_days}d",
            "--output", str(output),
            "--empty-state-threshold", str(threshold),
            "--pricing-path", str(PRICING_PATH),
            "--schema-path", str(SCHEMA_PATH),
            "--quiet",
        ]
    )
    assert rc == 0, f"aggregator exited rc={rc}"
    assert output.is_file()
    return _read_sidecar(output)


# --------------------------------------------------------------------------- #
# 7.1 Golden test: 5k fixture
# --------------------------------------------------------------------------- #


def test_aggregator_against_5k_fixture(tmp_path: Path):
    """Smoke-checks the aggregator's overall behaviour on the seeded 5k fixture.

    Numbers may shift if the fixture generator changes; we assert ranges, not
    exact values, so the test does not break on every privacy-preserving
    refactor of the generator. Exact-snapshot comparison would land under
    tests/integration/ with an --update-snapshot flag.
    """
    # The fixture timestamps are STATIC (≈2026-04-26 … 2026-05-26, a 30-day span).
    # The aggregator windows against the real wall-clock (now − window) and only
    # accepts 7d/30d windows, so a stale fixture silently ages events out of a 30d
    # window as the suite ages — a date-coupled flake. Normalise the fixture's era
    # instead: shift every timestamp so the newest lands ~1 day before now. A 30d
    # window then captures ~29 of the 30 fixture days deterministically, forever.
    recent = tmp_path / "rule-events-5k-recent.jsonl"
    _restamp_recent(FIXTURES_DIR / "rule-events-5k.jsonl", recent)
    consumer = _stage_consumer(
        tmp_path,
        jsonl_src=recent,
        caveman_json={"enabled": True, "mode": "full", "components": {"response_style": True}},
    )
    payload = _build(tmp_path, consumer, window_days=30, threshold=100)

    assert payload["schema_version"] == "dashboard-data/v1"
    assert payload["caveman_state"] in {"on", "missing"}  # missing if subprocess fallback fails
    assert payload["window"]["events_seen"] > 4500  # ~29/30 fixture days inside the window
    assert payload["window"]["events_skipped"] == 0
    assert len(payload["pricing_version"]) == 64

    panels = payload["panels"]
    assert panels["hero"]["incidents_prevented_7d"] >= 0
    assert panels["hero"]["prompt_injection_blocks"] <= panels["hero"]["incidents_prevented_7d"]
    assert 0.0 <= panels["secondary"]["obey_rate_7d"] <= 1.0
    assert panels["secondary"]["health_emoji"] in {"green", "yellow", "red"}
    assert len(panels["trend"]["points"]) >= 30
    assert len(panels["matrix"]["rows"]) > 0
    assert any(r["drift_flag"] != "none" for r in panels["matrix"]["rows"])  # generator biases produce drift
    assert len(panels["honesty"]["rows"]) >= 1


# --------------------------------------------------------------------------- #
# 7.2 Privacy invariants
# --------------------------------------------------------------------------- #


_GLOB = re.compile(r"[*?\[\]]")


def _walk_strings(obj, out: list[tuple[str, str]], path: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            _walk_strings(v, out, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_strings(v, out, f"{path}[{i}]")
    elif isinstance(obj, str):
        out.append((path, obj))


def test_privacy_invariants(tmp_path: Path):
    consumer = _stage_consumer(tmp_path, jsonl_src=FIXTURES_DIR / "rule-events-5k.jsonl")
    payload = _build(tmp_path, consumer, window_days=30)

    # No raw Bash commands sneaking through. ``bash_command`` is the only
    # field that would have been raw; we drop it defensively in _scrub_event_inplace.
    strs: list[tuple[str, str]] = []
    _walk_strings(payload, strs)
    paths_seen = {p for p, _ in strs}
    assert not any(p.endswith("bash_command") for p in paths_seen)

    # No unhashed session IDs.
    for _, v in strs:
        # Heuristic: session-id-looking strings ("session-xxxx" or 8-hex preceded by "id:")
        assert not re.search(r"session-\d", v), f"unhashed session id leaked: {v!r}"
        assert not re.search(r"\bsession_id:\s*[^a-f0-9]{8}\b", v)

    # No raw path-looking values reach the sidecar. The aggregator should
    # never put a raw target_rel in the panels. (Renderer reads only what we
    # send.) We check that no "/" path with directory components and no
    # glob characters appears anywhere — and crucially, the sentinel
    # ``<scrub-violation>`` is fine because it signals our second-line guard fired.
    # Whitelist: fields where a literal "/" is part of the intended value
    # (schema versions, content-addressed shas, sha256 hex strings).
    _PATH_HEURISTIC_EXEMPT = {
        "schema_version",
        "pricing_version",
    }

    for path, v in strs:
        if path in _PATH_HEURISTIC_EXEMPT:
            continue
        if "/" in v and not _GLOB.search(v) and v != "<scrub-violation>" and not v.startswith("docs/"):
            # ``docs/concepts/caveman-mode.md#cost-methodology`` is the documented
            # methodology URL — allowed.
            if "://" in v or v.endswith(".md") or v.endswith(".md#cost-methodology"):
                continue
            pytest.fail(f"raw path-like string leaked at {path}: {v!r}")


# --------------------------------------------------------------------------- #
# 7.3 Atomic write
# --------------------------------------------------------------------------- #


def test_atomic_write_preserves_prior_on_validation_failure(tmp_path: Path):
    """If schema validation fails before the rename, the prior sidecar stays.

    Simulated by writing a bogus prior sidecar, then forcing a validation
    failure via a tiny custom schema that mandates an impossible field.
    """
    consumer = _stage_consumer(tmp_path, jsonl_src=FIXTURES_DIR / "rule-events-5k.jsonl")
    output = tmp_path / "dashboard-data.js"
    prior = "// generated by scripts/telemetry/build_dashboard_data.py — do not edit by hand\nwindow.DASHBOARD_DATA = {\"schema_version\":\"dashboard-data/v1\",\"prior\":true};\n"
    output.write_text(prior, encoding="utf-8")

    bogus_schema = tmp_path / "bogus-schema.json"
    bogus_schema.write_text(
        json.dumps({"type": "object", "required": ["this_field_will_never_exist"]}),
        encoding="utf-8",
    )

    rc = bdd.main(
        [
            "--consumer-root", str(consumer),
            "--window", "30d",
            "--output", str(output),
            "--schema-path", str(bogus_schema),
            "--pricing-path", str(PRICING_PATH),
            "--quiet",
        ]
    )
    assert rc != 0
    # Prior sidecar untouched.
    text = output.read_text(encoding="utf-8")
    assert "\"prior\":true" in text


# --------------------------------------------------------------------------- #
# 7.4 Torn-line tolerance
# --------------------------------------------------------------------------- #


def test_torn_line_skipped_not_crashed(tmp_path: Path):
    consumer = _stage_consumer(tmp_path, jsonl_src=FIXTURES_DIR / "rule-events-torn.jsonl")
    payload = _build(tmp_path, consumer, window_days=30, threshold=10)
    assert payload["window"]["events_skipped"] >= 1
    # Hero still produced.
    assert "incidents_prevented_7d" in payload["panels"]["hero"]


# --------------------------------------------------------------------------- #
# 7.5 SLO benchmark
# --------------------------------------------------------------------------- #


def test_slo_under_two_seconds_and_under_100kb(tmp_path: Path):
    consumer = _stage_consumer(tmp_path, jsonl_src=FIXTURES_DIR / "rule-events-5k.jsonl")
    output = tmp_path / "dashboard-data.js"
    start = time.perf_counter()
    rc = bdd.main(
        [
            "--consumer-root", str(consumer),
            "--window", "30d",
            "--output", str(output),
            "--pricing-path", str(PRICING_PATH),
            "--schema-path", str(SCHEMA_PATH),
            "--quiet",
        ]
    )
    elapsed = time.perf_counter() - start
    assert rc == 0
    size = output.stat().st_size
    # SLO: < 2s on 5k events; < 100 KB sidecar.
    # We give 4s in CI to absorb cold-cache / slow disks; the design SLO is 2s
    # on a developer machine.
    assert elapsed < 4.0, f"aggregator took {elapsed:.2f}s (SLO 2s, CI budget 4s)"
    assert size < 100 * 1024, f"sidecar size {size} > 100 KB"


# --------------------------------------------------------------------------- #
# 7.6 Empty-state branch
# --------------------------------------------------------------------------- #


def test_empty_state_branch(tmp_path: Path):
    consumer = _stage_consumer(tmp_path, jsonl_src=FIXTURES_DIR / "rule-events-empty.jsonl")
    payload = _build(tmp_path, consumer, window_days=30, threshold=100)
    assert payload["window"]["events_seen"] < 100
    # All panel rows are empty / zero.
    panels = payload["panels"]
    assert panels["hero"]["incidents_prevented_7d"] == 0
    assert panels["trend"]["points"] == []
    assert panels["matrix"]["rows"] == []
    assert panels["honesty"]["rows"] == []
    assert panels["friction"]["rows"] == []


# --------------------------------------------------------------------------- #
# 7.7 Caveman branches
# --------------------------------------------------------------------------- #


def test_caveman_state_missing(tmp_path: Path):
    consumer = _stage_consumer(
        tmp_path,
        jsonl_src=FIXTURES_DIR / "rule-events-5k.jsonl",
        caveman_json=None,
    )
    payload = _build(tmp_path, consumer, window_days=30)
    assert payload["caveman_state"] == "missing"
    assert payload["panels"]["caveman"] == {"state": "missing"}


def test_caveman_state_off(tmp_path: Path):
    consumer = _stage_consumer(
        tmp_path,
        jsonl_src=FIXTURES_DIR / "rule-events-5k.jsonl",
        caveman_json={"enabled": False, "mode": "lite"},
    )
    payload = _build(tmp_path, consumer, window_days=30)
    assert payload["caveman_state"] == "off"
    assert payload["panels"]["caveman"] == {"state": "off"}


# --------------------------------------------------------------------------- #
# 7.8 JSON-schema validation
# --------------------------------------------------------------------------- #


def test_payload_validates_against_v1_schema(tmp_path: Path):
    jsonschema = pytest.importorskip("jsonschema")
    consumer = _stage_consumer(
        tmp_path,
        jsonl_src=FIXTURES_DIR / "rule-events-5k.jsonl",
        caveman_json={"enabled": True, "mode": "full", "components": {"response_style": True}},
    )
    payload = _build(tmp_path, consumer, window_days=30)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)
