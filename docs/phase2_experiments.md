# Phase 2 — Transactional Checkout Experiments

## 1. Purpose

The purpose of these experiments was to investigate how PostgreSQL handles concurrent transactions attempting to modify the same product's inventory.

The experiments were conducted using two independent PostgreSQL sessions connected to the development database.

The test product had an initial stock quantity of one unit.

These experiments informed the selection of a concurrency-control strategy for the eventual `place_order()` function. They do not yet constitute proof that the completed checkout implementation passes the official race test.

---

## 2. Experiment 1 — Explicit Row-Level Locking

### Objective

Determine how PostgreSQL handles two transactions attempting to lock and modify the same product row.

### Initial setup

A temporary product was created:

- Product ID: 9024
- Product name: ROW LOCK LAB FIXTURE
- Initial stock: 1
- Price: 100.00

### Session A — Acquire the lock

```sql
BEGIN;

SELECT
    product_id,
    stock_quantity
FROM products
WHERE product_id = 9024
FOR UPDATE;

UPDATE products
SET stock_quantity = stock_quantity - 1
WHERE product_id = 9024;
```

**Observed result:**

- The row was successfully locked.
- Stock was reduced from 1 to 0 within the open transaction.
- Session A retained the lock because the transaction had not committed.

### Session B — Compete for the same lock

```sql
BEGIN;

SELECT
    product_id,
    stock_quantity
FROM products
WHERE product_id = 9024
FOR UPDATE;
```

**Observed result:**

Session B waited while Session A held the row lock.

After Session A executed:

```sql
COMMIT;
```

Session B resumed and returned the updated stock quantity of 0.

A further conditional stock deduction was attempted:

```sql
UPDATE products
SET stock_quantity = stock_quantity - 1
WHERE product_id = 9024
  AND stock_quantity >= 1
RETURNING product_id, stock_quantity;
```

**Observed result:** UPDATE 0.

### Conclusion

PostgreSQL's row-level locking prevented the second session from proceeding while the first transaction held the lock.

After the first transaction committed, the second session observed the updated stock quantity.

The additional conditional update also prevented the stock from becoming negative.

---

## 3. Experiment 2 — Conditional Atomic UPDATE

### Objective

Determine whether stock validation and deduction can be performed safely in a single SQL statement.

### Initial setup

The test product's stock was reset to one unit.

### Session A

```sql
BEGIN;

UPDATE products
SET stock_quantity = stock_quantity - 1
WHERE product_id = 9024
  AND stock_quantity >= 1
RETURNING product_id, stock_quantity;
```

**Observed result:**

- One row was updated.
- The returned stock quantity was 0.
- Session A kept the transaction open.

### Session B

While Session A's transaction was still open, Session B executed:

```sql
BEGIN;

UPDATE products
SET stock_quantity = stock_quantity - 1
WHERE product_id = 9024
  AND stock_quantity >= 1
RETURNING product_id, stock_quantity;
```

**Observed result:**

Session B waited for Session A to finish.

After Session A committed, Session B resumed and returned:

```text
UPDATE 0
```

The condition `stock_quantity >= 1` was no longer satisfied.

### Conclusion

The conditional UPDATE performed the stock check and deduction in one statement.

PostgreSQL handled the competing update through row-level locking. The second transaction did not deduct stock after the available quantity had reached zero.

---

## 4. Comparison of the Approaches

| Consideration                | SELECT FOR UPDATE             | Conditional UPDATE           |
| ---------------------------- | ----------------------------- | ---------------------------- |
| Row-level locking            | Yes                           | Yes, automatically           |
| Separate stock-reading query | Yes                           | Not required                 |
| Stock validation             | Separate application/SQL step | Included in UPDATE condition |
| Updated stock returned       | Through SELECT or RETURNING   | Through RETURNING            |
| Experiment outcome           | Passed                        | Passed                       |

### Preliminary implementation preference

Conditional atomic UPDATE is the preferred approach for further implementation testing.

Reasons:

1. Stock validation and deduction occur in one statement.
2. It reduces the need for a separate stock-reading operation.
3. PostgreSQL handles conflicting updates through row-level locking.
4. The statement can return the updated product row.
5. It works with the default READ COMMITTED isolation level.

This is a preliminary design preference, not a finalized implementation decision. It must still be validated through the actual checkout function and the unchanged official concurrency test.

---

## 5. Experiment Cleanup

The temporary product was checked after the experiments.

```sql
SELECT product_id, product_name, stock_quantity
FROM products
WHERE product_id = 9024
  AND product_name = 'ROW LOCK LAB FIXTURE';
```

**Observed result:** Zero rows.

A further check was performed:

