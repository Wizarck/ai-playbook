"""Guards for the emergency SOPS re-key block (runbook-key-rotation-emergency Step 6).

The block is pasted into an operator's terminal during an incident, so each
property below is one that was measured to fail (sops 3.7.3, Git Bash):

- `sops ... /dev/stdin`: native sops cannot open it from Git Bash, and a
  path-scoped `.sops.yaml` rejects the stdin / temp file name outright.
- a top-level `set -euo pipefail` closes the operator's shell on any failure.
- `sops --rotate` that cannot decrypt exits 0 and, with --in-place, EMPTIES
  the store, so decryptability is proven first and a copy is put back unless
  the new key alone decrypts the result.
- a keys.txt that also holds a kept recipient's identity (a server key)
  always decrypts, so "the leaked key no longer decrypts" judged with keys.txt
  failed and restored every file: removal is read from the recipient list.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

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


def test_the_new_key_alone_verifies_and_the_leaked_key_leaves_the_recipients() -> None:
    assert "keys-both" not in BLOCK
    assert '! dec "$K/keys.txt"' not in BLOCK
    verified = 'dec "$K/keys-new.txt" "$f" && ! grep -qF "$OLD_PUB" "$f"'
    assert BLOCK.count(verified) == 2  # the done-by-an-earlier-run skip + after rotating


def test_a_leaked_key_that_is_not_a_recipient_stops_before_rotating() -> None:
    """A mistyped key would make `--rm-age` a silent no-op."""
    assert BLOCK.index('grep -qF "$OLD_PUB" "$f" ||') < BLOCK.index("sops --rotate")


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


# ---------------------------------------------------------------------------
# The block run end to end, against stand-ins for sops and age-keygen
# ---------------------------------------------------------------------------

# A store's recipients are its `sops_age__list_N__map_recipient=` lines (the
# dotenv metadata real sops writes); a key file decrypts it when one of its
# `# public key:` lines is among them. `--rotate` that cannot decrypt exits 0 and
# empties the file, as sops 3.7.3 was measured to.
FAKE_SOPS = r"""#!/usr/bin/env bash
f="${!#}"
can_dec() {
  [ -f "${SOPS_AGE_KEY_FILE:-}" ] || return 1
  for pub in $(sed -n 's/^# public key: //p' "$SOPS_AGE_KEY_FILE"); do
    grep -qx "sops_age__list_[0-9]*__map_recipient=$pub" "$f" && return 0
  done
  return 1
}
if [ "$1" = "-d" ]; then
  can_dec || { echo "fake sops: no identity can decrypt $f" >&2; exit 128; }
  grep -v '^sops_' "$f"
  exit 0
fi
add= rm=
while [ $# -gt 1 ]; do
  case "$1" in --add-age) add=$2; shift ;; --rm-age) rm=$2; shift ;; esac
  shift
done
can_dec || { : > "$f"; exit 0; }
{ grep -v '^sops_age' "$f"
  { sed -n 's/^sops_age__list_[0-9]*__map_recipient=//p' "$f" | grep -vxF "$rm"; echo "$add"; } |
    awk '{ print "sops_age__list_" (NR - 1) "__map_recipient=" $0 }'
} > "$f.fake-tmp" && mv "$f.fake-tmp" "$f"
"""
# -o refuses to overwrite, like the real one; -y prints the recipient.
FAKE_AGE_KEYGEN = r"""#!/usr/bin/env bash
case "$1" in
  -o) [ ! -e "$2" ] || { echo "age-keygen: $2: file exists" >&2; exit 1; }
      printf '# public key: age1newkey\nAGE-SECRET-KEY-1NEWKEY\n' > "$2" ;;
  -y) sed -n 's/^# public key: //p' "$2" ;;
