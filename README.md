# Kloud Kart - DE03 SQL Lab

This branch retains the environment setup and initial data integrity investigation.
The transactional checkout now passes all four official concurrency tests.

The performance optimization work requested as **Phase 3** is documented in
[docs/phase3_optimization.md](docs/phase3_optimization.md). The retained function
is [functions/phase3_place_order.sql](functions/phase3_place_order.sql); its final
three unmonitored flash-sale runs completed in **7.47, 7.46 and 7.58 seconds**
(median **7.47 seconds**), with 50 purchases, 350 refusals and zero errors each.
The original Phase 2 implementation and every investigation record remain available.

Current checkout testing uses only `kloudkart_rebuild` at `127.0.0.1:5433`,
database/user `postgres`, PostgreSQL 18.7. The original container on port 5432
is excluded. Do not run the original schema or loader to deploy this function.

## Progress

| Phase | Status |
|---|---|
| Phase 0 - Environment setup | COMPLETE |
| Phase 1 - Data integrity diagnosis | COMPLETE |
| Phase 2 - Safe checkout and inventory auditing | COMPLETE - official tests passed |
| Phase 3 - Monday customer-spending report | PENDING |
| Phase 4 - Recursive low-stock category rollup | PENDING |
| Phase 5 - Additional improvement and final deliverables | PENDING |

The progress table retains the supplied lab's report/rollup numbering; the latest
optimization brief calls checkout performance work Phase 3. The Monday report
and category rollup remain pending.

The completed investigation, quantified business impacts, observations requiring clarification and risk ranking are preserved in [docs/diagnosis.md](docs/diagnosis.md). Aggregate results and historical schema observations are preserved in [docs/phase1_results.md](docs/phase1_results.md).

`integrity_checks.sql` retains all 20 required checks and the supplemental stock-movement timestamp check numbered 21. No diagnosis findings or historical records have been removed or corrected.

## Retained resources

| File or directory | Purpose |
|---|---|
| [schema.sql](schema.sql) | Original supplied schema, unchanged. |
| [load.sql](load.sql) | Original supplied loader, unchanged. |
| [race_test.py](race_test.py) | Original supplied concurrency harness, unchanged; retained for later manual implementation work. |
| [integrity_checks.sql](integrity_checks.sql) | Completed data integrity investigation queries, unchanged. |
| [docs/diagnosis.md](docs/diagnosis.md) | Initial observations, quantified business impacts and problem ranking, unchanged. |
| [docs/phase1_results.md](docs/phase1_results.md) | Historical Phase 1 schema verification, aggregate results and preservation policy. |
| [.gitignore](.gitignore) | Keeps confidential local datasets outside Git. |
| `data/` | Six original local CSV files, retained unchanged and ignored by Git. |

## Recorded environment at the restart

- Project directory: `C:\Users\User\OneDrive\Desktop\amal\lab3`.
- Docker container: `kloudkart`; project mount: `/lab`.
- Database and database user: `postgres`.
- PostgreSQL version recorded during diagnosis: `18.7 (Debian 18.7-1.pgdg13+5)`.
- No Dockerfile or Compose configuration is supplied by this repository.

The earlier restart changed repository files only. Subsequent checkout work uses
the separate rebuilt environment described above. Historical Phase 1 schema
observations describe the diagnosis baseline.

Do not rerun `schema.sql` or `load.sql` against either existing database. The
original schema script includes destructive initialization statements. The
guarded [Phase 3 runner](tests/phase3/run_experiment.py) checks the rebuilt endpoint
and fixture safety before executing the unchanged official test harness.

## Confidential data

The six retained files are `categories.csv`, `products.csv`, `customers.csv`, `orders.csv`, `order_items.csv` and `inventory_log.csv`, all under `data/`.

Keep client data local and unchanged. Do not commit CSV records, credentials or individual customer/transaction output. The diagnosis documents contain aggregate findings only.
