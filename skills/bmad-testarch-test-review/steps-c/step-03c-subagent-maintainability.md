---
name: 'step-03c-subagent-maintainability'
description: 'Subagent: Check test maintainability (readability, structure, DRY)'
subagent: true
outputFile: '/tmp/tea-test-review-maintainability-{{timestamp}}.json'
---

# Subagent 3C: Maintainability Quality Check

## SUBAGENT CONTEXT

This is an **isolated subagent** running in parallel with other quality dimension checks.

**Your task:** Analyze test files for MAINTAINABILITY violations only.

---

## MANDATORY EXECUTION RULES

- ✅ Check MAINTAINABILITY only (not other quality dimensions)
- ✅ Output structured JSON to temp file
- ❌ Do NOT check determinism, isolation, coverage, or performance

---

## SUBAGENT TASK

### 1. Identify Maintainability Violations

**HIGH SEVERITY Violations**:

- Tests >1000 lines (too complex)
- No test.describe grouping
- Duplicate test logic (copy-paste)
- Unclear test names (no Given/When/Then structure)
- Magic numbers/strings without constants

**MEDIUM SEVERITY Violations**:

- Tests missing comments for complex logic
- Inconsistent naming conventions
- Excessive nesting (>3 levels)
- Large setup/teardown blocks

**LOW SEVERITY Violations**:

- Minor code style issues
- Could benefit from helper functions
- Inconsistent assertion styles

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
  "dimension": "maintainability",
  "violations": [
    {
      "file": "tests/e2e/complex-flow.spec.ts",
      "line": 1,
      "severity": "HIGH",
      "row": "<registry row id, e.g. H1>",
      "category": "test-too-long",
      "description": "Test file is 250 lines - too complex to maintain",
      "suggestion": "Split into multiple smaller test files by feature area",
      "code_snippet": "test.describe('Complex flow', () => { /* 250 lines */ });"
    }
  ],
  "passed_checks": 10,
  "failed_checks": 5,
  "violation_summary": {
    "HIGH": 2,
    "MEDIUM": 2,
    "LOW": 1
  },
  "recommendations": [
    "Split large test files into smaller, focused files (<1000 lines each)",
    "Add test.describe grouping for related tests",
    "Extract duplicate logic into helper functions"
  ],
  "summary": "Tests have maintainability issues - 5 violations (2 HIGH)"
}
```

---

## EXIT CONDITION

Subagent completes when JSON output written to temp file.

**Subagent terminates here.**
