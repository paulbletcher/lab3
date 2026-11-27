# Phase 2 — Flash Sale Performance Investigation

## Baseline

The official flash-sale concurrency test successfully processed 400 purchase attempts against 50 available units in 16.10 seconds.

All functional assertions passed, but the measured wall-clock duration exceeded the ten-second business performance target by 6.10 seconds.

## Investigation 1 — Database Environment

### Objective

Inspect the PostgreSQL environment and checkout implementation to identify possible sources of performance overhead before introducing optimizations.

### Investigation script

`tests/phase2/investigate_flash_sale.sql`

### Observed results

| Measurement             | Result                   |
| ----------------------- | ------------------------ |
| PostgreSQL version      | 18.7                     |
| Maximum connections     | 500                      |
| Shared buffers          | 128 MB                   |
| Work memory             | 4 MB                     |
| Effective cache size    | 4 GB                     |
| Synchronous commit      | On                       |
| fsync                   | On                       |
| Checkout table indexes  | Primary-key indexes only |
| Checkout table triggers | None                     |
| Recorded deadlocks      | 0                        |
| pg_stat_statements      | Not installed            |
| Function tracking       | Disabled                 |

### Conclusion

The initial inspection did not establish a specific database performance bottleneck.

The official race test includes Python thread creation, database connection establishment, concurrent checkout execution and connection cleanup in its wall-clock measurement.

Further investigation is required to distinguish connection overhead from database execution and row-lock contention.

No database configuration, indexes or checkout logic were modified during this investigation.

## Investigation 2 — Database Connection Overhead

### Objective

Determine how much overhead is introduced by creating 400 concurrent database connections independently of the checkout function.

### Investigation scripts

- `tests/phase2/connection_probe.sql`
- `tests/phase2/benchmark_connections.py`

### Test procedure

Created 400 independent PostgreSQL connections using Python threads and synchronized their execution using a threading barrier.

Each connection executed a lightweight SELECT 1 query instead of the checkout function.

### Observed results

| Measurement                 |         Result |
| --------------------------- | -------------: |
| Attempted connections       |            400 |
| Successful connections      |            400 |
| Successful queries          |            400 |
| Errors                      |              0 |
| Total wall-clock time       |   9.66 seconds |
| Time before barrier release |   8.02 seconds |
| Time after barrier release  |   1.64 seconds |
| Average connection time     | 1.1049 seconds |
| Maximum connection time     | 3.3242 seconds |
| Average query response time | 0.6403 seconds |
| Maximum query response time | 1.6035 seconds |

### Conclusion

The benchmark demonstrated significant overhead associated with establishing 400 independent database connections and coordinating concurrent threads.

Even without checkout operations, the benchmark required 9.66 seconds, approaching the ten-second business performance target.

This suggests that connection management and client-side concurrency overhead are important contributors to the measured flash-sale duration.

However, the difference between the connection benchmark and the official checkout benchmark cannot be attributed entirely to checkout logic because the measurements were obtained from separate executions.

Further investigation is required to measure database wait events and row-lock contention during the official flash-sale test.

No database records, configuration settings or checkout logic were modified.

## Investigation 3 — Fixture Cleanup and Safety Verification

### Objective

Verify that previous concurrency tests removed their temporary records and that the next flash-sale fixture does not conflict with existing historical references.

### Investigation script

`tests/phase2/check_fixture_cleanup.sql`

### Observed results

| Measurement   | Original count | Current count |
| ------------- | -------------: | ------------: |
| Products      |          4,023 |         4,023 |
| Orders        |        159,384 |       159,384 |
| Order items   |        336,559 |       336,559 |
| Inventory log |        282,352 |       282,352 |

| Fixture safety check              | Result |
| --------------------------------- | -----: |
| Remaining test fixtures           |      0 |
| Next flash-sale fixture ID        |  10123 |
| Existing order item references    |      0 |
| Existing inventory log references |      0 |

### Conclusion

All four table counts matched their original baseline counts, and no official test fixtures remained in the products table.

The next flash-sale fixture ID had no existing historical references in either order_items or inventory_log.

The database was therefore suitable for repeating the flash-sale test with this fixture ID.

Matching row counts provide evidence of successful cleanup but do not independently establish that every historical record remains unchanged.

No database records were modified during this investigation.

## Investigation 4 — PostgreSQL Wait-Event Monitoring During Flash Sale

