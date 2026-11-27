# Phase 3 - Checkout performance optimization

This is the optimization phase requested on 2026-11-27. Earlier Phase 2 records
remain unchanged. Only the rebuilt `kloudkart_rebuild` endpoint on host port 5433
is authorized; the original database, CSV files and supplied test harness are
preserved. Work remains local on branch `new`, without a commit or push.

## Method and baseline

The historical unmonitored Test 2 result is 16.10 seconds. The monitored and
instrumented Phase 2 trials are diagnostic evidence, not comparable benchmarks.
The Investigation 6 report was read before selecting any changes.

The supplied harness opens 400 independent connections and enables autocommit
before its barrier. Its reported Test 2 wall time includes thread startup,
connection establishment, the barrier, checkout and connection closure. Each
checkout SELECT commits implicitly; function return alone does not end the
transaction. Modifying the harness or silently substituting pooled connections
would change the acceptance workload and is not used here.

`tests/phase3/run_experiment.py` runs the original file in a separate Python
process, preserving the commands `python race_test.py --test N --verbose`.
There is no monitoring or open diagnostic connection while each test runs.
The runner captures raw output, whole-process duration separately from official
Test 2 wall time, and pre/post counts and orphan counts. It refuses existing
fixtures and any historical references in the harness's entire fixture-ID range.
It stops on any test failure or failed cleanup reconciliation.

Reproduction (from the project root, with the rebuilt `DATABASE_URL` set privately):

```powershell
python tests/phase3/run_experiment.py init
python tests/phase3/run_experiment.py suite baseline --repeats 3
```

Initialization is performed only once and refuses to overwrite an existing
baseline. If the URL is absent, this local lab runner obtains it privately from
the named rebuilt container for its child process only. It validates the endpoint
and matches the database cluster identity with that container before proceeding.
Credentials are not written to project files or output.

Original source and deployed function backups are under `tests/phase3/backups/`.
The initial working tree already contained uncommitted Phase 2 work; its status,
HEAD and file hashes are preserved in `tests/phase3/logs/baseline.json`.
No original working file is overwritten to create a backup.

Environment and investigation queries are saved in
`tests/phase3/inspect_environment.sql` and `tests/phase3/verify_integrity.sql`.
Initial observations: PostgreSQL 18.7, 500 maximum connections, shared buffers
128 MB, work memory 4 MB, synchronous commit and fsync enabled, SSL disabled,
JIT enabled with cost threshold 100000, two other idle client connections,
primary-key indexes only and no noninternal public triggers.

Whole-table fingerprints are taken at the beginning and end, outside benchmarks.
For each of the six tables, the exact query is
`SELECT count(*), md5(string_agg(md5(to_jsonb(t)::text), '' ORDER BY primary_key)) FROM public.table_name t`,
with fixed whitelisted identifiers substituted by the runner. Only aggregate
hashes leave PostgreSQL; customer rows are never printed. These fingerprints
supplement count/orphan reconciliation. Sequence gaps and MVCC maintenance
effects from synthetic activity are expected and are not reset.

### Fresh unmonitored baseline

All four official tests passed. Test 2 times were **15.73, 8.51, 7.38 seconds**,
median **8.51 seconds**, each with 50 successes, 350 refusals, zero errors and
final stock zero. This is a substantial warm-up/load variation, not evidence
that any change has already improved performance. The baseline fails the
requirement for three target-compliant runs. All post-test count/orphan checks
passed. Results: `tests/phase3/logs/baseline_20261127T125426Z_results.json`.

## Experiment 1 - Per-product transaction advisory queue

**Objective/problem.** Reduce the tuple-lock queue and lock-manager pressure
established by Investigations 4 and 5, without weakening the atomic stock update.
Investigation 6 also found substantial work before UPDATE and while its row lock
remained held, including large insert outliers.

**Investigation/initial observations.** The metadata and EXPLAIN statements in
`inspect_environment.sql` show primary-key index access for customer lookup and
product UPDATE. Missing indexes on these predicates are not established. Both
estimated plans cost under 10; a JIT or configuration change is unjustified.
No other advisory-lock protocol exists in the project. The proposal is based on
the observed many-to-many blocking queue, rather than an assumed slow table scan.

