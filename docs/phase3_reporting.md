# Phase 3: Monday Customer-Spending Report

Phases 0, 1 and 2 are complete. Phase 3 is in progress. This document preserves Steps 3.2 through 3.6 and adds **Step 3.7: integrated Monday spending report** below. The approved policy is RANK() <= 100 with ties preserved. The integrated report is validated; performance benchmarking and index optimization remain unstarted pending approval.

At the start of Step 3.2, the local working tree was clean. HEAD matched `2f59e117b47673994356f1547a6126a589005f03` (`Complete Phase 2 atomic checkout and inventory auditing`). The local schema, integrity queries, checkout implementation, README and Phase 1/2 documentation were reviewed before that change. Step 3.3 preserved the existing uncommitted Step 3.2 work. Historical results and execution logs remain preserved.

## Reporting Decisions

The measure is **recorded completed-order spending**, not verified revenue or cash collected. A completed status and a stored total do not establish payment settlement, and Phase 2 checkout creates pending reservations without processing payments.

| Decision | Reason |
| -------- | ------ |
| Normalize statuses with `LOWER(TRIM(status))`; include only `complete` and `completed`. | The historical extract contains case, whitespace and spelling variants. The agreed mapping recognizes those completed labels without rewriting them. |
| Use `orders.total_amount` as recorded. | This is the agreed order-level spending measure. Recalculating from items would replace historical totals despite unresolved discrepancies and missing line prices. |
| Preserve discrepant historical orders and add separate flags in later reporting. | A mismatch does not establish the correct replacement amount. This step neither repairs records nor filters them out because of line-item discrepancies. |
| Require a matching customer for the order-level base. | Unattributable completed orders must not be assigned to an unrelated customer. Their counts and amounts remain visible in reconciliation. |
| Identify customers by `customer_id`, irrespective of shared email addresses. | Duplicate normalized emails do not prove the customer records represent one person. No customer accounts are merged. |
| Use the exclusive cutoff `TIMESTAMP '2026-11-27 00:00:00'`. | This reproducible development boundary includes dates through November 26, 2026 and excludes dates at or beyond the cutoff. It does not rely on the execution date. |
| Do not impose a lower date boundary on the base. | Future lifetime spending must cover all eligible history before the cutoff. The monthly window will be applied separately later. |
| Keep NULL, zero and negative totals in otherwise eligible orders and count them separately. | No extra amount-based exclusion was agreed. Missing values must be visible rather than silently dropped or imputed. |

Missing order dates cannot satisfy the cutoff and are excluded from the base but reported separately. The schema stores `order_date` as `timestamp without time zone`, so this step compares it directly to the agreed timestamp literal without inventing a timezone conversion.

The agreed requirements for later steps are recorded here without implementation:

- Lifetime spending will cover all eligible completed-order history before the cutoff.
- Monthly output will cover 12 calendar months, including the partial current month, with zero-spending months represented. It will not mean a rolling 365-day interval.
- Customers without eligible completed orders will appear with zero spending and zero orders in the future customer-level output; they have no rows in the current order-level base.
- Running totals will be calculated at order level.
- The original top-100 assumption was deterministic tie-breaking among eligible purchasing customers. Step 3.6 below supersedes that tentative population with every existing customer, including zero-order customers, and compares three ranking methods before the business chooses a policy.

## SQL Implementation and Query Explanation

**SQL:** [report_base.sql](../report_base.sql)

The cutoff is defined once as the psql variable `reporting_cutoff`. Each query reads it through a small `report_parameters` CTE. It is fixed for this development run; later configurability can be introduced at that one definition.

The complete script runs in `BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY`. REPEATABLE READ gives the metric and reconciliation queries one consistent snapshot; READ ONLY prevents business-data writes. This is local to the reporting transaction and does not change the checkout/server default isolation. See [PostgreSQL 18 snapshot behavior](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-REPEATABLE-READ). The script creates no view, function, table or index, and prints no individual order/customer rows.

The execution header prints the database/user/cluster, transaction settings and cutoff to identify the target. The three business queries are:

1. **Base metrics.** `report_base` contains exactly `order_id`, `customer_id`, `order_date` and `total_amount`. It uses an `INNER JOIN` from orders to customers on `customer_id`, the normalized status filter and `order_date < cutoff`. It then prints eligible-order count, distinct purchasing-customer count, sum of known stored amounts, known/NULL/zero/negative amount counts, earliest/latest dates and duplicate order-ID rows. The duplicate metric is `COUNT(*) - COUNT(DISTINCT order_id)`, meaning surplus occurrences. The customer primary key prevents join multiplication; the metric verifies the observed result. There is no join to order items and no line-total recalculation.
2. **Exclusion reconciliation.** All normalized completed orders are classified once by an ordered `CASE`. Missing dates take first priority, dates at/beyond the cutoff second, and missing customer matches third. The remainder are eligible. This makes the four groups mutually exclusive and exhaustive, even when one order has several issues. A four-row group list preserves empty groups in the output. An independently aggregated total for all normalized completed orders appears beneath the groups.
3. **Validation assertions.** Independent source/base aggregates are compared against sums of the four classified groups. Checks cover order counts, known monetary amounts, NULL amounts, known-plus-NULL amount coverage, base/group eligible counts, amounts and NULLs, unique base order IDs and strictly pre-cutoff dates. Each prints `PASS` or `FAIL`. A failed check exits psql nonzero. Repeated CTE definitions keep the queries explicit and avoid persistent reporting objects; the cutoff remains centralized.

`SUM(total_amount)` ignores NULLs. The output therefore labels the value `recorded_spending_known_amounts` and includes both known and NULL counts. `COALESCE(SUM(...), 0)` supplies a zero known-amount sum for an empty/all-NULL group; it does not replace unknown order amounts with zero. Monetary reconciliation compares sums of known amounts and separately checks NULL coverage. An all-NULL nonempty group would be distinguished by its positive NULL count and zero known count.

## Execution Evidence

**Actual output:** [phase3_report_base_validation.txt](../tests/results/phase3_report_base_validation.txt)

The script was executed successfully with exit status 0 using the requested command:

```powershell
docker exec -w /lab -i kloudkart psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 -P pager=off -f report_base.sql
```

The observed connection matched the existing lab: container `kloudkart`, project mount `/lab`, database/user `postgres`, PostgreSQL `18.7 (Debian 18.7-1.pgdg13+5)` and cluster identifier `7712053334814294059`. The execution header confirmed `transaction_isolation = repeatable read`, `transaction_read_only = on` and cutoff `2026-11-27 00:00:00`. Evidence was saved under a new filename without overwriting earlier results.

## Observed Base Dataset

| Metric | Actual result |
| ------ | ------------- |
| Eligible completed orders | 111,195 |
| Distinct customers with eligible completed orders | 37,900 |
| Recorded completed-order spending, known amounts | 339,184,984.53 |
| Orders with known amounts | 111,195 |
| Orders with NULL amounts | 0 |
| Orders with zero amounts | 0 |
| Orders with negative amounts | 0 |
| Earliest eligible order timestamp | 2025-08-02 06:13:51 |
| Latest eligible order timestamp | 2026-10-07 18:49:00 |
| Duplicate order-ID rows | 0 |

No amount-based exclusion was applied. There were no NULL, zero or negative totals in this observed base. The 37,900 count includes only customers with eligible purchasing activity; this is not yet an all-customer report.

The latest eligible completed order is earlier than the cutoff by several weeks. That is an observed date boundary, not an extra filter and not evidence by itself of missing purchases or business inactivity. The base retains all otherwise eligible orders before the cutoff.

## Completed-Order Reconciliation

| Mutually exclusive group | Orders | Known amounts | NULL amounts | Recorded sum of known amounts |
| ------------------------ | -----: | ------------: | -----------: | ----------------------------: |
| Completed with missing order dates | 0 | 0 | 0 | 0.00 |
| Completed at or beyond the cutoff | 12 | 12 | 0 | 35,600.61 |
| Completed before cutoff with missing/nonexistent customers | 144 | 144 | 0 | 388,780.89 |
| Eligible completed before cutoff with matching customers | 111,195 | 111,195 | 0 | 339,184,984.53 |
| **All normalized completed orders** | **111,351** | **111,351** | **0** | **339,609,366.03** |

Count reconciliation:

```text
0 + 12 + 144 + 111,195 = 111,351
```

Known-amount monetary reconciliation:

```text
0.00 + 35,600.61 + 388,780.89 + 339,184,984.53 = 339,609,366.03
```

There are zero NULL amounts across all completed orders and all four groups, so the known sums cover every completed-order amount in this run. The SQL nevertheless verifies NULL counts explicitly rather than assuming this will remain true.