### Objective

Observe PostgreSQL activity during the official 400-buyer flash-sale test to identify connection activity, database waits and possible contention affecting checkout performance.

### Investigation script

`tests/phase2/monitor_flash_sale.sql`

The monitoring script was updated to:

- Return aggregated JSON monitoring samples.
- Record database connection counts.
- Distinguish active checkout connections from other active sessions.
- Record the oldest active checkout duration.
- Group connections by state and PostgreSQL wait event.
- Continue sampling during periods with no active checkout activity.

The actual investigation used an autocommit driver to execute the monitoring SELECT repeatedly at approximately 0.5-second intervals until test cleanup finished.

### Test procedure

Executed the unchanged official test:

`python .\race_test.py --test 2 --verbose`

The monitoring and official test ran concurrently against `kloudkart_rebuild` on port 5433.

### Observed results

| Measurement                                 |        Result |
| ------------------------------------------- | ------------: |
| Concurrent buyers                           |           400 |
| Successful purchases                        |            50 |
| Refused purchases                           |           350 |
| Errors                                      |             0 |
| Official test wall time                     | 12.89 seconds |
| Whole process including setup and cleanup   | 13.64 seconds |
| Peak database connections excluding monitor |           402 |
| Peak active connections excluding monitor   |           380 |
| Peak active checkout calls                  |           380 |

### PostgreSQL Wait-Event Observations

| Wait event             | Peak waiting connections | Samples containing event |
| ---------------------- | -----------------------: | -----------------------: |
| Client / ClientRead    |                      387 |                       30 |
| LWLock / LockManager   |                      269 |                        3 |
| LWLock / BufferContent |                       21 |                        1 |
| Lock / tuple           |                      286 |                        5 |
| Lock / transactionid   |                       82 |                        6 |
| IO / WalSync           |                        1 |                        4 |

The combined Lock peak was 287 connections.

These peaks occurred at different times and should not be added together.

### Representative observations

| UTC timestamp | Connections | Active | Observation                                               |
| ------------- | ----------: | -----: | --------------------------------------------------------- |
| 11:43:25.054  |         388 |      0 | 387 connections waiting in ClientRead                     |
| 11:43:26.300  |         402 |    380 | Significant LockManager and BufferContent waits           |
| 11:43:28.304  |         355 |    353 | LockManager, transaction ID and WAL synchronization waits |
| 11:43:28.789  |         290 |    288 | Significant tuple-lock waiting                            |
| 11:43:32.775  |           2 |      0 | Returned to baseline idle connections                     |

### Sampling Performance and Limitations

A total of 30 monitoring samples were collected over 16.28 seconds.

- Median sampling interval: 0.500 seconds.
- One monitoring query took 1.771 seconds.
- One sampling gap reached 2.286 seconds.

Short-lived waits and some actual peaks may therefore have been missed.

The monitoring did not capture complete blocking chains or identify individual lock targets.

### Interpretation

The ClientRead observations are consistent with database connections waiting for additional commands from Python clients, including buyers waiting at the synchronization barrier.

The tuple and transaction ID waits are consistent with contention involving concurrent transactions accessing the shared product.

The LockManager observations indicate additional internal PostgreSQL lock-management contention.

However, the investigation does not establish which of these factors contributes most to total execution time.

The sampled WAL synchronization waits were limited, but this does not independently rule out significant WAL latency.

### Fixture Cleanup Verification

Both pre-test and post-test cleanup checks passed.

| Table         |  Before |   After |
| ------------- | ------: | ------: |
| Products      |   4,023 |   4,023 |
| Orders        | 159,384 | 159,384 |
| Order items   | 336,559 | 336,559 |
| Inventory log | 282,352 | 282,352 |

No temporary test fixtures remained, and the next fixture had no existing historical references.

Matching row counts provide reconciliation evidence but do not establish row-by-row equality.

### Conclusion

The official flash-sale test passed all functional assertions but completed in 12.89 seconds, exceeding the ten-second business target by 2.89 seconds.

The monitoring identified substantial connection activity, lock-manager contention and row-lock waits during checkout.

These observations provide evidence of possible performance bottlenecks, but additional investigation is required to establish their individual contribution to execution time.

No checkout logic, indexes or PostgreSQL configuration settings were modified.

**Investigation 4 completed. Performance optimization remains outstanding.**

