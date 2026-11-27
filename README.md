# Kloud Kart - DE03 SQL Lab

A PostgreSQL solution for safe checkout, auditable inventory movements, customer spending, recursive low-stock visibility and a recurring completed-order review queue. Historical records are preserved. All five deliverables are mapped in [docs/submission_checklist.md](docs/submission_checklist.md).

The final implementation extends the existing project. The original `schema.sql`, `load.sql`, `race_test.py`, six confidential CSVs and historical investigation documents remain intact. `functions/phase3_place_order.sql` is the retained checkout; Phase 2 and the rejected experiments are historical references. Do not execute every SQL file indiscriminately.

## Project structure

```text
lab3/
  data/                         six confidential original CSVs; Git-ignored
  decisions/                    exactly six final architecture decision records
  docs/                         final deliverables plus retained phase investigations
  functions/                    retained checkout, movements and access control
  migrations/                   sequence defaults and safe ID initialization
  reports/                      spending, recursive low stock and order review queue
  tests/
    inventory_audit/             retained movement, rollback and role tests
    phase0/, phase2/, phase3/    retained investigation and concurrency evidence
    phase4/                     retained reporting investigation
    final_verification.py       guarded fresh-load and end-to-end runner
    final_*.sql                 assertions and rollback-only scenarios
    reference_customer_spending.sql  original report for exact comparison
    final_*.log/json/txt         final aggregate/synthetic evidence and plans
  schema.sql, load.sql           unchanged supplied initialization files
  race_test.py                  unchanged supplied concurrency harness
  integrity_checks.sql          retained 21 diagnosis checks
  setup_checks.sql              environment/object inspection
  run_all.sql                   complete fail-fast non-destructive installer
```

## Prerequisites and isolated setup

Use Windows PowerShell from this project directory, Docker Desktop, Python 3 and `psycopg2-binary`:

```powershell
Set-Location '<PROJECT_DIR>'
python -m pip install psycopg2-binary
docker ps --format '{{.Names}} {{.Ports}}'
docker inspect kloudkart_rebuild --format '{{json .Mounts}}'
```

Verified environment: `kloudkart_rebuild`, PostgreSQL 18.7, 500 maximum connections, loopback host port 5433. Its read-only `/lab` bind mount points to this project. The original `kloudkart` container on port 5432 is preserved. The existing rebuilt `postgres` database is also preserved: final tests use `kloudkart_submission_20261127` in the rebuilt container.

Only if `kloudkart_rebuild` does not exist, create that isolated environment from this directory. Supply the password interactively; do not put credentials in a file:

```powershell
$credential = Get-Credential -UserName postgres -Message 'Password for the new isolated PostgreSQL container'
$env:POSTGRES_PASSWORD = $credential.GetNetworkCredential().Password
docker run -d --name kloudkart_rebuild --env POSTGRES_PASSWORD --publish 127.0.0.1:5433:5432 --mount "type=bind,source=$($PWD.Path),target=/lab,readonly" postgres:18 -c max_connections=500
Remove-Item Env:POSTGRES_PASSWORD
docker exec kloudkart_rebuild pg_isready -U postgres
```

Wait until `pg_isready` accepts connections. Keep the six supplied CSVs under `data/`. Container-side `\ir` and `\copy` resolve `/lab` paths through the bind mount; they cannot read arbitrary Windows paths. Host `psql` is not required. The runner privately obtains the named container's password in memory and verifies that the host connection and container have the same cluster identifier. It never writes its connection string.

## Fresh load, installation and all checks

The following command creates a uniquely named disposable database, loads the original schema/CSVs, installs the solution twice to verify safe reinstallation, runs all final SQL checks and the unchanged official harness, collects three authenticated Linux flash-sale observations and times both reports. It now fails if any observation exceeds ten seconds (unless --allow-slow-race is explicitly selected):

```powershell
$testDb = 'kloudkart_submission_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
python tests/final_verification.py --fresh --database $testDb
if ($LASTEXITCODE -ne 0) { throw 'Final verification failed; inspect tests/final_*.log' }
```

`--fresh` refuses an existing database. It never drops or resets either existing database. The original `schema.sql` contains DROP statements and is run only after creating the new, verified disposable database. All commands execute inside `kloudkart_rebuild`, working directory `/lab`, with `ON_ERROR_STOP=1`. Raw records are not copied into evidence. Sequence numbers consumed by rolled-back tests intentionally remain consumed.

To repeat the complete verification on the already verified submission database:

```powershell
python tests/final_verification.py
if ($LASTEXITCODE -ne 0) { throw 'Final verification failed' }
```

To install only, against the loaded disposable database:

```powershell
docker exec -w /lab kloudkart_rebuild psql -X -U postgres -d kloudkart_submission_20261127 -v ON_ERROR_STOP=1 -f run_all.sql
```

`run_all.sql` installs sequences, checkout, controlled movements, restricted permissions, three spending views, four category views and the improvement, then runs reconciliation assertions. No historical corrections or CSV reloads occur in it. Run installations with application writers stopped: sequence synchronization is a maintenance operation. Roles are reused only if their privilege attributes are safe. The solution requires administrative installation privileges; both application roles are NOLOGIN and production authentication remains a deployment task.

Final test output is overwritten by a repeat; copy evidence locally first if you need to retain a particular run. The initial final-suite observation and its source-check correction are retained separately as `tests/final_initial_*`.

## Original official concurrency test

The guarded runner builds the pinned client in `tests/phase3/Dockerfile.client` and executes `race_test.py` unchanged in a temporary Linux client. It still opens 400 independent TCP connections, using the container bridge address and SCRAM password authentication; a preflight verifies that a wrong password is rejected. The source is mounted read-only. No CSVs enter the client image and no production service is added. First setup needs an image/package download; subsequent builds use the cache. Native Windows execution remains available with `--race-client windows --allow-slow-race` as a diagnostic. The default verification command is the accepted timing route. To invoke the unchanged harness directly from native Windows for comparison, privately enter the password:

