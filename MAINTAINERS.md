# Maintainers

| Role | Name | Contact | Scope |
|---|---|---|---|
| Owner / admin | Arturo Ramírez | 23051550+Wizarck@users.noreply.github.com | Everything. Final call on schema, specs, breaking changes. |

## Contribution

Until the first external dev lands (0–3 months horizon), Arturo is the single maintainer. RFC / governance flow is defined in [docs/contributing.md](docs/contributing.md) (populated in T14). Breaking changes (schema bump, dispatcher semantics) require an RFC under [rfcs/](rfcs/).

## Escalation

- Blocking issue in a consuming repo (`consumer-c-legacy`, `consumer-d`): open an issue in the consumer repo AND tag the playbook commit/tag that's pinned.
- Security / secret exposure: do NOT open a public issue. Email the maintainer directly.
