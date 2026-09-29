"""Tests for scripts/bootstrap_gh_project.py — gh failure → RuntimeError contract."""
from __future__ import annotations

import json
import subprocess

import pytest

from scripts import bootstrap_gh_project as bgp


def _fake_gh(monkeypatch: pytest.MonkeyPatch, *, org_ok: bool) -> None:
    """Mimic gh: a GraphQL error prints the body on stdout, 'gh: ...' on stderr, exit 1."""
    def fake_run(cmd, *args, input=None, check=False, **kwargs):  # type: ignore[no-untyped-def]
        query = json.loads(input)["query"]
        if "user(login" in query or not org_ok:
            out = json.dumps({"data": {"user": None}, "errors": [{"type": "NOT_FOUND"}]})
            if check:
                raise subprocess.CalledProcessError(1, cmd, output=out, stderr="gh: Could not resolve to a User")
            return subprocess.CompletedProcess(cmd, 1, out, "gh: Could not resolve to a User")
        out = json.dumps({"data": {"organization": {"projectV2": {"id": "P1", "number": 1, "title": "T"}}}})
        return subprocess.CompletedProcess(cmd, 0, out, "")
    monkeypatch.setattr(bgp.subprocess, "run", fake_run)


def test_lookup_project_falls_through_to_org_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_gh(monkeypatch, org_ok=True)
    proj = bgp.lookup_project("acme-org", 1)
    assert proj.id == "P1"


def test_gh_graphql_failure_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_gh(monkeypatch, org_ok=False)
    with pytest.raises(RuntimeError, match="NOT_FOUND"):
        bgp._gh_graphql("query { user(login: \"x\") { id } }")


def test_gh_missing_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("gh")
    monkeypatch.setattr(bgp.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="gh CLI not found"):
        bgp._gh(["repo", "view"])