```sql
SELECT COUNT(*) AS remaining_fixture_rows
FROM products
WHERE product_name = 'ROW LOCK LAB FIXTURE';
```

**Observed result:** 0.

The temporary fixture was therefore absent from the development database after the experiments.

---

## 6. Limitations

These were controlled, two-session experiments using one product with one available unit.

They demonstrate the relevant PostgreSQL locking behaviour but do not establish that the final checkout function is correct under the full workload.

Further testing is required for:

- 400 concurrent purchase attempts.
- Multiple-unit purchases.
- Insufficient stock.
- Invalid inputs.
- Transaction rollback.
- Order and inventory-log consistency.
- Safe concurrent ID generation.

The official `race_test.py` must pass unchanged before the checkout implementation is accepted.

## 7. Experiment 3 — Existing ID Generation Investigation

### Objective

Determine how primary-key values are currently generated and whether PostgreSQL sequences already exist.

### SQL investigation

The following queries were executed from `tests/phase2/inspect_id_generation.sql`:

- Count existing records and identify minimum and maximum primary-key values in orders, order_items and inventory_log.
- Inspect PostgreSQL sequences in the public schema.

### Observed results

| Table         | Records | Minimum ID | Maximum ID |
| ------------- | ------: | ---------: | ---------: |
| orders        | 159,384 |    500,001 |    659,384 |
| inventory_log | 282,352 |    700,001 |    982,487 |
| order_items   | 336,559 |    900,001 |  1,236,559 |

No sequences were returned by the sequence inspection query.

The original schema also showed that none of the three primary-key columns has an automatic default or identity definition.

### Conclusion

The existing tables rely on manually supplied primary-key values.

To support concurrent checkout operations, three independent PostgreSQL sequences will be introduced.

Each sequence will be synchronized with the maximum existing ID in its respective table so that newly generated values do not conflict with historical records.

Existing IDs and records will remain unchanged.

### Additional Check — Orphaned Order References

**Objective**

Determine whether existing order-item references could conflict with newly generated order IDs.

**Observed results**

| Measurement                          |  Result |
| ------------------------------------ | ------: |
| Orphaned order-item rows             |     692 |
| Highest orphaned order ID            | 999,862 |
| Highest order ID referenced by items | 999,862 |
| Highest existing order ID            | 659,384 |

**Conclusion**

The investigation identified 692 order-item records referencing order IDs that do not exist in the orders table. The highest orphaned reference is 999,862, which exceeds the highest existing order ID of 659,384.

Starting automatic order ID generation immediately after the maximum ID in the orders table would therefore be unsafe. A newly generated order could unintentionally match an existing orphaned reference.

The orders sequence must be synchronized above the highest order ID found across both the orders table and the order-item references. This means the first generated order ID should be 999,863, provided no intervening records are inserted before sequence setup.

Historical records will remain unchanged. This is a preventive measure, not a correction of existing orphaned records.

## Experiment 5 — Verify Automatic ID Generation

### Objective

Verify that PostgreSQL automatically generates primary-key values for
orders, order_items and inventory_log without manually supplying IDs.

### Test procedure

Executed `tests/phase2/verify_id_generation.sql`.

Temporary records were inserted inside a transaction and rolled back.

### Observed results

| Table         | Expected ID | Generated ID |
| ------------- | ----------: | -----------: |
| orders        |     999,863 |      999,863 |
| order_items   |   1,236,560 |    1,236,560 |
| inventory_log |     982,488 |      982,488 |

The generated order ID was also correctly assigned to the order item.

**Transaction result:** ROLLBACK.

### Conclusion

All three sequences successfully generated unique IDs without
requiring manually supplied primary-key values.

The temporary records were rolled back successfully. Sequence
values remained consumed, as expected in PostgreSQL.

Automatic ID generation is therefore verified.

## Experiment 6 — Checkout Function Verification

### Objective

Verify that place_order() correctly processes successful purchases
and rejects purchases when stock is insufficient.

### Test procedure

Executed `tests/phase2/test_place_order.sql`.

The test created a temporary product with two units in stock.

### Observed results

1. A purchase of one unit succeeded.
2. Generated order ID: 999864.
3. Stock decreased from 2 to 1.
4. One order was created.
5. One order item was created.
6. One inventory log entry was created.
7. A subsequent request for two units was rejected with
   an "Out of stock" message.
8. Stock remained at 1 after the rejected request.

**Transaction result:** ROLLBACK.

### Conclusion

The checkout function successfully handled normal purchases
and insufficient-stock requests.

Order creation, stock deduction, order-item creation and
inventory logging were verified together.

The test transaction was rolled back successfully, leaving
the original dataset unchanged.

The function is ready for concurrency testing.

## Experiment 7 — Concurrent Last-Unit Purchases

### Objective

