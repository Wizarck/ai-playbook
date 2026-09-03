---
name: 'step-03b-subagent-isolation'
description: 'Subagent: Check test isolation (no shared state/dependencies)'
subagent: true
outputFile: '/tmp/tea-test-review-isolation-{{timestamp}}.json'
---

# Subagent 3B: Isolation Quality Check

## SUBAGENT CONTEXT

This is an **isolated subagent** running in parallel with other quality dimension checks.

**Your task:** Analyze test files for ISOLATION violations only.

---

## MANDATORY EXECUTION RULES

- ✅ Check ISOLATION only (not other quality dimensions)
- ✅ Output structured JSON to temp file
- ❌ Do NOT check determinism, maintainability, coverage, or performance
- ❌ Do NOT modify test files (read-only analysis)

---

## SUBAGENT TASK

### 1. Identify Isolation Violations

**Scan test files for isolation issues:**

**HIGH SEVERITY Violations**:

- Global state mutations (global variables modified)
- Test order dependencies (test B depends on test A running first)
- Shared database records without cleanup
- beforeAll/afterAll with side effects leaking to other tests

**MEDIUM SEVERITY Violations**:

- Missing test cleanup (created data not deleted)
- Shared fixtures that mutate state
- Tests that assume specific execution order
- Environment variables modified without restoration

**LOW SEVERITY Violations**:

- Tests sharing test data (but not mutating)
- Missing test.describe grouping
- Tests that could be more isolated

### 2. Calculate Isolation Score

```javascript
const totalChecks = testFiles.length * checksPerFile;
const failedChecks = violations.length;
```

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
  "dimension": "isolation",
  "violations": [
    {
      "file": "tests/api/integration.spec.ts",
      "line": 15,
      "severity": "HIGH",
      "row": "<registry row id, e.g. H1>",
      "category": "test-order-dependency",
      "description": "Test depends on previous test creating user record",
      "suggestion": "Each test should create its own test data in beforeEach",
      "code_snippet": "test('should update user', async () => { /* assumes user exists */ });"
    }
  ],
  "passed_checks": 14,
  "failed_checks": 1,
  "total_checks": 15,
  "violation_summary": {
    "HIGH": 1,
    "MEDIUM": 0,
    "LOW": 0
  },
  "recommendations": [
    "Add beforeEach hooks to create test data",
    "Add afterEach hooks to cleanup created records",
    "Use test.describe.configure({ mode: 'parallel' }) to enforce isolation"
  ],
  "summary": "Tests are well isolated with 1 HIGH severity violation"
}
```

---

## EXIT CONDITION

Subagent completes when:

- ✅ All test files analyzed for isolation violations
- ✅ Score calculated
- ✅ JSON output written to temp file

**Subagent terminates here.**

---

## 🚨 SUBAGENT SUCCESS METRICS

### ✅ SUCCESS:

- Only isolation checked (not other dimensions)
- JSON output valid and complete

### ❌ FAILURE:

- Checked quality dimensions other than isolation
- Invalid or missing JSON output
