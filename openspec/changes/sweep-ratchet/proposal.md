# sweep-ratchet — freeze the orphan count, and name the exceptions

## Why

`enforcement-status.md` has held code-entropy at 🟡 for three releases with one
stated reason: **no axis publishes a ratchet number CI freezes.** Without it a
cleanup campaign undoes itself quietly — you remove ten orphans, fifteen appear
over the next quarter, and nothing ever fails.

The decidable axes (3, 4, 5) do not need a ratchet: `repo-hygiene` and
`capability-wiring` already block at zero findings. The gap is axes 1 and 2,
where `sweep_scan.py` is report-only by design.

## The split that makes a per-PR gate legitimate

The taxonomy says these axes are on-demand and monthly, and scanning entropy more
often than it changes is how a detector gets disabled. That applies to
**adjudication** — which needs a model and a human — and not to **counting**,
which is deterministic and takes 27 seconds on a 1674-file consumer.

So the ratchet counts on every pull request and adjudicates never. Catching a new
orphan on the PR that creates it is worth far more than catching it a month
later: the author still remembers why the file is there, and the fix is usually
to finish wiring it rather than to delete it.

## What changes

**`allow`, with a mandatory reason.** Some files are alive by a mechanism no
import graph can see — a webpack `resolve.alias`, a `COPY` in a Dockerfile, a
plugin entry point. Measured on the consumer: 4 of 14 candidates. Re-reporting
them every month trains the reader to skim past real findings, and a ratchet
cannot reach zero while they are counted.

The `reason` is required, and that is the whole difference between an exception
and a suppression: `"webpack resolve.alias in next.config.js:110-112"` is a fact
the next reader can re-verify; a bare path is a file someone silenced,
indistinguishable a year later from one that genuinely rotted.

**A stale `allow` entry fails the build**, borrowed from `repo-hygiene`'s
contract. An exception that stopped covering anything means the file was deleted,
renamed, or finally wired up — all three deserve an edit. Without this the allow
list becomes the unvisited graveyard a quarantine directory would have been,
except that this one silently shrinks what the scan can see.

**`sweep_scan.py check --max N`.** Exit 1 above the baseline, listing the
offending paths. And when the count is BELOW the baseline it says so, loudly:
ratchets only ratchet if somebody lowers them, and nobody lowers a number they
were never told had slack.

The failure message names the three real fixes — wire it in, delete it via
`sweep_execute.py`, or add an `allow` entry naming the mechanism — and states
that raising the baseline is not among them.

## Acceptance

1. An allowed path is not a finding.
2. An `allow` entry with no reason is a config error (exit 2).
3. A stale `allow` entry breaks the build (exit 2).
4. `check` passes at the baseline, fails above it, and reports the offenders.
5. Below the baseline, `check` passes AND tells the operator to lower it.
6. `check` refuses to publish a number when the probe gate fails — a count from a
   broken resolver is noise with an integer attached.

All six verified. 45 tests in `test_sweep_scan.py`.

## Non-goals

Flipping `enforcement-status` to ✅. The mechanism existing is not the same as a
consumer freezing a number with it; that flip waits until a real CI is running
the gate, which is the discipline this campaign has used throughout.
