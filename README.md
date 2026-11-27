# Kloud Kart - DE03 SQL Lab

This lab examines Kloud Kart's inherited PostgreSQL database and develops safe checkout, an inventory audit trail, and reliable reports. Phase 1 covers data diagnosis and the business risks identified in the supplied datasets.

## Current progress

| Phase | Status |
|---|---|
| Phase 0 - Environment setup | COMPLETE |
| Phase 1 - Data diagnosis | COMPLETE |
| Phase 2 - Safe checkout and inventory audit trail | NOT STARTED |
| Phase 3 - Monday customer-spending report | NOT STARTED |
| Phase 4 - Recursive low-stock category rollup | NOT STARTED |
| Phase 5 - Additional improvement and final deliverables | NOT STARTED |

All 21 integrity checks are complete. Their observations, business implications, clarification items, reporting considerations, and final risk ranking are documented in [docs/diagnosis.md](docs/diagnosis.md). Aggregate results and schema verification are recorded in [docs/phase1_results.md](docs/phase1_results.md).

No historical records have been corrected or deleted to resolve the findings. The database uses the supplied schema and datasets. Checkout and the inventory audit mechanism are future work.

## Active project structure

```text
lab3/
|-- README.md
|-- .gitignore
|-- schema.sql
|-- load.sql
|-- integrity_checks.sql
|-- race_test.py
|-- docs/
|   |-- diagnosis.md
|   `-- phase1_results.md
`-- data/                       # Confidential extracts; ignored by Git
```

| File | Responsibility |
|---|---|
| [schema.sql](schema.sql) | Defines the six tables with ordinary integer primary keys. No foreign keys or indexes beyond the primary keys. |
| [load.sql](load.sql) | Loads six local CSV datasets with client-side `\copy`, runs `ANALYZE`, and reports row counts. |
| [integrity_checks.sql](integrity_checks.sql) | Contains the 21 Phase 1 diagnosis queries. |
| [race_test.py](race_test.py) | Supplied checkout contract and concurrency test harness for Phase 2. |
| [docs/diagnosis.md](docs/diagnosis.md) | Integrity observations, business implications, and final risk ranking. |
| [docs/phase1_results.md](docs/phase1_results.md) | Schema verification, row counts, all 21 check results, and the historical-data preservation policy. |

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

## Future checkout verification

`race_test.py` belongs after an implementation of `place_order(bigint, bigint, integer)`, whose contract is documented in that file. The harness creates and removes database fixtures. A future test run requires Python, `psycopg2-binary`, and a suitable `DATABASE_URL`, as described in the supplied harness. Checkout concurrency tests have not been run.

## Confidential data

`data/` contains confidential extracts and is excluded by the `/data/` Git ignore rule. Keep CSV files local and unchanged. Do not commit or publish customer or transaction records or credentials. Documentation contains aggregate results only.
