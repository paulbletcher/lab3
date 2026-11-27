# Improvement beyond the brief: Completed-order review queue

## The problem it solves

Nana and Adwoa need a repeatable way to find completed orders whose recorded value or attribution needs review. A diagnosis alone does not produce tomorrow's work list. An inventory forecast would be misleading: on 2026-11-27 the supplied history contains no sales in the preceding thirty complete days, although historical sale timestamps are present and sale movements can be distinguished from restocks, returns, damage and corrections. Thirty-three sale records are future-dated. This is insufficient evidence of recent demand, not proof demand is zero. No supplier purchase-order/receipt dates support a replenishment lead-time estimate.

## What I built

`reports/order_review_queue.sql` installs the reusable, read-only `report_order_review_queue` view. It lists order ID, exception type, stored amount, full calculated line amount where known, signed stored-minus-lines difference and a practical review explanation. It uses all loaded completed dates, including future records, so the review process can investigate records the spending report excludes. Normalize status with the same trim/lowercase complete/completed mapping.

The view emits one row per exception: missing customer, incomplete line amount (including no lines), or mismatched/missing stored total with complete lines. Overlapping flags are intentional. An incomplete sum and its difference remain NULL; zero is never substituted for a missing price. Finance should verify charges/discounts against source records, and Ops should confirm attribution before authorizing a correction. The view is the current queue, not a persisted case-management ledger; it does not track assignees or review completion.

Actual-data tests reproduce **144** missing-customer, **95** incomplete-line and **1,624** total-mismatch flags. Stored amounts for the first two groups reconcile to 388,780.89 and 455,904.42. Mismatch differences reconcile to net -1,266,190.96 and absolute 2,074,053.86. The 1,863 flags cover 1,861 distinct orders; overlapping exceptions are not added as unique cases. These counts are recorded in `tests/final_evidence.json`.

Synthetic tests cover overlapping flags, NULL prices, missing lines, future completed orders, pending-order exclusion and signed differences. All fixtures roll back. `tests/final_improvement.log` records the assertions; all six full-table fingerprints match before and after the suite, demonstrating that the report and tests preserve historical records.

## What it is worth to Nana

Finance and Ops can repeatedly produce the same exception definitions without rebuilding an investigation. Recorded amounts identify which cases merit financial review, while NULL calculated amounts prevent false reconciliation. No monetary saving is claimed without measured review effort or confirmed recoveries.

## What it cost

One ordinary view and a rollback-only test script; no new indexes, infrastructure or recurring service cost. Each execution scans and aggregates order lines, so it has a runtime cost. Existing stock inaccuracies and source-record questions remain unresolved. The view needs an authorized reporting connection; application-only roles deliberately have no direct catalog/report access. Historic values and customer identities remain confidential. Corrections and review ownership still require the business, and a demand forecast should be revisited only after a current, complete movement history is available.
