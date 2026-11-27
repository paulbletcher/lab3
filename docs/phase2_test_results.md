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