All 144 unattributable completed orders fall before this cutoff. Their aggregate count and amount agree with the all-date Phase 1 observation, while the 12 later completed orders explain the additional difference between the eligible base and all completed orders. In total, 156 completed orders and recorded amounts of 424,381.50 are outside the base for the documented reasons. Later dates remain preserved and are not declared incorrect merely because this report excludes them.

## Validation Results

| Executed check | Actual result |
| -------------- | ------------- |
| Completed-order count reconciliation | PASS |
| Known-amount monetary reconciliation | PASS |
| NULL-amount count reconciliation | PASS |
| Known-plus-NULL amount coverage | PASS |
| Eligible-group versus base order count | PASS |
| Eligible-group versus base spending | PASS |
| Eligible-group versus base NULL amounts | PASS |
| Unique order IDs in the base | PASS |
| Base dates strictly before cutoff | PASS |
| Overall reporting-base validation | PASS |

These results were observed from the actual database execution; no numeric outcome was assumed in advance or hardcoded into the checks. No failing validation or unexpected monetary anomaly occurred.

## Housekeeping, Preservation and Limits

The README now marks Phase 2 complete and Phase 3 in progress, includes the current implementation/test files and explains checkout definition, isolated verification and reporting execution. `phase1_results.md` labels original schema observations as historical and updates current status. `phase2_identity.md` distinguishes the identity-stage absence of checkout/race execution from the subsequently completed implementation. All historical numeric observations and intermediate execution logs were retained.

`checkout.sql`, `place_order.sql` and `race_test.py` were not modified. SHA-256 verification confirmed those files and all pre-existing execution evidence were unchanged. No historical client data was modified, no CSV records were read, no database initialization was run, and no commit or push was performed.

The base intentionally retains unresolved stored-total discrepancies; separate discrepancy flags remain for later reporting. The schema and this step do not verify payment settlement or assign a currency/conversion policy. No claim is made that payment processing, reservation expiry, cancellation, permanent foreign-key enforcement or arbitrary-update inventory auditing exists.

The fixed cutoff makes the date boundary reproducible; it does not freeze later source-data edits across separate executions. REPEATABLE READ made the Step 3.2 execution internally consistent. At that stage, monthly grids, all-customer zero rows, lifetime customer totals, order-level running totals, deterministic top-100 ranking and performance optimization were unimplemented. Step 3.2 stopped for approval before customer-level aggregation; the subsequently authorized Step 3.3 is documented below.

## Step 3.3: Customer-Level Total Spending and Completed-Order Counts

### Objective and Granularity

Produce exactly one row per existing `customer_id`, including customers without eligible completed orders. Calculate lifetime recorded completed-order spending before the same exclusive cutoff, `2026-11-27 00:00:00`, without grouping or merging customers by email/name. There is no lower date boundary and no new status, amount or line-item eligibility filter.

**Reusable SQL:** [customer_spending.sql](../customer_spending.sql)

**Aggregate-only verifier:** [verify_customer_spending.py](../tests/verify_customer_spending.py)

**Actual execution evidence:** [phase3_customer_spending_c2b86904be69.txt](../tests/results/phase3_customer_spending_c2b86904be69.txt)

The reusable query returns `customer_id`, `total_recorded_spending`, `completed_order_count` and `missing_amount_count`. Its direct output is intended for private local use. The verifier embeds that exact query in aggregate-only statements; it never prints individual customer IDs, names, emails, order details or spending rows.

### SQL Implementation and Aggregation Reasoning

The three CTEs are:

1. `report_parameters` defines the same cutoff once for this reusable query. The verifier checks that it equals the Step 3.2 cutoff.
2. `report_base` retains the exact eligibility CTE from Step 3.2: orders INNER JOIN customers on `customer_id`, normalized `complete`/`completed` status and strictly pre-cutoff order dates. The verifier compares the two CTE definitions after whitespace normalization and fails on divergence. Totals come from `orders.total_amount`; there is no join to order items.
3. `customer_spending` starts with every customer, LEFT JOINs the eligible order base and groups by `customer_id`. `SUM` adds known recorded amounts, `COUNT(b.order_id)` counts real eligible orders, and a filtered count records eligible orders whose amounts are NULL.

The LEFT JOIN preserves customers without matching eligible orders. An INNER JOIN at this stage would remove those customers. An unmatched LEFT JOIN still produces a NULL-extended row, so `COUNT(*)` would incorrectly return one order for a customer with none. `COUNT(b.order_id)` returns zero because the unmatched order ID is NULL. The missing-amount count also counts non-null order IDs, so this placeholder row is not mistaken for an order with an unknown amount.

`COALESCE(SUM(b.total_amount), 0)` makes spending zero when no known amounts exist. The spending column is therefore the sum of **known recorded completed-order amounts**, not an imputation of unknown amounts:

- No eligible orders: spending 0, order count 0, missing count 0.
- Eligible orders with only NULL amounts: known spending 0, positive order count and positive missing count; actual complete monetary spending remains unknown.
- Mixed known and NULL amounts: spending is the known subtotal, order count includes all eligible orders, and missing count identifies incomplete monetary coverage.

A zero-order customer is identified by `completed_order_count = 0`, not by spending being zero. Zero and negative recorded amounts remain eligible; a net zero spending amount can also occur for customers who have orders. No source values are changed.

### Execution and Independent Reconciliation

Executed successfully, exit status 0:

```powershell
python tests/verify_customer_spending.py
```

The verifier uses Python's standard library and Docker's `psql` with `ON_ERROR_STOP=1`. It sends the live and synthetic queries inside one read-only REPEATABLE READ transaction with a 60-second statement timeout and a bounded subprocess timeout. The execution header verified database/user `postgres`, cluster `7712053334814294059`, isolation `repeatable read`, read-only `on` and the unchanged cutoff. No database objects or fixture records are created.

The live report is evaluated as a CTE rather than exported. Independent eligible-order queries read raw orders with the agreed status/date filters and `EXISTS` for the customer reference. They compute both overall totals and separate per-customer expected totals. Assertions compare every report customer's count, known sum and missing count against that independent grouping within the same snapshot. Thus a passing result does not depend only on historical hard-coded totals, nor could an incorrect allocation between customers hide behind an unchanged grand total.

The expected historical values are additional baseline checks. A changed source dataset would be reported as a baseline mismatch for review even if its live structural reconciliation still passed. The script reports failing checks clearly and exits nonzero on SQL errors, baseline differences or failed assertions. Every execution writes a unique new evidence file.

### Expected Versus Actual Aggregate Results

| Metric | Expected | Actual | Result |
| ------ | -------: | -----: | ------ |
| Total customer rows | 40,420 | 40,420 | PASS |
| Distinct customer IDs | 40,420 | 40,420 | PASS |
| Customers with eligible orders | 37,900 | 37,900 | PASS |
| Customers without eligible orders | 2,520 | 2,520 | PASS |
| Sum of completed-order counts | 111,195 | 111,195 | PASS |
| Sum of recorded customer spending | 339,184,984.53 | 339,184,984.53 | PASS |
| Duplicate customer IDs | 0 | 0 | PASS |
| Missing eligible order amounts | 0 | 0 | PASS |
| Customers with unknown amounts | 0 | 0 | PASS |

The last two expectations follow the previously observed zero NULL amounts in the Step 3.2 base. They were checked again against the live data; missing-value behavior was also tested synthetically because the live dataset does not exercise it.

### Live Assertion Results

| Executed assertion | Actual result |
| ------------------ | ------------- |
| Every existing customer appears exactly once | PASS |
| No nonexistent customer appears | PASS |
| No-order customers have zero spending, order count and missing count | PASS |
| Purchasing-customer count matches live eligible orders | PASS |
| Order counts reconcile to live eligible orders | PASS |
| Spending reconciles to live eligible orders | PASS |
| Missing amounts reconcile to live eligible orders | PASS |
| Every customer matches independent grouped eligible orders | PASS |
| Eligible order identifiers are unique | PASS |

The report covers 40,420 distinct customer IDs, with 37,900 purchasing and 2,520 nonpurchasing customers. The summed order counts and known spending equal the live eligible-order totals. Per-customer comparison and order-ID uniqueness also passed, providing observed evidence that joins did not multiply order totals or move spending between customers.

### VALUES-Based Synthetic Test Results

The verifier reuses the same production SQL inside a scope where `customers` and `orders` are VALUES-based CTEs. It uses six artificial customers and fifteen artificial orders, including two customers with the same synthetic email. These CTEs shadow the live relations only inside that test query. Results are reduced to PASS/FAIL checks before leaving PostgreSQL; no synthetic individual spending rows are printed.

