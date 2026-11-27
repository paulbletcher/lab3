# Kloud Kart - DE03 SQL Lab

This lab examines Kloud Kart's inherited PostgreSQL database and develops safe checkout, an inventory audit trail, and reliable reports. Phase 1 covers data diagnosis and the business risks identified in the supplied datasets.

## Current progress

| Phase | Status |
|---|---|
| Phase 0 - Environment setup | COMPLETE |
| Phase 1 - Data diagnosis | COMPLETE |
| Phase 2 - Safe checkout and inventory audit trail | COMPLETE |
| Phase 3 - Monday customer-spending report | IN PROGRESS - Step 3.5 running totals validated |
| Phase 4 - Recursive low-stock category rollup | NOT STARTED |
| Phase 5 - Additional improvement and final deliverables | NOT STARTED |

All 21 integrity checks are complete. Their observations, business implications, clarification items, reporting considerations, and final risk ranking are documented in [docs/diagnosis.md](docs/diagnosis.md). Aggregate results and schema verification are recorded in [docs/phase1_results.md](docs/phase1_results.md).

No historical records have been corrected or deleted to resolve the findings. The database retains the supplied datasets and their unresolved discrepancies. The original schema has been extended with generated identities and the checkout function; permanent foreign-key enforcement has not been added.

Phase 2 is complete: the three purchase-related primary keys use `GENERATED ALWAYS AS IDENTITY`, and `place_order` validates inputs, protects the customer key, locks the product, reserves stock and atomically creates a pending order, its item and a sale inventory movement. [Identity-stage verification](docs/phase2_identity.md) preserves the original migration investigation; [Phase 2 test results](docs/phase2_test_results.md) records the subsequent checkout, rollback, locking, audit and official race tests.

Checkout does not process payment. Reservation expiry, cancellation and stock restoration remain future work. The audit entry covers sales through `place_order`; arbitrary inventory updates are not automatically audited.

Phase 3 contains the validated order-level base, lifetime totals, monthly grid and order-level running totals, with LAG gaps and all-customer RANK practice. [Reporting decisions and results](docs/phase3_reporting.md) define recorded completed-order spending and the exclusive development cutoff of `2026-11-27 00:00:00`. The final top-100 report and its ranking-function decision remain for Step 3.6.

## Active project structure

