"""Retain a memory item — lesson / gotcha / decision / failure / fact — to Hindsight.

Companion to ``scripts.inject_context`` (read side). Sanitises the payload
through ``scripts.secrets_scan.sanitise`` before POST so a careless retain
cannot exfiltrate a leaked credential into durable memory.

Renamed from ``scripts.retain_lesson`` in v0.3.0 — the script handles every
``kind`` (lesson / gotcha / decision / failure / fact), not just lessons.
``scripts/retain_lesson.py`` ships as a deprecation shim that delegates
here and emits a warning to stderr. The shim will be removed in v1.0.0.

Per [`specs/memory-hierarchy.md`](../specs/memory-hierarchy.md) §5:

    - Retain on lesson, not on fact.
    - Every retain includes ``why`` (rationale), ``trace_id`` (OTel), ``tags``
      (≥1 of project, kind ∈ {lesson, gotcha, decision, failure}, optional ttl_days).
    - Never retain a secret — sanitiser is the gate.
    - Retain after significant events: ADR chosen, gotcha discovered,
      agentic-failure resolved, retro pattern.

CLI
---

Single retain, project + kind from flags:

    python -m scripts.retain_lesson \\
        --bank eligia \\
        --kind decision \\
        --project ai-playbook \\
        --content "Rotated PAT scope from full repo to fine-grained scoped to consumers.yaml" \\
        --why "least-privilege; god-mode PAT was a 1-week stop-gap" \\
        --tag rotation --tag security

Bulk retain from a JSONL file (one item per line, same field shape as flags):

    python -m scripts.retain_lesson --bank eligia --bulk lessons.jsonl

Degraded queue replay (when Hindsight comes back after an outage):

    python -m scripts.retain_lesson --bank eligia --replay-queue

Required env (typically supplied via ``sops exec-env secrets/secrets.env -- ...``):

    HINDSIGHT_URL
    CF_ACCESS_CLIENT_ID + CF_ACCESS_CLIENT_SECRET    OR    HINDSIGHT_API_KEY

Exit codes
----------
    0  success (retained or queued in degraded mode)
    1  user-actionable error (missing required field, malformed JSONL)
    2  setup error (missing env vars, missing JSONL file)
    3  hard block (sanitiser detected secret-shaped content; OVERRIDE: none)
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# UTF-8 stdio.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

# Make sibling-script imports work whether invoked via `-m scripts.retain_lesson`
# or by direct path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._break_glass import add_break_glass_flag, apply_break_glass  # noqa: E402
from scripts._hindsight import (  # noqa: E402
    HindsightAuthMissing,
    HindsightUrlMissing,
    load_credentials,
    post_retain,
)

SCRIPT_BASENAME = "retain_lesson.py"
QUEUE_FILE = ".ai-playbook/hindsight-queue.jsonl"
ALLOWED_KINDS = {"lesson", "gotcha", "decision", "failure", "fact"}


@dataclass
class RetainItem:
    """One memory item ready to POST."""

    content: str
    bank: str
    project: str | None = None
    kind: str = "lesson"
    why: str | None = None
    trace_id: str | None = None
    tags: list[str] = field(default_factory=list)
    context: str | None = None
    ttl_days: int | None = None
    timestamp: str | None = None  # ISO-8601 or "unset"
    document_id: str | None = None

    def to_hindsight(self) -> dict[str, Any]:
        """Render to the Hindsight ``MemoryItem`` shape."""
        text = self.content.strip()
        if self.why:
            text = f"{text}\n\nWHY: {self.why}"
        out: dict[str, Any] = {"content": text}
        if self.timestamp:
            out["timestamp"] = self.timestamp
        if self.context:
            out["context"] = self.context
        elif self.kind:
            out["context"] = self.kind
        # Tag set always carries kind + project + extras.
        tag_set = list(dict.fromkeys(self.tags + ([self.kind] if self.kind else []) +
                                     ([self.project] if self.project else [])))
        if tag_set:
            out["tags"] = tag_set
        # Metadata: free-form string→string for cross-referencing.
        meta: dict[str, str] = {}
        if self.trace_id:
            meta["trace_id"] = self.trace_id
        if self.ttl_days is not None:
            meta["ttl_days"] = str(int(self.ttl_days))
        if self.project:
            meta["project"] = self.project
        if self.kind:
            meta["kind"] = self.kind
        if meta:
            out["metadata"] = meta
        if self.document_id:
            out["document_id"] = self.document_id
        return out


# ---------------------------------------------------------------------------
# Sanitisation — defence-in-depth. Never POST suspected secrets.
# ---------------------------------------------------------------------------


def _sanitise_or_block(item: RetainItem) -> tuple[RetainItem, list[str]]:
    """Return ``(safe_item, kinds_redacted)``. Empty list = nothing redacted.

    If sanitiser flags ``api-key`` or ``aws-key`` shapes we BLOCK the retain
    rather than silently redact — for that high-blast pattern the right move
    is to fix the source (the dev pasted a real secret into a lesson). For
    softer patterns (URLs with embedded tokens, base64-ish, etc.) we redact
    inline and continue.
    """
    try:
        from scripts.secrets_scan import sanitise

        full = (item.content or "") + "\n" + (item.why or "")
        clean, kinds = sanitise(full)
        if any(k in {"anthropic-api-key", "openai-api-key", "github-pat", "aws-secret"}
               for k in kinds):
            return item, [k for k in kinds if k.endswith("key") or k.endswith("secret")
                          or k.endswith("pat")]
        if not kinds:
            return item, []
        # Redact: replace content with the sanitised version, but keep the why
        # field separate (don't merge them in storage — the helper only needs
        # the merged copy for matching).
        clean_content, content_kinds = sanitise(item.content or "")
        clean_why, why_kinds = sanitise(item.why or "") if item.why else ("", [])
        new = RetainItem(
            content=clean_content,
            bank=item.bank,
            project=item.project,
            kind=item.kind,
            why=clean_why or None,
            trace_id=item.trace_id,
            tags=item.tags + ["sanitised"],
            context=item.context,
            ttl_days=item.ttl_days,
            timestamp=item.timestamp,
            document_id=item.document_id,
        )
        return new, sorted(set(content_kinds + why_kinds))
    except Exception:  # noqa: BLE001 — fail-OPEN on tooling gap
        return item, []


# ---------------------------------------------------------------------------
# Degraded-mode queue — append to JSONL when Hindsight is unreachable.
# ---------------------------------------------------------------------------


def _resolve_queue_path(consumer_root: Path) -> Path:
    return consumer_root / QUEUE_FILE


def _queue_item(consumer_root: Path, item: RetainItem) -> Path:
    qp = _resolve_queue_path(consumer_root)
    qp.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "item": item.to_hindsight(),
        "bank": item.bank,
    }
    with qp.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return qp


def _drain_queue(consumer_root: Path, bank: str, dry_run: bool) -> tuple[int, int]:
    """Replay every queued retain. Returns (sent, kept_in_queue)."""
    qp = _resolve_queue_path(consumer_root)
    if not qp.is_file():
        return 0, 0
    try:
        creds = load_credentials()
    except (HindsightAuthMissing, HindsightUrlMissing) as exc:
        print(f"[retain] cannot drain queue: {exc}", file=sys.stderr)
        return 0, sum(1 for _ in qp.open(encoding="utf-8"))

    sent = 0
    kept: list[str] = []
    with qp.open(encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                kept.append(raw)
                continue
            if rec.get("bank") and rec["bank"] != bank:
                kept.append(raw)
                continue
            if dry_run:
                sent += 1
                continue
            r = post_retain(creds, bank, [rec["item"]])
            if r.ok:
                sent += 1
            else:
                kept.append(raw)
    if not dry_run:
        qp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return sent, len(kept)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scripts.retain_lesson",
        description="Retain a lesson/gotcha/decision/failure to Hindsight.",
    )
    p.add_argument("--bank", required=True, help="Hindsight bank_id (e.g. eligia, opentrattos).")

    g = p.add_argument_group("single-item flags")
    g.add_argument("--content", help="Lesson body text (≥10 chars).")
    g.add_argument("--why", help="Rationale (recommended, becomes part of stored content).")
    g.add_argument("--kind", default="lesson", choices=sorted(ALLOWED_KINDS),
                   help="Item kind. Default: lesson.")
    g.add_argument("--project", help="Project slug (added to tags + metadata).")
    g.add_argument("--trace-id", help="OTel trace id for cross-reference.")
    g.add_argument("--tag", action="append", default=[], dest="tags",
                   help="Add a tag (repeatable).")
    g.add_argument("--context", help="Optional context string (defaults to --kind).")
    g.add_argument("--ttl-days", type=int, default=None,
                   help="Override default 90-day soft decay.")
    g.add_argument("--timestamp", help='ISO-8601 datetime, or "unset" for timeless.')
    g.add_argument("--document-id", help="Optional document id to group items.")

    p.add_argument("--bulk", type=Path,
                   help="Path to a JSONL file; one item per line. Each line: object with same "
                        "fields as the single-item flags.")
    p.add_argument("--replay-queue", action="store_true",
                   help="Drain .ai-playbook/hindsight-queue.jsonl for this bank and exit.")

    p.add_argument("--consumer-root", type=Path, default=Path.cwd(),
                   help="Where the queue file lives (default: cwd).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be POSTed; do not call Hindsight.")
    p.add_argument("--queue-on-fail", action="store_true", default=True,
                   help="(Default true) When Hindsight is unreachable, append to "
                        "hindsight-queue.jsonl instead of erroring.")
    p.add_argument("--no-queue-on-fail", dest="queue_on_fail", action="store_false")

    add_break_glass_flag(p)
    return p


def _items_from_args(args: argparse.Namespace) -> list[RetainItem]:
    items: list[RetainItem] = []
    if args.bulk is not None:
        if not args.bulk.is_file():
            print(f"❌ --bulk file not found at {args.bulk}", file=sys.stderr)
            sys.exit(2)
        for lineno, line in enumerate(args.bulk.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                rec = json.loads(stripped)
            except json.JSONDecodeError as exc:
                print(f"❌ malformed JSONL at {args.bulk}:{lineno} — {exc}", file=sys.stderr)
                sys.exit(1)
            if "content" not in rec:
                print(f"❌ {args.bulk}:{lineno} missing required field 'content'", file=sys.stderr)
                sys.exit(1)
            items.append(_record_to_item(rec, args.bank))
    elif args.content:
        items.append(RetainItem(
            content=args.content,
            bank=args.bank,
            project=args.project,
            kind=args.kind,
            why=args.why,
            trace_id=args.trace_id,
            tags=list(args.tags),
            context=args.context,
            ttl_days=args.ttl_days,
            timestamp=args.timestamp,
        ))
    return items


def _record_to_item(rec: dict[str, Any], bank: str) -> RetainItem:
    return RetainItem(
        content=rec["content"],
        bank=bank,
        project=rec.get("project"),
        kind=rec.get("kind") or "lesson",
        why=rec.get("why"),
        trace_id=rec.get("trace_id"),
        tags=list(rec.get("tags") or []),
        context=rec.get("context"),
        ttl_days=rec.get("ttl_days"),
        timestamp=rec.get("timestamp"),
        document_id=rec.get("document_id"),
    )


def main() -> int:
    args = _build_parser().parse_args()

    if args.kind and args.kind not in ALLOWED_KINDS:
        print(f"❌ --kind must be one of {sorted(ALLOWED_KINDS)}", file=sys.stderr)
        return 1

    if args.replay_queue:
        sent, kept = _drain_queue(args.consumer_root, args.bank, args.dry_run)
        print(f"replayed {sent} item(s); {kept} remain queued")
        return 0

    items = _items_from_args(args)
    if not items:
        print("❌ supply either --content TEXT or --bulk FILE.jsonl", file=sys.stderr)
        return 1

    safe_items: list[RetainItem] = []
    for it in items:
        safe, redacted = _sanitise_or_block(it)
        if redacted and any(k.endswith(("key", "secret", "pat")) for k in redacted):
            print(
                f"❌ retain payload looks like a secret ({', '.join(redacted)}) at "
                f"retain_lesson.py:--content",
                file=sys.stderr,
            )
            print("   FIX: scrub the secret from the lesson body before retaining.",
                  file=sys.stderr)
            print("   OVERRIDE: none", file=sys.stderr)
            return 3
        if redacted:
            print(f"⚠️ sanitised: {', '.join(redacted)}", file=sys.stderr)
        safe_items.append(safe)

    if args.dry_run:
        for it in safe_items:
            print(json.dumps(it.to_hindsight(), indent=2, ensure_ascii=False))
        return 0

    try:
        creds = load_credentials()
    except (HindsightAuthMissing, HindsightUrlMissing) as exc:
        if args.queue_on_fail:
            for it in safe_items:
                _queue_item(args.consumer_root, it)
            print(
                f"⚠️ Hindsight unreachable ({exc}); queued {len(safe_items)} item(s) "
                f"to {QUEUE_FILE}",
                file=sys.stderr,
            )
            return 0
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    payload = [it.to_hindsight() for it in safe_items]
    r = post_retain(creds, args.bank, payload)
    if r.ok:
        body = r.body if isinstance(r.body, dict) else {}
        print(
            f"✅ retained {body.get('items_count', len(payload))} item(s) "
            f"to bank={args.bank}; usage="
            f"{(body.get('usage') or {}).get('total_tokens', '?')} tokens"
        )
        return 0

    # Hindsight reachable but call failed — queue if allowed.
    if args.queue_on_fail and r.reason.startswith("degraded"):
        for it in safe_items:
            _queue_item(args.consumer_root, it)
        print(f"⚠️ POST failed ({r.reason}); queued {len(safe_items)} item(s)", file=sys.stderr)
        return 0

    print(
        f"❌ Hindsight POST failed: {r.reason} status={r.status} body={r.raw[:200]}",
        file=sys.stderr,
    )
    if args.force_reason:
        apply_break_glass(
            gate="hindsight-retain",
            script=SCRIPT_BASENAME,
            reason=args.force_reason,
            override_allowed=True,
            repo_root=args.consumer_root,
        )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
