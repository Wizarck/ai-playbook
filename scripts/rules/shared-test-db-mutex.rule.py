#!/usr/bin/env python3
"""Hardrule for `docs/rules/shared-test-db-mutex.rule.md`.

One test database, one test run at a time.

THE MEASURED INCIDENT (geeplo, 2026-08-16). A 40-minute full-suite run was in
flight to answer a real question — whether 743 previously ungated tests stay
green when interleaved with the rest of the suite in one process. Two short
pytest invocations were started alongside it. Backend pytest DROPS AND RECREATES
the schema in its session fixture, so the long run began failing from 33%. The
failures looked exactly like the contamination the run existed to detect.

That is what makes this worth a hook rather than a note. The cost is not the
wasted 40 minutes; it is that the corrupted run produces a plausible ANSWER to
the question you were asking, in the same shape a real answer would take. The
second run after the incident was misread too, for the same reason.

WHY A LOCK AND NOT A WARNING. The rule "do not run pytest while another run is
going" is trivially known and was still broken twice in one session, because the
second invocation always feels small — a single file, ten seconds. The lock does
not need to be smart; it needs to fire when the operator is not thinking about
it, which is precisely when the damage happens.

WHAT THIS DOES NOT COVER, stated rather than implied:

  * a test run started outside the agent's Bash tool (a terminal, an IDE runner,
    CI). Nothing local can see those.
  * two machines against one remote database. The lock is per-filesystem.
  * a test runner that is not matched by the patterns in the doc's frontmatter.
    A new runner joins by adding a pattern, and until it does it is unguarded —
    which is why the doc says the pattern list is the gate's real boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

if __name__ == "__main__":  # pragma: no cover - path bootstrap
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from scripts.rules._hook_contract import HookVerdict, bash_command, block
except ImportError:  # pragma: no cover - direct execution from the rules dir
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.rules._hook_contract import HookVerdict, bash_command, block

SLUG = "shared-test-db-mutex"
SKIP_ENV = "AIPLAYBOOK_TEST_DB_MUTEX_SKIP"

# A lock older than this is presumed abandoned. Set well ABOVE any real suite:
# a TTL at or below the true runtime turns every slow-but-healthy run into a
# silently released lock, which is the failure this file exists to prevent,
# rebuilt in a new shape. geeplo's longest measured lane is ~45 min.
STALE_AFTER_SECONDS = 3 * 60 * 60

# Commands that mutate a shared test database. Deliberately narrow: `pytest`
# with no DB in reach is harmless, but distinguishing that statically is not
# possible, so the trade is made toward false positives — which cost one
# environment variable to override, while a false negative costs a measurement.
_RUNNER_RE = re.compile(
    r"(?:^|[\s;&|(])"
    r"(?:"
    r"python\s+-m\s+pytest|pytest|tox"
    r"|alembic\s+(?:upgrade|downgrade)"
    # Seeding scripts are invoked by path (`python scripts/bootstrap-test-db.py`),
    # so the leading directories have to be allowed here — the boundary class
    # above does not include `/`, and without this the most destructive command
    # in the set was the one the gate could not see.
    r"|[\w./\\-]*bootstrap-test-db\.py"
    r")"
    r"(?:[\s;&|)]|$)",
)

# `--collect-only` and `--help` do not touch the database. Neither does a run
# explicitly pointed at no DB. Cheap exemptions that keep the gate from being
# annoying on the commands people run to LOOK at the suite.
_HARMLESS_RE = re.compile(r"--collect-only|--co\b|--help|--version|--fixtures")


def _lock_dir() -> Path:
    root = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
    if os.name == "nt":  # pragma: no cover - platform branch
        root = os.environ.get("TEMP") or os.environ.get("TMP") or root
    d = Path(root) / "ai-playbook-test-db-locks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _database_key(command: str) -> str:
    """Which database this command will hit.

    Read from the command's own inline `DATABASE_URL=` if it sets one, else from
    the ambient environment, else a per-repo fallback. Keying on the DB rather
    than on the repo is what lets two projects with separate databases run at
    once — the resource being protected is the database, not the checkout.
    """
    inline = re.search(r"DATABASE_URL=(\S+)", command)
    url = inline.group(1) if inline else os.environ.get("DATABASE_URL", "")
    if not url:
        url = f"cwd:{Path.cwd()}"
    return hashlib.sha256(url.strip().strip('"\'').encode()).hexdigest()[:16]


def _pid_alive(pid: int) -> bool:
    """Best effort, and honest about it.

    On POSIX, signal 0 is the standard probe.

    WINDOWS USED TO RETURN True UNCONDITIONALLY, and the comment justifying it
    called that "the safe direction: a genuinely dead holder is released by the
    TTL rather than by a guess". That reasoning was wrong for the only platform
    this actually runs on. With no liveness probe, the TTL IS the release
    mechanism — so any interrupted run (Ctrl-C, a killed background task, a
    crashed worker) wedges the database for three hours. Measured within fifteen
    minutes of first wiring the hook up: a probe process exited, its lock
    survived, and the next legitimate command was refused by a dead holder.

    A mutex whose failure mode is a three-hour outage gets switched off, and
    then it protects nothing at all. `OpenProcess` is in the stdlib via ctypes
    and costs microseconds, so the honest fix is to actually ask.
    """
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


#: OpenProcess access right that needs no elevation just to ask "does it exist".
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5
_ERROR_INVALID_PARAMETER = 87
_STILL_ACTIVE = 259


def _pid_alive_windows(pid: int) -> bool:
    """Ask Windows whether `pid` is a live process.

    Two subtleties, both of which decide the direction of the answer:

    * ``ERROR_ACCESS_DENIED`` means the process EXISTS and we may not inspect
      it (another user, higher integrity). That is alive, not dead — treating
      it as dead would let one user's lock be stolen by another's.
    * A process that has exited but whose handle is still open remains
      openable, and reports exit code != ``STILL_ACTIVE``. Without that second
      check a zombie holder would read as alive forever, which is the exact bug
      being fixed, just narrower.

    Anything unexpected answers True — keeping a lock held is recoverable (the
    TTL still exists, and there is a documented override); releasing one that
    is genuinely held corrupts a running suite silently.
    """
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:  # pragma: no cover - ctypes missing is not a real config
        return True

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid),
        )
        if not handle:
            err = ctypes.get_last_error()
            if err == _ERROR_ACCESS_DENIED:
                return True
            if err == _ERROR_INVALID_PARAMETER:
                return False
            return True
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # pragma: no cover - defensive
        return True


def _read(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_stale(entry: dict[str, Any], now: float | None = None) -> bool:
    now = time.time() if now is None else now
    if now - float(entry.get("started", 0)) > STALE_AFTER_SECONDS:
        return True
    pid = int(entry.get("pid", 0) or 0)
    return bool(pid) and not _pid_alive(pid)


def _held_by_other(path: Path, session: str) -> dict[str, Any] | None:
    entry = _read(path)
    if not entry:
        return None
    if entry.get("session") == session:
        return None  # our own lock: a second command in the same session run
    if _is_stale(entry):
        return None
    return entry


def _session_id(event: dict) -> str:
    return str(event.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or os.getpid())


def touches_test_db(command: str) -> bool:
    if not command or _HARMLESS_RE.search(command):
        return False
    return bool(_RUNNER_RE.search(command))


def pretooluse(event: dict) -> HookVerdict | None:
    """Block a test run while another one holds the same database."""
    if os.environ.get(SKIP_ENV):
        return None
    command = bash_command(event)
    if not touches_test_db(command):
        return None

    session = _session_id(event)
    path = _lock_dir() / f"{_database_key(command)}.json"

    holder = _held_by_other(path, session)
    if holder is not None:
        started = float(holder.get("started", 0))
        mins = max(0, int((time.time() - started) / 60))
        return block(
            f"{SLUG}: another test run holds this database.\n\n"
            f"  holder : {holder.get('command', '?')[:140]}\n"
            f"  since  : {mins} min ago (pid {holder.get('pid', '?')})\n\n"
            "Backend pytest drops and recreates the schema in its session "
            "fixture, so starting a second run corrupts the first — and the "
            "corrupted run still produces a plausible-looking answer, which is "
            "the expensive part. Wait for it, or point this run at another "
            "database with an inline DATABASE_URL=.\n\n"
            f"OVERRIDE: {SKIP_ENV}=1"
        )

    try:
        path.write_text(json.dumps({
            "session": session,
            "pid": os.getpid(),
            "started": time.time(),
            "command": command[:400],
        }), encoding="utf-8")
    except OSError:
        return None  # cannot write the lock: never make that an outage
    return None


def posttooluse(event: dict) -> HookVerdict | None:
    """Release our own lock when the run returns."""
    command = bash_command(event)
    if not touches_test_db(command):
        return None
    path = _lock_dir() / f"{_database_key(command)}.json"
    entry = _read(path)
    if entry and entry.get("session") == _session_id(event):
        try:
            path.unlink()
        except OSError:
            pass
    return None


if __name__ == "__main__":  # pragma: no cover
    print(f"{SLUG}: lock dir {_lock_dir()}")