## Investigation 5 — Blocking Transactions and Lock Targets

### Objective

Identify the transactions blocking concurrent buyers during the official flash-sale test and establish whether contention is occurring on the shared product row.

### Investigation script

`tests/phase2/investigate_blocking.sql`

The investigation used:

- `pg_blocking_pids()` to identify blocking relationships.
- `pg_stat_activity` to inspect waiting and blocking sessions.
- `pg_locks` to inspect granted and ungranted locks.
- `pg_class` to resolve relation identifiers to table names.

### Test procedure

Executed the unchanged official test:

`python .\race_test.py --test 2 --verbose`

Blocking relationships were sampled repeatedly during the test using autocommit monitoring queries.

### Observed results

| Measurement                               |        Result |
| ----------------------------------------- | ------------: |
| Official Test 2 execution time            | 21.26 seconds |
| Whole process including setup and cleanup | 22.49 seconds |
| Successful purchases                      |            50 |
| Refused purchases                         |           350 |
| Errors                                    |             0 |
| Overselling incidents                     |             0 |
| Monitoring samples                        |            31 |
| Samples containing blocking relationships |             8 |
| Peak blocked sessions                     |           324 |
| Peak distinct reported blockers           |           324 |
| Peak sessions blocked by one backend      |           323 |
| Peak blocking relationships               |        52,327 |

The blocking relationship graph was dense because PostgreSQL can report earlier conflicting transactions in the lock queue as blockers, including sessions that are themselves waiting.

### Lock-target observations

| Lock type      | Requested mode | Peak requests | Resolved relation          | Maximum sampled wait age |
| -------------- | -------------- | ------------: | -------------------------- | -----------------------: |
| Tuple          | ExclusiveLock  |           323 | public.products            |            4.776 seconds |
| Transaction ID | ShareLock      |            64 | No direct relation mapping |            0.880 seconds |

Corresponding granted holders had ExclusiveLock.

No ungranted relation locks or other heavyweight lock types were sampled.

### Confirmed product-row contention

Seven monitoring samples identified a contested product tuple whose physical coordinates matched the visible synthetic flash-sale fixture row.

Up to 323 requests were waiting for that matched tuple.

An earlier sample contained six other product tuple locations without a confirmed logical identity.

At the peak, one backend held the contested tuple's ExclusiveLock while itself waiting for a transaction-ID ShareLock. A total of 323 sessions listed it as a blocker.

### Sampling limitations

| Measurement                                        |        Result |
| -------------------------------------------------- | ------------: |
| Total samples                                      |            31 |
| Median sampling interval                           | 0.501 seconds |
| Maximum sampling gap                               | 3.765 seconds |
| Slowest monitoring query                           | 3.252 seconds |
| Relationships without matching lock-target context |            57 |

Activity snapshots, lock snapshots and blocker-function calls were not globally atomic. Some short-lived waits may have been missed.

The reported wait ages represent elapsed time for current waits, not completed per-call wait durations.

### Fixture cleanup verification

| Table         |  Before |   After |
| ------------- | ------: | ------: |
| Products      |   4,023 |   4,023 |
| Orders        | 159,384 | 159,384 |
| Order items   | 336,559 | 336,559 |
| Inventory log | 282,352 | 282,352 |

No temporary test fixtures remained, and no historical references to the next fixture ID were found.

### Interpretation

The investigation confirmed substantial contention on the synthetic flash-sale product row.

The tuple-lock observations establish that concurrent buyers were competing for the same physical product record.

Transaction-ID waits and LockManager contention were also observed.

The findings are consistent with PostgreSQL serializing competing stock updates to protect inventory consistency.

However, the investigation does not quantify the proportion of total execution time attributable to product-row contention.

The 21.26-second result was obtained under heavier monitoring and cannot be directly compared with earlier runs to measure optimization effects.

### Conclusion

The checkout function maintained inventory correctness under heavy concurrent demand.

Exactly 50 purchases succeeded, 350 were refused, and no errors or overselling occurred.

Product-row contention is now a confirmed performance concern requiring further investigation.

No checkout logic, indexes, PostgreSQL configuration or original race-test code were modified.

\*\*Investigation 5 completed. Performance optimization remains outstanding.

## Investigation 6 — Checkout Transaction Duration and Lock-Holding Time

### Objective

Measure the execution time of individual checkout operations and estimate how long the product-row lock remains held during concurrent purchases.

