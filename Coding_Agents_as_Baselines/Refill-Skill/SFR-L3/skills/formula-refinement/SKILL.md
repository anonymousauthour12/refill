---
name: formula-refinement
description: How to repair a candidate formula that executes but does not fully reproduce the stored values, by diagnosing its mismatches on concrete rows and rewriting it minimally. Use when a formula is structurally valid but its confidence is below 100.
---

# Formula refinement

A formula that executes without errors but has a confidence below 100 is structurally valid and not yet accurate. Often a small change is enough (for example `qty * price` ignores a rebate column; `qty * price * (1 - rebate)` fixes it). Concrete discrepancies are more effective than starting over or looking for another formula.

## Evidence
Look at the rows where the prediction is wrong or NULL, with the stored value and the predicted value side by side. About **10 rows** are enough:

`SELECT actual_value, computed_value FROM (computation SQL) AS t WHERE actual_value <> computed_value OR computed_value IS NULL LIMIT 10;`

Keep also the columns the formula uses when you need them.

## Diagnosis
`actual_value` is always correct and `computed_value` is wrong. Compare them to spot the type of error: a constant offset, a missing term, a wrong rounding, a wrong join that duplicates or loses rows, NULLs that are not handled, a wrong branch of a condition, an off-by-one in a window or in the previous/next row.

## Rewriting
Apply the smallest fix that explains the mismatches; do not redesign the formula unless it is fundamentally wrong. The corrected query must be executable immediately, valid MySQL and free of errors, and all the rules that apply to any candidate formula remain (no reading of the target column, no hard-coded data). A rewritten formula is judged like any other candidate: keep the better of the original and the rewritten one; both are valid results if both reach 80. One diagnosis round per candidate is the default.
