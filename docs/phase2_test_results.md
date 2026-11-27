# Phase 2 — Test Results

This document records the verification of the safe checkout and inventory audit implementation. Test scripts and execution logs are maintained separately so that the results can be reproduced.

## 1. Automatic ID Generation

See [phase2_identity.md](phase2_identity.md) for the identity migration tests, results and historical data preservation checks.

## 2. Basic Checkout Parameter Validation

**Objective:** Verify that the checkout function rejects missing required parameters and non-positive purchase quantities.

**Test script:** [test_checkout_validation.sql](../tests/test_checkout_validation.sql)

**Execution evidence:** [basic_validation.txt](../tests/results/basic_validation.txt)

| Test ID | Scenario          | Expected response                  | Actual response                    | Result |
| ------- | ----------------- | ---------------------------------- | ---------------------------------- | ------ |
| VAL-01  | NULL customer ID  | Required input is missing          | Required input is missing          | PASS   |
| VAL-02  | NULL product ID   | Required input is missing          | Required input is missing          | PASS   |
| VAL-03  | NULL quantity     | Required input is missing          | Required input is missing          | PASS   |
| VAL-04  | Zero quantity     | Quantity must be greater than zero | Quantity must be greater than zero | PASS   |
| VAL-05  | Negative quantity | Quantity must be greater than zero | Quantity must be greater than zero | PASS   |

### Results

All five test cases passed. Every invalid request returned `success = false`, a NULL order ID and the expected explanatory message.

Rejecting non-positive quantities prevents invalid checkout requests, including negative quantities that could incorrectly increase stock instead of deducting it.

### Limitations

These tests verify basic parameter validation and returned responses only. They do not independently verify database side effects, customer or product existence, catalog price validity, stock availability, transaction atomicity or concurrent checkout behaviour.

Further tests will cover these requirements as the implementation progresses.

## 3. Customer Existence Validation

**Objective:** Verify that checkout rejects requests referencing nonexistent customers without breaking existing parameter validation.

**Test script:** [test_checkout_validation.sql](../tests/test_checkout_validation.sql)

**Execution evidence:** [customer_validation.txt](../tests/results/customer_validation.txt)

| Test ID | Scenario             | Expected response  | Actual response    | Result |
| ------- | -------------------- | ------------------ | ------------------ | ------ |
| VAL-06  | Nonexistent customer | Customer not found | Customer not found | PASS   |

### Results

All six validation tests passed, including the five previous parameter validation tests. The nonexistent customer request returned `success = false`, a NULL order ID and the expected message.

The test uses a customer ID outside the range of the PostgreSQL integer data type to guarantee that no matching customer exists.

This validation addresses the risk of creating new orders that reference nonexistent customers, a problem identified during Phase 1, where 210 existing orders had missing customer references.

### Limitations

The existence check does not independently prevent a customer from being deleted concurrently during checkout. Database-level referential integrity and transaction guarantees will be addressed separately.

### Saved Evidence Verification

The actual output in [customer_validation.txt](../tests/results/customer_validation.txt) was reviewed before adding product validation. It contains six rows, VAL-01 through VAL-06, all marked `PASS`. Each row reports `success = f` (false), a blank NULL order ID and the expected message. VAL-06 reports `Customer not found`. The original execution evidence is preserved unchanged.

## 4. Product Existence Validation

**Objective:** Verify that checkout rejects requests referencing nonexistent products after customer validation, without breaking the six existing validation tests.

**Test script:** [test_checkout_validation.sql](../tests/test_checkout_validation.sql)

**Execution evidence:** [product_validation.txt](../tests/results/product_validation.txt)

| Test ID | Scenario            | Expected response | Actual response   | Result |
| ------- | ------------------- | ----------------- | ----------------- | ------ |
| VAL-07  | Nonexistent product | Product not found | Product not found | PASS   |

### Results

All seven validation tests passed. VAL-01 through VAL-03 returned `Required input is missing`; VAL-04 and VAL-05 returned `Quantity must be greater than zero`; VAL-06 returned `Customer not found`; VAL-07 returned `Product not found`. Every row returned `success = false` and a NULL order ID.

VAL-07 uses the minimum existing customer ID, product ID `2147483648` and purchase quantity `1`. Read-only database checks confirmed that a customer exists, both ID columns use PostgreSQL integer, and neither sentinel ID exists. The product ID exceeds the integer range, while the function accepts bigint inputs, so the request reaches product validation with a valid customer and quantity.

The function checks `products` using `IF NOT EXISTS` immediately after customer existence validation and returns before the temporary checkout response when the product is absent. Its signature remains `place_order(bigint, bigint, integer)`.

