### Investigation 2 â€” Database write permissions

The investigation examined ownership, table privileges, login roles and effective permissions for the `products` and `inventory_log` tables.

**Findings:**

- Both tables are owned by `postgres`.
- The `postgres` role has full table privileges, including INSERT, UPDATE and DELETE.
- `postgres` is the only login role and has superuser privileges.
- No separate application role exists.
- Direct stock updates are therefore possible without going through a controlled inventory operation.

**Decision:**

Introduce a restricted application role that can execute approved inventory functions but cannot directly modify the products or inventory_log tables.

The existing checkout function will remain responsible for sales. A separate controlled inventory movement function will handle restocks, inspected returns, corrections, damages and stock takes.

Each successful operation must update the stock balance and insert its audit record within the same transaction.

The database administrator retains administrative access.

**Limitation:** Tests performed using the postgres superuser alone cannot demonstrate application-level permission restrictions. Additional role-based tests will be required.

## Controlled inventory movement testing

Test script: `tests/inventory_audit/04_test_inventory_movement.sql`

All 19 tests passed against PostgreSQL 18.7 in the
`kloudkart_rebuild` container.

| Test | Description                              | Result |
| ---- | ---------------------------------------- | ------ |
| 1    | Restock                                  | PASS   |
| 2    | Return with successful inspection        | PASS   |
| 3    | Positive correction                      | PASS   |
| 4    | Negative correction                      | PASS   |
| 5    | Damage deduction                         | PASS   |
| 6    | Stock take with positive adjustment      | PASS   |
| 7    | Stock take with negative adjustment      | PASS   |
| 8    | Stock take with no adjustment            | PASS   |
| 9    | Return without inspection approval       | PASS   |
| 10   | Insufficient stock                       | PASS   |
| 11   | Invalid movement reason                  | PASS   |
| 12   | Zero restock quantity                    | PASS   |
| 13   | Negative restock quantity                | PASS   |
| 14   | Zero correction quantity                 | PASS   |
| 15   | Negative physical stock count            | PASS   |
| 16   | Sale through inventory movement function | PASS   |
| 17   | NULL return inspection approval          | PASS   |
| 18   | Nonexistent product                      | PASS   |
| 19   | Stock and audit trail reconciliation     | PASS   |

### Reconciliation results

- Initial stock: 20 units.
- Net inventory movement: +5 units.
- Final stock: 25 units.
- Inventory audit records: 8.
- Failed tests: 0.

### Interpretation

The controlled inventory movement function correctly handled
all supported movement types in the tested scenarios.

Returns without successful inspection approval were rejected.
Invalid movements did not alter the synthetic product's stock
or create additional audit records in the rejection tests
that explicitly checked these conditions.

The sale movement was rejected because sales remain the
responsibility of place_order(), preventing duplicate sale
audit records through this function.

The final stock balance reconciled with the sum of the
recorded inventory movements.

All synthetic records were rolled back after testing.
Historical client records were not modified. Sequence
values consumed during testing are not restored by rollback.

### Remaining verification

- Atomic rollback when audit insertion fails.
- Concurrent inventory movements.
- Restricted application-role permissions.
- Official checkout concurrency regression tests.

The results demonstrate functional correctness for the
tested scenarios but do not yet establish complete
inventory audit enforcement.

## Inventory movement atomicity and rollback testing

Test script: `tests/inventory_audit/05_test_inventory_rollback.sql`

### Test objective

Verify that a stock adjustment cannot survive when its
corresponding inventory audit record fails to insert.

### Test method

A synthetic product was created with an initial stock of
20 units. A temporary CHECK constraint was introduced to
prevent inventory log insertion for that product.

An otherwise valid restock of 10 units was attempted.
The expected constraint violation was caught, and the
product's stock balance and audit records were inspected.

The constraint was then removed, and the same movement
was attempted again to verify successful recovery.

### Actual results

| Measurement                           | Result    |
| ------------------------------------- | --------- |
| Initial stock                         | 20        |
| Requested restock                     | 10        |
| Forced audit insertion failure        | Confirmed |
| Stock after failure                   | 20        |
| Audit records after failure           | 0         |
| Stock after recovery                  | 30        |
| Matching audit records after recovery | 1         |
| Overall result                        | PASS      |

### Interpretation

The function successfully rolled back the stock adjustment
when the corresponding inventory log insertion failed.