| Test ID | Scenario | Actual result |
| ------- | -------- | ------------- |
| SYN-01 | Multiple orders, normalized statuses and history before the current reporting year | PASS |
| SYN-02 | Customer without any orders receives zero values | PASS |
| SYN-03 | All-NULL eligible amounts are distinct from no eligible orders | PASS |
| SYN-04 | Mixed known/NULL amounts retain known sum and missing count | PASS |
| SYN-05 | Zero and negative recorded totals remain eligible | PASS |
| SYN-06 | A customer with only ineligible orders still receives a zero row | PASS |
| SYN-07 | Complete expected-row equality and uniqueness after cutoff, missing-date, status and orphan exclusions | PASS |
| SYN-08 | Known spending, order counts and missing counts reconcile | PASS |
| SYN-09 | Shared email does not merge customer IDs | PASS |

The boundary fixture includes an order immediately before the cutoff, one exactly at it and one after it. Missing dates, NULL/blank/cancelled/pending statuses and an unmatched customer reference are also exercised. The aggregate synthetic expectations were known spending 32.50, seven eligible orders and two missing amounts; all matched. VALUES fixtures leave no records or test objects requiring cleanup.

### Preservation, Git Scope and Limitations

Created `customer_spending.sql`, the aggregate-only verifier and its new execution evidence. Extended this document and updated the README descriptions, structure and reporting instructions. Existing uncommitted Step 3.2 SQL and documentation changes were preserved. SHA-256 verification confirmed `report_base.sql`, the checkout/identity implementations, `race_test.py`, the Phase 1/identity documentation and every pre-existing execution-evidence file were unchanged during this step.

No historical records or schema objects were modified, no CSV records or credentials were read, no initial setup was rerun, and no commit or push was performed. There were no unexpected findings or execution failures. The verified spending measure remains recorded completed-order spending rather than payment settlement or verified revenue; historical discrepancies are preserved.

Consumers must examine `missing_amount_count` before treating a spending value as complete. The fixed cutoff does not freeze source-data changes between separate runs. At completion of Step 3.3, monthly spending, running totals, rankings and performance optimization remained unimplemented. Step 3.3 stopped for approval before the subsequently authorized monthly step below.

## Step 3.4: Monthly Customer Spending

### Objective, Window and Grain

Provide exactly one row per existing customer per reporting month, including every zero-activity month, with recorded known spending, completed-order count and missing-amount count. Lifetime spending and eligibility remain unchanged. The current window is:

- Inclusive start: `2025-12-01 00:00:00`.
- Exclusive end: `2026-11-27 00:00:00`.
- Twelve month labels: December 2025 through November 2026, with November partial.