**Proposed change and implementation.**
`tests/phase3/experiments/01_product_advisory_queue.sql` adds only a transaction
advisory lock per product before customer validation, following basic input
validation. The two-integer namespace `1145385011` is reserved for checkout;
the second integer is the product primary key. Guarding the cast preserves the
bigint API's behavior for missing product IDs outside the int range. Other
checkout logic and SQL operations are unchanged, including conditional UPDATE,
order/item insertion and inventory logging. Calls for different products use
different locks. The expected benefit is queueing before the product-row lock
manager storm and spreading first-use statement work across hot-product calls.
This mechanism is a hypothesis until timed tests complete.

**Correctness risks.** Lock scope must extend to commit/rollback; session locks
would be incorrect. The conditional UPDATE remains necessary for writers that
do not use this protocol. Caller transactions ordering several products must
use a consistent lock order, just as with ordinary row locks. The reserved
namespace must not be reused for another purpose. No table-wide/global lock is
introduced. Invalid customer/product outcomes remain the same, though they can
wait behind a purchase of the same product. Throughput for mixed-product or
long-lived external transactions is not established by the official workload.

**Test procedure and rollback.**

```powershell
python tests/phase3/run_experiment.py apply advisory tests/phase3/experiments/01_product_advisory_queue.sql
python tests/phase3/run_experiment.py suite advisory --repeats 3
```

The apply command backs up the deployed function immediately before replacement
and applies the candidate atomically. The source and deployed Phase 2 originals
remain available. The official suite will test 1, three unmonitored runs of 2,
3 and 4, with fixture and orphan reconciliation between runs. Results, comparison
and keep/rollback decision follow after execution.

**Actual results and conclusion.** All four official tests passed. Test 2:
**16.76, 9.30, 7.34 seconds**, median **9.30 seconds**. Counts and historical
orphan aggregates were restored after each test. This is not an improvement over
the fresh baseline median 8.51 seconds and does not satisfy the three-run target.
The similar first-run/warm-run pattern is a confounder. The queue candidate is
**rejected**; restoring the original function is the next operation. This does
not disprove row contention, but it does show this additional queue has not
demonstrated a benefit for the measured workload. No additional index or server
setting was changed. Raw results:
`tests/phase3/logs/advisory_20261127T125628Z_results.json`.

Seventeen additional rollback-only business/atomicity checks passed using
`tests/phase3/check_business_rules.py advisory`, including invalid IDs/quantities,
NULL/negative prices, valid zero price, multi-unit checkout, and an actual order
INSERT numeric-overflow error after stock deduction. The latter verified stock
and all write counts rolled back. The original deployed function was restored
with `run_experiment.py apply restore_original tests/phase3/backups/deployed_place_order_original.sql`.

## Experiment 2 - Consolidate checkout writes with data-modifying CTEs

**Objective/problem.** The original successful path executes four independently
planned write statements while retaining the product-row lock. Investigation 6
recorded long INSERT outliers. Reduce statement setup/control transitions while
keeping identical validation and all four required writes.

**Investigation and proposed change.** PostgreSQL supports data-modifying CTEs
with communication through RETURNING. The candidate chains stock UPDATE,
order INSERT, item INSERT and inventory INSERT via their returned rows. The
final SELECT references the movement, so completion depends on the entire chain.
No order/item/log source row exists when UPDATE deducts no stock. Customer and
input validation retain their original order, and a fresh fallback query reports
missing product, invalid price or insufficient stock as before.

**Implementation/risks.** Exact SQL:
`tests/phase3/experiments/02_checkout_write_cte.sql`. This is based on the original,
without experiment 1's advisory lock. Explicit RETURNING dependencies matter:
textual CTE order alone is not an execution guarantee. More complex planning on
the refused path could outweigh fewer statement transitions. Error propagation
must roll back the UPDATE and every downstream write. No index, configuration
or client-connection change accompanies this experiment.

**Test procedure.** Apply with `run_experiment.py apply cte tests/phase3/experiments/02_checkout_write_cte.sql`,
run `python -B tests/phase3/check_business_rules.py cte`, then
`run_experiment.py suite cte --repeats 3`. Keep the change only if correctness
and performance evidence justify it; rollback backups are automatic.

**Failed validation and correction.** The first CTE revision failed the
out-of-integer-range bigint product-ID test with SQLSTATE 22003
(`NumericValueOutOfRange`). A separate call reproduced the failure; no product
matched and no writes survived. Evidence: `tests/phase3/logs/cte_validation_failure.json`.
Unlike the original separate INSERT path, the combined plan contains the
integer INSERT casts even for an empty UPDATE. The original was immediately
restored before revising the candidate. The failed SQL is retained unchanged.
`02b_checkout_write_cte_guarded.sql` now explicitly returns Product not found
for IDs outside the integer primary-key domain, after customer validation to
preserve error precedence. The original API still accepts bigint inputs.
This is a correctness repair to the same experiment, not a second performance
change. It requires the complete edge-case and official suite again.

