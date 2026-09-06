---
name: 'step-03a-subagent-determinism'
description: 'Subagent: Check test determinism (no random/time dependencies)'
subagent: true
outputFile: '/tmp/tea-test-review-determinism-{{timestamp}}.json'
---

# Subagent 3A: Determinism Quality Check

## SUBAGENT CONTEXT

This is an **isolated subagent** running in parallel with other quality dimension checks.

**What you have from parent workflow:**

- Test files discovered in Step 2
- Knowledge fragment: test-quality (determinism criteria)
- Config: test framework

**Your task:** Analyze test files for DETERMINISM violations only.

---

## MANDATORY EXECUTION RULES

- 📖 Read this entire subagent file before acting
- ✅ Check DETERMINISM only (not other quality dimensions)
- ✅ Output structured JSON to temp file
- ❌ Do NOT check isolation, maintainability, coverage, or performance (other subagents)
- ❌ Do NOT modify test files (read-only analysis)
- ❌ Do NOT run tests (just analyze code)

---

## SUBAGENT TASK

### 1. Identify Determinism Violations

**Scan test files for non-deterministic patterns:**

**HIGH SEVERITY Violations**:

- `Math.random()` - Random number generation
- `Date.now()` or `new Date()` without mocking
- `setTimeout` / `setInterval` without proper waits
- External API calls without mocking
- File system operations on random paths
- Database queries with non-deterministic ordering

**MEDIUM SEVERITY Violations**:

- `page.waitForTimeout(N)` - Hard waits instead of conditions
- Flaky selectors (CSS classes that may change)
- Race conditions (missing proper synchronization)
- Test order dependencies (test A must run before test B)

**LOW SEVERITY Violations**:

- Missing test isolation (shared state between tests)
- Console timestamps without fixed timezone

### 2. Analyze Each Test File

For each test file from Step 2:

```javascript
const violations = [];

// Check for Math.random()
if (testFileContent.includes('Math.random()')) {
  violations.push({
    file: testFile,
    line: findLineNumber('Math.random()'),
    severity: 'HIGH',
    category: 'random-generation',
    description: 'Test uses Math.random() - non-deterministic',
    suggestion: 'Use faker.seed(12345) for deterministic random data',
  });
}

// Check for Date.now()
if (testFileContent.includes('Date.now()') || testFileContent.includes('new Date()')) {
  violations.push({
    file: testFile,
    line: findLineNumber('Date.now()'),
    severity: 'HIGH',
    category: 'time-dependency',
    description: 'Test uses Date.now() or new Date() without mocking',
    suggestion: 'Mock system time with test.useFakeTimers() or use fixed timestamps',
  });
}

// Check for hard waits
if (testFileContent.includes('waitForTimeout')) {
  violations.push({
    file: testFile,
    line: findLineNumber('waitForTimeout'),
    severity: 'MEDIUM',
    category: 'hard-wait',
    description: 'Test uses waitForTimeout - creates flakiness',
    suggestion: 'Replace with expect(locator).toBeVisible() or interceptNetworkCall-based network waits',
  });
}

// ... check other patterns
```

### 3. Calculate Determinism Score

**Scoring Logic**:

```javascript
const totalChecks = testFiles.length * checksPerFile;
const failedChecks = violations.length;
const passedChecks = totalChecks - failedChecks;

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

Write JSON to temp file: `/tmp/tea-test-review-determinism-{{timestamp}}.json`

```json
{
  "dimension": "determinism",
  "violations": [
    {
      "file": "tests/api/user.spec.ts",
      "line": 42,
      "severity": "HIGH",
      "row": "<registry row id, e.g. H1>",
      "category": "random-generation",
      "description": "Test uses Math.random() - non-deterministic",
      "suggestion": "Use faker.seed(12345) for deterministic random data",
      "code_snippet": "const userId = Math.random() * 1000;"
    },
    {
      "file": "tests/e2e/checkout.spec.ts",
      "line": 78,
      "severity": "MEDIUM",
      "row": "<registry row id, e.g. H1>",
      "category": "hard-wait",
      "description": "Test uses waitForTimeout - creates flakiness",
      "suggestion": "Replace with expect(locator).toBeVisible()",
      "code_snippet": "await page.waitForTimeout(5000);"
    }
  ],
  "passed_checks": 12,
  "failed_checks": 3,
  "total_checks": 15,
  "violation_summary": {
    "HIGH": 1,
    "MEDIUM": 1,
    "LOW": 1
  },
  "recommendations": [
    "Use faker with fixed seed for all random data",
    "Replace all waitForTimeout with conditional waits",
    "Mock Date.now() in tests that use current time"
  ],
  "summary": "Tests are mostly deterministic with 3 violations (1 HIGH, 1 MEDIUM, 1 LOW)"
}
```

**On Error:**

```json
{
  "dimension": "determinism",
  "success": false,
  "error": "Error message describing what went wrong"
}
```

---

## EXIT CONDITION

Subagent completes when:

- ✅ All test files analyzed for determinism violations
- ✅ Score calculated (0-100)
- ✅ Violations categorized by severity
- ✅ Recommendations generated
- ✅ JSON output written to temp file

**Subagent terminates here.** Parent workflow will read output and aggregate with other quality dimensions.

---

## 🚨 SUBAGENT SUCCESS METRICS

### ✅ SUCCESS:

- All test files scanned for determinism violations
- Score calculated with proper severity weighting
- JSON output valid and complete
- Only determinism checked (not other dimensions)

### ❌ FAILURE:

- Checked quality dimensions other than determinism
- Invalid or missing JSON output
- Score calculation incorrect
- Modified test files (should be read-only)