The updated function was applied and the full validation suite executed successfully inside the `kloudkart` container against database `postgres`:

```powershell
docker exec -w /lab kloudkart psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 -f place_order.sql
docker exec -w /lab kloudkart psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 -P pager=off -f tests/test_checkout_validation.sql
```

The actual test output was saved to the execution evidence linked above. Previous test cases and execution logs were preserved. No historical data or the supplied `race_test.py` was modified.

### Limitations

These seven tests verify rejection responses only; they do not independently verify database side effects or exercise a valid checkout. Valid customer and product inputs still reach the temporary `Checkout not implemented` response.

An existence check alone does not protect against concurrent product or customer deletion. Catalog price validation, stock validation, concurrency control, order creation, inventory auditing and transaction guarantees remain unimplemented and untested at this step.

## 5. Catalog Price Validation

**Objective:** Reject NULL, zero and negative catalog prices while preserving all seven previous validation rules and the temporary checkout response.

**Test scripts:** [test_checkout_validation.sql](../tests/test_checkout_validation.sql) and [test_catalog_price_validation.sql](../tests/test_catalog_price_validation.sql)

**Execution evidence:**

- [catalog_price_function_apply.txt](../tests/results/catalog_price_function_apply.txt): successful function application inside `kloudkart`, database `postgres`.
- [catalog_price_previous_validation.txt](../tests/results/catalog_price_previous_validation.txt): VAL-01 through VAL-07 rerun.
- [catalog_price_validation.txt](../tests/results/catalog_price_validation.txt): VAL-08 through VAL-10 and rollback cleanup.
- [catalog_price_positive_path_smoke.txt](../tests/results/catalog_price_positive_path_smoke.txt): temporary positive-price check and rollback cleanup.
- [catalog_price_cleanup_verification.txt](../tests/results/catalog_price_cleanup_verification.txt): independent cleanup verification from a fresh connection.

| Test ID | Scenario               | Expected response     | Actual response       | Response rows | Result |
| ------- | ---------------------- | --------------------- | --------------------- | ------------- | ------ |
| VAL-08  | NULL catalog price     | Invalid product price | Invalid product price | 1             | PASS   |
| VAL-09  | Zero catalog price     | Invalid product price | Invalid product price | 1             | PASS   |
| VAL-10  | Negative catalog price | Invalid product price | Invalid product price | 1             | PASS   |

### Results

All ten validation tests passed. The seven existing cases retained their inputs and expected messages and each returned exactly one row with `success = false` and a NULL order ID. Each new price case also returned exactly one row with `success = false`, a NULL order ID and `Invalid product price`.

Both permanent test scripts now enforce assertions with `ON_ERROR_STOP`: incorrect response values, missing or duplicate response rows, or an unexpected number of test results cause a SQL exception and a nonzero test-command exit status. The original harness retains its seven cases and adds result materialization, per-case row-count validation and an assertion block. The price harness aggregates each function call to count its actual response rows and validate all returned values.

A separate, temporary check used an existing customer, a synthetic product priced at `12.50`, stock quantity `10` and purchase quantity `1`. It returned exactly one row with `success = false`, a NULL order ID and `Checkout not implemented`, marked `PASS`. That check was generated in memory from the fixture harness and sent to `psql` through standard input. Only its execution evidence is retained; the temporary checkout response is not a permanent regression assertion.

The updated function was applied and the permanent scripts run using:

```powershell
docker exec -w /lab kloudkart psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 -f place_order.sql
docker exec -w /lab kloudkart psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 -P pager=off -f tests/test_checkout_validation.sql
docker exec -w /lab kloudkart psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 -P pager=off -f tests/test_catalog_price_validation.sql
```

### Implementation Explanation

Strictly positive catalog prices are required so that future order calculations have a defined positive unit price. NULL prices can propagate missing totals, zero prices could allow unintended free purchases and negative prices could produce negative order values. This step validates the catalog value without changing any source records.

The variable `v_price` uses `products.price%TYPE` so its type follows the catalog column. A single `SELECT p.price INTO v_price` replaces the separate product existence check. Because `product_id` is a primary key, the query retrieves at most one row. `IF NOT FOUND` immediately follows the query: an absent row returns `Product not found`, whereas an existing row with a NULL price sets `FOUND` to true and proceeds to `Invalid product price`. The next condition rejects `v_price IS NULL OR v_price <= 0`. The function signature, earlier validations and temporary response remain unchanged.

### Fixture Safety and Cleanup