esac
"""
LEAKED, KEPT, OTHER, NEW = "age1leakedkey", "age1keptkey", "age1otherkey", "age1newkey"
STORE_FILES = ("secrets/app-secrets.env", "secrets/prod-secrets.env")
BASH = shutil.which("bash")


def _identity(pub: str) -> str:
    return f"# public key: {pub}\nAGE-SECRET-KEY-1{pub[4:].upper()}\n"


@pytest.fixture
def sandbox(tmp_path: Path) -> SimpleNamespace:
    if BASH is None:
        pytest.skip("bash not on PATH")
    # On Windows `bash` can be WSL's, which cannot see a Windows temp path.
    seen = subprocess.run([BASH, "-c", 'test -d "$1"', "_", tmp_path.as_posix()])
    if seen.returncode != 0:
        pytest.skip("this bash cannot see the test directory")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("sops", FAKE_SOPS), ("age-keygen", FAKE_AGE_KEYGEN)):
        (bin_dir / name).write_bytes(body.encode())
        (bin_dir / name).chmod(0o755)
    keys, repo = tmp_path / "keys", tmp_path / "repo"
    keys.mkdir()
    (repo / "secrets").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return SimpleNamespace(bin=bin_dir, keys=keys, repo=repo)


def _seed(
    sb: SimpleNamespace, keys_txt: str, recipients: tuple[str, ...] = (LEAKED, KEPT),
    files: tuple[str, ...] = STORE_FILES,
) -> None:
    (sb.keys / "keys.txt").write_bytes(keys_txt.encode())
    store = "API_TOKEN=ENC[x]\n" + "".join(
        f"sops_age__list_{i}__map_recipient={pub}\n" for i, pub in enumerate(recipients)
    )
    for rel in files:
        (sb.repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (sb.repo / rel).write_bytes(store.encode())
    # -f: a developer's global gitignore may cover *.env.
    subprocess.run(["git", "add", "-f", "--", *files], cwd=sb.repo, check=True)


def _run(sb: SimpleNamespace, leaked: str = LEAKED, store: str | None = None) -> tuple[int, str]:
    """The block's exit status and stderr; asserts the outer shell survived it."""
    script = BLOCK.replace("K=~/.config/sops/age", f"K='{sb.keys.as_posix()}'", 1)
    script = script.replace("<leaked-pub-key>", leaked)
    if store is not None:
        script = script.replace("STORE=('*secrets*.env')", f"STORE=({store})", 1)
    env = dict(os.environ, PATH=str(sb.bin) + os.pathsep + os.environ.get("PATH", ""))
    r = subprocess.run(
        [BASH, "-c", script + '\necho "block-rc=$?"'], cwd=sb.repo, env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert "block-rc=" in r.stdout, f"the block ended the outer shell:\n{r.stderr}"
    return int(r.stdout.rsplit("block-rc=", 1)[1].split()[0]), r.stderr


def _snapshot(sb: SimpleNamespace) -> dict[str, bytes]:
    return {rel: (sb.repo / rel).read_bytes() for rel in STORE_FILES}


def _recipients(path: Path) -> set[str]:
    return {
        ln.split("=", 1)[1]
        for ln in path.read_text(encoding="utf-8").splitlines()
        if "__map_recipient=" in ln
    }


@pytest.mark.parametrize("keys_txt", [
    _identity(LEAKED),
    _identity(LEAKED) + _identity(KEPT),   # a kept recipient's identity: it always decrypts
    _identity(LEAKED) + _identity(OTHER),  # an identity no store file lists
])
def test_the_block_completes_and_a_retry_changes_nothing(sandbox, keys_txt: str) -> None:
    _seed(sandbox, keys_txt)
    rc, err = _run(sandbox)
    assert rc == 0, err
    for rel in STORE_FILES:
        assert _recipients(sandbox.repo / rel) == {KEPT, NEW}
    assert not list((sandbox.repo / "secrets").glob("*.pre-rekey"))

    done = _snapshot(sandbox)
    rc, err = _run(sandbox)
    assert rc == 0, err
    assert _snapshot(sandbox) == done


def test_a_mistyped_leaked_key_changes_nothing(sandbox) -> None:
    _seed(sandbox, _identity(LEAKED))
    before = _snapshot(sandbox)
    rc, err = _run(sandbox, leaked=OTHER)
    assert rc == 1
    assert f"{OTHER} is not a recipient" in err
    assert _snapshot(sandbox) == before


def test_a_store_pathspec_that_matches_nothing_fails_before_any_change(sandbox) -> None:
    """A store the default pathspec misses (`.secrets/*.env.enc`) used to exit 0
    having re-keyed nothing, and the next step, retiring the leaked identity,
    then locked the operator out of a store still encrypted to it."""
    enc = (".secrets/app.env.enc",)
    _seed(sandbox, _identity(LEAKED), files=enc)
    before = (sandbox.repo / enc[0]).read_bytes()
    rc, err = _run(sandbox)
    assert rc == 1
    assert "no store files matched *secrets*.env" in err
    assert not (sandbox.keys / "keys-new.txt").exists()
    assert (sandbox.repo / enc[0]).read_bytes() == before

    rc, err = _run(sandbox, store="'.secrets/*.env.enc'")
    assert rc == 0, err
    assert _recipients(sandbox.repo / enc[0]) == {KEPT, NEW}


def test_the_store_pathspec_is_named_and_checked_before_any_side_effect() -> None:
    assert LINES[2].strip().startswith("STORE=(")
    assert 'git ls-files -- "${STORE[@]}"' in BLOCK
    assert BLOCK.index('[ -n "$FILES" ] ||') < BLOCK.index("age-keygen -o")


def test_a_keys_txt_that_cannot_decrypt_changes_nothing(sandbox) -> None:
    """Without the guard, the stand-in (like sops 3.7.3) would empty the files."""
    _seed(sandbox, _identity(OTHER))
    before = _snapshot(sandbox)
    rc, err = _run(sandbox)
    assert rc == 1
    assert "keys.txt cannot decrypt" in err
    assert _snapshot(sandbox) == before
    assert not list((sandbox.repo / "secrets").glob("*.pre-rekey"))