**Actual results/evaluation.** The guarded revision passed all 17 rollback-only
business checks and all four official tests. Test 2: **13.87, 9.62, 7.86 seconds**,
median **9.62 seconds**. Historical count/orphan checks passed after every test.
The median is worse than the fresh baseline's 8.51 seconds, and three compliant
runs were not obtained. The CTE change is **rejected**, and the original deployed
function was restored. Neither reduced statement count nor a lower first-run
time is sufficient evidence to retain this more complex implementation.
Results: `tests/phase3/logs/cte_guarded_20261127T125945Z_results.json`.

## Experiment 3 - Local connection negotiation

**Objective/problem.** Connection-only work previously took 9.66 seconds, and
both SQL candidates failed to improve the median. The server reports SSL off,
while libpq defaults can negotiate unsupported encryption protocols before
ordinary startup. Removing unnecessary negotiation for this existing plaintext
loopback endpoint is a focused client-connection hypothesis, not a server change.

**Investigation/query/script.** `SHOW ssl` and
`tests/phase3/benchmark_transport.py`. The connection-only control alternates
default, explicit local transport, explicit local transport, default. Each run
opens 400 separate connections, uses a barrier, executes SELECT 1 and closes
connections. No checkout calls or historical writes occur. The original function
was restored before this diagnostic.

**Proposed implementation/risks.** For the already non-TLS loopback server only,
set DSN `sslmode=disable` and `gssencmode=disable` in the invoking process. Keep
authentication credentials, endpoint, number of connections and transactions
unchanged. This must not become a recommendation for a remote production
endpoint. A client wrapper must refuse the option if the server supports TLS.
No server configuration or user-level/global environment variable is changed.
Only consider an official suite with this transport if the control justifies it.

**Measured control and decision.** Default connection-only runs: **5.333 and
5.261 seconds** (median 5.297). Explicit local transport: **5.245 and 7.082
seconds** (median 6.163). All four controls had 400 connections and zero errors.
There is **no repeatable benefit**; the proposal is rejected without changing
application defaults. No official checkout result is attributed to this control.
Evidence: `tests/phase3/logs/transport_control_results.json`.

## Experiment 4 - Customer validation inside the conditional stock UPDATE

**Objective/problem/investigation.** Investigation 6 measured approximately
1.67 seconds before the UPDATE under contention. Existing index plans do not
justify more indexes. The original issues a separate customer EXISTS statement
before UPDATE for every call, requiring separate SPI statement setup/execution.
Experiments 1 and 2 did not help; neither is included in this candidate.

**Proposed optimization and implementation.**
`tests/phase3/experiments/04_customer_update_guard.sql` places the same indexed
customer EXISTS predicate in the original conditional UPDATE. Missing customers
cannot deduct stock. If it affects no row, a single fallback SELECT returns
customer existence and product existence/price/stock to preserve customer-first
error messages. The successful path removes one separate SQL statement; the
refused path uses two statements instead of three. All three original INSERTs
remain separate and unchanged. No advisory lock, CTE write chain, connection
option, index or server configuration change is combined with this candidate.

**Correctness risks.** The EXISTS condition must guard the stock change, not
merely check the customer afterwards. Missing customer/product/invalid price
precedence must be preserved. Unrelated concurrent customer deletion is not
prevented by either the original or this function: the supplied schema has no
customer FK. The lab's original customer-validation rules remain unchanged.
Actual insertion failures must still roll back the deduction and partial writes.

**Test procedure.** Apply `04_customer_update_guard.sql` as label `customer_guard`,
run all 17 rollback-only business checks, then the complete official suite with
three unmonitored Test 2 runs. Each application has an immediate rollback backup.
Results and keep/rollback decision will be recorded after execution.

**Initial results.** All 17 business checks and all four official tests passed.
Test 2: **7.99, 7.48, 8.43 seconds**, median **7.99 seconds**. Every run had
50 purchases, 350 out-of-stock refusals, zero errors and final stock zero. All
fixture/count/orphan checks passed. This meets the three-run target. Compared
with the fresh baseline median 8.51, the descriptive improvement is 6.11%; the
historical 16.10 comparison is not a controlled causal estimate. Results:
`tests/phase3/logs/customer_guard_20261127T130235Z_results.json`.