After removing the test constraint, the same movement
succeeded, increasing stock to 30 and producing exactly
one matching audit record.

This demonstrates that the stock adjustment and audit
insertion behave as one atomic operation in the tested
failure scenario.

All synthetic records and temporary schema changes were
rolled back. Historical client records were preserved.

### Limitations

The failure was deliberately simulated using a CHECK
constraint. This verifies atomic rollback for the tested
failure scenario, but does not simulate every possible
production failure.

The test temporarily locks the inventory log table and
should only be executed in an isolated test environment.
Sequence values consumed during testing are not restored
by transaction rollback.

## Concurrent inventory movement testing

Test script:
`tests/inventory_audit/06_test_inventory_concurrency.py`

### Objective

Verify that simultaneous inventory movements cannot cause
negative stock, lost stock updates or inconsistent audit
records. Also verify compatibility between the controlled
inventory movement function and the existing optimized
checkout function.

### Test method

Three concurrency scenarios were executed, with 10 rounds
per scenario. Each round used a synthetic product with an
initial stock balance of 10 units.

Two independent PostgreSQL connections were used in each
round, with a threading barrier to release both operations
at approximately the same time.

### Actual results

| Scenario                    | Rounds | Passed | Final stock per round |
| --------------------------- | -----: | -----: | --------------------: |
| Competing damage deductions |     10 |     10 |                     3 |
| Concurrent restocks         |     10 |     10 |                    20 |
| Checkout versus damage      |     10 |     10 |                     3 |
| Total                       |     30 |     30 |                   N/A |

Additional results:

- Total attempted operations: 60.
- Successful operations: 40.
- Expected refusals: 20.
- Failed test rounds: 0.
- Negative stock incidents: 0.
- Audit reconciliation failures: 0.

In the checkout versus damage scenario, checkout won
1 round and damage deduction won 9 rounds.

### Interpretation

Competing damage deductions correctly prevented two
operations from consuming more stock than was available.

Concurrent restocks preserved both stock increases,
demonstrating that neither update was lost.

The checkout and damage scenario demonstrated that the
atomic UPDATE in place_order() and the row-level locking
in record_inventory_movement() work safely together.

Every successful operation produced exactly one audit
record, and the resulting stock balance reconciled with
the recorded inventory movements in every tested round.

The distribution of checkout and damage winners does not
indicate a correctness failure because neither operation
was assigned priority.

### Limitations

These tests demonstrate correctness under the tested
two-operation contention scenarios. They do not establish
maximum throughput, fairness or performance under larger
inventory workloads.

The test script performs explicit cleanup of synthetic
products, orders, order items and inventory records.
All rounds completed successfully, including cleanup.

The original race_test.py was not modified.

## Restricted application-role implementation

Implementation script:
`functions/phase3_inventory_permissions.sql`

Test script:
`tests/inventory_audit/07_test_inventory_permissions.sql`

### Architecture decision

Two restricted database roles were introduced:

- kloudkart_function_owner: Owns the approved functions
  and has only the underlying privileges required for
  their execution.
- kloudkart_app: Executes approved functions without
  direct write access to the operational tables.

Both roles are non-superuser roles with NOLOGIN.

The existing place_order() and record_inventory_movement()
functions were configured as SECURITY DEFINER functions
with a restricted search_path.

The optimized checkout function body was not modified.

### Actual test results

| Test | Operation | Result |
|---|---|---|
| 1 | Direct stock update | Denied |
| 2 | Direct audit insertion | Denied |
| 3 | Direct audit modification | Denied |
| 4 | Direct audit deletion | Denied |
| 5 | Direct product deletion | Denied |
| 6 | Direct product insertion | Denied |
| 7 | Direct sequence access | Denied |
| 8 | Direct order insertion | Denied |
| 9 | Direct product reading | Denied |
| 10 | Approved restock function | PASS |
| 11 | Approved checkout function | PASS |
| 12 | Stock and audit reconciliation | PASS |

All 12 application permission tests passed.

### Reconciliation

- Initial stock: 20 units.
- Approved restock: +10 units.
- Approved checkout: -7 units.
- Final stock: 23 units.
- Inventory audit records: 2.
- Orders created: 1.

### Interpretation

The restricted application role could execute both approved
functions successfully but could not directly modify stock,
insert unauthorized audit records or alter existing audit
records.

This establishes database-level enforcement of the tested
inventory movement paths for the restricted application role.

