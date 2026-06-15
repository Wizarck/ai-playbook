# Runbook: set up graphify in a project

> **When to use this runbook.** A repo commits (or wants to commit) a
> graphify knowledge graph under `graphify-out/`, and you want every
> developer's clone to share it without leaking machine-specific paths
> or colliding on the multi-MB `graph.json`. Covers install, the
> one-time per-clone hook, verification, freshness, and uninstall.

## Background

graphify commits a code knowledge graph the whole team shares (see
[../concepts/graphify.md](../concepts/graphify.md)). For that to work across
machines two things must hold: the `graphifyy` version is recent enough to store
relative paths, and each clone has registered the `graph.json` union-merge
driver. The [graphify-adoption rule](../rules/graphify-adoption.rule.md) is the
enforcer; this runbook is the operator walkthrough.

## 1. Install the CLI (per machine)

```
uv tool install "graphifyy>=0.8.31"     # or: pipx install "graphifyy>=0.8.31"
graphify --version                       # confirm >= 0.8.31
```

The `>=0.8.31` floor matters: earlier versions baked absolute machine paths into
the graph, making the committed artifacts non-portable.

## 2. Register the merge driver + hooks (per clone)

```
graphify hook install
```

This writes the shared `.gitattributes` mapping for `graphify-out/graph.json`
AND registers the matching `merge.*.driver` in this clone's `.git/config`, plus
post-commit / post-checkout hooks. Without it, two developers committing graph
updates in parallel hand-resolve a multi-MB JSON conflict.

## 3. Apply the gitignore hygiene (once, committed)

```
python .ai-playbook/scripts/rules/graphify-adoption.rule.py apply
```

Appends the per-machine / per-run ignore entries (`.graphify_python`,
`.graphify_uncached.txt`, `cost.json`, `cache/`, dated snapshot dirs) under a
managed header. If those files were already tracked, untrack them once (kept on
disk):

```
git rm -r --cached graphify-out/.graphify_python graphify-out/.graphify_uncached.txt \
  graphify-out/cost.json graphify-out/cache graphify-out/????-??-??/
```

## 4. Verify

```
python .ai-playbook/scripts/rules/graphify-adoption.rule.py validate   # expect exit 0
```

Exit 1 lists what is missing (gitignore entries or the merge-driver mapping). A
`graphifyy` older than 0.8.31 or absent is reported as an advisory.

## 5. Keep the graph fresh

```
graphify update .     # re-parse changed files (AST-only, no token cost)
```

Run after code changes (a post-commit hook from step 2 can automate this).
Commit the updated `graphify-out/` portable artifacts alongside the code.

## Troubleshooting

- **`graphify: command not found`** — the CLI is not installed on this machine
  (step 1). The committed graph is still readable, but you cannot query or
  regenerate it; agent hooks that nag "run graphify" are then noise.
- **Merge conflict on `graph.json`** — `graphify hook install` was not run in
  this clone (step 2); the union-merge driver is not registered locally.
- **Diffs full of `cache/` churn or a duplicate dated dir** — the gitignore
  hygiene (step 3) was not applied; untrack and ignore.

## Uninstall

```
graphify hook uninstall          # if supported by your version
git rm -r --cached graphify-out  # stop tracking the graph
```

Then remove the graphify block from `.gitignore` and the `.gitattributes` line.

## See also

- [../concepts/graphify.md](../concepts/graphify.md) — what the graph is + graphify vs RAG.
- [../rules/graphify-adoption.rule.md](../rules/graphify-adoption.rule.md) — the enforced invariants.
- [../../skills/graphify/SKILL.md](../../skills/graphify/SKILL.md) — agent usage.
