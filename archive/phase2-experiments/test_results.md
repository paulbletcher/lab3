# Verification and performance results

This record separates completed verification from pending work. The identity and sequence results below were supplied from the lab's completed verification and are consistent with the implementation in [checkout.sql](../checkout.sql). They were not rerun during this documentation update. The original execution date, PostgreSQL version, and raw query output were not supplied.

No database scripts or race tests were executed for this update. The existing diagnosis is preserved in [diagnosis.md](diagnosis.md), including its scope and limitations.

## Completed — Identity-column configuration

| Table | Column | Is identity | Generation |
|---|---|---|---|
| inventory_log | log_id | YES | BY DEFAULT |
| order_items | order_item_id | YES | BY DEFAULT |
| orders | order_id | YES | BY DEFAULT |

These results establish that all three target columns were configured as identities using `BY DEFAULT` when checked. They confirm the configuration, not that concurrent checkout behavior has passed testing.

[test.sql](../test.sql) selects `is_identity` but does not select `identity_generation`. To reproduce both fields in a future read-only recheck, use the following query; it was not executed during this review:

```sql
SELECT table_name,
       column_name,
       is_identity,
       identity_generation AS generation
FROM information_schema.columns
WHERE table_schema = 'public'
  AND (table_name, column_name) IN (
      ('inventory_log', 'log_id'),
      ('order_items', 'order_item_id'),
      ('orders', 'order_id')
  )
ORDER BY table_name;
```

## Completed — Initial sequence state

The second statement in [checkout_prechecks.sql](../checkout_prechecks.sql) reads `last_value` and `is_called` directly from the three sequences after migration. The recorded results are:

| Table | last_value | is_called |
|---|---:|---|
| orders | 999863 | False |
| order_items | 1236560 | False |
| inventory_log | 982488 | False |

With `is_called = False`, the next allocation returns the recorded `last_value`, provided no intervening allocation or reset occurs. Read-only inspection was used instead of `nextval()` because `nextval()` consumes a value even if its transaction is rolled back. [PostgreSQL sequence functions](https://www.postgresql.org/docs/current/functions-sequence.html).

Together with the preliminary maxima documented in [Decision 002](decisions.md#historical-orphan-protection), this confirms the intended initial boundaries: the order sequence is above both existing orders and historical item references, and the other two sequences are above their existing IDs. These are configuration snapshots, not a measurement of throughput or proof of successful order insertion.

**Concurrent ID generation has not been load-tested.** Checkout correctness, stock safety, and audit behavior remain unverified. PostgreSQL's sequence-allocation guarantees support the design rationale; they are not a substitute for executing the lab tests.

## Pending verification

### Checkout input validation

**Status: Pending.** After input rules and the checkout function are implemented, verify valid requests and the agreed handling of missing or unknown customers/products, `NULL` inputs, and nonpositive quantities. Record returned results and database effects; the exact validation policy remains to be agreed.

### Transaction atomicity

**Status: Pending.** Verify that a successful checkout creates the order and its associated item and stock/audit changes in one transaction. Verify that a rejected request or an induced failure leaves no partial business changes. Consumed sequence values may still leave gaps.

### Concurrency race tests

**Status: Pending — `race_test.py` has not been executed.** Once `place_order` exists with the supplied signature, run the harness unchanged and record its output. Its cases cover two buyers competing for one unit over 25 rounds, the 400-buyer/50-unit flash sale, a request for more stock than exists, and inventory-log coverage after contention. Record successes, refusals, unhandled errors, remaining stock, and order counts. These are planned checks, not observed outcomes.

### Flash-sale execution time

**Status: Pending.** Record the wall-clock time reported by test 2 for 400 concurrent attempts against 50 units, alongside correctness results and the environment used. The harness prints a note if execution exceeds 10 seconds; that note is not an enforced timing assertion. No duration or performance claim is available yet.

### Inventory audit trail verification

**Status: Pending.** After the audit mechanism is agreed and implemented, verify movement quantities, product references, timestamps, and the agreed reason and purchase-linking convention. The harness's fourth case counts log rows against successful calls; a complete reconciliation of movement contents still needs separate verification.

### Spending report performance before and after optimization

**Status: Pending.** The report is not implemented. Capture the baseline and optimized query plans and timings under comparable conditions, then verify that results remain equivalent. Record the reporting cutoff, spending definition, indexes, and environment when those choices are made. No baseline, optimized duration, or speedup has been measured.

### Recursive category rollup correctness and performance

**Status: Pending.** The rollup is not implemented. Verify totals and traversal behavior for ordinary hierarchies, cycles, missing parents, and uncategorized products against the agreed reporting rules. Record query plans and timings only after correctness has been checked.

### Fresh-load reproducibility

**Status: Pending.** In a separately authorized disposable lab database, reproduce the [documented script order](../README.md#script-execution-order), including the preliminary maximum-ID statement before migration and sequence checks afterward. Compare diagnosis findings and sequence boundaries with this record. No reset or reload was performed during this documentation update.

## Recording future results

For each completed check, record its date, PostgreSQL version and Docker configuration, script revision, relevant parameters, expected behavior, actual result, timing where applicable, and limitations. Keep credentials and confidential source rows out of shared evidence. Replace a pending status only when the verification has actually been executed.