All synthetic test records were rolled back.

### Limitations and deployment requirements

The postgres administrator retains unrestricted access.
The audit trail is therefore protected against restricted
application access, not privileged administrators.

Application authentication has not been configured.
Production application connections must use a restricted
login role rather than postgres.

Both checkout and inventory operations are currently granted
to the same application role. Production deployment may
benefit from separating checkout and warehouse permissions.

Permission testing used SET LOCAL ROLE rather than a
separate authenticated application connection.

Direct product reading is currently restricted. Appropriate
read-only catalogue and reporting access can be configured
separately.

The inventory permissions migration is a one-time migration
and must follow creation of the checkout and inventory
movement functions.


## Official concurrency regression after security changes

The original race_test.py was executed without modification
after implementing restricted application permissions and
SECURITY DEFINER execution.

### Actual results

| Test | Result |
|---|---|
| Last-unit competition | 25/25 rounds passed |
| Flash-sale successful purchases | 50 |
| Flash-sale refusals | 350 |
| Flash-sale errors | 0 |
| Flash-sale wall-clock time | 10.86 seconds |
| Oversell attempt | PASS |
| Inventory audit trail | 5 sales, 5 movements |
| Overall official test result | PASS |

### Performance observation

The previous optimized flash-sale median was 7.47 seconds.
The first regression run after security changes completed
in 10.86 seconds.

This represents an observed increase of 3.39 seconds
(approximately 45.4%).

All correctness requirements tested by the official harness
passed, but the ten-second performance target was exceeded.

A single measurement is insufficient to attribute the
slowdown to the security changes. Additional measurements
are required before drawing a performance conclusion.


### Repeated flash-sale regression benchmark

Following the initial regression measurement of 10.86
seconds, three additional flash-sale tests were executed
using the original, unmodified race_test.py.

| Run | Buyers | Sold | Refused | Errors | Wall-clock time |
|---|---:|---:|---:|---:|---:|
| 1 | 400 | 50 | 350 | 0 | 11.00 s |
| 2 | 400 | 50 | 350 | 0 | 6.90 s |
| 3 | 400 | 50 | 350 | 0 | 6.27 s |

- Previous optimized median: 7.47 seconds.
- Repeated regression median: 6.90 seconds.
- Median reduction: 0.57 seconds (approximately 7.6%).
- Failed correctness tests: 0.

### Interpretation and decision

The repeated benchmark median was below the ten-second
flash-sale target. All three runs preserved correct stock
balances and produced the expected purchase and refusal
counts without errors.

However, execution times varied between runs. Two of the
four post-security measurements exceeded ten seconds.

The results do not establish a consistent performance
regression caused by the security changes, nor do they
prove that the security changes improved performance.

The existing optimized checkout implementation and
restricted application permissions will be retained.

Further optimization is not justified without evidence
of a specific bottleneck.

### Limitations

The benchmark includes connection establishment and
thread scheduling overhead. Local machine workload and
Docker resource availability may influence its results.

The ten-second target was achieved by the repeated
benchmark median, but not consistently in every run.

These results represent local simulated workloads,
not guaranteed production performance.


## Final inventory audit verification

Verification script:
`tests/inventory_audit/08_verify_inventory_audit.sql`

### Cleanup and historical integrity results

| Verification | Original/Expected | Actual |
|---|---:|---:|
| Remaining synthetic test products | 0 | 0 |
| Remaining test constraints | 0 | 0 |
| Products with negative stock | 14 | 14 |
| Products with NULL stock | 0 | 0 |
| Orphaned inventory logs | 120 | 120 |
| Inventory logs with NULL product IDs | 0 | 0 |

### Historical movement counts

| Reason | Original count | Final count |
|---|---:|---:|
| Correction | 485 | 485 |
| Damage | 268 | 268 |
| Restock | 18857 | 18857 |
| Return | 564 | 564 |
| Sale | 262088 | 262088 |
| Stock take | 90 | 90 |

All movement counts and movement direction distributions
matched the original investigation results.

### Security verification

Both approved functions:

- Are owned by kloudkart_function_owner.
- Execute using SECURITY DEFINER.
- Use search_path = pg_catalog, pg_temp.

Both newly created roles:

- Cannot log in directly.
- Are not superusers.
- Cannot create roles or databases.
- Do not have replication or row-level security bypass privileges.

The application role:

