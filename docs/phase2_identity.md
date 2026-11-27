# Phase 2: Automatic ID Generation

Verified on 2026-11-27 (UTC), using PostgreSQL 18.7 in Docker container `kloudkart`, database/user `postgres`.

This document records the historical identity-migration stage. At that stage, automatic ID generation was complete; checkout, input validation, stock-concurrency controls and an audit mechanism were not implemented, and the supplied `race_test.py` had not been changed or executed.

**Current project state:** Phase 2 is complete and Phase 3 is in progress. `place_order` now validates and locks requests, reserves stock and atomically creates a pending order, item and sale movement. The unchanged official race harness has since passed all four tests; see [Phase 2 test results](phase2_test_results.md). Step 3.2 reporting decisions and results are recorded in [Phase 3 reporting](phase3_reporting.md). Payment processing, reservation expiry, cancellation handling, permanent foreign keys and auditing of arbitrary inventory updates remain unimplemented.

## Historical connection investigation and cause

The active Docker database already had `ALWAYS` identities on all three target columns when inspected. Their sequences were at the correct initial values, with `is_called = false`.

At the start of this investigation, the root `checkout.sql` unconditionally used `ADD GENERATED ALWAYS AS IDENTITY`. Adding identity to an existing identity column raises the reported error. Its unconditional `setval(..., calculated_start, false)` calls would also risk rewinding a used sequence if they were rerun independently. The archived migration uses `BY DEFAULT`; it is reference material rather than the active implementation. The corrected migration behavior is described below.

During identity-stage verification, the observed VS Code sessions for both `checkout.sql` and `checkout_prechecks.sql` appeared in Docker's `pg_stat_activity`, connected to database `postgres` from `172.17.0.1`. Those sessions and Docker's terminal reached the same database. This was server-side evidence rather than an assumption based on both connections using port 5432; it is not a fresh inspection of today's editor sessions.

| Target | Cluster identifier | State |
|---|---|---|
| Docker PostgreSQL | `7712053334814294059` | Running; data directory `/var/lib/postgresql/18/docker` |
| Windows PostgreSQL installation | `7679895446199702688` | Service `postgresql-x64-18` stopped; local cluster shut down |

Docker publishes port 5432. The observed Windows listeners belong to `com.docker.backend` and `wslrelay`, not a running Windows PostgreSQL server. No service, port, VS Code connection, or server configuration was changed.

The earlier `NO` result cannot describe these same columns at the same time as the identity error. It may have been obtained before a successful migration or from a different earlier connection/snapshot. Its original execution time and server fingerprint are unavailable, so that earlier target cannot be established conclusively. There is no evidence of a current connection mismatch. The confirmed migration defect is unconditional reapplication of `ADD ... AS IDENTITY`.

The read-only `checkout_prechecks.sql` now reports a cluster/database fingerprint so future observations can be attributed to a specific target. It works with absent identity sequences and prints their exact state as notices once they exist. A NULL `column_default` is normal for an identity column; use `is_identity`, `identity_generation`, and the associated sequence, rather than interpreting the default alone.

## Migration behavior

The root [checkout.sql](../checkout.sql) performs only the ID-generation step:

1. Begin a transaction and lock the three tables before reading ID boundaries.
2. Add `ALWAYS` identity when missing, convert an existing `BY DEFAULT` identity with `SET GENERATED ALWAYS`, and retain an existing `ALWAYS` identity.
3. Discover the associated sequence with `pg_get_serial_sequence()`.
4. Acquire a sequence DDL lock before reading its state and enforce `NO CYCLE`. This also blocks direct allocations while the migration transaction is open.
5. Calculate the first safe ID from the actual data. Orders include both existing order IDs and every order ID referenced by items.
6. Calculate the sequence's next value as `last_value` when `is_called = false`, otherwise `last_value + 1`.
7. Use a transactional `ALTER SEQUENCE ... RESTART WITH` only when that next value is below the safe data boundary. An already safe or higher sequence is not restarted.

The migration supports the lab's standard integer sequences with increment 1 and cache 1. It fails transactionally for unexpected type/increment/cache settings or exhausted integer capacity, rather than silently replacing objects or changing those settings. The lock timeout is local to the transaction and does not change server configuration.

