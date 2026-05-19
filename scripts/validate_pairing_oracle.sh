#!/usr/bin/env bash
# Parallel shell oracle for validate_pairing.py (D12 — defense-in-depth).
#
# Re-implements signal #1 (filename-slug existence) as a ~30-line shell
# tripwire. If the Python validator has a bug and silently passes drift,
# this script catches the most-common case: an orphan rule script with
# no matching docs entry.
#
# Slice 4 reality: legacy docs/rules/*.rule.md files do NOT yet have
# frontmatter (content rewrite is Slice 5). The Python validator treats
# missing frontmatter as `paired_hardrule: null` (advisory) by default;
# this shell oracle matches by skipping doc->script direction entirely
# during Slice 4 and only enforcing script->doc (which IS deterministic).
# Slice 5 will tighten this oracle once frontmatter is universal.
#
# Exit 0 on clean; exit 2 on script with no matching doc.

set -euo pipefail
cd "$(dirname "$0")/.."

errors=0

# Reverse: every script must have a doc (deterministic — no frontmatter
# inspection needed).
for script in scripts/rules/*.rule.py; do
  [ -e "$script" ] || continue
  slug=$(basename "$script" .rule.py)
  doc="docs/rules/${slug}.rule.md"
  if [ ! -f "$doc" ]; then
    echo "[orphan-hardrule] $script has no matching $doc" >&2
    errors=$((errors+1))
  fi
done

if [ "$errors" -gt 0 ]; then
  echo "validate_pairing_oracle: $errors orphan(s) detected" >&2
  exit 2
fi

echo "validate_pairing_oracle: OK (script->doc direction; doc->script direction enforced in Slice 5 strict mode)"
exit 0
