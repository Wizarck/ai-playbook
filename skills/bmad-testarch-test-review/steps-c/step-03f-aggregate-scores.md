---
name: 'step-03f-aggregate-scores'
description: 'Aggregate quality dimension scores into overall 0-100 score'
nextStepFile: './step-04-generate-report.md'
outputFile: '{test_artifacts}/test-review.md'
---

# Step 3F: Aggregate Quality Scores

## STEP GOAL

Read the violations from the 4 quality subagents, deduplicate them, apply one deduction ledger, and derive the review recommendation.

---

## MANDATORY EXECUTION RULES

- 📖 Read the entire step file before acting
- ✅ Speak in `{communication_language}`
- ✅ Read all 4 subagent outputs
- ✅ Apply the deduction ledger once, over all dimensions together
- ✅ Derive the recommendation from the violation counts, never by judgement
- ❌ Do NOT re-evaluate quality, and do NOT re-assign a severity: both are settled by `./criteria-registry.md`

---

## EXECUTION PROTOCOLS:

- 🎯 Follow the MANDATORY SEQUENCE exactly
- 💾 Record outputs before proceeding
- 📖 Load the next step only when instructed

---

## MANDATORY SEQUENCE

### 1. Read All Subagent Outputs

```javascript
// Use the SAME timestamp generated in Step 3 (do not regenerate).
const timestamp = subagentContext?.timestamp;
if (!timestamp) {
  throw new Error('Missing timestamp from Step 3 context. Pass Step 3 timestamp into Step 3F.');
}
const dimensions = ['determinism', 'isolation', 'maintainability', 'performance'];
const results = {};

dimensions.forEach((dim) => {
  const outputPath = `/tmp/tea-test-review-${dim}-${timestamp}.json`;
  results[dim] = JSON.parse(fs.readFileSync(outputPath, 'utf8'));
});
```

**Verify all succeeded:**

```javascript
const allSucceeded = dimensions.every((dim) => results[dim].score !== undefined);
if (!allSucceeded) {
  throw new Error('One or more quality subagents failed!');
}
```

---

### 2. Deduplicate Across Dimensions

Two dimensions can notice the same defect. Deduplicate before scoring, on the
row that fired rather than on the prose, so one defect is charged once:

```javascript
const seen = new Map();
dimensions.forEach((dim) => {
  results[dim].violations.forEach((v) => {
    const key = `${v.file}:${v.line}:${v.row}`;
    if (!seen.has(key)) seen.set(key, { ...v, dimensions: [dim] });
    else seen.get(key).dimensions.push(dim);
  });
});
const allViolations = [...seen.values()];
```

---

### 3. Apply the Deduction Ledger

One ledger, applied once, over every violation from every dimension. Severity
comes from `./criteria-registry.md` and was already resolved by the subagents.

```javascript
const DEDUCTION = { CRITICAL: 10, HIGH: 5, MEDIUM: 2, LOW: 1 };

const totalDeduction = allViolations.reduce((sum, v) => sum + (DEDUCTION[v.severity] ?? 0), 0);
const roundedScore = Math.max(0, 100 - totalDeduction);

const getGrade = (score) => {
  if (score >= 90) return 'A';
  if (score >= 80) return 'B';
  if (score >= 70) return 'C';
  if (score >= 60) return 'D';
  return 'F';
};
const overallGrade = getGrade(roundedScore);
```

An unknown severity is a bug in the subagent output, not a zero-cost violation.
Fail loudly rather than absorbing it:

```javascript
const unknown = allViolations.filter((v) => !(v.severity in DEDUCTION));
if (unknown.length) {
  throw new Error(
    `Violations carry a severity the ledger does not define: ` +
      unknown.map((v) => `${v.file}:${v.line} (${v.severity})`).join(', '),
  );
}
```

**Why one ledger and not four weighted dimensions.** Each dimension used to score
itself out of 100 and the aggregator averaged those with fixed weights, so the
same defect cost 3 points when determinism found it and 1.5 when performance did.
Two reviewers of one pull request could land three points apart and return
opposite recommendations. Severity now decides cost, and where the defect was
noticed decides nothing.

---

### 4. Derive the Recommendation

The recommendation is computed from what was found, never chosen:

