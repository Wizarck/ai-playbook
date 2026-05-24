# Caveman 3-arm eval harness

Honest evaluation of the caveman skill: does it cut tokens *beyond* what
generic terseness already buys? The harness compares three arms against
the same prompt set:

| Arm           | System prompt                                  |
|---------------|------------------------------------------------|
| `baseline`    | (none)                                          |
| `terse`       | `Answer concisely.`                             |
| `caveman`     | `Answer concisely.\n\n{skills/caveman/SKILL.md body}` |

The **honest delta** is `caveman vs terse`, NOT `caveman vs baseline`.
Comparing against baseline conflates the caveman skill with generic
terseness — that hides the real value-add. Discipline borrowed from the
upstream JuliusBrussee/caveman `evals/` harness.

## Files

- `run.py` — orchestrator. Reads prompts, invokes each arm via
  `scripts._llm.call`, writes JSON results.
- `prompts/en.txt` — ~10 representative prompts (one per line).
- `snapshots/` — committed once the LiteLLM proxy is up. CI reads from
  here without re-running the API calls.
- `report.py` — offline tokenizer (tiktoken approximation of Claude
  tokenizer) that turns a snapshot into a markdown table.

## Running it

Prerequisite: LiteLLM proxy reachable at `$LITELLM_BASE_URL`
(default `http://localhost:4000`). The harness routes through
[scripts/_llm.py](../../../scripts/_llm.py), so the proxy's router config
decides the actual model (task_class = `doc_writing_edit`).

```bash
# Dry run — count prompts + arms, don't call the API
python tests/evals/caveman/run.py --dry-run

# Run all arms × all prompts, save snapshot
python tests/evals/caveman/run.py --emit-snapshot

# Re-emit the markdown table from an existing snapshot
python tests/evals/caveman/report.py tests/evals/caveman/snapshots/results.json
```

## Adding prompts

Append a new line to `prompts/en.txt`. The harness auto-discovers all
non-comment, non-blank lines.

## Adding arms

The arms are defined inline in `run.py` (`ARMS` dict). Add an entry with
the system prompt; the harness picks it up automatically.

## Why no snapshots in this commit?

Snapshots require real API spend. They get committed in a follow-up once
the LiteLLM proxy has run the suite end-to-end. The Phase G commit ships
the harness *infrastructure* only; the snapshots get added as a separate
data commit so the size delta is clean.
