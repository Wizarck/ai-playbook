# hygiene-ratchet — gate the count without inflating the severity

## Why

`repo-hygiene` is permanently non-blocking: every check is S3, and `BLOCKING` is
`("S1", "S2")`. The consumer's CI comment promised to "raise the severities once
ledger item 15 is resolved". Item 15 landed, the rule reports zero findings, and
the promise turned out to be the wrong instrument.

Relabelling S3 findings as S2 so a step fails buys a gate at the price of the
severity scale meaning anything. None of these findings is a correctness defect;
saying they are, so that CI goes red, is how a team learns to wave through the
S2s that do matter.

The confusion is between two questions that only look like one:

- **How bad is this finding?** → severity. S3, correctly, and permanently.
- **Has this got worse?** → a baseline. Zero today, and it must stay zero.

## What changes

`check --max N`, matching `sweep_scan.py check --max` exactly so a consumer
learns one idea rather than two:

- exit 1 above the baseline, with the count and the real fixes named;
- below it, say so — ratchets only ratchet if somebody lowers them, and nobody
  lowers a number they were never told had slack;
- a negative baseline is refused: a ceiling that can never be met is a job that
  is red forever, and a job that is red forever gets switched off;
- **opt-in.** Without `--max` nothing changes for any existing consumer.

## Acceptance

1. A finding that is S3 (and therefore never blocking) IS gated by `--max 0`.
2. `--max` at the current count passes.
3. Below the baseline it passes and says to lower it.
4. A negative `--max` exits 2.
5. Without `--max`, behaviour is byte-for-byte what it was.

All five verified. 60 tests.

## Non-goals

Changing any severity, anywhere. That is the whole point.