```javascript
const count = (sev) => allViolations.filter((v) => v.severity === sev).length;

const deriveRecommendation = () => {
  if (count('CRITICAL') > 0) return 'Request Changes';
  if (count('HIGH') > 0) return 'Request Changes';
  if (count('MEDIUM') > 0) return 'Approve With Comments';
  return 'Approve';
};

const recommendation = deriveRecommendation();

const violationSummary = {
  total: allViolations.length,
  CRITICAL: count('CRITICAL'),
  HIGH: count('HIGH'),
  MEDIUM: count('MEDIUM'),
  LOW: count('LOW'),
};
```

The score is reported alongside the recommendation but does not produce it. A
score threshold would reintroduce the disagreement the ledger removed, because
two reviewers who find the same defects but describe a different number of minor
ones would land either side of a cutoff.

**Recommendations to the author** are collected from the dimensions unchanged and
capped at ten, ordered by the severity of the violation each one addresses:

```javascript
const SEVERITY_ORDER = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };
const prioritizedRecommendations = dimensions
  .flatMap((dim) => results[dim].recommendations.map((rec) => ({ dimension: dim, recommendation: rec })))
  .slice(0, 10);
```

---

### 5. Create Review Summary Object

**Aggregate all results:**

```javascript
const reviewSummary = {
  overall_score: roundedScore,
  overall_grade: overallGrade,
  total_deduction: totalDeduction,
  recommendation,

  // Dimensions report where a defect was noticed, not how much it cost.
  violations_by_dimension: Object.fromEntries(
    dimensions.map((dim) => [dim, allViolations.filter((v) => v.dimensions.includes(dim)).length]),
  ),

  violations_summary: violationSummary,

  all_violations: allViolations,

  blocking_violations: allViolations.filter((v) => v.severity === 'CRITICAL' || v.severity === 'HIGH'),

  top_10_recommendations: prioritizedRecommendations,

  subagent_execution: 'PARALLEL (4 quality dimensions)',
};

// Save for Step 4 (report generation)
fs.writeFileSync(`/tmp/tea-test-review-summary-${timestamp}.json`, JSON.stringify(reviewSummary, null, 2), 'utf8');
```

---

### 6. Display Summary to User

```
✅ Quality Evaluation Complete (Parallel Execution)

📊 Overall Quality Score: {roundedScore}/100 (Grade: {overallGrade})

🧾 Recommendation: {recommendation}   (derived from the counts below)

📈 Violations by dimension (where noticed, not what it cost):
- Determinism:      {determinism_count}
- Isolation:        {isolation_count}
- Maintainability:  {maintainability_count}
- Performance:      {performance_count}

ℹ️ Coverage is excluded from `test-review` scoring. Use `trace` for coverage analysis and gates.

⚠️ Violations Found (after cross-dimension deduplication):
- CRITICAL: {critical_count}  (−10 each)
- HIGH:     {high_count}  (−5 each)
- MEDIUM:   {medium_count}  (−2 each)
- LOW:      {low_count}  (−1 each)
- TOTAL:    {total_count}, deducting {total_deduction} points

🚀 Performance: Parallel execution ~60% faster than sequential

✅ Ready for report generation (Step 4)
```

---

---

### 7. Save Progress

**Save this step's accumulated work to `{outputFile}`.**

- **If `{outputFile}` does not exist** (first save), create it using the workflow template (if available) with YAML frontmatter:

  ```yaml
  ---
  stepsCompleted: ['step-03f-aggregate-scores']
  lastStep: 'step-03f-aggregate-scores'
  lastSaved: '{date}'
  ---
  ```

  Then write this step's output below the frontmatter.

- **If `{outputFile}` already exists**, update:
  - Add `'step-03f-aggregate-scores'` to `stepsCompleted` array (only if not already present)
  - Set `lastStep: 'step-03f-aggregate-scores'`
  - Set `lastSaved: '{date}'`
  - Append this step's output to the appropriate section of the document.

---

## EXIT CONDITION

Proceed to Step 4 when:

- ✅ All subagent outputs read successfully
- ✅ Overall score calculated
- ✅ Violations aggregated
- ✅ Recommendations prioritized
- ✅ Summary saved to temp file
- ✅ Output displayed to user
- ✅ Progress saved to output document

Load next step: `{nextStepFile}`

---

## 🚨 SYSTEM SUCCESS METRICS

### ✅ SUCCESS:

- All 4 subagent outputs read and parsed
- Score is 100 minus the ledger total, and the recommendation follows from the counts
- Violations aggregated correctly
- Summary complete and saved

### ❌ FAILURE:

- Failed to read one or more subagent outputs
- A severity outside the ledger was absorbed instead of raised
- Summary missing or incomplete

**Master Rule:** One defect, one row, one deduction. Where it was noticed changes nothing about what it costs.
