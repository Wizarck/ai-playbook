# cross-language-tooling.md

> **Status**: v1.0.0. New in ai-playbook v0.10.0. Codifies the convention
> for shipping non-primary-language tools (typically Python services /
> scripts) inside a Turborepo TS monorepo or a Python-primary monorepo,
> without forcing the foreign language to pretend it's a workspace.
>
> **Enforcement**: 📋 spec-only — see [enforcement-status.md](enforcement-status.md).
> No automated linter detects departures; reviewer rejects on PR if a
> proposal violates the convention without explicit ADR justification.

## 1. Why this spec

Most ai-playbook consumer projects are single-language by primary intent
(TypeScript monorepo, Python monorepo, Go monorepo, …). Reality intrudes:

- **consumer-e** (Python primary) needs an OpenBB sidecar (Python ML
  service that doesn't fit the FastAPI app's deps).
- **consumer-c** (TypeScript primary, Turborepo) needs a RAG proxy
  (Python FastAPI service translating LightRAG to the canonical
  contract) plus a corpus ingestion package (Python scripts piping
  authoritative sources into the RAG vector store).
- **consumer-d-rag** (Python primary) integrates Hindsight (TypeScript MCP
  server).

The choice is structural: **does the foreign-language code live inside
the primary monorepo's workspace structure, or as a peer subdirectory
with its own toolchain?**

This spec codifies the second answer (peer subdirectory) and explains
why.

## 2. The pattern: `tools/<name>/` peer subdirectory

### 2.1 Directory layout

```
<consumer-root>/
├── apps/                        # primary-language workspaces (Turborepo / poetry)
│   ├── api/
│   ├── web/
│   └── ...
├── packages/                    # shared primary-language packages
│   ├── shared-types/
│   └── ...
├── tools/                       # non-primary-language tools (peer to apps/)
│   ├── rag-proxy/               # Python FastAPI service
│   │   ├── pyproject.toml
│   │   ├── src/rag_proxy/
│   │   ├── tests/
│   │   ├── Dockerfile           # multi-stage python:3.12-slim
│   │   ├── docker-compose.example.yml
│   │   └── .env.example
│   ├── rag-corpus/              # Python ingestion scripts
│   │   ├── pyproject.toml
│   │   ├── src/rag_corpus/
│   │   ├── tests/
│   │   └── scripts/run_all.sh
│   └── README.md                # one-paragraph explanation per tool
└── .github/workflows/
    └── python-tools.yml         # separate CI workflow
```

### 2.2 What goes in `tools/`

**Yes**: stateless services / libraries / scripts that:

- Bridge a third-party to the canonical contract (rag-proxy → LightRAG).
- Run as a sidecar (OpenBB compute, ML inference).
- Run as ingestion / migration / seed scripts (rag-corpus).
- Are deployed independently (own Dockerfile, own deploy cadence).

**No**: anything that's a workspace-shaped peer of `apps/api/` or
`apps/web/`. If it walks like a workspace and quacks like a workspace,
make it a workspace under `apps/` even if the language differs.

### 2.3 Standalone toolchain per tool

Each `tools/<name>/` has its own complete toolchain:

| File | Purpose |
|---|---|
| `pyproject.toml` (or equivalent) | Deps + lint + type-check + test config |
| `src/<name>/` | Source root (matches package name, snake_case) |
| `tests/` | Pytest tree mirroring `src/` |
| `Dockerfile` | Multi-stage build; `python:3.12-slim` for Python |
| `docker-compose.example.yml` | Local-dev / VPS-deploy template |
| `.env.example` | Documented env vars for the service |
| `README.md` | Quickstart + deployment notes |

The tool does **not** appear in the root `package.json` workspaces, the
root `pyproject.toml` dependencies, or the root `turbo.json`. It is
peer to those, not under them.

### 2.4 CI: separate workflow with path filter

```yaml
# .github/workflows/python-tools.yml
on:
  pull_request:
    paths: ["tools/rag-proxy/**", "tools/rag-corpus/**", ".github/workflows/python-tools.yml"]

jobs:
  rag-proxy:
    name: rag-proxy (lint + test)
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: tools/rag-proxy } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: ruff check src/ tests/
      - run: mypy --strict src/
      - run: pytest --cov=src/rag_proxy --cov-fail-under=85
```