Each price run dynamically selects the minimum existing customer ID and inserts only synthetic products with stock quantity `10`. Product IDs are allocated from the integer range starting at its lower bound. `INSERT ... ON CONFLICT (product_id) DO NOTHING` retries occupied IDs, so fixtures cannot overwrite existing products. A unique run marker identifies only that run's fixture names; customer IDs and historical product values are not printed.

Fixture inserts and assertions run inside a transaction, followed by `ROLLBACK`. A failing assertion stops the script, and closing the test connection rolls back its open transaction. No existing customer or product records are updated. Explicit product IDs avoid advancing a sequence for these fixtures.

Both the three-case price run and the temporary positive-price run reported `Remaining synthetic fixtures: 0` and `Fixture cleanup: PASS` after rollback. A fresh connection independently found zero products with the synthetic catalog-price prefix and reported `Fixture cleanup: PASS`. SHA-256 comparisons also confirmed that the three earlier execution logs and supplied `race_test.py` were unchanged. No commit or push was performed.

### Limitations

Checkout remains incomplete. Price validation covers NULL and non-positive catalog prices; it does not establish pricing policy beyond these rules. Stock validation, row locking, concurrency control, order creation and inventory auditing have not been implemented. The price read does not prevent concurrent price changes or product/customer deletion. These tests verify returned validation responses and synthetic fixture cleanup, rather than transaction atomicity or concurrent checkout behaviour.

## 6. Product Row Locking and Stock Validation

**Objective:** Lock the requested product before validating its price and stock under the unchanged READ COMMITTED isolation level. Preserve the function signature, previous refusal messages and one-row response contract without implementing purchase writes.

**Test scripts:** [test_checkout_validation.sql](../tests/test_checkout_validation.sql), [test_catalog_price_validation.sql](../tests/test_catalog_price_validation.sql), [test_stock_validation.sql](../tests/test_stock_validation.sql) and [verify_checkout_locking.py](../tests/verify_checkout_locking.py).

**Execution evidence:**

- [stock_locking_function_apply.txt](../tests/results/stock_locking_function_apply.txt): successful application to `postgres` inside `kloudkart`.
- [stock_locking_previous_validation.txt](../tests/results/stock_locking_previous_validation.txt): VAL-01 through VAL-07.
- [stock_locking_catalog_price_validation.txt](../tests/results/stock_locking_catalog_price_validation.txt): VAL-08 through VAL-10.
- [stock_validation.txt](../tests/results/stock_validation.txt): permanent stock tests, business-data fingerprints and rollback cleanup.
- [stock_sufficient_temporary_checks.txt](../tests/results/stock_sufficient_temporary_checks.txt): temporary exact/excess stock checks, business-data fingerprints and rollback cleanup.
- [checkout_locking_verification.txt](../tests/results/checkout_locking_verification.txt): four separate-connection locking tests and disposable database cleanup.
- [stock_locking_data_cleanup_verification.txt](../tests/results/stock_locking_data_cleanup_verification.txt): fresh-connection cleanup, all six active tables unchanged, prior evidence and supplied harness preserved.

### Implementation and Concurrency Decision

The function declares `v_stock_quantity products.stock_quantity%TYPE`. Its product lookup retrieves price and stock together and adds `FOR UPDATE`. `IF NOT FOUND` still immediately follows that query, and catalog price validation still precedes stock validation. Every handled validation path returns one false/NULL response row. There are no stock deductions, order inserts, item inserts, inventory log inserts, constraints, triggers or routine diagnostic messages for refusals.

`SELECT FOR UPDATE` was chosen to make the product's price and stock available for readable, ordered validation while excluding competing updates to that row. The lock lasts until the caller's transaction ends, including after a refused request. It does not require an exclusive lock on the entire products table. Callers should finish transactions promptly. See [PostgreSQL 18 row-level locking](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-ROWS).

READ COMMITTED is sufficient for the selected single-product design when validation and future stock deduction remain in one transaction under the product lock. A locking read waits for a conflicting transaction and, after its commit, returns the updated row if it still matches the product ID. The tests below verify this behavior for both stock and price. This conclusion does not extend to arbitrary cross-row business rules or unlocked customer checks. See [PostgreSQL 18 READ COMMITTED behavior](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-READ-COMMITTED).

A conditional `UPDATE` could instead deduct stock only where the product has an acceptable price and enough stock, using `RETURNING` to detect success. That is a valid alternative for the eventual atomic decrement. It was not chosen for this step because it introduces stock mutation before purchase writes are implemented, and a zero-row result alone would not distinguish missing products, invalid prices, unknown or invalid stock, and insufficient stock. The agreed locking read preserves the individual refusal messages and separates validation from future writes. No conditional stock update was implemented.