**Additional evaluation needed.** Earlier suites showed a large first-run effect.
Before retaining the change, restore the original for a further three-run
unmonitored suite (`warm_control`), then reapply the customer guard for an
identical final suite. This resolves an attribution concern, rather than hiding
unfavorable measurements or treating initial cache/load variation as a benefit.

**Confirmation results and decision.** The original-function control produced
**8.94, 7.08, 8.80 seconds**, median **8.80 seconds**. Reapplying the customer
guard and running the same full suite produced **7.47, 7.46, 7.58 seconds**,
median **7.47 seconds**. All six official test processes in each suite passed,
including every Test 2 correctness assertion, with reconciliation after each.
The retained change has now delivered six out of six target-compliant Test 2
runs across its two suites. It is **kept**. The final source is
`functions/phase3_place_order.sql`, whose function body exactly matches the
deployed version. Its original Phase 2 source remains unchanged.

The final median is descriptively 1.33 seconds / **15.11%** lower than the
intervening original control median, and **12.22%** lower than the initial fresh
baseline median. Both retained-candidate suite medians are lower than both
original-function suite medians. This supports retaining the measured, minimal
change; it does not isolate how much improvement was caused by SQL rather than
host scheduling, caches or load. The original also met the three-run target in
the warm control, so the evidence does not establish an architectural inability
to meet the requirement with the original implementation.

## Complete performance record

All official times below include 400 independent database connections and come
from the unmodified harness's own Test 2 timer. They exclude fixture setup,
printing, assertions and cleanup, as the supplied timer does. Whole-process
durations are saved separately in the JSON records.

| Implementation / condition | Test 2 runs (seconds) | Median | Decision |
|---|---|---:|---|
| Historical original, earlier session | 16.10 | Not applicable | Historical reference only |
| Original, fresh Phase 3 suite | 15.73, 8.51, 7.38 | 8.51 | Baseline; one run over target |
| Experiment 1: advisory queue | 16.76, 9.30, 7.34 | 9.30 | Rejected and restored |
| Experiment 2: guarded write CTE | 13.87, 9.62, 7.86 | 9.62 | Rejected and restored |
| Experiment 4: customer guard, initial | 7.99, 7.48, 8.43 | 7.99 | Three compliant runs |
| Original, intervening warm control | 8.94, 7.08, 8.80 | 8.80 | Attribution control |
| Retained customer guard, final suite | **7.47, 7.46, 7.58** | **7.47** | **Three compliant confirmation runs** |

The historical comparison is a reduction from 16.10 to 7.47 seconds (53.60%),
but the difference must not be presented as a controlled causal speedup.
Monitored/instrumented Phase 2 results are excluded from the acceptance table.
Experiment 3 connection-only results are diagnostic controls, not acceptance runs.
No unfavorable result has been discarded from these comparisons.

## Final correctness results

Final suite: `tests/phase3/logs/final_customer_guard_20261127T130457Z_results.json`.
The six exact commands executed by the runner were Test 1, Test 2 three times,
Test 3 and Test 4, each with `--verbose`, using the same DATABASE_URL defaults.

| Official test | Actual result |
|---|---|
| 1: last unit, 25 rounds | 25 successes, 25 refusals, zero errors; every round stock 0 and one order |
| 2: 400 buyers, repeated three times | Each: 50 successes, 350 refusals, zero errors, stock 0, 50 orders, no overselling |
| 3: 10 requested against 3 units | Refused, zero errors; stock stayed 3 |
| 4: audit trail under contention | 5 successes, 7 refusals, zero errors; 5 inventory movements |

Every process returned zero and printed PASSED. The final Test 2 whole-process
times were 8.154357, 8.091993 and 8.223382 seconds respectively; these are
separate from the official 7.47, 7.46, 7.58-second fire() measurements.

The retained SQL also passed the 17 checks in
`tests/phase3/check_business_rules.py customer_guard`. The actual failed-insert
test deliberately overflows the order total after a valid stock deduction;
SQLSTATE 22003 is expected there. Rolling back to the savepoint restored stock
and all three write-table counts. All business-check fixtures were then rolled
back, with before/after count/orphan equality. No successful customer transaction
is allowed to omit an order item or inventory movement.

## Final data, deployment and environment verification

`python -B tests/phase3/final_verification.py` passed. Evidence:
`tests/phase3/logs/final_verification_20261127T130641Z.json`.

| Historical table | Before | After |
|---|---:|---:|
| categories | 94 | 94 |
| customers | 40,420 | 40,420 |
| products | 4,023 | 4,023 |
| orders | 159,384 | 159,384 |
| order_items | 336,559 | 336,559 |
| inventory_log | 282,352 | 282,352 |

