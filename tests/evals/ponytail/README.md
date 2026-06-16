# Ponytail eval harness

A 3-arm comparison that measures whether the ponytail skill actually produces
**less code** — and measures it *honestly*.

## The arms

| Arm | System prompt | Why |
|-----|---------------|-----|
| `baseline` | *(none)* | Context only — what an unguided agent writes. |
| `minimal`  | `Write only the code… as minimal as possible.` | The confound. A generic "be terse with code" instruction already cuts lines. |
| `ponytail` | `<minimal>\n\n<skills/ponytail/SKILL.md body>` | The treatment. |

**The honest delta is `ponytail` vs `minimal`, not `ponytail` vs `baseline`.**
Claiming ponytail saves N% vs baseline conflates the skill with the generic
"write minimal code" instruction. The same discipline the playbook applies to
the [caveman eval](../caveman/README.md) (caveman vs `Answer concisely.`).

## The metric

Where caveman measures **output tokens** (prose compression), ponytail measures
**code lines (LOC)** — the count of non-blank lines inside fenced ``` blocks in
the deliverable (`run.count_code_lines`). Ponytail is about the size of the
code, not the chattiness of the prose.

## Running

```bash
# No API calls — just list what would run:
python tests/evals/ponytail/run.py --dry-run

# Run all prompts × all arms against the LiteLLM proxy, write a snapshot:
python tests/evals/ponytail/run.py --emit-snapshot

# Render a snapshot to a markdown LOC table:
python tests/evals/ponytail/report.py snapshots/results.json
```

Requires the LiteLLM proxy reachable at `$LITELLM_BASE_URL` with a
`code_generation` task class wired (edit `run._default_llm_call` if your proxy
names it differently).

## Files

- `run.py` — arm construction + suite runner + LOC counter.
- `report.py` — offline markdown LOC-table renderer with the honest delta.
- `prompts/en.txt` — small coding tasks where stdlib/native/one-line wins.
- `snapshots/` — written by `--emit-snapshot` (gitignored output).

Harness logic is covered (no API) by
[`tests/test_ponytail_evals.py`](../../test_ponytail_evals.py).