### Stock Rules and Business Justification

| Condition | Response | Reason |
| --------- | -------- | ------ |
| NULL stock | Stock quantity unavailable | Unknown inventory cannot establish availability. |
| Negative stock | Invalid stock quantity | Corrupt inventory must not authorize another purchase. |
| Stock below requested quantity | Product out of stock | Prevent approval beyond the available quantity; includes zero stock for a positive request. |
| Exact or excess stock | Continue to temporary checkout response | The availability check passes; purchasing is still unimplemented. |

### Regression Results

All ten existing cases passed with exactly one response row, `success = false`, a NULL order ID and the expected message. Their original inputs and expected messages were preserved. The two existing SQL scripts now also display and assert READ COMMITTED and use local bounded statement/lock timeouts, without changing isolation.

| Test ID | Scenario | Actual response | Result |
| ------- | -------- | --------------- | ------ |
| VAL-01 | NULL customer ID | Required input is missing | PASS |
| VAL-02 | NULL product ID | Required input is missing | PASS |
| VAL-03 | NULL quantity | Required input is missing | PASS |
| VAL-04 | Zero quantity | Quantity must be greater than zero | PASS |
| VAL-05 | Negative quantity | Quantity must be greater than zero | PASS |
| VAL-06 | Nonexistent customer | Customer not found | PASS |
| VAL-07 | Nonexistent product | Product not found | PASS |
| VAL-08 | NULL catalog price | Invalid product price | PASS |
| VAL-09 | Zero catalog price | Invalid product price | PASS |
| VAL-10 | Negative catalog price | Invalid product price | PASS |

### Permanent Stock Results

Each case used a synthetic product with price `12.50`, an existing customer selected dynamically and a positive purchase quantity. Each returned exactly one row with `success = false`, a NULL order ID and the expected refusal message.

| Test ID | Stock | Requested quantity | Expected and actual response | Result |
| ------- | ----- | ------------------ | ---------------------------- | ------ |
| STOCK-01 | NULL | 1 | Stock quantity unavailable | PASS |
| STOCK-02 | -1 | 1 | Invalid stock quantity | PASS |
| STOCK-03 | 0 | 1 | Product out of stock | PASS |
| STOCK-04 | 2 | 3 | Product out of stock | PASS |

Before rollback, ordered full-row MD5 fingerprints and row counts matched for `products`, `orders`, `order_items` and `inventory_log`. Thus the refusal suite left all product values, including stock, and all three purchase/audit tables unchanged in its observed transaction. Only equality results were printed, not client records or fingerprint values.

### Temporary Sufficient-Stock Checks

| Temporary check | Stock | Requested quantity | Expected and actual response | Result |
| --------------- | ----- | ------------------ | ---------------------------- | ------ |
| TEMP-EXACT | 3 | 3 | Checkout not implemented | PASS |
| TEMP-EXCESS | 4 | 3 | Checkout not implemented | PASS |

Both returned exactly one false/NULL response row. The same four business-table fingerprints remained unchanged. These checks were generated in memory from the stock fixture harness and executed through `psql` standard input. Their output is retained as evidence, but no permanent regression assertion requires the placeholder response.

### Locking Results and Blocking Evidence

The Python verifier uses only the standard library and Docker's `psql`. Each persistent `PsqlSession` owns an independent PostgreSQL backend connection. An observer and each holder/checkout session verified READ COMMITTED without setting a different isolation level. The verifier creates a uniquely named database from `template0`, applies `schema.sql` and `place_order.sql` only there and seeds one synthetic customer and two synthetic products. It never runs `load.sql` or reads the CSVs.

| Test ID | Coordination and observed behavior | Actual checkout response | Result |
| ------- | ---------------------------------- | ------------------------ | ------ |
| LOCK-01 | Holder locked product 1; checkout of that product was observed blocked; holder rolled back. Stock remained 10, request was 11. | Product out of stock | PASS |
| LOCK-02 | Checkout requesting 5 was observed blocked; holder changed stock from 10 to 2 and committed. Checkout used the committed stock. | Product out of stock | PASS |
| LOCK-03 | Checkout requesting 5 was observed blocked; holder changed price from 12.50 to 0 and committed. Checkout used the committed price. | Invalid product price | PASS |
| LOCK-04 | Holder retained product 1's lock while checkout of product 2 completed; checkout had zero blockers. Stock was 10, request was 11. | Product out of stock | PASS |