All six full-table aggregate fingerprints also matched, providing stronger
evidence than row counts alone. Pre-existing orphan counts were preserved:
210 orders with missing customers, 692 items with missing orders, zero items
with missing products, and 120 movements with missing products. There are zero
remaining official fixtures and no historical references in the next fixture-ID
range. No historical data correction was attempted.

The deployed function body exactly matches `functions/phase3_place_order.sql`.
The original harness, schema, loader, six CSV files, initial diagnosis and all
previous Phase 2 files/logs have matching baseline file hashes. README is the
only intentionally edited pre-existing project file. New implementation,
documentation, experiment, backup and log files are confined to the documented
Phase 3 locations. No file was deleted.

The inspected PostgreSQL settings, six primary-key index definitions and trigger
metadata match the baseline. The rejected advisory function has been replaced;
no advisory protocol, CTE implementation, new index, temporary schema/function,
timing table, connection option change or server setting change remains. The
original container was not accessed. Branch remains `new`, HEAD is unchanged,
and no commit or push was made.

## Reproduction and rollback

For an environment initialized with the same original schema/data and Phase 2
sequence defaults already in place, use the guarded runner against the rebuilt
endpoint. Do not rerun schema.sql, load.sql, or the sequence synchronization
migration on the existing database. The initialization command creates a new
baseline only if none exists.

```powershell
# DATABASE_URL must identify the rebuilt localhost:5433 endpoint, privately.
python tests/phase3/run_experiment.py apply retained functions/phase3_place_order.sql
python -B tests/phase3/check_business_rules.py retained
python tests/phase3/run_experiment.py suite retained --repeats 3
python -B tests/phase3/final_verification.py
```

These are reproduction commands; the final suite was already executed and need
not be repeated to obtain the recorded result. To restore the original function,
use `run_experiment.py apply rollback tests/phase3/backups/deployed_place_order_original.sql`.
That would change the deployed implementation and should be followed by the
official suite; do not confuse the rejected experimental SQL with the retained
function. Applying a different function causes final_verification.py's exact
deployment check to fail until the intended final SQL is restored.

## Limitations and submission review

- Acceptance is demonstrated for the observed local rebuilt environment, with
  default connection options, 400 new connections and no benchmark monitoring.
  No cache flushing, container restarts or artificial load isolation was used.
  Earlier first-run/load variation remains real; this is not a universal latency
  guarantee or a controlled production-capacity study.
- Reducing standalone SQL statements is verified by inspection. This phase did
  not instrument the final function's stages during acceptance runs, so it does
  not claim an exact reduction in lock wait, commit duration or pre-UPDATE time.
  Stock UPDATE still includes lock acquisition, and row locks last until commit.
- Client connection startup remains substantial. A real application could
  investigate pooling separately, but substituting it in the official harness
  would change this workload. No pool was introduced.
- Original historical data-quality issues and the absence of foreign keys remain
  outside this optimization's scope. No new business rule was invented.
- Review the final SQL, this document, the result JSON and final verification
  before submission. Raw verbose logs contain synthetic test order IDs only,
  not customer details or historical transaction rows. CSV files stay local and
  ignored by Git. No credentials appear in the saved artifacts.
- The source, documentation and curated evidence can be reviewed for a later
  approved commit. Nothing has been staged, committed or pushed by this work.

The mandatory deliverables are the final SQL, original/rollback backups, four
Python scripts and diagnostic/verification SQL under `tests/phase3/`, this
central document, and the full evidence under `tests/phase3/logs/`.
`tests/phase3/logs/phase3_results_summary.json` is the concise machine-readable
index, including results of every official suite and final test outcomes.

## Technical references

- [PostgreSQL advisory and row locking](https://www.postgresql.org/docs/18/explicit-locking.html)
  informed experiment 1 and the transaction-scope analysis.
- [Data-modifying CTE rules](https://www.postgresql.org/docs/18/queries-with.html#QUERIES-WITH-MODIFYING)
  informed experiment 2's RETURNING dependencies and shared-snapshot limitations.
- [libpq connection parameters](https://www.postgresql.org/docs/18/libpq-connect.html#LIBPQ-PARAMKEYWORDS)
  informed the rejected local transport control.

**Phase 3 performance acceptance is complete for the measured local workload.**
No further optimization was undertaken after the confirmation suite and final
integrity/deployment checks passed.
