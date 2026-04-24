"""Shared Hindsight HTTP client for inject_context.py + retain_lesson.py.

Hindsight runs behind Cloudflare Access (machine-to-machine service auth via
``CF-Access-Client-Id`` + ``CF-Access-Client-Secret`` headers) and exposes the
canonical FastAPI surface documented at ``<HINDSIGHT_URL>/openapi.json``:

    POST /v1/default/banks/{bank_id}/memories         — RetainRequest
    POST /v1/default/banks/{bank_id}/memories/recall  — RecallRequest
    GET  /v1/default/banks                            — list banks
    GET  /health                                       — liveness

Per [`specs/memory-hierarchy.md`](../specs/memory-hierarchy.md) the bank_id
matches the project slug (`consumer-c-legacy`, `consumer-d`, `consumer-b`, …) — see
[`specs/env-vars.md`](../specs/env-vars.md) for the env var contract.

This client is **stdlib-only** (no SDK dep): consumers run it from
SessionStart hooks where minimising the dep graph matters.

Auth resolution
---------------
The client tries CF Access service auth first (current consumer-d deployment),
falls back to bearer token (legacy / future direct-network deploy).

    CF_ACCESS_CLIENT_ID + CF_ACCESS_CLIENT_SECRET → CF Access headers
    HINDSIGHT_API_KEY                              → Authorization: Bearer

If neither is present the call raises ``HindsightAuthMissing``.

Bank-id resolution order (least → most specific):
    1. ``HINDSIGHT_BANK_ID`` env var (catch-all default).
    2. ``bank_id`` arg passed by the caller.

Endpoint resolution: ``HINDSIGHT_URL`` env var, no default. Required.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

# Force UTF-8 stdio.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


DEFAULT_TIMEOUT_SECS = 45.0
"""Default Hindsight HTTP timeout. Recall is the slow path — semantic search
+ scoring on a cold call can take 30+ seconds against the production
deployment. 45 s gives one retry margin without breaking the SessionStart
hook envelope (which should configure ``timeout: 60`` to match)."""

USER_AGENT = "ai-playbook/_hindsight"


class HindsightError(Exception):
    """Base for all Hindsight client errors."""


class HindsightAuthMissing(HindsightError):
    """No CF Access creds AND no HINDSIGHT_API_KEY in the environment."""


class HindsightUrlMissing(HindsightError):
    """HINDSIGHT_URL env var is unset."""


@dataclass
class HindsightCreds:
    """Resolved credentials. Either CF Access pair OR bearer api_key is set."""

    url: str
    cf_client_id: str | None = None
    cf_client_secret: str | None = None
    api_key: str | None = None

    @property
    def auth_method(self) -> str:
        if self.cf_client_id and self.cf_client_secret:
            return "cf-access"
        if self.api_key:
            return "bearer"
        return "none"

    def headers(self) -> dict[str, str]:
        h: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        if self.cf_client_id and self.cf_client_secret:
            h["CF-Access-Client-Id"] = self.cf_client_id
            h["CF-Access-Client-Secret"] = self.cf_client_secret
        elif self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        # If a deployment requires both layers (CF Access + Bearer to the
        # upstream API), the caller can extend this dict — for now consumer-d's
        # deployment terminates auth at the CF Access layer.
        return h


def load_credentials(env: dict[str, str] | None = None) -> HindsightCreds:
    """Resolve URL + auth from the environment.

    Raises ``HindsightUrlMissing`` if HINDSIGHT_URL is unset, and
    ``HindsightAuthMissing`` if neither CF Access pair nor bearer key is set.
    """
    e = env if env is not None else os.environ
    url = (e.get("HINDSIGHT_URL") or "").strip()
    if not url:
        raise HindsightUrlMissing("HINDSIGHT_URL env var is unset")

    cf_id = (e.get("CF_ACCESS_CLIENT_ID") or "").strip() or None
    cf_secret = (e.get("CF_ACCESS_CLIENT_SECRET") or "").strip() or None
    api_key = (e.get("HINDSIGHT_API_KEY") or "").strip() or None

    if not (cf_id and cf_secret) and not api_key:
        raise HindsightAuthMissing(
            "neither CF_ACCESS_CLIENT_ID+SECRET nor HINDSIGHT_API_KEY are set"
        )

    return HindsightCreds(
        url=url.rstrip("/"),
        cf_client_id=cf_id,
        cf_client_secret=cf_secret,
        api_key=api_key,
    )


@dataclass
class HttpResult:
    """Outcome of a single HTTP call. Distinguishes 5 shapes."""

    ok: bool
    status: int | None
    body: Any  # parsed JSON when ok=True
    raw: str  # raw body text for debugging
    reason: str  # "ok" | "degraded:<cause>" | "error:<cause>"


def _post_json(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    timeout: float = DEFAULT_TIMEOUT_SECS,
) -> HttpResult:
    """POST a JSON body. Never raises — encodes failure into the result."""
    payload = json.dumps(body).encode("utf-8")
    req = urlrequest.Request(url, data=payload, method="POST", headers=headers)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            # ``status`` exists on http.client.HTTPResponse (real urllib).
            # Test mocks may stub the raw body without the attribute — fall back
            # to ``code`` (legacy alias) and finally to None.
            status = getattr(resp, "status", None) or getattr(resp, "code", None) or 200
    except urlerror.HTTPError as exc:
        raw_body = ""
        try:
            raw_body = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
        return HttpResult(
            ok=False, status=exc.code, body=None, raw=raw_body, reason=f"error:http-{exc.code}"
        )
    except urlerror.URLError as exc:
        return HttpResult(
            ok=False, status=None, body=None, raw="", reason=f"degraded:url:{exc.reason}"
        )
    except TimeoutError:
        return HttpResult(ok=False, status=None, body=None, raw="", reason="degraded:timeout")
    except OSError as exc:
        return HttpResult(
            ok=False, status=None, body=None, raw="", reason=f"degraded:os:{exc}"
        )

    try:
        parsed = json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
        return HttpResult(
            ok=False, status=status, body=None, raw=raw, reason="error:malformed-json"
        )
    return HttpResult(ok=True, status=status, body=parsed, raw=raw, reason="ok")


def recall_url(creds: HindsightCreds, bank_id: str) -> str:
    return f"{creds.url}/v1/default/banks/{bank_id}/memories/recall"


def retain_url(creds: HindsightCreds, bank_id: str) -> str:
    return f"{creds.url}/v1/default/banks/{bank_id}/memories"


def post_recall(
    creds: HindsightCreds,
    bank_id: str,
    query: str,
    *,
    max_tokens: int = 4096,
    types: list[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECS,
) -> HttpResult:
    """Call POST /v1/default/banks/{bank_id}/memories/recall."""
    body: dict[str, Any] = {"query": query, "max_tokens": int(max_tokens)}
    if types:
        body["types"] = list(types)
    return _post_json(recall_url(creds, bank_id), body, creds.headers(), timeout=timeout)


def post_retain(
    creds: HindsightCreds,
    bank_id: str,
    items: list[dict[str, Any]],
    *,
    async_mode: bool = False,
    timeout: float = DEFAULT_TIMEOUT_SECS,
) -> HttpResult:
    """Call POST /v1/default/banks/{bank_id}/memories.

    Each item must at least have ``content`` (str). Optional fields per
    Hindsight openapi: ``timestamp``, ``context``, ``metadata`` (str→str),
    ``document_id``, ``tags`` (list[str]).
    """
    body: dict[str, Any] = {"items": items, "async": bool(async_mode)}
    return _post_json(retain_url(creds, bank_id), body, creds.headers(), timeout=timeout)


__all__ = [
    "DEFAULT_TIMEOUT_SECS",
    "HindsightAuthMissing",
    "HindsightCreds",
    "HindsightError",
    "HindsightUrlMissing",
    "HttpResult",
    "USER_AGENT",
    "load_credentials",
    "post_recall",
    "post_retain",
    "recall_url",
    "retain_url",
]
