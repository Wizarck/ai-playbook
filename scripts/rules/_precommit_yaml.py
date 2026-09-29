"""Insert a repo item into a consumer's `.pre-commit-config.yaml` without a YAML rewrite.

Shared by the `pre-commit-hooks` and `lint-parity-precommit` hardrules. The
block is spliced as text right after the last item of the top-level `repos:`
sequence, re-indented to the file's own style (`  - repo:`, zero-indent
`- repo:` or sample-config `-   repo:`), so comments and formatting survive.
The result is then parsed with `yaml.safe_load`; anything that does not parse,
or does not yield the new repo in `repos`, raises instead of being written.
"""
from __future__ import annotations

import re

import yaml

_REPOS_RE = re.compile(r"^repos\s*:\s*(#.*)?$")


def insert_repo(text: str, block: str, *, repo_url: str, hook_ids: list[str]) -> str:
    """Return ``text`` with ``block`` appended to its ``repos:`` sequence.

    ``block`` is written in canonical form at column 0: an optional ``#``
    comment, then ``- repo: …`` with continuation lines indented two spaces.
    Raises ``ValueError`` (with the reason) when the file cannot be safely
    extended.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"existing file is not valid YAML: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("repos"), list) or not data["repos"]:
        raise ValueError("no non-empty block-style top-level `repos:` sequence to extend")

    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if _REPOS_RE.match(ln)), None)
    if start is None:
        raise ValueError("top-level `repos:` is not in block style")
    first = next(
        (i for i in range(start + 1, len(lines))
         if lines[i].strip() and not lines[i].lstrip().startswith("#")),
        None,
    )
    if first is None or not lines[first].lstrip().startswith("-"):
        raise ValueError("`repos:` is not followed by a block sequence item")
    item = lines[first]
    ind = len(item) - len(item.lstrip(" "))
    after_dash = item[ind + 1:]
    off = ind + 1 + len(after_dash) - len(after_dash.lstrip(" "))

    last = first
    for k in range(first + 1, len(lines)):
        ln = lines[k]
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        if not ln[0].isspace() and not ln.startswith("-"):
            break  # next top-level key ends the sequence
        last = k

    out: list[str] = []
    for bl in block.strip("\n").splitlines():
        if bl.startswith("- "):
            out.append(" " * ind + "-" + " " * (off - ind - 1) + bl[2:])
        elif bl.startswith("#"):
            out.append(" " * ind + bl)
        else:
            out.append(" " * off + bl[2:])

    new_text = nl.join(lines[: last + 1] + out + lines[last + 1:])
    if text.endswith(("\n", "\r")) or last + 1 >= len(lines):
        new_text += nl

    try:
        new_data = yaml.safe_load(new_text)
    except yaml.YAMLError as exc:
        raise ValueError(f"insertion would produce invalid YAML: {exc}") from exc
    repos = new_data.get("repos") if isinstance(new_data, dict) else None
    ok = isinstance(repos, list) and any(
        isinstance(r, dict) and r.get("repo") == repo_url
        and set(hook_ids) <= {h.get("id") for h in r.get("hooks") or [] if isinstance(h, dict)}
        for r in repos
    )
    if not ok:
        raise ValueError("insertion did not yield the new repo as a `repos` item")
    return new_text