The window consists of the last twelve calendar months containing timestamps before the exclusive cutoff, rather than a rolling 365-day interval. The last month is derived from `DATE_TRUNC('month', cutoff - INTERVAL '1 microsecond')`; the start is eleven calendar months before that month. PostgreSQL timestamps have one-microsecond resolution, so subtracting one microsecond selects the last representable instant before the cutoff. A cutoff exactly at month start therefore selects the previous month. See [PostgreSQL timestamp resolution](https://www.postgresql.org/docs/18/datatype-datetime.html).

For example, a cutoff of `2026-11-01 00:00:00` produces November 2025 through October 2026, not a zero-length November 2026 month. A January 1 cutoff similarly ends with the previous December. Both interpretations were tested. The source timestamps remain without time zone; this implementation adds no timezone conversion.

**Reusable SQL:** [monthly_spending.sql](../monthly_spending.sql)

**Aggregate-only verifier:** [verify_monthly_spending.py](../tests/verify_monthly_spending.py)

**Actual evidence:** [phase3_monthly_spending_4d0cc4a5486f.txt](../tests/results/phase3_monthly_spending_4d0cc4a5486f.txt)

The report columns are `customer_id`, `spending_month` (a month-start date), `monthly_recorded_spending`, `completed_order_count` and `missing_amount_count`. Direct query output is confidential and intended for private local use. Only aggregate summaries and assertions were returned during verification.

### SQL CTEs and Join Reasoning

1. `report_parameters` contains the single cutoff definition for the reusable query.
2. `month_anchor` derives the final reporting month from the exclusive cutoff.
3. `report_window` derives the inclusive start by subtracting eleven months and retains the cutoff/final month.
4. `report_base` preserves the exact Step 3.2 eligibility CTE: normalized `complete`/`completed`, matching customer and order date before cutoff. The verifier checks the cutoff and eligibility definition against both previous reporting scripts.
5. `reporting_months` uses `GENERATE_SERIES` with a one-month interval from the inclusive window start through the final month. It emits twelve month-start dates.
6. `windowed_orders` keeps eligible orders at or after the monthly window start and before the cutoff. Older eligible orders remain part of the unchanged lifetime query.
7. `monthly_totals` groups order records by `customer_id` and `DATE_TRUNC('month', order_date)::date`, summing known amounts and counting orders/missing amounts.
8. `customer_month_grid` intentionally CROSS JOINs all customers with the twelve months. The final LEFT JOIN adds the already aggregated monthly values and fills absent cells with zeros.

`DATE_TRUNC` supplies one common calendar-month key; `GENERATE_SERIES` supplies months even when no order exists. See [PostgreSQL date truncation](https://www.postgresql.org/docs/18/functions-datetime.html#FUNCTIONS-DATETIME-TRUNC) and [series generation](https://www.postgresql.org/docs/18/functions-srf.html).

The CROSS JOIN is intentional at the customer/month grain. Individual orders are aggregated before this grid join; they are never cross joined to all twelve month rows. The monthly totals have one row per active customer-month, so joining on both keys does not duplicate orders or spending. No persistent report object, explicit materialization, index or performance tuning was introduced.

### Zero Activity and Missing Monetary Amounts

Absent monthly aggregates become spending 0, order count 0 and missing count 0. An existing all-NULL monthly aggregate has known spending 0 but positive order/missing counts. Mixed known/NULL amounts produce a known subtotal with a positive missing count. This preserves the Step 3.3 distinction between no purchases and unknown monetary coverage.

Zero and negative order totals remain eligible. Counts use order IDs; missing amounts are counted explicitly. A zero spending value by itself does not prove a month had no orders or that all its amounts are known. No order total is corrected, recomputed from items or filtered because of its amount.

### Execution and Expected Versus Actual Shape

Executed with exit status 0:

```powershell
python tests/verify_monthly_spending.py
```

The verifier uses Docker's `psql`, `ON_ERROR_STOP=1`, a read-only REPEATABLE READ transaction, a 60-second statement timeout and a bounded subprocess timeout. The header confirmed database/user `postgres`, cluster `7712053334814294059`, isolation `repeatable read`, read-only `on`, the unchanged cutoff and derived start `2025-12-01 00:00:00`.

| Metric | Expected | Actual | Result |
| ------ | -------- | ------ | ------ |
| Distinct customers | 40,420 | 40,420 | PASS |
| Reporting months | 12 | 12 | PASS |
| Customer-month rows | 485,040 | 485,040 | PASS |
| Minimum rows per customer | 12 | 12 | PASS |
| Maximum rows per customer | 12 | 12 | PASS |
| Duplicate customer-month keys | 0 | 0 | PASS |
| Earliest month | 2025-12-01 | 2025-12-01 | PASS |
| Latest month | 2026-11-01 | 2026-11-01 | PASS |

These historical expectations are additional checks. The verifier independently derives a reference window using an explicit month-start `CASE`, builds expected grid keys from live customers and independently aggregates raw eligible orders with `EXISTS` for customer references. All reference queries operate on sets and grouped rows, not per-grid-row correlated scans. The exact reusable monthly and lifetime SQL are embedded unchanged in the same snapshot.

### Actual Twelve-Month Aggregate Summary

| Reporting month | Eligible completed orders | Recorded spending | Purchasing customers | Missing amounts |
| --------------- | ------------------------: | ----------------: | -------------------: | --------------: |
| 2025-12-01 | 3,836 | 11,773,386.73 | 3,645 | 0 |
| 2026-01-01 | 5,153 | 16,816,058.30 | 4,842 | 0 |
| 2026-02-01 | 5,326 | 16,086,645.57 | 4,974 | 0 |
| 2026-03-01 | 7,055 | 21,837,074.59 | 6,467 | 0 |
| 2026-04-01 | 9,976 | 30,080,595.04 | 8,839 | 0 |
| 2026-05-01 | 11,715 | 35,751,841.28 | 10,188 | 0 |
| 2026-06-01 | 15,537 | 47,361,107.98 | 12,971 | 0 |
| 2026-07-01 | 18,570 | 56,633,957.32 | 14,899 | 0 |
| 2026-08-01 | 25,290 | 76,665,230.57 | 18,851 | 0 |
| 2026-09-01 | 4 | 6,379.64 | 4 | 0 |
| 2026-10-01 | 1 | 1,768.01 | 1 | 0 |
| 2026-11-01 | 0 | 0.00 | 0 | 0 |

Purchasing-customer counts are distinct within each month; adding them does not produce a distinct customer count for the whole window. November has zero eligible orders, zero spending and zero missing amounts in the actual snapshot. This was observed rather than forced into the SQL or asserted as a historical requirement.

The sharp decline after August is also visible: September has four eligible orders and October one. These are aggregate observations under the agreed eligibility rules, not evidence by themselves of missing data or business inactivity. No additional records were removed to obtain these results.

### Monthly and Lifetime Reconciliation

| Eligible history partition | Orders | Recorded known spending | Missing amounts |
| -------------------------- | -----: | ----------------------: | --------------: |
| Before 2025-12-01 | 8,732 | 26,170,939.50 | 0 |
| Within monthly window | 102,463 | 313,014,045.03 | 0 |
| Lifetime before cutoff | 111,195 | 339,184,984.53 | 0 |

```text
8,732 + 102,463 = 111,195 eligible completed orders
26,170,939.50 + 313,014,045.03 = 339,184,984.53 recorded spending
0 + 0 = 0 missing monetary amounts
```

The full monthly report reconciled with independent grouped window orders, and each customer's monthly totals plus that customer's eligible pre-window amounts/counts matched the actual Step 3.3 query. The lifetime SQL was not changed. The eight live shape expectations, nineteen live assertions and seventeen synthetic tests all passed.

### Live Assertion Results

| Executed assertion | Actual result |
| ------------------ | ------------- |
| Row count equals live customer count times twelve | PASS |
| Every existing customer-month key is present | PASS |
| No extra customer-month keys | PASS |
| Exactly twelve rows and distinct months per customer | PASS |
| No duplicate customer-month keys | PASS |
| No nonexistent customers | PASS |
| Twelve derived months and correct endpoints | PASS |
| No months outside the derived window | PASS |
| No-purchase cells have correct zero values | PASS |
| Monthly order counts match independent eligible window orders | PASS |
| Monthly spending matches independent eligible window orders | PASS |
| Monthly missing amounts match independent eligible window orders | PASS |
| Every customer-month matches the independently grouped reference | PASS |
| Every eligible window order belongs to exactly one reporting month | PASS |
| Before plus within spending equals lifetime | PASS |
| Before plus within orders equals lifetime | PASS |
| Before plus within missing amounts equals lifetime | PASS |
| Actual Step 3.3 totals match independent lifetime orders | PASS |
| Actual Step 3.3 report reconciles per customer with pre-window plus monthly | PASS |

Failures produce a nonzero verifier exit status. Evidence consists only of shape metrics, monthly aggregate summaries, reconciliation totals and test outcomes, not the full 485,040-row report.

### VALUES-Based Synthetic Test Results

The verifier embeds the actual production SQL with VALUES-based customers/orders that shadow the live relations only in the synthetic query. Alternative-cutoff scenarios change only the centralized timestamp literal, leaving month derivation and aggregation unchanged. No client records or test objects are created.

| Test ID | Scenario | Actual result |
| ------- | -------- | ------------- |
| MONTH-SYN-01 | Multiple completed orders and normalized statuses in the same month | PASS |
| MONTH-SYN-02 | Orders in different months and December-to-January boundary | PASS |
| MONTH-SYN-03 | Customer without orders has twelve zero cells | PASS |
| MONTH-SYN-04 | Missing months between purchases are zero-filled | PASS |
| MONTH-SYN-05 | All-NULL amounts retain positive order and missing counts | PASS |
| MONTH-SYN-06 | Mixed known/NULL amounts retain subtotal and missing count | PASS |
| MONTH-SYN-07 | Zero and negative totals remain eligible | PASS |
| MONTH-SYN-08 | Immediately pre-window order contributes only to lifetime | PASS |
| MONTH-SYN-09 | Order exactly at inclusive window start is included | PASS |
| MONTH-SYN-10 | Order immediately before cutoff is included | PASS |
| MONTH-SYN-11 | At/after-cutoff orders, invalid statuses/dates and missing customers excluded | PASS |
| MONTH-SYN-12 | Only-ineligible-order customer has twelve zero cells | PASS |
| MONTH-SYN-13 | Full expected synthetic grid has exactly one row per key | PASS |
| MONTH-SYN-14 | Monthly and lifetime spending/order/missing counts reconcile | PASS |
| MONTH-SYN-15 | Leap-year February and exclusive March-start cutoff | PASS |
| MONTH-SYN-16 | Month-start cutoff ends with the previous month | PASS |
| MONTH-SYN-17 | January-start cutoff ends with the previous December/year | PASS |

The main fixtures expected monthly spending 45.50 across nine orders with two missing amounts, plus earlier spending 50.00 across one order. Lifetime expectations were 95.50, ten orders and two missing amounts. Exact expected-grid comparisons also passed. The leap-year case included February 29, 2024 and excluded March 1 at the cutoff. The alternate month-start case expected November 2025 through October 2026; the year-start case expected January through December 2025. All matched actual execution.

### Preservation, Scope and Limitations

Created `monthly_spending.sql`, `tests/verify_monthly_spending.py` and the unique aggregate evidence file linked above. Updated this document and the README while preserving earlier observations and all existing uncommitted work. SHA-256 checks confirmed the previous reporting SQL/verifier, checkout implementation, race harness, Phase 1/identity documents and every prior evidence file were unchanged. Documentation links and whitespace checks passed.

No historical data, permanent database objects or indexes were modified; no schema/load script was rerun. VALUES fixtures require no cleanup because no records or objects were created. No full customer-month output or identifiable spending records were printed or saved. No credentials or confidential CSV records were read, and nothing was committed or pushed. No unexpected execution failures occurred.

Amounts remain recorded completed-order spending, not verified revenue or cash collected. Consumers must inspect missing-amount counts before treating subtotals as complete. The cutoff is fixed for development, and separate runs may observe later source edits. Source timestamps remain without time zone. At completion of Step 3.4, running totals, rankings and performance optimization were unimplemented, and work stopped for approval before the subsequently authorized running-total step below.

## Step 3.5: Running Customer Totals and Window-Function Practice

### Objective and Query Grain

Retain exactly one row per eligible completed order while calculating cumulative known spending, missing-amount counts, order counts, previous-order dates, calendar-day gaps and a lifetime-spending RANK. The unchanged cutoff is `2026-11-27 00:00:00`, exclusive. Running totals cover all eligible history, including orders before the twelve-month window.

**Reusable SQL:** [running_customer_totals.sql](../running_customer_totals.sql)

**Aggregate-only verifier:** [verify_running_totals.py](../tests/verify_running_totals.py)

**Actual evidence:** [phase3_running_totals_a712c38901fb.txt](../tests/results/phase3_running_totals_a712c38901fb.txt)

The output includes the requested customer/order/date/amount fields, `running_recorded_spending`, `running_missing_amount_count`, `previous_order_date`, `days_since_previous_order` and `customer_total_spend_rank`. It also includes `running_order_count` for position/final-count verification and `date_peer_recorded_spending` as a diagnostic. Direct order-level output is confidential; only aggregates were returned during testing.

### CTEs and Window Functions

`report_parameters` defines the cutoff. `report_base` retains the exact earlier eligibility CTE. `customer_spending` retains the Step 3.3 customer-total definition, including every customer and zero-order customers. `customer_ranks` applies `RANK() OVER (ORDER BY total_recorded_spending DESC)` to those totals. `order_windows` calculates windows over the full eligible order base, then the final query joins each order to its customer's rank.

A running total is the accumulated known spending through the current order in that customer's chronology. A regular grouped aggregate would collapse multiple orders into a single row; window aggregates preserve each order. The separate grouped customer-total CTE exists only to supply ranks and does not replace or collapse the final order-level output. See [PostgreSQL window-function tutorial](https://www.postgresql.org/docs/18/tutorial-window.html).

`PARTITION BY customer_id` restarts calculations for each customer. `ORDER BY order_date, order_id` establishes chronology and deterministically breaks timestamp ties. The named `customer_order` window holds that shared specification. `customer_rows` extends it with `ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`; this includes each individual ordered row through the current row. Spending, missing counts and order counts reuse that explicit frame. `LAG(order_date)` reuses `customer_order`. Named windows avoid repeating ordering specifications that could otherwise diverge.

`date_peers` uses `ORDER BY order_date RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`. It includes the current timestamp's entire peer group, including peers that follow the current row under the deterministic order-ID ordering. Explicit frames make that distinction visible rather than depending on a default. Here `order_date` is a full timestamp: orders on the same calendar day with different times are not RANGE peers. The ROWS result remains the main per-order cumulative measure.

`LAG` returns the preceding eligible order timestamp, or NULL for the first order. The gap is `order_date::date - previous_order_date::date`, so it counts calendar-day boundaries rather than elapsed 24-hour periods. Two minutes across midnight gives one day; different times on one calendar day give zero. First-order dates and gaps remain NULL.

RANK preserves equal spending values and leaves gaps after ties. The rank ordering deliberately has no customer-ID tie-breaker. All existing customers, including zero-order customers, participate before ranks are joined to purchasing orders. No top-100 filter or final ranking-function decision was introduced. See [PostgreSQL LAG, RANK and peer behavior](https://www.postgresql.org/docs/18/functions-window.html).

### Unknown, Zero and Negative Amounts

`COALESCE(SUM(total_amount) OVER customer_rows, 0)` retains the established known-amount semantics: an all-NULL prefix has known spending zero, accompanied by a positive running missing count. This does not assert that the unknown amounts were actually zero. Mixed known/NULL prefixes retain a known subtotal and explicit missing count.

Zero and negative amounts remain eligible. A running sum may decrease when a negative recorded amount is encountered; monotonic growth is not assumed. Ranks use the same known spending definition and are not payment/revenue verification. The report's running missing count is prefix-specific, while customer rank uses the entire lifetime known total before cutoff.

### Execution and Expected Versus Actual Results

Executed successfully with exit status 0:

```powershell
python tests/verify_running_totals.py
```

The verifier checked cutoff consistency across base/lifetime/monthly/running scripts and exact eligibility/customer-total CTE consistency. It embedded the actual running query, the unchanged Step 3.3 query and the actual all-customer rank CTE in aggregate-only SQL. Live and VALUES tests shared one read-only REPEATABLE READ transaction, using `ON_ERROR_STOP=1`, bounded statement/subprocess timeouts and a unique evidence filename.

The connection header confirmed database/user `postgres`, cluster `7712053334814294059`, isolation `repeatable read`, read-only `on` and the unchanged cutoff.

| Metric | Expected | Actual | Result |
| ------ | -------: | -----: | ------ |
| Eligible order rows | 111,195 | 111,195 | PASS |
| Distinct order IDs | 111,195 | 111,195 | PASS |
| Purchasing customers | 37,900 | 37,900 | PASS |
| Duplicate order IDs | 0 | 0 | PASS |
| Missing order amounts | 0 | 0 | PASS |
| Customers included in RANK | 40,420 | 40,420 | PASS |

The historical values are additional baseline checks. Independent live references determine eligibility and correctness in the same snapshot rather than relying only on these constants.

### ROWS Versus RANGE: Actual Findings and Synthetic Demonstration

| Aggregate diagnostic | Actual result |
| -------------------- | ------------: |
| Customers with exact-timestamp order ties | 0 |
| Customers with multiple orders on one calendar day | 651 |
| Customers with ROWS/RANGE differences | 0 |
| Order rows affected by ROWS/RANGE differences | 0 |
| Real-data frame difference observed | No |

No suitable exact-timestamp peer group occurred in the live eligible base. The 651 calendar-day ties do not produce a difference because their order timestamps differ. The implementation does not cast timestamps to dates for RANGE ordering.

The VALUES fixture therefore demonstrates the distinction explicitly. Two synthetic orders share a timestamp and have amounts 10 and 20, ordered by increasing synthetic order ID. Their ROWS sums are 10 then 30, while both RANGE sums are 30. A later synthetic order on the same day at a different time adds 5: its sum is 35, while the earlier peer group's RANGE sum remains 30. One synthetic customer and one order row differ between the frames. These are artificial example amounts, not client transaction values.

### Independent Validation Approach

Raw eligible orders use the agreed status/date rules with `EXISTS` for customer references. A reference chronology supplies each order's expected position and preceding order ID. Set joins then verify the recurrence `current known sum = previous known sum + current known amount`, using zero only as the additive contribution to the known subtotal for an unknown amount. A separate recurrence tracks missing counts. Correct first values plus every transition establish the full chronological running sequence without a correlated cumulative sum per row.

The reference chronology also supplies expected LAG timestamps and calendar gaps. Each customer's final row is compared with Step 3.3 spending, missing count and order count. RANGE is checked independently by first grouping exact timestamp peers and then cumulatively adding those grouped peer sums.

Rank reference totals include all customers. Instead of repeating RANK, the verifier groups equal spending into buckets and calculates each bucket's rank as one plus the number of customers in higher-spending buckets. It compares those expectations with the actual rank CTE for every customer and checks the order-level rank joins. There were 1,080 all-customer spending tie groups; all preserved equal ranks. This count is aggregate evidence and does not expose the tied spending values or customer IDs.

### Live Assertion Results

| Executed assertion | Actual result |
| ------------------ | ------------- |
| Every eligible order appears exactly once | PASS |
| No ineligible order or altered source values appear | PASS |
| No nonexistent customer appears | PASS |
| No NULL date or order at/beyond cutoff appears | PASS |
| First running known spending and missing count are correct | PASS |
| Deterministic chronological positions are correct | PASS |
| Known running spending satisfies independent recurrence | PASS |
| Running missing count satisfies independent recurrence | PASS |
| Final spending matches Step 3.3 for every purchasing customer | PASS |
| Final missing counts match Step 3.3 | PASS |
| Final order counts match Step 3.3 | PASS |
| Previous dates match preceding eligible orders | PASS |
| Calendar-day gaps are correct | PASS |
| First orders have NULL previous dates and gaps | PASS |
| All-customer ranks match independent spending-bucket counts | PASS |
| Order-level rank joins match the actual customer rank CTE | PASS |
| Equal spending totals receive equal RANK values | PASS |
| RANGE matches independently grouped timestamp peers | PASS |
| No order maps to multiple customers or positions | PASS |

All nineteen live assertions and six baseline comparisons passed. Assertions fail the process on SQL errors or mismatches; no individual order/customer data is printed or saved.

### VALUES-Based Synthetic Results

The actual SQL runs against eight artificial customers and twenty-one VALUES order rows, with twelve eligible orders. Exact expected-row comparisons cover cumulative spending/counts, LAG dates/gaps, ranks and RANGE values without exporting those rows. All fixture objects exist only as query CTEs.

| Test ID | Scenario | Actual result |
| ------- | -------- | ------------- |
| RUN-SYN-01 | Multiple chronological orders retain individual running values | PASS |
| RUN-SYN-02 | Different customer partitions accumulate independently | PASS |
| RUN-SYN-03 | Same-timestamp ties use order ID despite shuffled fixture input | PASS |
| RUN-SYN-04 | RANGE includes the full exact-timestamp peer group | PASS |
| RUN-SYN-05 | Same calendar day/different timestamps are not one peer group | PASS |
| RUN-SYN-06 | Single-order customer has NULL first LAG and gap | PASS |
| RUN-SYN-07 | Same-day and same-timestamp gaps are zero | PASS |
| RUN-SYN-08 | Multi-day gap uses calendar-day subtraction | PASS |
| RUN-SYN-09 | Two minutes across midnight gives one calendar day | PASS |
| RUN-SYN-10 | All-NULL amounts retain known zero and increasing missing count | PASS |
| RUN-SYN-11 | Mixed known/NULL amounts retain subtotal and missing count | PASS |
| RUN-SYN-12 | Zero/negative amounts remain and can decrease running spending | PASS |
| RUN-SYN-13 | RANK preserves spending ties and subsequent rank gaps | PASS |
| RUN-SYN-14 | Zero-order customers affect ranks but have no order-output rows | PASS |
| RUN-SYN-15 | Ineligible statuses/dates and missing references are excluded | PASS |
| RUN-SYN-16 | Just-before cutoff is included; exact/after cutoff excluded | PASS |
| RUN-SYN-17 | History older than the monthly window remains in cumulative totals | PASS |
| RUN-SYN-18 | Full expected running/LAG/RANK/RANGE rows match | PASS |
| RUN-SYN-19 | Synthetic frame difference affects one customer and one row | PASS |
| RUN-SYN-20 | Final known spending/missing/order counts match Step 3.3 | PASS |

All twenty synthetic tests passed. The synthetic lifetime totals were known spending 95, twelve eligible orders and three missing amounts. Zero-order customers were included in rank validation: their zero totals rank above a synthetic negative-spending purchaser, demonstrating that rank input is not restricted to purchasing customers.

### Preservation, Scope and Limitations

Created `running_customer_totals.sql`, `tests/verify_running_totals.py` and the unique aggregate evidence file. Updated the README and this document while preserving prior implementations, historical results and existing uncommitted work. SHA-256 checks confirmed all previous reporting SQL/verifiers, protected checkout files, Phase 1/identity documents and prior evidence were unchanged. Syntax, whitespace and documentation-link checks passed.

No historical records, schema objects or permanent database objects were changed. No schema/load script, optimization, commit or push was performed. VALUES fixtures require no cleanup and contain no client data. There were no unexpected execution failures.

The live dataset cannot independently demonstrate a frame difference because it has no eligible exact-timestamp ties; the synthetic test supplies that evidence. Unknown monetary values require missing-count interpretation. Calendar-day gaps use the existing timestamp-without-time-zone dates. The fixed cutoff does not freeze edits across separate executions. RANK here is a learning exercise over known lifetime totals, not the final choice for Nana's top-100 report. Work stops after Step 3.5; Step 3.6 remains unimplemented pending approval.

## Step 3.6: Top-100 Customer Ranking Comparison

### Purpose, Population and Spending Measure

Compare the evidence for Nana's top-customer list before choosing whether it must contain exactly 100 customers or retain everyone tied at the qualifying boundary. This step implements an aggregate comparison only. The final policy and the combined reporting components have not been implemented.

**Reusable aggregate SQL:** [top_100_ranking_analysis.sql](../top_100_ranking_analysis.sql)

**Verifier:** [verify_top100_ranking.py](../tests/verify_top100_ranking.py)

**Actual execution evidence:** [phase3_top100_ranking_comparison_4da05907c540.txt](../tests/results/phase3_top100_ranking_comparison_4da05907c540.txt)

The ranking input has one row per existing `customer_id`: 40,420 rows, including 37,900 customers with eligible orders and 2,520 without. This explicitly supersedes the early purchasing-only assumption. Customer identity is not inferred from names, emails or telephone numbers. Zero-order customers retain zero spending/counts and remain in the population; a synthetic negative-total customer ranks below them.

The `report_base` and `customer_spending` CTEs are unchanged copies of the established definitions. Verification rejects divergence from prior eligibility, cutoff and customer-total CTEs. Orders qualify only when `LOWER(TRIM(status))` is `complete` or `completed`, the timestamp is strictly before `2026-11-27 00:00:00`, and the customer exists. Spending uses stored `orders.total_amount` over all eligible history with no lower date limit. Lifetime spending measures accumulated recorded completed-order activity; applying the monthly window would answer a different question and can change customer order.

Historical discrepancies, NULLs, zeros and negatives are not repaired or excluded. `missing_amount_count` remains in the customer CTE and internal ranking rows; its aggregate is exposed as `missing_eligible_order_amounts` (observed: zero). The known-amount sum follows Step 3.3: an empty or all-NULL group has zero known spending, while its order/missing counts preserve the distinction. These are recorded amounts, not verified revenue or cash collected; payment settlement and currency conversion are not established here.

### Implementation and Ranking Semantics

`customer_rankings` calculates all three methods before any top-100 condition. Its internal columns include customer ID, lifetime recorded spending, completed-order count, missing-amount count and the three ranking values. Only aggregate counts, the requested boundary amount/ranks and a boundary-crossing indicator leave the query.

```sql
ROW_NUMBER() OVER (
    ORDER BY total_recorded_spending DESC, customer_id ASC
) AS row_number_position,
RANK() OVER (
    ORDER BY total_recorded_spending DESC
) AS spending_rank,
DENSE_RANK() OVER (
    ORDER BY total_recorded_spending DESC
) AS spending_dense_rank
```

| Method | Tie behavior | Meaning of a value <= 100 |
| ------ | ------------ | ------------------------ |
| ROW_NUMBER | Unique sequential positions; ascending customer ID determines the order of equal totals. | Exactly 100 customers when at least 100 exist. A boundary tie can be split. |
| RANK | Equal spending receives the same rank; subsequent ranks skip positions occupied by ties. For totals 50, 50, 20, ranks are 1, 1, 3. | Customers whose spending group begins within the first 100 positions. Boundary ties are retained, so more than 100 can qualify. |
| DENSE_RANK | Equal spending receives the same rank without gaps. For totals 50, 50, 20, ranks are 1, 1, 2. | The top 100 distinct spending levels, potentially many more than 100 customers. |

Customer ID is a deterministic tie-breaker only for ROW_NUMBER. Adding it to RANK or DENSE_RANK would destroy spending peer groups; order counts are also excluded from those ordering clauses. Preserving ties matters because equal recorded spending provides no spending-based reason to favor one customer. A fixed-size list requires an explicit tie-breaking policy.

For populations below 100, all three filters return the available customers. The analysis reports a NULL 100th-position amount/ranks, zero boundary counts and a false crossing indicator when position 100 does not exist. Empty populations are also verified.

`spending_groups` measures population ties and their presence in the first 100 ROW_NUMBER positions. `boundary` extracts only the amount and two ranks at position 100. `boundary_counts` counts every customer sharing that amount and the number admitted by each candidate filter. The final SELECT returns one aggregate row; it never emits customer identifiers or individual ranking records.

### Actual Candidate Counts and Boundary Findings

| Metric | Actual result |
| ------ | ------------: |
| Existing customer rows / distinct customer IDs | 40,420 / 40,420 |
| Customers with / without eligible orders | 37,900 / 2,520 |
| ROW_NUMBER <= 100 | 100 |
| RANK <= 100 | 100 |
| DENSE_RANK <= 100 | 100 |
| Distinct spending values in the first 100 ROW_NUMBER positions | 100 |
| Spending tie groups across the full population | 1,080 |
| First-100 customers whose spending is tied anywhere in the population | 0 |
| First-100 customers sharing a spending value within the selected 100 | 0 |
| Recorded spending at ROW_NUMBER position 100 | 109,814.46 |
| Total customers sharing that boundary amount | 1 |
| Boundary customers included by ROW_NUMBER | 1 |
| Boundary customers included by RANK | 1 |
| Boundary customers included by DENSE_RANK | 1 |
| RANK / DENSE_RANK at ROW_NUMBER position 100 | 100 / 100 |
| Tie crosses the 100th-customer boundary | No |
| Missing eligible order amounts | 0 |

All three methods currently identify the same 100 customers. No customer in the first 100 shares a spending total with anyone else in the population. The 1,080 tie groups occur below this selection. The two tied-customer measures are reported separately to avoid ambiguity: a customer can belong to a population tie even when only one member of that tie is selected by ROW_NUMBER. Both measures are zero in this live snapshot.

The boundary reconciles as `RANK count = ROW_NUMBER count + boundary group size - boundary members selected by ROW_NUMBER`, or `100 = 100 + 1 - 1`. Both tie-preserving methods include the entire one-customer boundary group. DENSE_RANK admits zero additional customers beyond RANK in this snapshot. This observed agreement cannot settle the future behavior Nana wants when spending ties occur at or above the boundary.

### Execution and Independent Live Verification

At the start of this step, the working tree was clean and HEAD matched `19c743844611bd03fd63a9dd0b8d128b51e944f7` (`Implement Phase 3 spending reports through Step 3.5`). The requested earlier SQL, verifiers, README and reporting documentation were reviewed. Docker was initially unavailable; Docker Desktop was started, and the existing `kloudkart` container became available without initialization or loading.

Executed locally:

```powershell
python tests/verify_top100_ranking.py
```

Exit status was 0. The verified bind mount was this project at `/lab`, and the connection identified database/user `postgres`, PostgreSQL `18.7 (Debian 18.7-1.pgdg13+5)` and cluster `7712053334814294059`. The successful run on November 27, 2026 at 07:48 UTC recorded snapshot `1075:1075:`, `transaction_isolation = repeatable read` and `transaction_read_only = on`. The evidence includes source SQL SHA-256 hashes and aggregate results only.

The verifier runs the exact complete reusable analysis, extracts its actual ranking CTE and reuses the unchanged Step 3.3 query inside one read-only REPEATABLE READ transaction. The live comparison and every fixture confirmed the same snapshot identifier. Neither the verifier nor the SQL creates temporary or permanent database objects.

Independent references first aggregate eligible orders by customer, then join those grouped totals to all customers. Spending buckets count customers and collect synthetic/local IDs in ascending order internally. The expected RANK is one plus the number of higher-spending customers; expected DENSE_RANK is one plus the number of higher spending levels; expected ROW_NUMBER adds the customer's array position within its spending bucket. These references do not call any of the three ranking functions. Separate bucket arithmetic calculates every expected aggregate and boundary count rather than reusing the analysis's expressions.

| Live assertion | Result |
| -------------- | ------ |
| Every existing customer appears exactly once | PASS |
| No nonexistent customer appears | PASS |
| All customer spending/order/missing counts match independent source totals | PASS |
| Every customer has exactly one non-NULL value for each ranking method | PASS |
| ROW_NUMBER values are unique and sequential from one | PASS |
| ROW_NUMBER top 100 returns min(100, population) | PASS |
| ROW_NUMBER follows spending then ascending customer ID | PASS |
| Equal spending receives equal RANK values | PASS |
| Equal spending receives equal DENSE_RANK values | PASS |
| RANK starts at one and skips the preceding tie size | PASS |
| DENSE_RANK starts at one and increments once per spending level | PASS |
| RANK matches independent higher-customer counts | PASS |
| DENSE_RANK matches independent higher-level counts | PASS |
| Customer IDs/order counts do not break spending ties | PASS |
| Every ranking matches independently aggregated spending | PASS |
| Customer totals match the unchanged Step 3.3 query | PASS |
| Zero-order customers retain zero spending/missing counts | PASS |
| Every aggregate analysis field matches independent bucket arithmetic | PASS |
| All candidate counts match independent thresholds | PASS |
| Boundary amount, ranks and inclusion counts match the reference bucket | PASS |
| Boundary tie counts reconcile with all three candidate counts | PASS |

All **21 live assertions** and **five baseline comparisons** passed. Baselines require 40,420 customer rows, 40,420 distinct IDs, 37,900 purchasing customers, 2,520 nonpurchasing customers and exactly 100 ROW_NUMBER candidates. Baseline drift fails validation rather than silently replacing the historical expectations. The target database/user/cluster and transaction settings also passed verification. SQL failures and assertion mismatches return a nonzero process status while withholding potentially sensitive server details.

### VALUES-Based Synthetic Results

Each fixture runs the actual analysis and ranking SQL, all 21 independent checks, an exact expected customer/rank-row comparison inside PostgreSQL, explicit expected candidate counts and explicit expected boundary findings. Inputs are reversed to challenge tie-breaking order. Only aggregate counts and pass/fail results are exported. All **168 assertions across seven fixtures** passed.

| Fixture | Population / purpose | ROW_NUMBER <= 100 | RANK <= 100 | DENSE_RANK <= 100 | Result |
| ------- | -------------------- | ----------------: | ----------: | ----------------: | ------ |
| `distinct_small` | 5 customers with distinct totals; fewer than 100 | 5 | 5 | 5 | PASS |
| `distinct_large` | 105 customers with distinct totals | 100 | 100 | 100 | PASS |
| `internal_top_tie` | 105 customers; two tied at the top and within the first 100 | 100 | 100 | 101 | PASS |
| `crossing_boundary_tie` | 105 customers; four tied across positions 99 through 102 | 100 | 102 | 103 | PASS |
| `all_tied_over100` | 102 customers sharing the highest spending total | 100 | 102 | 102 | PASS |
| `eligibility_zero_negative` | 8 customers; eligibility, lifetime history, NULL/zero/negative totals, no orders and different order counts at equal spending | 8 | 8 | 8 | PASS |
| `empty_population` | No customers; safe absent-boundary behavior | 0 | 0 | 0 | PASS |

The crossing fixture has 98 higher-spending customers and four customers at the boundary amount. ROW_NUMBER includes two members of that group; RANK and DENSE_RANK each include all four. Their boundary ranks are both 99. RANK returns `98 + 4 = 102`; DENSE_RANK also admits the next spending level and returns 103. This proves that retaining the boundary tie and selecting 100 distinct spending levels are different requirements.

The internal top tie demonstrates RANK gaps and DENSE_RANK's lack of gaps even without a tie at position 100: their total candidate counts are 100 and 101. The all-tied fixture checks deterministic ROW_NUMBER selection against two tie-preserving methods when the top spending level alone exceeds 100 customers.

The eligibility fixture retains zero and negative amounts, an all-NULL order amount with a positive missing count, a customer with no orders and a customer with only ineligible activity. Equal spending from two orders versus one receives equal RANK and DENSE_RANK values. It also tests normalized status variants, lifetime dates in 2020, the instant just before the cutoff, exact/after-cutoff exclusions, missing dates, pending/cancelled/NULL/blank statuses and NULL/nonexistent customer references. No historical records are involved.

### Technical Recommendation and Outstanding Business Decision

The technical evidence shows that all three methods currently select the same 100 customers and no tie is split. It also shows that ties exist elsewhere and that the methods produce different results on valid synthetic data. No final ranking policy is selected by this step.

For the decision review, use ROW_NUMBER with the documented customer-ID tie-breaker if Nana requires a fixed list of exactly 100 customers. Use RANK if Nana wants all customers tied at the qualifying 100th-customer boundary, accepting that the list may exceed 100. DENSE_RANK fits a separate request for the top 100 distinct spending levels. Recommend resolving the fixed-size versus boundary-ties requirement explicitly before implementing the final report; today's agreement is insufficient to choose that future behavior.

### Preservation and Scope

Created the analysis SQL, verifier and unique aggregate evidence file; updated only the README and this document. Prior SQL, verifiers and all earlier evidence remain unchanged, as do `checkout.sql`, `place_order.sql` and `race_test.py`. No historical records or database objects were modified, no schema/load script was run, and no performance optimization was implemented. Confidential extracts were not read and customer-level report records were not printed or saved. Nothing was committed or pushed.

The fixed cutoff preserves the date rule, while the read-only transaction preserves one execution snapshot; separate future runs can observe source changes. Work stops after this ranking comparison. Final policy selection and combining reporting components require the user's subsequent approval.

## Step 3.7: Integrated Monday Spending Report

### Approved Policy and Reporting Grains

The user approved the final ranking policy after reviewing Step 3.6: **customers with RANK() <= 100 are included, with ties preserved**. Rank ordering is lifetime recorded spending descending, with no customer-ID or order-count tie-breaker. Customer ID appears only in the final presentation ordering. The list can exceed 100 customers when a qualifying spending group crosses position 100. Step 3.6's open-policy discussion and comparison evidence above remain preserved as historical observations.

**Full integrated SQL:** [monday_spending_report.sql](../monday_spending_report.sql)

**Aggregate-only verifier:** [verify_monday_spending_report.py](../tests/verify_monday_spending_report.py)

The five reporting requirements are lifetime spending, completed-order counts, top-customer ranking, monthly spending and running totals. They have different grains. Lifetime spending and order counts share the customer grain and appear together; the other outputs retain their own grains:

| Result set | Grain | Columns |
| ---------- | ----- | ------- |
| 1. Customer lifetime summary | One row per existing customer | `customer_id`, `total_recorded_spending`, `completed_order_count`, `missing_amount_count`, `customer_total_spend_rank` |
| 2. Top-100 with ties | One row per qualifying customer from the same full population | `customer_id`, `total_recorded_spending`, `completed_order_count`, `customer_total_spend_rank` |
| 3. Trailing twelve months | One row per customer per calendar month | `customer_id`, `spending_month`, `monthly_recorded_spending`, `completed_order_count`, `missing_amount_count` |
| 4. Running totals | One row per eligible completed order | `customer_id`, `order_id`, `order_date`, `total_amount`, `running_recorded_spending`, `running_missing_amount_count`, `running_order_count`, `previous_order_date`, `days_since_previous_order` |

One enormous customer JOIN would repeat values across these grains. For example, joining a customer's two order rows to twelve monthly rows produces 24 rows, repeats each order twelve times and repeats each monthly value twice. Summing that result inflates spending and counts. This script instead executes four independent SELECT statements in a coordinated transaction. Monthly orders are aggregated before joining to the customer-month grid; running windows retain individual orders. No report output is joined to all the other outputs.

### Shared Rules and SQL Organization

The psql variable `reporting_cutoff` is defined once as `2026-11-27 00:00:00`. Each result set reads it through `SELECT TIMESTAMP :'reporting_cutoff' AS cutoff`. The script sets `ON_ERROR_STOP`, begins `REPEATABLE READ READ ONLY`, sets a local 60-second statement timeout and commits only after all four result sets complete. It creates no tables, views, indexes or functions.

All statements preserve the established `report_base` CTE: normalize status with `LOWER(TRIM(status))`, include only `complete` and `completed`, require a matching customer and require `order_date < cutoff`. Stored `orders.total_amount` remains the measure. NULL, zero, negative and historically discrepant totals are not corrected or excluded. Known-amount sums and missing-amount counts retain their earlier meanings. These measures are recorded completed-order spending, not verified revenue or cash collected.

The first two result sets use identical Step 3.3 `customer_spending` CTEs. RANK is calculated over every existing customer before the second SELECT applies `customer_total_spend_rank <= 100`. Zero-order customers retain zero known spending, zero orders and zero missing amounts. The monthly statement preserves all Step 3.4 CTEs, deriving December 2025 through November 2026 and respecting the partial final month. The running statement preserves Step 3.5's `order_windows` CTE, including deterministic `(order_date, order_id)` ordering, the explicit ROWS frame and LAG behavior. Its earlier RANGE diagnostic remains internal and is not an extra output column or result set.

The shared snapshot prevents orders or customer edits committed between statements from producing inconsistent sections. READ ONLY prevents business-data writes by the reporting transaction. Repeated CTE definitions are statement-local because PostgreSQL CTE scope ends with its statement; no permanent or temporary reporting objects were introduced to share intermediate results. All four use the same fixed date rule and transaction snapshot.

### Actual Rows and Monetary Reconciliation

| Result set | Expected rows in unchanged dataset | Actual rows | Result |
| ---------- | --------------------------------: | ----------: | ------ |
| Customer lifetime summary | 40,420 | 40,420 | PASS |
| RANK <= 100 customer list | 100 currently | 100 | PASS |
| Twelve-month customer grid | 485,040 | 485,040 | PASS |
| Eligible-order running totals | 111,195 | 111,195 | PASS |

The summary has 40,420 distinct customer IDs, with 37,900 purchasing and 2,520 zero-order customers. The monthly report has twelve unique customer-month keys per customer, from `2025-12-01` to `2026-11-01`; 399,359 cells have zero eligible activity. The running report has 111,195 distinct order IDs, valid customers throughout and 37,900 final customer rows. There are no duplicate customer, customer-month or order keys, and no join fanout was observed.

| Measure | Recorded spending | Completed orders |
| ------- | ----------------: | ---------------: |
| Customer lifetime summary | 339,184,984.53 | 111,195 |
| Trailing twelve-month report | 313,014,045.03 | 102,463 |
| Eligible history before December 2025 | 26,170,939.50 | 8,732 |
| Sum of final running totals per purchasing customer | 339,184,984.53 | 111,195 |

```text
313,014,045.03 + 26,170,939.50 = 339,184,984.53
102,463 + 8,732 = 111,195
```

The monthly report is smaller than lifetime because it intentionally excludes earlier eligible history. Reconciliation passes both globally and separately for every customer, including missing-amount counts. Current lifetime and monthly missing-amount counts are zero. Summing every running-total row would count prefixes repeatedly; reconciliation correctly uses only each purchaser's final running row.

The current top list contains 100 unique qualifying customers, matches both the customer-summary subset and the unchanged Step 3.6 ranking CTE, and preserves every spending tie. The Step 3.6 boundary findings remain applicable to this unchanged snapshot: position-100 spending is 109,814.46, one customer shares that amount and no tie crosses the boundary. The production rule is the approved RANK filter, rather than a fixed row-count assumption.

### Execution Evidence and Independent Verification

**Successful psycopg2 validation:** [phase3_monday_spending_integration_ad8dfeda5693.txt](../tests/results/phase3_monday_spending_integration_ad8dfeda5693.txt)

**Whole psql script execution:** [phase3_monday_psql_execution_b0929e0cdcb5.txt](../tests/results/phase3_monday_psql_execution_b0929e0cdcb5.txt)

**Preserved initial preflight failure:** [phase3_monday_spending_integration_3caaa555f1a6.txt](../tests/results/phase3_monday_spending_integration_3caaa555f1a6.txt)

At the start of Step 3.7, HEAD remained `19c743844611bd03fd63a9dd0b8d128b51e944f7`. The Step 3.6 SQL, verifier and evidence were untracked local files, and the README/reporting document had local modifications. Those files and diffs were inspected locally; no assumption was made that they existed on remote main. SHA-256 baselines were captured before implementing this step.

Executed with exit status 0:

```powershell
python tests/verify_monday_spending_report.py
```

The verifier requires psycopg2 and uses a single connection with read-only REPEATABLE READ. It extracts the four actual SELECT statements from the integrated SQL, validates the psql controls and exact output schemas, and binds the one cutoff through psycopg2. It checks CTE consistency with the original base and prior implementations, then executes the actual SELECTs inside aggregate validation wrappers. Individual client records never leave PostgreSQL during verification. Connection settings may come from `DATABASE_URL`; otherwise the existing Docker connection settings are read privately. Credentials and potentially sensitive driver/server errors are not logged.

The connection identified `/lab` mounted to this project, database/user `postgres`, PostgreSQL `18.7 (Debian 18.7-1.pgdg13+5)` and cluster `7712053334814294059`. The successful run began on November 27, 2026 at 08:03 UTC and used snapshot `1075:1075:`. The live outputs, prior reporting references and all VALUES fixtures confirmed that same snapshot. The read-only transaction committed successfully.

Independent customer references aggregate eligible source orders before joining to customers. Expected ranks count customers in higher spending buckets without invoking RANK. Monthly references independently derive the calendar bounds, aggregate source months and construct the complete customer-month population. Running references use a prefix join on customer and `(order_date, order_id)`, summing preceding orders and selecting the previous date from a descending array; they do not reuse the report's SUM window or LAG expression. Exact two-way set comparisons and key counts check coverage, values and multiplicity. Unchanged Step 3.3-3.6 queries provide additional regression comparisons in the same snapshot.

| Validation group | Checks | Result |
| ---------------- | ------ | ------ |
| Customer summary | Coverage/uniqueness, independent totals/ranks, Step 3.3 equality, zero-order semantics, source spending/order/missing reconciliation | PASS |
| Top report | Independent qualifying set, Step 3.6 equality, unique qualifying ranks, summary-subset equality, no partial tie selection | PASS |
| Monthly grid | Twelve unique rows/customer, independent cell equality, Step 3.4 equality, calendar bounds, zero cells, source totals | PASS |
| Running totals | Eligible-order coverage/uniqueness, valid customers, independent prefix equality, Step 3.5 equality, first-order NULLs, final customer totals | PASS |
| Cross-component | Per-customer monthly-plus-earlier reconciliation, final running sums, source eligibility and no monetary/order fanout | PASS |

All **25 live assertions**, **23 live baseline comparisons** and **four output-schema checks** passed. Baseline differences return a clear failure rather than silently updating expected counts. No live monetary discrepancy, missing-amount anomaly or unexpected row-count change was found.

The complete unmodified psql script was also executed locally with `-o /dev/null`, discarding all individual result rows inside the container. That separate smoke execution passed with exit status 0 and exercised the actual psql variable substitution, error handling and transaction wrapper. It has its own transaction; all comparisons within the psycopg2 verifier use the single snapshot described above.

### VALUES-Based Integration Results

Each fixture executes all four actual report SELECTs, all 25 independent checks and four additional exact expected-result checks. Complete expected customer, top, monthly and running rows are stated independently and compared inside PostgreSQL. Input orders are reversed/shuffled to test deterministic timestamp ties. No records or database objects are created.

| Fixture | Summary rows | Top rows | Monthly rows | Running rows | Result |
| ------- | -----------: | -------: | -----------: | -----------: | ------ |
| `integration_edges` | 8 | 8 | 96 | 12 | PASS |
| `boundary_tie` | 105 | 102 | 1,260 | 105 | PASS |
| `empty_population` | 0 | 0 | 0 | 0 | PASS |

All **87 synthetic assertions** and **30 explicit synthetic baseline comparisons** passed across the three fixtures. The mixed fixture covers multiple customers/orders, old lifetime-only history, purchases across months, zero-activity months, identical timestamps with different order IDs, NULL amounts, zero/negative amounts, a customer without orders, a customer with only pending activity and equal spending from different order counts. It includes orders just before the exclusive cutoff, exactly at/after it, missing dates, invalid statuses and NULL/nonexistent customer references.

Its lifetime spending is 288.50 over twelve eligible orders; monthly spending is 138.50 over ten orders; earlier history is 150 over two orders. Both lifetime and monthly missing counts are two, and 89 monthly cells have zero activity. Exact expected results prove that neither the twelve-month grid nor the multiple order rows multiply spending/counts across sections.

The boundary fixture has 98 higher-spending customers followed by four customers sharing rank 99 at positions 99-102. All four are retained, yielding 102 top customers. This explicitly verifies the approved policy when more than 100 rows qualify. The empty fixture verifies safe empty sums/sets and absent monthly endpoints.

### Findings, Preservation and Limits

An initial preflight attempt rejected the valid monthly query because the verifier counted a semicolon in an existing SQL comment as a second statement. The parser was corrected to ignore full-line comments before counting statement terminators. That attempt stopped before connecting to the database; its failure evidence remains preserved. All subsequent live/synthetic assertions and the whole-script execution passed.

Added the integrated SQL, psycopg2 verifier and uniquely named execution logs; extended the README and this document. The Step 3.6 SQL, verifier, execution evidence and complete historical discussion remain preserved. Prior SQL/verifiers, protected checkout/race files, schema/load files and all previous evidence were not modified. No historical records or confidential CSV files were changed or read. No permanent or temporary database objects, indexes or functions were created. Nothing was committed or pushed.

The report still measures known stored totals, with missing counts needed to interpret incomplete amounts. The top subset omits its own missing-count column as requested; consult its customers' lifetime summary when interpreting completeness. Payment settlement, historical monetary repairs, account merging and currency conversion remain outside scope. The fixed cutoff does not freeze source edits across future runs. Full direct report output is confidential and must not be saved to shared logs. This step stops at integration validation; no performance benchmarking or index optimization has begun.