### Investigation files

- `tests/phase2/place_order_timed.sql`
- `tests/phase2/benchmark_checkout_stages.py`

A separate diagnostic function was created to instrument checkout operations without modifying the original `public.place_order()` function.

### Test procedure

Simulated 400 concurrent buyers competing for 50 units using the diagnostic checkout function.

The diagnostic runner preserved the transaction boundary used by the official race-test harness, which relies on autocommit rather than a separate worker commit operation.

### Observed results

The diagnostic run completed in 21.109 seconds, including 11.330 seconds before barrier release and 9.779 seconds afterwards.

| Measurement                               |         Result |
| ----------------------------------------- | -------------: |
| Concurrent buyers                         |            400 |
| Successful purchases                      |             50 |
| Refused purchases                         |            350 |
| Errors                                    |              0 |
| Final stock                               |              0 |
| Diagnostic execution time                 | 21.109 seconds |
| Whole process including setup and cleanup |  22.49 seconds |

### Checkout Operation Timings

All timings are in milliseconds and are reported as average / median / maximum.

| Measured interval                  | Successful purchases              | Refused purchases                 |
| ---------------------------------- | --------------------------------- | --------------------------------- |
| Before stock UPDATE                | 1,686.689 / 1,892.814 / 3,714.114 | 1,672.029 / 1,728.067 / 3,901.407 |
| Stock UPDATE, including lock waits | 1,448.357 / 1,395.925 / 3,983.353 | 4,756.390 / 4,737.167 / 9,103.084 |
| Order INSERT                       | 33.857 / 3.384 / 1,183.010        | Not applicable                    |
| Order-item INSERT                  | 19.082 / 0.779 / 791.300          | Not applicable                    |
| Inventory-log INSERT               | 5.955 / 1.668 / 85.355            | Not applicable                    |
| Total function execution           | 3,204.676 / 3,350.809 / 4,908.155 | 6,430.851 / 6,530.596 / 9,169.099 |

The pre-UPDATE interval is a derived residual covering validation and other work before the stock UPDATE timer begins.

The stock UPDATE measurement includes both waiting for the product-row lock and executing the update. It does not isolate lock-acquisition time.

### Lock-Holding Time

The diagnostic runner measured the interval between successful stock UPDATE completion and function near-return.

| Measurement                                |       Result |
| ------------------------------------------ | -----------: |
| Average post-UPDATE interval               |    69.630 ms |
| Median post-UPDATE interval                |    13.840 ms |
| Maximum post-UPDATE interval               | 2,466.649 ms |
| Average client-acknowledgement upper bound |   110.554 ms |
| Maximum estimated upper bound              | 2,624.206 ms |

The product-row lock remains held until transaction completion, not merely until the function returns.

The measured post-UPDATE interval provides a lower bound on lock residence after stock deduction. Client acknowledgement provides an estimated upper bound under the diagnostic clock assumptions.

Exact commit duration and exact lock-acquisition wait were not isolated.

### Interpretation

The investigation identified three important areas of performance overhead.

1. Significant time was spent before the stock UPDATE, averaging approximately 1.67 seconds for both successful and refused purchases.
2. The stock UPDATE experienced substantial contention. Refused purchases spent an average of approximately 4.76 seconds in this operation, compared with approximately 1.45 seconds for successful purchases.
3. The successful checkout path performed order creation, order-item insertion and inventory logging while the product-row lock remained held.

The relatively small median insertion times suggest that the insert operations are not necessarily the dominant source of delay. However, their maximum values indicate occasional long-running operations.

The measurements do not establish the exact proportion of total execution time attributable to each underlying cause.

### Cleanup and Integrity Verification

The diagnostic test completed successfully:

- All 50 available units were sold.
- The remaining 350 purchases were refused.
- No errors occurred.
- Final stock was zero.
- All six historical table counts were restored.
- Temporary synthetic records were removed.
- The diagnostic function and schema were removed.

The original `race_test.py` and `public.place_order()` remained unchanged.

### Conclusion

The investigation confirmed substantial time spent waiting during stock deduction, particularly for unsuccessful purchases competing for an exhausted product.

It also identified significant pre-UPDATE execution time and additional work performed before the transaction releases its product-row lock.

These findings provide a basis for targeted performance improvements.

No optimization was implemented during this investigation.

**Investigation 6 completed. Performance optimization remains outstanding.**
