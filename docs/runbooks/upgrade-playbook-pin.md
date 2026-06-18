---
schema: runbook/v1
slug: upgrade-playbook-pin
description: Bump a consumer repo's .ai-playbook submodule pin to a newer tag and re-activate everything in one pass.
audience: developer
estimated_time: 10-20 min
prerequisite_runbooks: [onboard-new-project]
last_validated: "2026-06-17"
---

# Runbook: upgrade the .ai-playbook pin in a consumer

> **When to use this runbook.** A consumer repo already vendors `.ai-playbook/`
> as a submodule and you want to move it to a newer semver tag *and* re-activate
> the playbook-owned artefacts (skills, managed blocks, MCP render, feature
> toggles) so the working tree matches the new tag. This is the one procedure
> that ties **bump → reconcile → verify** together; doing only the `git checkout`
> leaves skills and auto-managed blocks stale.

## Background

The playbook ships on a **pull model** (v0.19.0+): a new tag is published and
each consumer bumps on its own schedule — nothing reaches into consumer repos.
Two halves must both happen on a bump:

1. **Bump** — advance the submodule pin to the new tag and re-pin `inherits_from`
   in `AGENTS.md` (the schema requires they match — see the
   [update-playbook rule](../rules/update-playbook.rule.md)).
2. **Reconcile** — re-run the single "door" (`bootstrap.py --update`) so skills,
   auto-managed blocks, MCP config and feature toggles are regenerated from the
   new tag. This reuses the same machinery as onboarding; there is no separate
   "upgrade" script to maintain.

## 1. Bump the pin (assisted)

```
python .ai-playbook/scripts/rules/update-playbook.rule.py apply --execute
```

This fetches tags, checks out the latest semver tag, re-pins `inherits_from` in
`AGENTS.md`, and stages both. It deliberately does **not** commit — the
reconcile in step 2 produces more changes that belong in the same commit. Add
`--dry-run` to preview, or drop `--execute` to print the manual plan instead.

Manual equivalent:

```
cd .ai-playbook && git fetch --tags && git checkout vX.Y.Z && cd ..
git add .ai-playbook
# then edit AGENTS.md frontmatter: inherits_from … @vX.Y.Z
```

## 2. Reconcile the working tree

```
python .ai-playbook/scripts/bootstrap.py --update
```

Re-materialises skills into the mirrors, refreshes every `auto-managed` block,
re-renders MCP config, and re-applies the enabled feature toggles. Idempotent —
safe to run repeatedly. New **opt-in** features in the tag (e.g. `graphify`)
are materialised but stay off until you enable them; default-on features
(caveman, ponytail) are reconciled automatically.

## 3. Verify health (and self-heal deps)

```
cd .ai-playbook && python -m scripts.doctor
```

Expect `0 fail`. If it reports `pyyaml`/`jsonschema` not importable (common when
the consumer venv does not list them), self-heal in place:

```
cd .ai-playbook && python -m scripts.doctor --install-deps
```

That editable-installs the playbook (`pip install -e`, with an `ensurepip`
fallback) so the hard deps resolve, then re-runs the checks.

## 4. (Optional) graphify

If the consumer uses graphify, bootstrap the external CLI + per-clone hooks:

```
python -m scripts.graphify setup
```

See the [graphify setup runbook](graphify-setup.md) for the manual steps.

## 5. Validate the pin and commit

```
python .ai-playbook/scripts/rules/update-playbook.rule.py validate   # expect exit 0
python .ai-playbook/scripts/rules/cleanup-on-bump.rule.py validate    # zombie sweep
git commit -m "chore(playbook): bump ai-playbook <old> → <new>"
```

Commit the submodule pointer, the re-pinned `AGENTS.md`, and the reconciled
managed files together so the pin and its activated state never diverge.

## One-time: untrack rendered MCP configs (≥ v0.19.18)

`.mcp.json` and `.gemini/settings.json` are LOCAL build artifacts (the
base+project+**personal** merge) and are gitignored by the playbook so personal/
tenant servers never land in a committed file. If your repo committed them before
v0.19.18, untrack them once (kept on disk) and re-render:

```
git rm --cached .mcp.json .gemini/settings.json
python .ai-playbook/scripts/mcp/render.py        # regenerate locally
git commit -m "chore(mcp): untrack rendered MCP configs (now local build artifacts)"
```

The committed source of truth stays `mcp-servers.project.yaml` (no personal) +
`~/.config/mcp-servers.yaml` (personal, local-only). On a fresh clone, run the
render once to materialise the local configs.

## Troubleshooting

- **`doctor` fails on jsonschema/pyyaml** — run step 3 with `--install-deps`, or
  create a venv that has `pip` (`python -m venv .venv`) first.
- **MCP servers missing after a fresh clone** — `.mcp.json` is gitignored now;
  run `python .ai-playbook/scripts/mcp/render.py` once to regenerate it locally.
- **Skills look stale after the bump** — step 2 was skipped; `bootstrap.py
  --update` is what re-materialises them, not the `git checkout`.
- **Submodule shows dirty after enabling a feature** — feature state files
  (`caveman.json`, `graphify.json`, `ponytail.json`) live at the submodule root
  and are gitignored by the playbook; if your checkout predates that, update the
  pin.