For LOCK-01, LOCK-02 and LOCK-03, `pg_stat_activity` reported `wait_event_type=Lock`, `wait_event=transactionid`; `pg_blocking_pids()` included the known holder backend and checkout had not finished. Waiting on the holder's transaction ID is the observed mechanism of this row-lock conflict. The holder was released only after this relationship was observed. LOCK-04 completed while the holder transaction still retained its other-product lock.

Every locking result contained exactly one false/NULL refusal row. Checkout transactions were committed before checking persisted state. The three business tables remained unchanged and product prices/stocks matched only the holder's intentional fixture changes. No checkout business writes were observed.

Coordination polls server lock state with a six-second deadline; a fixed sleep is not used as proof of blocking. Sessions use a 15-second statement timeout, 12-second lock timeout and 25-second idle-in-transaction timeout, plus bounded Python waits and Docker command timeouts. Failed assertions raise exceptions and exit nonzero. Cleanup releases the holder before closing the checkout connection, rolls back unfinished transactions and drops only the generated database, including remaining connections if necessary.

### Data Preservation, Cleanup and Execution

The active-database SQL fixtures allocate unused explicit integer product IDs, retry collisions with `ON CONFLICT DO NOTHING`, and use a unique run marker. No existing client record is updated. The price, permanent stock and temporary sufficient-stock fixtures were rolled back; each run reported zero remaining fixtures.

A fresh connection independently found zero synthetic stock fixtures, zero synthetic catalog-price fixtures and zero locking verification databases. The Python verifier also checked from a fresh connection that its exact generated database name was absent after removal.

Before and after the complete run, row counts and ordered full-row MD5 fingerprints matched for all six active tables: categories, customers, products, orders, order items and inventory logs. SHA-256 comparisons confirmed that every previous evidence file and `race_test.py` was unchanged. The active database was not reset, and neither `schema.sql` nor `load.sql` was run against it. The official race test was not executed. No commit or push was performed.

Reproduce the permanent checks from the project root:

```powershell
docker exec -w /lab kloudkart psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 -f place_order.sql
docker exec -w /lab kloudkart psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 -P pager=off -f tests/test_checkout_validation.sql
docker exec -w /lab kloudkart psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 -P pager=off -f tests/test_catalog_price_validation.sql
docker exec -w /lab kloudkart psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 -P pager=off -f tests/test_stock_validation.sql
python tests/verify_checkout_locking.py
```

The Docker role needs permission to create/drop the disposable database and inspect its sessions. All executed functional assertions passed on the first run; no test or implementation failures required correction. Actual outputs were saved under new filenames without overwriting historical evidence.

### Limitations and Next Step

Row-locking verification does not yet prove that completed checkout prevents overselling: stock deduction and order creation have not been implemented. Valid requests still return `Checkout not implemented`. There is no inventory audit write, completed-purchase atomicity test, multi-product lock ordering, retry policy or customer-deletion protection. SQL fingerprints are equality evidence for the observed runs, not exhaustive proof of all possible side effects; sequence consumption and concurrent unrelated writers are outside those comparisons. No active purchase sequence is used by this implementation or these explicit-ID fixtures.

The recommended next development step is atomic order placement: keep the product lock while deducting stock and creating the order and order item in the same transaction, with inventory auditing addressed as specified for that step. Failure rollback and completed-checkout overselling tests will be required then. This development step stops at locked validation; no purchase writes were added.

## 7. Atomic Order Placement and Inventory Auditing

**Objective:** Reserve stock and create one pending order, one order item and one linked sale movement atomically, preserving all previous validation responses and READ COMMITTED isolation.

**Implementation:** [place_order.sql](../place_order.sql)

**New permanent verifier:** [verify_atomic_checkout.py](../tests/verify_atomic_checkout.py)

**Execution evidence:**

- [atomic_function_apply.txt](../tests/results/atomic_function_apply.txt): updated function applied to the active database in `kloudkart`.
- [atomic_previous_validation.txt](../tests/results/atomic_previous_validation.txt): VAL-01 through VAL-07.
- [atomic_catalog_price_validation.txt](../tests/results/atomic_catalog_price_validation.txt): VAL-08 through VAL-10.
- [atomic_stock_validation.txt](../tests/results/atomic_stock_validation.txt): STOCK-01 through STOCK-04 and business-table preservation.
- [atomic_product_locking_verification.txt](../tests/results/atomic_product_locking_verification.txt): LOCK-01 through LOCK-04 rerun.
- [atomic_order_verification_7f71c7a72ed1.txt](../tests/results/atomic_order_verification_7f71c7a72ed1.txt): success, refusal, rollback, customer-lock, generated-ID and audit assertions; timings and cleanup.
- [atomic_official_race_7f71c7a72ed1.txt](../tests/results/atomic_official_race_7f71c7a72ed1.txt): actual output from the unchanged official race harness, process duration and exit status.
- [atomic_data_cleanup_verification.txt](../tests/results/atomic_data_cleanup_verification.txt): independent active-data/fixture checks and preservation of all previous evidence and `race_test.py`.