```powershell
$credential = Get-Credential -UserName postgres -Message 'Password for kloudkart_rebuild'
$env:PGPASSWORD = $credential.GetNetworkCredential().Password
$env:DATABASE_URL = 'host=127.0.0.1 port=5433 dbname=kloudkart_submission_20261127 user=postgres'
python race_test.py --verbose
$raceExit = $LASTEXITCODE
Remove-Item Env:PGPASSWORD
Remove-Item Env:DATABASE_URL
if ($raceExit -ne 0) { throw 'Official concurrency test failed' }
```

Use this fixture-creating harness only in a disposable database. The guarded runner also checks the fixture IDs and complete six-table fingerprints before/after cleanup. Do not point it to the original database.

## Run the reports

These commands display confidential reports locally. Keep customer/order rows out of Git and shared logs.

```powershell
# All customers: totals, twelve monthly amounts, ranks and top-100 indicator.
docker exec kloudkart_rebuild psql -X -U postgres -d kloudkart_submission_20261127 -c 'SELECT * FROM public.report_customer_spending ORDER BY top_100_position;'
# Running totals, with deterministic same-time order-ID tie breaking.
docker exec kloudkart_rebuild psql -X -U postgres -d kloudkart_submission_20261127 -c 'SELECT * FROM public.report_customer_order_running_totals ORDER BY customer_id, order_date, order_id;'
# Recursive low stock, inclusive threshold of ten units.
docker exec kloudkart_rebuild psql -X -U postgres -d kloudkart_submission_20261127 -c 'SELECT * FROM public.report_low_stock_by_category ORDER BY category_id;'
docker exec kloudkart_rebuild psql -X -U postgres -d kloudkart_submission_20261127 -c 'SELECT * FROM public.report_category_exceptions; SELECT * FROM public.report_category_cycles;'
# Additional improvement: Finance/Ops review queue, including overlapping flags.
docker exec kloudkart_rebuild psql -X -U postgres -d kloudkart_submission_20261127 -c 'SELECT * FROM public.report_order_review_queue ORDER BY exception_type, order_id;'
# Execution plans without printing customer rows.
docker exec -w /lab kloudkart_rebuild psql -X -U postgres -d kloudkart_submission_20261127 -v ON_ERROR_STOP=1 -f reports/phase6_performance_baseline.sql
```

Reports use live `CURRENT_DATE`; recorded baseline totals apply to 2026-11-27. The spending report uses recorded totals for attributable complete/completed orders through today, with the current and preceding eleven calendar months. It includes 2,520 zero-order customers on the verified date. Future dates and absent customers are excluded. The review queue intentionally covers all completed dates. Neither output establishes actual receipts. Unknown prices are never invented.

The category rollup has cycle protection and no fixed depth cap; disconnected assignments and NULL stock are disclosed separately. Sum only root-category totals when reconciling distinct products. See ADR-004/005 for the definitions and limitations.

## Submission documents and retained evidence

- [Data findings](docs/data_findings.md) (D1); original [diagnosis](docs/diagnosis.md) and [all 21 check results](docs/phase1_results.md) remain available.
- [Complete installer](run_all.sql) and SQL under `functions/`, `migrations/`, `reports/` (D2).
- [Six ADRs](decisions/) (D3).
- [One-page memo to Nana](docs/client_memo.md) (D4).
- [Implemented improvement](docs/improvement.md) and [review view](reports/order_review_queue.sql) (D5).
- [Measurement report](docs/performance_report.md), [submission checklist](docs/submission_checklist.md), [final evidence](tests/final_evidence.json), [raw plans](tests/final_plans.txt) and [official output](tests/final_race.log).
- Prior checkout timing investigations: [Phase 2 performance](docs/phase2_performance.md), [experiments](docs/phase2_experiments.md), [Phase 3 optimization](docs/phase3_optimization.md), [inventory audit](docs/inventory_audit.md). Their historical pending/status statements are snapshots; this README and final deliverables describe the completed submission.

## Confidentiality and limitations

The six original files are categories.csv, products.csv, customers.csv, orders.csv, order_items.csv and inventory_log.csv. They remain local and ignored. Do not commit credentials, environment files or customer-level records. No commit or push is part of this work.

Local simulation does not establish production readiness or a consistent ten-second flash-sale bound. The measurement report retains over-target observations. Audit enforcement depends on restricted application connections; administrators retain bypass privileges. Historical inconsistencies need business evidence. A current stock-runway forecast was rejected because the inventory history has no recent sales and contains future records; the completed-order review queue is the delivered improvement.


The final selected checkout is the lock-first version in `functions/phase3_place_order.sql`: lock the current product balance, validate availability, then deduct stock and insert the order, item and movement atomically. Its authenticated Linux trials were **9.29, 7.98 and 7.54 seconds**, each with 50 purchases, 350 refusals and zero errors. The final full-suite confirmation took 19.62 seconds, so the ten-second target remains inconsistent. All four correctness tests passed. Native Windows and production latency are not established by the faster trials. See `tests/phase3/logs/flash_final_selected.json` for final confirmation and `docs/phase3_optimization.md` for retained unfavorable comparisons.


Official deliverables: [D1 findings](docs/data_findings.md), [D2 SQL](run_all.sql), [D3 decisions](decisions/), [D4 memo](docs/client_memo.md), [D5 improvement](docs/improvement.md). Historical test evidence is marked in [tests/README.md](tests/README.md). See [three-minute gap-fix summary](docs/gapfix_summary.md) for completed work and limits.
