"""Guards for the emergency SOPS re-key block (runbook-key-rotation-emergency Step 6).

The block is pasted into an operator's terminal during an incident, so each
property below is one that was measured to fail (sops 3.7.3, Git Bash):

- `sops ... /dev/stdin`: native sops cannot open it from Git Bash, and a
  path-scoped `.sops.yaml` rejects the stdin / temp file name outright.
- a top-level `set -euo pipefail` closes the operator's shell on any failure.
- `sops --rotate` that cannot decrypt exits 0 and, with --in-place, EMPTIES
  the store, so decryptability is proven first and a copy is put back unless
  the new key alone decrypts the result.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

RUNBOOK = (
    Path(__file__).resolve().parents[1]
    / "docs" / "runbooks" / "runbook-key-rotation-emergency.md"
)


def _step6_block() -> str:
    text = RUNBOOK.read_text(encoding="utf-8")
    step6 = text[text.index("6. **If the leaked credential"):]
    start = step6.index("```bash\n") + len("```bash\n")
    body = step6[start: step6.index("\n   ```", start)]
    return "\n".join(ln[3:] if ln.startswith("   ") else ln for ln in body.splitlines())


BLOCK = _step6_block()
LINES = [ln for ln in BLOCK.splitlines() if ln.strip()]


def test_the_block_runs_in_a_subshell() -> None:
    """`set -e` must end the block, not the operator's shell or SSH session."""
    assert LINES[0].strip() == "(" and LINES[-1].strip() == ")"
    assert "set -euo pipefail" in LINES[1]


def test_no_stdin_pipe_and_no_temp_file_for_sops_to_name_check() -> None:
    assert "/dev/stdin" not in BLOCK
    assert "--rotate --in-place" in BLOCK
    assert ".new" not in BLOCK


def test_the_new_key_alone_verifies_and_the_leaked_key_must_not_decrypt() -> None:
    assert "keys-both" not in BLOCK
    assert 'dec "$K/keys-new.txt" "$f" && ! dec "$K/keys.txt" "$f"' in BLOCK


def test_decryptability_is_proven_and_a_copy_kept_before_rotating() -> None:
    """sops 3.7 `--rotate --in-place` with a key that cannot decrypt exits 0
    and leaves a 0-byte file: the guard and the copy must come first."""
    rotate = BLOCK.index("sops --rotate")
    assert BLOCK.index('dec "$K/keys.txt" "$f" ||') < rotate
    assert BLOCK.index('cp "$f" "$f.pre-rekey"') < rotate
    assert 'mv "$f.pre-rekey" "$f"' in BLOCK[rotate:]


def test_a_retry_reuses_the_new_key() -> None:
    """age-keygen -o refuses to overwrite: an unguarded call fails every retry."""
    assert '[ -f "$K/keys-new.txt" ] || age-keygen -o "$K/keys-new.txt"' in BLOCK


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
def test_the_block_is_valid_bash() -> None:
    script = BLOCK.replace("<leaked-pub-key>", "age1placeholder")
    r = subprocess.run(["bash", "-n"], input=script, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
