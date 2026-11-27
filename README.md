# Kloud Kart - DE03 SQL Lab

This branch resumes the lab after environment setup and the initial data integrity investigation. All implementation phases are pending.

## Progress

| Phase | Status |
|---|---|
| Phase 0 - Environment setup | COMPLETE |
| Phase 1 - Data integrity diagnosis | COMPLETE |
| Phase 2 - Safe checkout and inventory auditing | PENDING |
| Phase 3 - Monday customer-spending report | PENDING |
| Phase 4 - Recursive low-stock category rollup | PENDING |
| Phase 5 - Additional improvement and final deliverables | PENDING |

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

## Recorded environment

- Project directory: `C:\Users\User\OneDrive\Desktop\amal\lab3`.
- Docker container: `kloudkart`; project mount: `/lab`.
- Database and database user: `postgres`.
- PostgreSQL version recorded during diagnosis: `18.7 (Debian 18.7-1.pgdg13+5)`.
- No Dockerfile or Compose configuration is supplied by this repository.

This restart changes repository files only. The existing PostgreSQL database and Docker containers are left unchanged and may still contain objects or changes from later implementation work. Database state will be handled separately; the historical Phase 1 schema observations are not a claim about its current state.

Do not rerun `schema.sql` or `load.sql` as part of this restart. The original schema script includes destructive initialization statements. The supplied race harness also creates and cleans test fixtures; retaining it does not authorize running it.

## Confidential data

The six retained files are `categories.csv`, `products.csv`, `customers.csv`, `orders.csv`, `order_items.csv` and `inventory_log.csv`, all under `data/`.

Keep client data local and unchanged. Do not commit CSV records, credentials or individual customer/transaction output. The diagnosis documents contain aggregate findings only.