Verify that two buyers competing for the last available unit cannot both complete a purchase, and confirm that the checkout function prevents overselling under concurrent requests.

### Test procedure

Executed the unchanged official `race_test.py` using:

```powershell
python .\race_test.py --test 1 --verbose
```

The test repeated the simultaneous two-buyer purchase scenario 25 times, with one unit available in each round.

Each round involved two independent database connections attempting to purchase the same product at approximately the same time.

### Observed results

| Measurement              | Result |
| ------------------------ | -----: |
| Concurrent rounds        |     25 |
| Total purchase attempts  |     50 |
| Successful purchases     |     25 |
| Refused purchases        |     25 |
| Unhandled errors         |      0 |
| Failed rounds            |      0 |
| Negative stock incidents |      0 |

Each round produced exactly one successful purchase and one out-of-stock refusal.

Stock reached zero in every round, with exactly one order created per round.

### Execution Performance

The official test harness recorded the execution time of each individual checkout function call.

| Performance measurement   |       Result |
| ------------------------- | -----------: |
| Total individual calls    |           50 |
| Fastest individual call   |       9.0 ms |
| Slowest individual call   |      55.3 ms |
| Total test execution time | Not reported |

The recorded times represent individual database function-call response times, not the total duration of the complete test.

### Conclusion

The checkout function successfully handled concurrent attempts to purchase the last available unit across all 25 rounds.

The conditional atomic UPDATE prevented two buyers from purchasing the same remaining unit. PostgreSQL handled competing updates through row-level locking, ensuring that the second buyer observed the updated stock quantity.

No unhandled errors, negative stock values or incorrect order counts were observed.

**Official Test 1: PASSED (25/25 rounds).**

## Experiment 8 — Inventory Audit Trail Under Contention

### Objective

Verify that successful purchases made during concurrent checkout attempts are recorded in the inventory_log table.

### Test procedure

Executed the unchanged official `race_test.py` using:

```powershell
python .\race_test.py --test 4 --verbose
```

The test created a product with five units in stock and initiated 12 concurrent purchase attempts.

### Observed results

| Measurement                  | Result |
| ---------------------------- | -----: |
| Concurrent buyers            |     12 |
| Initial stock                |      5 |
| Successful purchases         |      5 |
| Refused purchases            |      7 |
| Inventory movements recorded |      5 |
| Unhandled errors             |      0 |

All five successful purchases had corresponding inventory movement records.

The remaining seven requests were refused because the available stock had been exhausted.

### Execution Performance

The official test harness recorded the response time of each individual checkout function call.

| Performance measurement   |       Result |
| ------------------------- | -----------: |
| Total individual calls    |           12 |
| Fastest individual call   |      63.2 ms |
| Slowest individual call   |     122.4 ms |
| Total test execution time | Not reported |

### Conclusion

The checkout function successfully maintained the inventory audit trail during concurrent purchase attempts.

All five successful purchases were accompanied by five inventory movement records. The seven unsuccessful requests did not result in additional stock deductions.

No unhandled errors were observed.

**Official Test 4: PASSED.**

## Experiment 9 — Flash Sale Concurrency Test (400 Buyers, 50 Units)

### Objective

Evaluate the checkout function under heavy concurrent demand and verify that 400 simultaneous purchase attempts cannot oversell 50 available units.

### Test procedure

Executed the unchanged official `race_test.py` using:

```powershell
python .\race_test.py --test 2 --verbose
```

The test simulated 400 buyers attempting to purchase one unit each of a product with 50 units available.

### Observed results

| Measurement           | Result |
| --------------------- | -----: |
| Concurrent buyers     |    400 |
| Initial stock         |     50 |
| Successful purchases  |     50 |
| Refused purchases     |    350 |
| Database errors       |      0 |
| Overselling incidents |      0 |
| Final stock           |      0 |

The database successfully processed exactly 50 purchases and refused the remaining 350 requests because stock was exhausted.

### Execution Performance

The official test harness recorded individual checkout response times and total wall-clock execution time.

| Performance measurement          |        Result |
| -------------------------------- | ------------: |
| Total purchase attempts          |           400 |
| Fastest individual call          |    1,548.0 ms |
| Slowest individual call          |    4,147.4 ms |
| Average individual response time |    3,087.7 ms |
| Median individual response time  |    3,099.6 ms |
| Total execution time             | 16.10 seconds |

### Conclusion

The checkout function successfully handled 400 concurrent purchase attempts without overselling the available inventory.

Exactly 50 buyers completed their purchases, while the remaining 350 received out-of-stock responses. No database errors or overselling incidents occurred.

The conditional atomic stock deduction successfully protected inventory under heavy concurrent demand.

**Official Test 2: PASSED.**