```text
lab3/
|-- README.md
|-- .gitignore
|-- schema.sql
|-- load.sql
|-- integrity_checks.sql
|-- checkout_prechecks.sql
|-- checkout.sql
|-- place_order.sql
|-- report_base.sql
|-- customer_spending.sql
|-- monthly_spending.sql
|-- running_customer_totals.sql
|-- race_test.py
|-- docs/
|   |-- diagnosis.md
|   |-- phase1_results.md
|   |-- phase2_identity.md
|   |-- phase2_test_results.md
|   `-- phase3_reporting.md
|-- tests/
|   |-- test_checkout_validation.sql
|   |-- test_catalog_price_validation.sql
|   |-- test_stock_validation.sql
|   |-- verify_identity_migration.py
|   |-- verify_checkout_locking.py
|   |-- verify_atomic_checkout.py
|   |-- verify_customer_spending.py
|   |-- verify_monthly_spending.py
|   |-- verify_running_totals.py
|   `-- results/                # Preserved aggregate/test execution evidence
`-- data/                       # Confidential extracts; ignored by Git
```

| File | Responsibility |
|---|---|
| [schema.sql](schema.sql) | Defines the original six tables with ordinary integer primary keys. Apply the separate identity migration after loading. No foreign keys or indexes beyond the primary keys. |
| [load.sql](load.sql) | Loads six local CSV datasets with client-side `\copy`, runs `ANALYZE`, and reports row counts. |
| [integrity_checks.sql](integrity_checks.sql) | Contains the 21 Phase 1 diagnosis queries. |
| [checkout_prechecks.sql](checkout_prechecks.sql) | Read-only connection fingerprint, ID maxima, identity definitions, and exact sequence-state notices. Works before and after migration. |
| [checkout.sql](checkout.sql) | Repeatable migration to `ALWAYS` identities; advances sequences only when below the safe data boundary. |
| [place_order.sql](place_order.sql) | Defines atomic pending-order placement, customer/product locking, validation, stock reservation and linked sale auditing. |
| [report_base.sql](report_base.sql) | Constructs the four-column completed-order base and prints aggregate metrics, exclusion reconciliation and validation checks in a read-only snapshot. |
| [customer_spending.sql](customer_spending.sql) | Reusable local query: one row per customer with known recorded spending, completed-order count and missing-amount count. Its direct output is confidential; use the verifier for aggregate-only evidence. |
| [monthly_spending.sql](monthly_spending.sql) | Reusable local query: one row per customer per month across 12 derived calendar months, with zero-activity cells and explicit missing-amount counts. Direct output is confidential. |
| [running_customer_totals.sql](running_customer_totals.sql) | Reusable local order-level query: deterministic ROWS running spending/counts, timestamp-peer RANGE diagnostic, LAG calendar-day gaps and lifetime customer RANK. Direct output is confidential. |
| [race_test.py](race_test.py) | Supplied checkout contract and concurrency test harness for Phase 2. |
| [docs/diagnosis.md](docs/diagnosis.md) | Integrity observations, business implications, and final risk ranking. |
| [docs/phase1_results.md](docs/phase1_results.md) | Schema verification, row counts, all 21 check results, and the historical-data preservation policy. |
| [docs/phase2_identity.md](docs/phase2_identity.md) | Historical identity-stage observations, migration decisions, evidence and limitations. |
| [docs/phase2_test_results.md](docs/phase2_test_results.md) | Preserves intermediate validation evidence and completed atomic checkout/race verification. |
| [docs/phase3_reporting.md](docs/phase3_reporting.md) | Reporting rules and Steps 3.2 through 3.5 explanations, aggregate evidence, window-function findings and limitations. |
| [tests/verify_identity_migration.py](tests/verify_identity_migration.py) | Verifies the migration using a disposable database and removes that database afterward. |
| [tests/verify_checkout_locking.py](tests/verify_checkout_locking.py) | Verifies product-row blocking and committed-value visibility in a disposable synthetic database. |
| [tests/verify_atomic_checkout.py](tests/verify_atomic_checkout.py) | Verifies purchases, refusals, rollback, customer locks and IDs, then executes the unmodified official race harness in a disposable synthetic container. |
| [tests/verify_customer_spending.py](tests/verify_customer_spending.py) | Wraps the exact reusable customer query in aggregate-only live assertions and VALUES-based synthetic tests within one read-only snapshot; saves unique evidence logs. |
| [tests/verify_monthly_spending.py](tests/verify_monthly_spending.py) | Verifies the exact monthly query, grid completeness, independent monthly/lifetime reconciliation and date/NULL edge cases; prints only aggregates and saves unique evidence. |
| [tests/verify_running_totals.py](tests/verify_running_totals.py) | Verifies the actual running/rank CTEs using set-based recurrence, grouped timestamp peers, independent rank buckets and VALUES fixtures; saves aggregate-only evidence. |

## Environment

- PostgreSQL: `18.7 (Debian 18.7-1.pgdg13+5)`.
- Docker container: `kloudkart`.
- Database: `postgres`; database user: `postgres`.
- Windows project directory: `C:\Users\User\OneDrive\Desktop\amal\lab3`.
- Container project bind mount: `/lab`.

Run commands from the project directory in PowerShell. The commands use the container's `psql`, so host-installed `psql`, a host port mapping, and `DATABASE_URL` are not required. The container and project mount must be available. This repository does not supply a Dockerfile or Compose configuration.

```powershell
Set-Location 'C:\Users\User\OneDrive\Desktop\amal\lab3'
docker inspect --format '{{.State.Status}}' kloudkart
docker inspect --format '{{json .Mounts}}' kloudkart
docker exec -w /lab -i kloudkart psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 -c "SELECT current_database(), current_user, current_setting('server_version');"
```

Verify that the container is running, `/lab` maps to this project, and the connection identifies the intended database and user. If the container is stopped, start it with `docker start kloudkart`.

## Initial database setup

For initial setup, execute these scripts in order, proceeding only when each command succeeds:

```powershell
docker exec -w /lab -i kloudkart psql -U postgres -d postgres -v ON_ERROR_STOP=1 -f schema.sql
docker exec -w /lab -i kloudkart psql -U postgres -d postgres -v ON_ERROR_STOP=1 -f load.sql
docker exec -w /lab -i kloudkart psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 -f integrity_checks.sql
```

`schema.sql` drops any existing lab tables before creating the six tables, so it should only be used when intentionally initializing the lab. `load.sql` imports the datasets into empty tables. `ON_ERROR_STOP=1` stops the current script on an SQL error. Client-side `\copy` reads `/lab/data/` because `psql` runs with `/lab` as its working directory.

For diagnosis on an initialized database, execute only `integrity_checks.sql`. The checks report aggregate observations without changing historical data.

## Phase 2 automatic ID generation

On the initialized lab database, inspect the target, apply the migration, then inspect its configuration:

```powershell
docker exec -w /lab -i kloudkart psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 -f checkout_prechecks.sql
docker exec -w /lab -i kloudkart psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 -f checkout.sql
docker exec -w /lab -i kloudkart psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 -f checkout_prechecks.sql
```

Run the complete migration. It handles missing identities, converts `BY DEFAULT` to `ALWAYS`, and preserves existing `ALWAYS` identities. It dynamically finds the sequences and advances them only if necessary. Existing table rows are unchanged. The migration briefly takes exclusive table and sequence locks and stops if a lock cannot be acquired within 10 seconds.

The connection fingerprint can also be run in VS Code. Compare the cluster identifier and database name with Docker's output. A Unix-socket connection inside Docker can have a NULL server address while VS Code uses TCP; that alone does not mean they use different servers. Exact sequence-state values appear as notices in the client's Messages output.

To verify fresh-load behavior without touching the current database, run from the project root with Python 3:

```powershell
python tests/verify_identity_migration.py
```

This creates a uniquely named temporary database inside `kloudkart`, loads the supplied datasets there, exercises the migration, and removes only that temporary database afterward. Server errors are withheld from test output to protect confidential source values. Archived SQL is reference material; use the root scripts for the active implementation.

## Phase 2 checkout execution and verification

After the datasets and identity migration are in place, apply the checkout definition:

```powershell
docker exec -w /lab -i kloudkart psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 -f place_order.sql
```

Applying the definition does not place an order. Calling `place_order(bigint, bigint, integer)` can reserve stock and create business records. Explicit transaction callers must commit a successful call or roll back errors; the function does not commit internally. New orders have status `pending`, and the success response does not confirm payment.

For repeatable checkout verification, use Python 3 with `psycopg2-binary` and Docker:

```powershell
python tests/verify_atomic_checkout.py
```

This verifier creates a disposable PostgreSQL container with synthetic data and sufficient connections for 400 buyers, applies schema/identity/function setup only there, runs preliminary assertions and invokes `race_test.py` unchanged. It supplies the temporary `DATABASE_URL`, preserves uniquely named logs, and removes the isolated environment. The official harness creates and cleans committed fixtures, so use the isolated verifier for reruns.

The completed Phase 2 run passed all four official race tests: 25/25 last-unit rounds; 50 sales and 350 refusals with zero errors for 400 buyers; unchanged stock on an oversized request; and five sale movements for five successful purchases. These are historical executed results, with original output and limitations in [Phase 2 test results](docs/phase2_test_results.md).

## Phase 3 reporting-base verification

Run against the existing initialized database:

```powershell
docker exec -w /lab -i kloudkart psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 -P pager=off -f report_base.sql
```

The script uses a read-only REPEATABLE READ transaction and prints aggregates only. Its centralized cutoff is exclusive; it retains recorded order totals without recalculating line-item amounts. No permanent reporting objects are created. See [Phase 3 reporting](docs/phase3_reporting.md) for the actual results and reconciliation. This command does not require reinitializing or reloading the database.

For Step 3.3 aggregate-only customer-total verification, use Python 3 and Docker (no database driver or credentials are required):

```powershell
python tests/verify_customer_spending.py
```

The verifier checks the cutoff and eligibility CTE against `report_base.sql`, reuses `customer_spending.sql` unchanged inside aggregate queries, and validates live totals and synthetic edge cases in a read-only REPEATABLE READ transaction. Direct execution of `customer_spending.sql` is available for private local reporting and returns individual customer spending; do not use that output for shared logs or evidence. The spending column sums known recorded amounts; consult `missing_amount_count` before treating a customer's monetary total as complete.

For Step 3.4 aggregate-only monthly verification:

```powershell
python tests/verify_monthly_spending.py
```

The monthly window is derived from the cutoff: currently December 1, 2025 inclusive through November 27, 2026 exclusive. A cutoff exactly at a month boundary selects the previous month as the final reporting month. The verifier prints the twelve-month aggregate summary, checks every customer-month against grouped references, reconciles with the unchanged lifetime query and runs VALUES-only synthetic tests in one read-only REPEATABLE READ transaction. It requires only Python 3 and Docker. Direct execution of `monthly_spending.sql` returns individual customer-month records for private local use; keep that output out of shared logs.

For Step 3.5 aggregate-only running-total and window-function verification:

```powershell
python tests/verify_running_totals.py
```

The verifier reuses the actual order-level SQL and its all-customer rank CTE, checks recurrence/final totals against independent references and Step 3.3, and demonstrates ROWS/RANGE timestamp-peer behavior. LAG gaps use calendar-day subtraction. All live and VALUES-only checks run in one read-only REPEATABLE READ transaction. The reusable query covers lifetime eligible history and does not select a top 100. Keep its direct order-level output private.

## Confidential data

`data/` contains confidential extracts and is excluded by the `/data/` Git ignore rule. Keep CSV files local and unchanged. Do not commit or publish customer or transaction records or credentials. Documentation contains aggregate results only.
