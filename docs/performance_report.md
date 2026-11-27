# Report execution and flash-sale measurement report

## Target

The brief asks for the complete customer-spending report in seconds, the recursive low-stock rollup in a couple of seconds, and a spike of 400 attempts on one product within ten seconds. The report wording supplies no narrower numeric spending threshold; no invented service-level target is claimed. Local report executions satisfy the stated scale. **Latest flash-sale timing does not meet ten seconds**, although all correctness assertions pass.

## Method

- Hardware / container spec: Windows host with Docker Desktop/WSL2; the Docker engine reports 4 logical CPUs and 4,039,696,384 bytes (about 3.76 GiB) memory. No container-specific CPU/memory limits are configured; these are shared engine resources, not a dedicated production allocation. Host CPU model and physical RAM were not recorded. Kernel: 6.18.58.1-microsoft-standard-WSL2; Docker 29.9.2.
- PostgreSQL 18.7 (Debian 18.7-1.pgdg13+5), x86-64; max_connections 500, work_mem 4 MB, shared_buffers 128 MB, session timezone Etc/UTC. Test database: kloudkart_submission_20261127, inside kloudkart_rebuild, loopback port 5433. Both existing databases were preserved.
- What was timed: `EXPLAIN (ANALYZE, BUFFERS, SUMMARY) SELECT *` from each complete view, using the plan's server Execution Time. It executes every output row but excludes client transfer, display and JSON rendering in a reporting interface. The original summary is preserved as a temporary reference view; it uses the same installed eligibility rules as the optimized summary. Running-order detail is validated separately and is not part of the summary-view timer.
- Three sequential observations per scenario, original reference then permanently integrated spending then recursive low stock. Median and worst are reported. Prior validation warmed data; no cache flush, restart or cold-cache claim. Runs share the same loaded database and use unchanged planner settings. Order effects and host/engine contention are uncontrolled; this is a descriptive comparison.
- The unchanged official race harness times connection establishment, barrier release, calls and thread completion for 400 independent buyers. Its timer excludes fixture setup and cleanup. One full four-test invocation and two additional Test 2 invocations produced three final observations. Diagnostic connections were closed during those race measurements. Whole-process time is recorded separately.
- Reproduce from the project root in PowerShell: `python tests/final_verification.py` for the verified database, or `python tests/final_verification.py --fresh --database kloudkart_submission_measurement_20261127` for a new, not-yet-existing disposable database. Run `python tests/check_submission.py` for document/source checks. The README supplies setup, private credential and direct report commands. The runner refuses existing databases with --fresh and never resets either protected database.

## Results

All report times below are milliseconds. Flash-sale times are explicitly seconds. p95 is insufficiently sampled in every three-run series; none is estimated.

| Scenario | Runs | Median | p95 | Worst | Target met? |
|---|---|---:|---|---:|---|
| Prior original spending, handoff | 4,922.222; 3,731.280; 2,456.607 ms | 3,731.280 ms | Insufficient n=3 | 4,922.222 ms | Local seconds scale |
| Prior temporary candidate, rolled back | 1,136.656; 1,222.963; 2,222.412 ms | 1,222.963 ms | Insufficient n=3 | 2,222.412 ms | Local seconds scale; not then deployed |
| Prior low-stock baseline, handoff | 25.265; 25.119; 23.449 ms | 25.119 ms | Insufficient n=3 | 25.265 ms | Yes, local |
| Final original spending reference | 2,611.769; 2,463.959; 2,398.090 ms | 2,463.959 ms | Insufficient n=3 | 2,611.769 ms | Local seconds scale |
| Final permanently integrated spending | 1,334.088; 1,515.989; 1,708.638 ms | 1,515.989 ms | Insufficient n=3 | 1,708.638 ms | Yes, local |
| Final recursive low stock | 17.522; 14.119; 14.156 ms | 14.156 ms | Insufficient n=3 | 17.522 ms | Yes, local |
| Final flash sale, 400 buyers / 50 units | 14.32; 10.08; 17.49 s | 14.32 s | Insufficient n=3 | 17.49 s | **No: all three exceed 10 s** |

Each final flash run had 50 purchases, 350 out-of-stock refusals, zero errors, final stock zero and one order per purchase. Test 1 passed all 25 rounds; Test 3 refused 10 units against 3 without a stock change; Test 4 had 5 purchases, 7 refusals and exactly 5 movements. These correctness results are separate from the failed latency target.

The first final-verification attempt also passed all SQL and official tests, with flash time 11.64 s, spending median 1,497.109 ms and low-stock median 13.561 ms. Its final source comparison failed because container psql preserved Windows CRLF while Python normalized it; the comparison was corrected to normalize line endings, without changing checkout SQL. Initial raw evidence remains in `tests/final_initial_*`. No slow observation was discarded as a correctness failure.

## Before / after

| Query / stage | Before | After | Change |
|---|---:|---:|---|
| Prior spending experiment, handoff medians | 3,731.280 ms | 1,222.963 ms | 67.22% lower; temporary, rolled back |
| Spending, same final database medians | 2,463.959 ms | 1,515.989 ms | 38.47% lower; permanently installed |
| Historical baseline to final spending | 3,731.280 ms | 1,515.989 ms | 59.37% lower descriptively; separate sessions |
| Low-stock, prior versus final | 25.119 ms | 14.156 ms | Both already fast; depth-cap correctness fix, no index optimization claimed |

The spending rewrite replaces 485,040 customer-month rows with a single twelve-key zero template overlaid with observed months, and materializes eligible orders once per statement. Exact `EXCEPT ALL` comparisons in both directions produced zero differing rows; 40,420 customers, 111,195 qualifying orders and recorded spending of 339,184,984.53 reconcile on 2026-11-27. Synthetic tests also validate month boundaries, zero months, date/ID ordering and rank ties.

## Caveats

- Final optimized plans still show **15,400 kB external merge sorting**, five-batch hash aggregation and an additional nine-batch aggregate with roughly 3,584 kB disk usage, plus temporary block I/O. The previous candidate's 15,400 kB sort/five-batch observation is corroborated, not eliminated. Final raw plans are in `tests/final_plans.txt`; timings and resources are in `tests/final_performance.json` and `tests/final_evidence.json`.
- The low-stock plan uses small in-memory sorting (about 786 kB), and its complete output executes in tens of milliseconds. No additional index was justified. Exactly the six original primary-key indexes and zero custom triggers remain. No planner or server settings were changed by this work.
- Prior handoff measurements are retained as reported historical evidence; their original plan captures were not supplied as saved files. Fresh reference measurements and the integrated measurements above are independently reproducible. Prior checkout evidence in `docs/phase3_optimization.md` includes a 7.47-second median; `docs/inventory_audit.md` also records over-target runs. Those earlier observations do not override the latest failure to meet ten seconds.
- The official harness creates 400 new connections. Connection startup, Python thread scheduling, host load, the shared 4-CPU/3.76-GiB engine, row-lock waits and commit work can all affect wall time. Earlier connection-only investigations suggest startup overhead matters, but these final runs do not isolate a cause. No new causal claim or resource change is made. Measure a realistic production workload before choosing another SQL change, pooling or hardware.
- Production load, data growth, network and the alleged forty-minute report were not reproduced. A larger server purchase is not justified by these local report timings alone. Do not present them as a measured improvement from forty minutes or as production capacity proof.
- Results move with CURRENT_DATE. The fixed 2026-11-27 report-count assertion is conditional on that date; general equality, coverage, monthly and running-total checks remain active on later dates. The all_checks_passed evidence field refers to correctness/installation/preservation; the flash latency target is recorded separately as false.
