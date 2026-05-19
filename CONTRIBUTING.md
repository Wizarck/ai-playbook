# Contributing

PRs welcome. Issues welcome. This is a solo-maintained, MIT-licensed project — keep it that way by following a few simple rules:

- **Commits**: [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
- **Style**: `ruff check` + `ruff format` (config in `pyproject.toml`).
- **Tests**: every script ships with `tests/test_<name>.py`. CI red blocks merge.
- **Before opening a PR**: `pre-commit run --all-files` must pass.
- **Breaking changes** (schema bumps, dispatcher semantics, exit-code changes, renaming public scripts): file an RFC under [`rfcs/`](rfcs/) — template in `rfcs/README.md`. Everything else: direct PR.
- **Security issues**: email the maintainer directly, do not open a public issue.

**Maintainer**: Arturo Ramírez (`23051550+Wizarck@users.noreply.github.com`).
