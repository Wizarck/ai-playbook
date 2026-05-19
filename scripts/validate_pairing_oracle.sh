#!/usr/bin/env bash
# Parallel shell oracle for validate_pairing.py (D12 — defense-in-depth).
#
# Re-implements signal #1 (filename-slug existence) as a ~30-line shell
# tripwire. If the Python validator has a bug and silently passes drift,
# this script catches the most-common case: a docs/rules/<slug>.rule.md
# with no scripts/rules/<slug>.rule.py (and vice versa).
#
# Exit 0 on clean; exit 2 on orphan.

set -euo pipefail
cd "$(dirname "$0")/.."

errors=0

# Forward: every doc must have a (possibly null-paired) script OR be advisory.
for doc in docs/rules/*.rule.md; do
  [ -e "$doc" ] || continue
  slug=$(basename "$doc" .rule.md)
  hardrule="scripts/rules/${slug}.rule.py"
  if grep -qE '^paired_hardrule:\s*null' "$doc"; then
    continue  # advisory — allowed
  fi
  if [ ! -f "$hardrule" ]; then
    echo "[orphan-doc] $doc has no matching $hardrule" >&2
    errors=$((errors+1))
  fi
done

# Reverse: every script must have a doc.
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

echo "validate_pairing_oracle: OK"
exit 0