### Design and Transaction Handling

Validation still rejects missing parameters, non-positive quantities, nonexistent customers/products, invalid prices and unavailable/invalid/insufficient stock before successful-purchase writes. The function signature remains `place_order(bigint, bigint, integer) RETURNS TABLE (success boolean, order_id bigint, message text)`.

The customer lookup now uses `PERFORM ... FOR KEY SHARE` followed immediately by `IF NOT FOUND`. This protects the referenced customer key while preserving `Customer not found`. The customer lock is acquired before the product's existing `SELECT FOR UPDATE` lock. Key-share locking blocks deletion and key-changing updates without unnecessarily blocking ordinary non-key customer updates. See [PostgreSQL 18 row-level lock modes](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-ROWS).

After validation, a defensive conditional `UPDATE` subtracts the requested quantity only where stock is still sufficient. It uses `RETURNING` and checks `FOUND`; a zero-row update returns `Product out of stock` before creating any order, item or movement. Under the existing product lock this is a defensive invariant check rather than a second unlocked availability decision.

The function then inserts the order, retrieves its generated ID with `INSERT ... RETURNING`, inserts the item using the locked catalog price, and inserts a sale movement. It returns exactly one success row with that order ID and `Order placed successfully`.

All four writes belong to the caller's transaction. The function has no internal commit, rollback or error-catching handler. An insertion error propagates so partial writes cannot be reported as a successful purchase. In an explicit transaction, the caller must commit to persist success or roll back after failure; an autocommit statement commits the complete call as one unit. The controlled failure test below uses a harness savepoint to inspect rollback without changing this production behavior. See [PostgreSQL 18 PL/pgSQL error behavior](https://www.postgresql.org/docs/18/plpgsql-control-structures.html#PLPGSQL-ERROR-TRAPPING).

### Pending Status and Stock Reservation Assumption

Every new order receives status `pending`. This is the agreed business assumption: the function reserves stock and records the purchase request, but does not process or confirm payment. Order totals use catalog unit price multiplied by requested quantity. Order and audit timestamps both use the current database transaction timestamp.

A later workflow must handle failed or expired payments by cancelling the pending order and restoring reserved stock exactly once, with a corresponding inventory movement. Payment processing, expiry, cancellation and stock restoration were not implemented here.

### Inventory Auditing and IDs

Each successful call writes exactly one inventory row with the purchased product ID, `change_qty = -p_quantity`, reason `sale`, the database timestamp and note `Order <generated order ID>`. The note permits a human-readable link to the order without including customer personal information. The order item retains the locked unit price, product and purchased quantity.

Inspection confirmed all three active business IDs already use `GENERATED ALWAYS AS IDENTITY`. The existing [checkout.sql](../checkout.sql) remains unchanged: it is the existing setup migration to run after schema/data loading, and safely advances identities beyond historical ID boundaries. Checkout itself never calculates IDs or uses `MAX(id) + 1`; it omits identity columns from inserts and obtains the order ID with `RETURNING`.