The path filter ensures TS-only PRs don't pay the Python install cost,
and Python-tool PRs don't run the full Turborepo CI matrix.

## 3. Why this beats workspace-fication

### 3.1 Workspace-fication fails on toolchain mismatch

`pnpm` doesn't run `pip`. `turbo` doesn't understand `pyproject.toml`.
Forcing Python under `apps/foo/` in a Turborepo means writing
npm-script wrappers (`"lint": "ruff check ."`) that pretend Python is
a TS workspace. Reviewers grep for `"build": "tsc"` and find Python
shims. CI matrix gets weird (skip patterns, conditional shells).

### 3.2 Workspace-fication couples deploy cadence

A TS workspace's release rides the monorepo's release pipeline. A
Python sidecar likely deploys to a different host (VPS Docker, k8s,
Lambda) on a different schedule. Workspace-fication makes the foreign
service inherit a release process it doesn't actually use.

### 3.3 The `tools/` convention is widely understood

`tools/` as a peer to `apps/` in a multi-language monorepo is convention
across many open-source projects (Bazel monorepos, Google internal,
many polyglot dev shops). New contributors recognise it immediately.

## 4. The escape hatch: when to break the rule

### 4.1 Build-time codegen

If a Python script generates types consumed by a TS workspace at build
time (e.g. proto codegen, OpenAPI schema → TS types), the script can
live inside the consumer workspace's `scripts/` directory and be
invoked from a `package.json` script. The consumer is responsible for
ensuring CI has Python available.

### 4.2 Tightly-coupled per-workspace tooling

If the script is *only* meaningful to one workspace (e.g. a workspace-
specific seed loader, a workspace-specific migration validator), put it
in `apps/<workspace>/scripts/` not `tools/`. The boundary is "would two
different workspaces consume this?".

## 5. Anti-patterns

### 5.1 Faking Python as a TS workspace

Adding a `package.json` to a Python service with scripts that shell out
to `pip` / `pytest` is **rejected**. The pretence costs more than
"there's a Python thing in `tools/`" honesty.

### 5.2 Mixing primary-language code into `tools/`

`tools/` is for *non-primary-language* code. Don't move pure-TS
ingestion scripts into `tools/foo-ingest/` to "isolate them". Use
`apps/<workspace>/scripts/` or `packages/foo-ingest/`.

### 5.3 Reaching across language boundaries via filesystem

A Python tool that reads `apps/api/dist/` build output, or a TS app
that reads `tools/rag-proxy/.cache/`, breaks isolation. Cross-language
contracts go over the network (HTTP, gRPC, queue) or via explicit
codegen artefacts in `packages/<contract>/`.

## 6. Reference implementations

- **consumer-c** Wave 1.8 (`m2-ai-yield-corpus`, PR #88, 2026-05-06):
  introduced `tools/rag-proxy/` (FastAPI, ~750 LOC + 60 tests, mypy
  strict, ruff, 93.35% coverage) and `tools/rag-corpus/` (4 ingestion
  scripts: USDA + EU 1169/2011 + Escoffier + CIAA-gated). Net
  TypeScript LOC change in `apps/api/`: 0. CI workflow at
  `.github/workflows/python-tools.yml`.

- **consumer-e** v1 (planned R4 slice `openbb-sidecar-container`):
  will introduce `tools/openbb-sidecar/` for the OpenBB Platform
  compute that doesn't fit the apps/api Python deps tree. Same pattern
  even though the primary language is also Python (the sidecar's deps
  set is too large to merge into apps/api).

## 7. Cross-references

- [release-management.md](release-management.md) §2 (branch model — `tools/<name>/` work follows the same `slice/<change-id>` discipline)
- [event-and-data-patterns.md](event-and-data-patterns.md) §7 (stateless proxy + stateful caller — the *behavioural* pattern that often informs why a `tools/` service exists)
- [bmad-openspec-bridge.md](bmad-openspec-bridge.md) §3.1 (slicing artefact rows naming `tools/<name>/` paths in the "Components" column)
- [enforcement-status.md](enforcement-status.md) (live adoption matrix)