`SET GENERATED` changes future insert behavior without rewriting historical row values. A forward `RESTART` is transactional, whereas `setval()` is not rolled back with the surrounding transaction. See the PostgreSQL 18 documentation for [identity alteration](https://www.postgresql.org/docs/18/sql-altertable.html) and [sequence alteration](https://www.postgresql.org/docs/18/sql-altersequence.html).

## Verified configuration at the identity-migration stage

| Table / column | Identity mode | Associated sequence | last_value | is_called | Next ID |
|---|---|---|---:|---|---:|
| orders.order_id | ALWAYS | public.orders_order_id_seq | 999863 | false | 999863 |
| order_items.order_item_id | ALWAYS | public.order_items_order_item_id_seq | 1236560 | false | 1236560 |
| inventory_log.log_id | ALWAYS | public.inventory_log_log_id_seq | 982488 | false | 982488 |

All three sequences have type `integer`, start/minimum 1, maximum 2147483647, increment 1, cache 1, and no cycling. The starting configuration value of 1 is separate from the current sequence state shown above.

| Data boundary | Observed maximum |
|---|---:|
| Existing order IDs | 659384 |
| Order IDs referenced by items | 999862 |
| Existing item IDs | 1236559 |
| Existing inventory log IDs | 982487 |

These numbers are observed results, not constants in the migration. The order boundary prevents a new order from taking an ID already referenced by a historical orphaned item.

The revised migration committed successfully against the current database. It retained the existing identities and all three sequence states; none required advancement or replacement. No `nextval()` or test inserts were executed against the current database.

Aggregate fingerprints and row counts for all six tables were identical before and after migration. At that stage, 692 orphaned order-item references remained and no `place_order` function existed. Historical records were not altered. The function was implemented and verified later, as documented in [Phase 2 test results](phase2_test_results.md).

## Isolated verification

Run [tests/verify_identity_migration.py](../tests/verify_identity_migration.py) from the project root with Python 3. It creates a uniquely named database from `template0` inside the same Docker PostgreSQL server. Only that temporary database receives `schema.sql`, `load.sql`, synthetic inserts, and deliberately invalid test settings.

The following checks passed:

| Case | Result |
|---|---|
| Original schema and fresh dataset load | All three initially have no identities; prechecks complete without missing-sequence errors |
| First migration | All three become `ALWAYS`, with next IDs 999863, 1236560, and 982488 |
| Repeat before any allocations | Exact sequence states and sequence object IDs are retained |
| Generated inserts | Default-generated IDs equal the safe initial values; synthetic rows are rolled back |
| Explicit ID inserts | All three reject ordinary explicit IDs under `ALWAYS` |
| Repeat after IDs have been issued | Sequence states are retained; issued values are not reused |
| Existing `BY DEFAULT` identities | Converted to `ALWAYS` without replacing sequences or changing allocation state |
| Later migration failure | An unsupported cache setting aborts the migration; an earlier forward adjustment rolls back |
| Historical test data | Counts and orphan count remain unchanged after rolled-back synthetic inserts |
| Cleanup | Temporary verification database removed; no verification databases remain |

## Identity-stage limitations

- The identity-stage tests alone establish ID generation, not checkout correctness, overselling protection, input validation or an inventory audit trail. Subsequent tests cover the implemented checkout path in [Phase 2 test results](phase2_test_results.md).
- Exclusive locks briefly block other table access. A lock timeout causes the transaction to fail safely; rerun the complete script after resolving contention.
- Integers retain their existing range. Allocation fails at the sequence maximum rather than wrapping around.
- Sequences can have gaps, including after rolled-back transactions; IDs are identifiers rather than consecutive business numbers.
- `ALWAYS` rejects ordinary explicit IDs, but administrators can bypass it with `OVERRIDING SYSTEM VALUE` or bulk loading. Future deliberate imports and manual sequence changes must preserve the data and historical-reference boundaries. See [PostgreSQL 18 identity columns](https://www.postgresql.org/docs/18/ddl-identity-columns.html).
- The exact historical source of the earlier `NO` output remains unproven; use the new fingerprint query for future checks.
