---
schema: runbook/v1
slug: docs-build-deploy
description: Build the static documentation site locally with mkdocs-material + Pagefind static-index, validate it strict, and (optionally) preview on http://localhost:8000.
audience: developer
estimated_time: 5 min
last_validated: "2026-05-19"
---

# Build and deploy the docs site

## Outcome

A static site directory at `site/` containing the rendered HTML + Material assets + a Pagefind index (`site/pagefind/`). The site is verified to build under `mkdocs build --strict` (exit 0) and serves the same content GitHub Pages publishes on push to `main`.

## When to use this

Before opening a PR that touches `docs/`, `README.md`, or `mkdocs.yml`. Also when validating that a doc edit does not break the published site (broken navigation entries, missing files, malformed Mermaid).

Skip when the change is scoped to source code only and does not modify any markdown.

## Prerequisites

- Python 3.11+ and the playbook installed as an editable package: `pip install -e .`
- `mkdocs` + `mkdocs-material` installed: `pip install mkdocs mkdocs-material`.
- (Optional, for Pagefind) Node.js 18+ on `PATH` so `npx pagefind` is available.

## Steps

### 1. Strict mkdocs build

```bash
python -m mkdocs build --strict
```

Expected tail of output:

```
INFO    -  Documentation built in 1.78 seconds
```

Strict mode is configured to ignore link references outside `docs/` (see `mkdocs.yml` `validation:` block) because many docs intentionally cite `scripts/`, `schemas/`, or `.github/` paths. Those references are validated separately by `scripts/check_link_integrity.py`.

If you see `Aborted with N warnings in strict mode`, read the warnings — they are either:

- a missing target file (add the file or remove the reference);
- a malformed Mermaid block (verify the fence is ` ```mermaid `, not ` ```mermaid ` with trailing spaces); or
- a nav entry pointing at a file that no longer exists (sync `mkdocs.yml`).

### 2. Build the Pagefind static search index

```bash
npx pagefind --site site
```

Expected tail:

```
[Pagefind] Indexed N pages
[Pagefind] Indexed N words
[Pagefind] Indexed N filters
[Pagefind] Indexed N sorts
[Pagefind] Finished in <1s
```

Pagefind generates `site/pagefind/` — a static, JS-side, fuzzy-matching search index. The mkdocs-material in-memory search continues to work without Pagefind; Pagefind is an enhancement for sites large enough that the in-memory index degrades.

If `npx pagefind` is not available, skip this step and document the gap in the PR description. The site is still publishable without Pagefind.

### 3. (Optional) Preview locally

```bash
python -m mkdocs serve
```

Open <http://localhost:8000> in a browser. Edit a markdown file; the page auto-reloads. Stop with `Ctrl+C`.

## Validation

The strict build (`exit 0`) is the validation gate. A green build means:

- Every nav entry resolves to a real file.
- Every internal link inside `docs/` resolves.
- Every Mermaid fence parses.

Cross-tree links (to `scripts/`, `schemas/`, `.github/`) are validated by `python scripts/check_link_integrity.py docs/` — run it as a second pass.

## Rollback

The build is purely local until the deployment workflow (`.github/workflows/docs-deploy.yml`) runs on `main`. If a bad build merges:

1. Revert the offending commit on `main`.
2. The next push triggers a fresh deploy.

No manual rollback step required — GitHub Pages always serves the latest `gh-pages` branch tip.

## See also

- [../concepts/enforcement-layers.md](../concepts/enforcement-layers.md) — the L3 workflow `.github/workflows/docs-deploy.yml` is one of the server-side gates.
- [`scripts/build_docs.sh`](../../scripts/build_docs.sh) — the one-shot helper that runs steps 1 + 2 together.
