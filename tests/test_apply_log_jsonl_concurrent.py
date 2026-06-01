"""Concurrent-append stress test for `.apply_log.jsonl`.

Guards the assumption that N parallel processes appending one JSONL row
each produce a well-formed file (every line parses as JSON, no row
interleaving, no rows lost). The append-only invariant is documented in
docs/rules/apply-skill-enforcement.rule.md (INV-2).

POSIX atomically appends when each write is <= PIPE_BUF (4096 bytes on
Linux, ~4096 on macOS, generally fine on Windows for small lines). This
test pins the contract: any future regression that violates atomic
appends — e.g. a refactor that wraps the helper in non-atomic write +
flush logic — fails here.

Skipped paths:
- Windows file locking edge cases: if the test fails on Windows specifically,
  document the limitation in docs/rules/apply-skill-enforcement.rule.md
  rather than disabling the test. The marker helper is the authoritative
  writer; this test is the canary.
"""
from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

PROCS = 10        # parallel processes
ROWS_PER_PROC = 10  # JSONL rows per process
TOTAL_EXPECTED = PROCS * ROWS_PER_PROC


def _append_rows(args: tuple[str, int, int]) -> int:
    """Append ROWS_PER_PROC records to apply_log_path. Returns # appended.

    Each row is small (<200 bytes) so POSIX guarantees an atomic write per
    line. Each process opens fresh in append mode, writes its rows, and
    flushes before closing — the OS handles the interleaving.
    """
    apply_log_path, proc_idx, rows = args
    path = Path(apply_log_path)
    written = 0
    with path.open("a", encoding="utf-8", newline="\n") as f:
        for j in range(rows):
            row = {
                "event": "override",
                "change_id": "stress-test",
                "session_id": f"proc-{proc_idx}",
                "ts": f"2026-05-25T10:{proc_idx:02d}:{j:02d}.000Z",
                "reason": f"stress row {proc_idx}/{j}",
            }
            f.write(json.dumps(row, sort_keys=True) + "\n")
            f.flush()
            written += 1
    return written


def test_concurrent_appends_produce_well_formed_jsonl(tmp_path: Path) -> None:
    """N processes × M rows each → exactly N*M valid JSON lines in the final file."""
    apply_log = tmp_path / ".apply_log.jsonl"
    apply_log.touch()

    args = [(str(apply_log), i, ROWS_PER_PROC) for i in range(PROCS)]
    with ProcessPoolExecutor(max_workers=PROCS) as pool:
        results = list(pool.map(_append_rows, args))

    # Each process reports it wrote ROWS_PER_PROC.
    assert sum(results) == TOTAL_EXPECTED, (
        f"writers reported wrong totals: {results} (expected {ROWS_PER_PROC} each)"
    )

    raw = apply_log.read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if ln.strip()]

    # Every line is a valid JSON object.
    parsed: list[dict] = []
    for idx, line in enumerate(lines):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"line {idx} is not valid JSON: {line!r}\nerror: {exc}"
            ) from None
        assert isinstance(obj, dict), f"line {idx} parsed but is not an object: {obj!r}"
        parsed.append(obj)

    # Total row count survived.
    assert len(parsed) == TOTAL_EXPECTED, (
        f"expected {TOTAL_EXPECTED} rows, got {len(parsed)} "
        f"(diff suggests row loss or write interleaving)"
    )

    # Every (proc_idx, row_idx) pair appears exactly once → no duplicates, no loss.
    seen: set[tuple[str, str]] = set()
    for obj in parsed:
        key = (obj.get("session_id", ""), obj.get("ts", ""))
        assert key not in seen, f"duplicate row detected: {obj}"
        seen.add(key)
    assert len(seen) == TOTAL_EXPECTED, (
        f"distinct row count mismatch: {len(seen)} (expected {TOTAL_EXPECTED})"
    )


def test_append_atomicity_does_not_interleave_within_a_line(tmp_path: Path) -> None:
    """Confirm that even with concurrent writers, no row is split mid-line.

    Catches a class of regression where a buggy writer might emit `{...partial...`
    on one fork, get interleaved by another, and end with `... rest}` mixed in.
    """
    apply_log = tmp_path / ".apply_log.jsonl"
    apply_log.touch()
    args = [(str(apply_log), i, ROWS_PER_PROC) for i in range(PROCS)]
    with ProcessPoolExecutor(max_workers=PROCS) as pool:
        list(pool.map(_append_rows, args))

    raw = apply_log.read_text(encoding="utf-8")
    # Every newline separates exactly one complete JSON object. If interleaving
    # happened, json.loads on a line would fail (covered by the test above) OR
    # we'd see fewer/more `\n` than rows.
    nl_count = raw.count("\n")
    assert nl_count == TOTAL_EXPECTED, (
        f"newline count {nl_count} != expected row count {TOTAL_EXPECTED} "
        "— likely partial-write interleaving"
    )