- Can execute both approved functions.
- Has no tested direct table or column access privileges.
- Has no direct sequence privileges.
- Cannot create objects in the public schema.
- Is not a member of the function-owner role.

The function owner cannot update, delete or truncate
existing inventory audit records.

### Interpretation

All final inventory verification checks returned the
expected results.

No synthetic test products or temporary test constraints
remained in the database.

The historical inventory integrity counts and movement
distributions remained unchanged. The existing negative
stock balances and orphaned audit records were preserved
rather than corrected without supporting business evidence.

The restricted application role can perform approved
inventory operations without directly modifying the
underlying operational tables.

### Limitations

Matching aggregate counts does not establish that every
historical record is individually identical to its
original state.

Privileged administrators retain the ability to bypass
the controlled inventory movement functions.

The remaining historical integrity faults require
business-led investigation and remediation.


## Full integrity regression

The original integrity_checks.sql script was executed
after completing the inventory audit implementation,
security configuration and concurrency regression tests.

All 21 result sets were returned successfully.

### Key regression measurements

| Integrity check | Final count |
|---|---:|
| Orders with orphaned customers | 210 |
| Order items with orphaned orders | 692 |
| Order items with orphaned products | 0 |
| Orphaned inventory logs | 120 |
| Products without categories | 37 |
| Categories with missing parents | 1 |
| Categories in loops | 2 |
| Products with negative stock | 14 |
| Invalid order-item quantities | 0 |
| Order items with zero prices | 152 |
| Order items with NULL prices | 148 |
| Orders without items | 0 |
| Orders with incomplete lines | 147 |
| Order total mismatches | 2279 |
| Duplicate email groups | 533 |
| Completed orders with missing customers | 144 |
| Completed orders with total mismatches | 1624 |
| Completed orders with incomplete lines | 95 |
| Inventory movements without timestamps | 0 |

### Financial integrity measurements

- Stored total for completed orders with missing
  customers: 388780.89.
- Net difference for completed order total mismatches:
  -1266190.96.
- Total absolute difference: 2074053.86.
- Stored total for completed orders with incomplete
  lines: 455904.42.

### Interpretation

The integrity regression results matched the available
previously recorded baseline measurements.

The original baseline of 692 orphaned order items was confirmed against docs/diagnosis.md, docs/phase1_results.md and docs/phase2_experiments.md. The count remained unchanged.

Historical integrity faults were deliberately preserved.
No evidence of additional integrity problems was found
in the compared measurements.

Aggregate comparisons do not establish complete
row-by-row historical data equivalence.


## Phase 3 conclusion

The inventory audit implementation supports:

- Sales through the existing optimized checkout function.
- Restocking.
- Returns following successful inspection.
- Positive and negative inventory corrections.
- Damage deductions.
- Physical stock takes.

Each successful controlled movement records its stock
adjustment in the inventory log within the same
transaction.

Row-level locking prevents competing operations from
incorrectly consuming or overwriting available stock.

Restricted application permissions prevent the tested
direct stock and audit modifications.

### Acceptance evidence

| Test category | Result |
|---|---|
| Functional inventory tests | 19/19 passed |
| Atomic rollback tests | Passed |
| Concurrent inventory tests | 30/30 passed |
| Application permission tests | 12/12 passed |
| Official concurrency tests | 4/4 passed |
| Repeated flash-sale median | 6.90 seconds |
| Remaining synthetic test products | 0 |
| Remaining temporary test constraints | 0 |
| Final inventory verification | Passed |

### Would triggers alone prevent overselling?

Not necessarily. A trigger can automatically record
inventory changes or reject invalid values, but it does
not by itself guarantee that competing purchases cannot
claim the same available stock.

The checkout implementation uses an atomic conditional
stock deduction, while other inventory movements lock
the affected product before calculating adjustments.

These mechanisms coordinate competing operations.
Explicit audit logging ensures that successful stock
changes and their corresponding movement records are
committed together.

Restricted database permissions prevent the application
from bypassing these controlled operations.

### Remaining limitations

- Historical data inconsistencies remain unresolved.
- Administrators can bypass application restrictions.
- Application authentication is not yet configured.
- Return inspection approval depends on trusted input.
- Flash-sale execution times are not consistently below
  ten seconds despite the repeated median of 6.90 seconds.
- Local test results do not guarantee production performance.
- Final fresh-load integration testing remains part of
  Phase 8.
