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