The isolated verifier also applies `schema.sql`, then the existing identity migration, then the function, and asserts all three ALWAYS identities before any purchase tests. No redundant sequence/default mechanism or setup-script change was needed. Sequences can have gaps after failed or rolled-back purchases; allocation is not rolled back and IDs are not a gapless ledger. See [PostgreSQL 18 sequence behavior](https://www.postgresql.org/docs/18/functions-sequence.html).

### Regression Results

All 14 permanent refusal cases and all four existing product-locking cases were rerun successfully. Every refusal returned exactly one row, false, a NULL order ID and its unchanged expected message. All testing sessions verified READ COMMITTED; no isolation level was changed.

| Test ID | Actual response or verified behavior | Result |
| ------- | ------------------------------------ | ------ |
| VAL-01 | Required input is missing | PASS |
| VAL-02 | Required input is missing | PASS |
| VAL-03 | Required input is missing | PASS |
| VAL-04 | Quantity must be greater than zero | PASS |
| VAL-05 | Quantity must be greater than zero | PASS |
| VAL-06 | Customer not found | PASS |
| VAL-07 | Product not found | PASS |
| VAL-08 | Invalid product price | PASS |
| VAL-09 | Invalid product price | PASS |
| VAL-10 | Invalid product price | PASS |
| STOCK-01 | Stock quantity unavailable | PASS |
| STOCK-02 | Invalid stock quantity | PASS |
| STOCK-03 | Product out of stock | PASS |
| STOCK-04 | Product out of stock | PASS |
| LOCK-01 | Same-product checkout observed waiting for the conflicting holder | PASS |
| LOCK-02 | Waiting checkout used committed reduced stock and refused | PASS |
| LOCK-03 | Waiting checkout used committed invalid price and refused | PASS |
| LOCK-04 | Different-product checkout completed while the first product remained locked | PASS |

The historical sufficient-stock checks against `Checkout not implemented` were intentionally temporary. They were not rerun as permanent assertions; the successful-purchase tests below now verify the completed behavior instead. Earlier placeholder evidence remains unchanged.

### Successful Purchases and Refusals

The new verifier creates a disposable PostgreSQL 18 container, bound only to loopback, with 500 allowed connections for the official 400-buyer test. It mounts the project read-only, loads no CSVs and uses only synthetic customers/products. Docker and `psycopg2` are prerequisites. The active lab container is not used by this verifier.

| Test ID | Actual checked result | Result |
| ------- | --------------------- | ------ |
| ORDER-01 | Quantity 1 at 12.50; stock 5 to 4; pending total 12.50 | PASS |
| ORDER-02 | Quantity 3 at 12.50; stock 10 to 7; pending total 37.50 | PASS |
| ORDER-03 | Quantity 4 at 12.50; stock 4 to 0; pending total 50.00 | PASS |
| REFUSE-01 | Insufficient stock: Product out of stock | PASS |
| REFUSE-02 | Zero stock: Product out of stock | PASS |
| REFUSE-03 | Negative stock: Invalid stock quantity | PASS |
| REFUSE-04 | NULL stock: Stock quantity unavailable | PASS |
| REFUSE-05 | Zero price: Invalid product price | PASS |
| REFUSE-06 | Missing customer: Customer not found | PASS |
| REFUSE-07 | Missing product: Product not found | PASS |

Each success assertion checked exactly one true response with a positive generated order ID, one pending order with the correct customer/total/database timestamp, one item with matching order/product/quantity/unit price and a generated item ID, and one negative sale movement with a generated log ID, matching order note and database timestamp. Stock deductions matched the purchased quantities.

Each refusal assertion checked exactly one false/NULL response and compared complete product, order, item and inventory rows before and after the call. Every comparison matched. Native fixtures were rolled back after each of these cases. The active stock regression suite independently confirmed unchanged row counts and full-row fingerprints before its rollback.

### Atomic Rollback, Customer Locks and Concurrent IDs

| Test ID | Actual checked result | Result |
| ------- | --------------------- | ------ |
| ROLLBACK-01 | Inventory-insert trigger observed prior stock deduction, pending order and item; raised controlled P0001; stock restored and no order/item/movement remained | PASS |
| CUSTOMER-LOCK-01 | Concurrent customer deletion observed blocked until checkout transaction ended | PASS |
| CUSTOMER-LOCK-02 | Concurrent customer key update observed blocked until checkout transaction ended | PASS |
| ID-01 | 20 concurrent committed purchases generated 20 distinct order IDs, 20 distinct item IDs and 20 distinct log IDs; stock reached zero | PASS |

The rollback fixture began with stock 5 and requested 2. A test-only BEFORE INSERT inventory trigger first verified stock 3, a pending order and its item within the failing statement, then deliberately raised SQLSTATE `P0001`. The harness required that exact error to propagate and rolled back to its pre-call savepoint. Complete before/after rows matched: stock was 5 again and order, item and movement counts were all zero. Rolling back the enclosing fixture transaction removed the trigger and its temporary trigger function; a fresh connection confirmed both were absent. No test trigger was added to the active database.

Both customer-lock tests first placed an order in an open transaction, then attempted deletion or a key-changing update in a separate backend. Monitoring observed a `Lock/transactionid` wait with the checkout holder listed in `pg_blocking_pids()`. The modifier resumed only after checkout rolled back; the modifier was also rolled back. These checks establish protection for the transaction lifetime, not permanent referential integrity after commit.

The ID test released 20 independent buyer connections through a barrier. All 20 purchases committed successfully. It checked exact row and distinct-ID counts in all three business tables, stock zero, and 20 correctly linked pending orders/items/sale movements with expected amounts and quantities. The committed synthetic rows were removed afterward. Assertions raise errors and return a failing process status; sessions, waits and subprocesses use bounded timeouts.

### Official Race Test Results

Only after all regression, product-locking and new preliminary checks had passed, the verifier executed the supplied `race_test.py` as a separate Python process with no source changes, argument changes or monkeypatching. All four default tests ran. The connection environment pointed to the isolated synthetic database. The harness cleaned its fixtures, and a fresh connection verified zero remaining products, orders, items, movements or test trigger objects.

Actual output follows, including the measured process duration and exit status:

```text
race_test.py — Kloud Kart order placement under contention
==================================================================
  place_order found: place_order(p_customer_id bigint, p_product_id bigint, p_quantity integer)

Test 1 — two buyers, one unit, 25 rounds
  ok    25/25 rounds: exactly one winner, stock 0, one order, no errors

Test 2 — flash sale: 400 buyers, 50 units
        50 sold, 350 refused, 0 errored, wall clock 8.03s
  ok    exactly 50 sold, none oversold, no errors, 8.03s

Test 3 — asking for more than exists
  ok    refused cleanly, stock untouched

Test 4 — audit trail after contention
  ok    5 sold, 5 movements recorded

==================================================================
PASSED — exactly one buyer gets the last unit, every time.

Actual process elapsed: 10.962s
Exit status: 0
```

The official audit test checks movement counts; the preliminary success and concurrent-ID tests additionally checked exact movement contents and order-note links. Together these provide observed evidence for both the supplied contention contract and this implementation's detailed audit design.

### Actual Timings

| Executed operation | Measured duration |
| ------------------ | ----------------- |
| Active function application | 1.258 s |
| VAL-01 through VAL-07 | 0.399 s |
| VAL-08 through VAL-10 | 1.832 s |
| STOCK-01 through STOCK-04, including fingerprints | 6.004 s |
| Existing four product-locking tests, including disposable DB cleanup | 7.744 s |
| ORDER-01 / ORDER-02 / ORDER-03 | 0.043 / 0.041 / 0.034 s |
| Seven new refusal/no-change tests | 0.251 s |
| Controlled rollback and trigger cleanup | 0.061 s |
| Customer deletion / key-update locking tests | 0.099 / 0.440 s |
| Concurrent generated-ID and exact audit-link test | 0.393 s |
| Official 400-buyer flash-sale portion | 8.03 s |
| Complete official race process | 10.962 s |
| Complete isolated atomic verifier, including startup, race and cleanup | 22.100 s |

These are measured verification durations on this environment, not production performance guarantees. No performance tuning was performed.

### Cleanup, Preservation and Reproduction

Fresh connections confirmed zero isolated product/order/item/log fixtures and zero test trigger objects before and after the official race run. The disposable container and its anonymous PostgreSQL data volume were removed. Independent Docker inspection found no remaining atomic verification container. The two product-locking and customer-locking environments contained synthetic data only; no client data was copied into them.

In the active database, all six tables retained identical pre/post row counts and ordered full-row MD5 fingerprints. A fresh connection found zero stock/price/atomic/race fixtures and zero injected-failure triggers. The existing product-lock verifier's generated database was also absent. SHA-256 comparisons confirmed that all prior execution evidence and `race_test.py` were unchanged. The active database was never reset, `schema.sql` and `load.sql` were not rerun against it, and no commit or push was performed.

Reproduce the new comprehensive verification from the project root:

```powershell
python tests/verify_atomic_checkout.py
```

Each invocation generates unique evidence filenames and a unique disposable container. Apply the function and rerun the three existing SQL suites using the same Docker/psql commands recorded in Section 6; [verify_checkout_locking.py](../tests/verify_checkout_locking.py) remains the product-lock regression command. Keep prior output files when recording another run.

No unexpected implementation or test failures occurred. The deliberately injected inventory-insertion exception was an expected assertion of rollback behavior.

### Remaining Limitations

Pending stock reservations require a future cancellation/payment-expiry and stock-restoration workflow. Payment confirmation, refunds and reservation expiry are not implemented. The note-based inventory/order link is not a structured foreign key, and this change adds no database constraints or permanent triggers. Customer key locking protects the in-flight transaction; it does not prevent a later deletion after commit in the current schema.

Callers must commit successful explicit transactions and roll back failed ones promptly to release locks. Repeating a successfully committed request can create another order because request idempotency is not implemented. The current design covers one product per call; multi-product lock ordering and broader retry policy remain future decisions. Existing numeric/identity column limits still apply: overflow or other storage failures propagate and roll back the business writes, and identity sequences may retain gaps.

The tests demonstrate completed checkout without overselling for the executed contention scenarios, not every possible application workflow or arbitrary external writer. Data fingerprints provide observed row-equality evidence and are not an exhaustive proof of all possible side effects. No Monday spending report, category rollup or performance optimization was started. This stage stops after atomic order placement and inventory auditing verification.
