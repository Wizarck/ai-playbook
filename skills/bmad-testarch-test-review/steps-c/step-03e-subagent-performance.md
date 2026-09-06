---
name: 'step-03e-subagent-performance'
description: 'Subagent: Check test performance (speed, efficiency, parallelization)'
subagent: true
outputFile: '/tmp/tea-test-review-performance-{{timestamp}}.json'
---

# Subagent 3E: Performance Quality Check

## SUBAGENT CONTEXT

This is an **isolated subagent** running in parallel with other quality dimension checks.

**Your task:** Analyze test files for PERFORMANCE violations only.

---

## MANDATORY EXECUTION RULES

- ✅ Check PERFORMANCE only (not other quality dimensions)
- ✅ Output structured JSON to temp file
- ❌ Do NOT check determinism, isolation, maintainability, or coverage

---

## SUBAGENT TASK

### 1. Identify Performance Violations

What this dimension looks for:

- Excessive navigation (reloading pages unnecessarily)
- No fixture reuse (repeating expensive operations)
- Inefficient selectors (page.$$ instead of locators)
- Large data sets in tests without pagination
- Excessive logging

What this dimension must **not** report, and why:

- **Serial execution.** `test.describe.serial` is how a Pact suite and anything
  sharing a broker fixture stay correct. Whether a file may run in parallel is
  decided by isolation, which reads shared state directly; a speed dimension
  guessing at it penalises correct code.
- **Per-test database setup.** A fresh database per test is the isolation the
  rubric asks for elsewhere. Charging for it here made the review argue with
  itself, and the file that obeyed both rules could not exist.
- **Hard waits.** They belong to determinism, row H1, and are charged there. A
  timer is a correctness defect that happens to also be slow, and it was being
  deducted twice in a single pass.

### 2. Read Severity From the Registry

Severity is not computed here. For every violation, read the severity that
`./criteria-registry.md` pins for the row that fired, and put that row's id in
the `row` field so the aggregator can deduplicate a defect that two dimensions
both notice. A defect matching no row is reported in prose under
recommendations, with no severity and no deduction.

The deduction ledger is applied once, over all four dimensions together, by
`step-03f-aggregate-scores.md`. Scoring per dimension and then averaging is what
let one defect cost a different number of points depending on which subagent
found it.

---

## OUTPUT FORMAT

```json
{
  "dimension": "performance",
  "violations": [
    {
      "file": "tests/api/bulk-operations.spec.ts",
      "line": 35,
      "severity": "MEDIUM",
      "row": "<registry row id, e.g. H1>",
      "category": "slow-setup",
      "description": "Test creates 1000 records in setup - very slow",
      "suggestion": "Use smaller data sets or fixture factories",
      "code_snippet": "beforeEach(async () => { for (let i=0; i<1000; i++) { ... } });"
    }
  ],
  "passed_checks": 13,
  "failed_checks": 2,
  "violation_summary": {
    "HIGH": 1,
    "MEDIUM": 1,
    "LOW": 0
  },
  "performance_metrics": {
    "parallelizable_tests": 80,
    "serial_tests": 20,
    "avg_test_duration_estimate": "~2 seconds",
    "slow_tests": ["bulk-operations.spec.ts (>30s)"]
  },
  "recommendations": [
    "Enable parallel mode where possible",
    "Reduce setup data to minimum needed",
    "Use fixtures to share expensive setup across tests",
    "Remove unnecessary .serial constraints"
  ],
  "summary": "Good performance with 2 violations - 80% tests can run in parallel"
}
```

---

## EXIT CONDITION

Subagent completes when JSON output written to temp file.

**Subagent terminates here.**
