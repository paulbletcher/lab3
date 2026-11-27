# Submission checklist and handover

**Date:** 2026-11-27
**Branch:** new-gapfix
**Outcome:** All five deliverable artifacts are implemented and documented. Correctness and preservation checks pass. The latest flash-sale latency target remains unmet; do not represent this submission as meeting every performance criterion.

## Deliverables

| Deliverable | Actual files | Result |
|---|---|---|
| D1 Written diagnosis | [data_findings.md](data_findings.md); retained [diagnosis.md](diagnosis.md), [phase1_results.md](phase1_results.md) | Complete; original findings and risk order retained |
| D2 Working SQL | [run_all.sql](../run_all.sql); functions/, migrations/, reports/; final SQL assertions | Fresh-load installation and reinstallation pass; timing gap disclosed below |
| D3 Decisions | [decisions/](../decisions/) | Exactly six Accepted decisions with implementation and test evidence |
| D4 One-page memo | [client_memo.md](client_memo.md) | Complete; one A4 page verified by rendering |
| D5 Additional improvement | [improvement.md](improvement.md); [order_review_queue.sql](../reports/order_review_queue.sql) | Implemented, actual-data and synthetic tests pass |
| Measurement evidence | [performance_report.md](performance_report.md); [final_evidence.json](../tests/final_evidence.json); [raw plans](../tests/final_plans.txt) | Complete; actual timings, spills and unsuccessful latency result retained |

## Six ADR files

1. `decisions/ADR-001-atomic-stock-reservation.md`
2. `decisions/ADR-002-transactional-checkout.md`
3. `decisions/ADR-003-inventory-movement-audit.md`
4. `decisions/ADR-004-customer-spending-definition.md`
5. `decisions/ADR-005-recursive-category-rollup.md`
6. `decisions/ADR-006-report-performance-optimization.md`

## Changes and organization

The folder structure is preserved and extended: `data/`, `docs/`, `functions/`, `migrations/`, `reports/`, `tests/`, with the required new `decisions/` directory. Existing tests and logs remain in their original phase folders. The final runner, assertions, reference report and evidence are directly under `tests/`. The full tree and purpose of each directory appear in [README.md](../README.md).

Files modified for the initial submission:

- `.gitignore`
- `README.md`
- `functions/phase3_inventory_permissions.sql`
- `migrations/phase2_create_id_sequences.sql`
- `reports/phase4_customer_spending.sql`
- `reports/phase5_low_stock.sql`
- `run_all.sql`

The customer summary now reuses a twelve-month template and per-statement eligible-order materialization. Its invalid inline JSON-length validation and customer-detail samples were replaced with tested aggregate assertions; customer samples remain only in the existing optional validation script. The category implementation now has no fixed depth limit; its original exploratory validation block is retained at `tests/phase5_low_stock_validation.sql`. Role installation is repeatable and sequence installation does not rewind consumed values. Original checkout and controlled-movement function bodies were preserved.

Created files (evidence is aggregate or synthetic, never the CSV/customer records):

- `decisions/ADR-001-atomic-stock-reservation.md`
- `decisions/ADR-002-transactional-checkout.md`
- `decisions/ADR-003-inventory-movement-audit.md`
- `decisions/ADR-004-customer-spending-definition.md`
- `decisions/ADR-005-recursive-category-rollup.md`
- `decisions/ADR-006-report-performance-optimization.md`
- `docs/client_memo.md`
- `docs/data_findings.md`
- `docs/improvement.md`
- `docs/performance_report.md`
- `docs/submission_checklist.md`
- `reports/order_review_queue.sql`
- `tests/check_submission.py`
- `tests/final_assertions.sql`
- `tests/final_audit_rollback.log`
- `tests/final_checkout.log`
- `tests/final_documentation_checks.json`
- `tests/final_evidence.json`
- `tests/final_improvement.log`
- `tests/final_improvement.sql`
- `tests/final_initial_performance.json`
- `tests/final_initial_plans.txt`
- `tests/final_initial_race.log`
- `tests/final_initial_validation.json`
- `tests/final_install.log`
- `tests/final_load.log`
- `tests/final_memo_layout.json`
- `tests/final_movements.log`
- `tests/final_performance.json`
- `tests/final_permissions.log`
- `tests/final_plans.txt`
- `tests/final_race.log`
- `tests/final_race_repeat_2.log`
- `tests/final_race_repeat_3.log`
- `tests/final_recursive.log`
- `tests/final_recursive.sql`
- `tests/final_reinstall.log`
- `tests/final_reporting.log`
- `tests/final_reporting.sql`
- `tests/final_schema.log`
- `tests/final_verification.py`
- `tests/phase5_low_stock_validation.sql`
- `tests/reference_customer_spending.sql`
- `tests/test_support.sql`

## Actual final verification

- Fresh disposable load: categories 94; products 4,023; customers 40,420; orders 159,384; order items 336,559; inventory log 282,352. Original scripts run through the verified `/lab` mount in `kloudkart_rebuild` against new database `kloudkart_submission_20261127`.
- Complete installer runs top to bottom and runs a second time successfully. Sequence-consumption check proves reinstallation does not rewind an allocated ID. Required functions, views, ownership, security context, six original indexes and absence of custom triggers were checked.
- Unchanged official harness: Test 1, 25 rounds, exactly 25 purchases and 25 refusals, stock zero each round; Test 2, each of three runs 50 purchases, 350 refusals, zero errors and no overselling; Test 3 clean refusal with stock still three; Test 4 exactly five purchases, seven refusals and five movement rows.
- Additional checkout edge tests cover NULL/zero/negative inputs, absent customers/products, out-of-integer-domain IDs, price/stock exceptions, refusal without partial writes, a forced insert error and caller rollback. The follow-up adds bigint-customer and final audit-insert failure cases; all 19 checks pass.
- Retained SQL tests: basic checkout, all 19 movement cases, forced audit-insert failure and all 12 application permission cases pass. Application permissions are exercised through SET LOCAL ROLE; production authentication is not configured.
- Customer report: zero differences in both EXCEPT ALL directions; 40,420 customers, 2,520 with no qualifying orders, 111,195 orders and 339,184,984.53 spending; every customer has 12 months; full monthly sums and ending running totals reconcile. Synthetic tests verify normalized statuses, the date cutoff, monthly/lifetime distinction, deterministic order ties and ranking.
- Recursive report: 91 reachable categories, actual depth four, two cycle members, one missing parent, three unreachable categories, 37 uncategorized products and 1,931 eligible low-stock products. Synthetic 35-level hierarchy, self/two-member cycles, orphan/uncategorized products, NULL/negative stock, threshold inclusivity and duplicate-path tests pass. Root reconciliation passes.
- Improvement: 144 missing-customer flags, 95 incomplete-line flags and 1,624 mismatch flags; 1,863 flags represent 1,861 distinct orders. Net/absolute mismatch amounts reconcile. Synthetic overlaps, missing lines/prices, future completed and pending orders pass. No historical correction was made.
- All six full-table fingerprints match before and after tests. The existing rebuilt postgres database's fingerprints also match. The original container was not operated on. Supplied schema, loader, harness and all six CSV hashes are unchanged. Git HEAD is unchanged; no staging, commit or push was performed.
- Document templates, six ADRs, file links, unchanged original-source hashes, memo length and Git whitespace checks are verified by `tests/check_submission.py`; its output is `tests/final_documentation_checks.json`. The client memo was rendered and visually reviewed as one A4 page; layout metadata is in `tests/final_memo_layout.json`.

## Final timings and limitations

Customer summary: **1,334.088 / 1,515.989 / 1,708.638 ms**, median **1,515.989 ms**. Original reference on the same final database: median **2,463.959 ms**, giving a descriptive **38.47%** reduction. Low-stock rollup: **17.522 / 14.119 / 14.156 ms**, median **14.156 ms**. No extra indexes or planner settings were added.

Latest flash-sale runs: **14.32 / 10.08 / 17.49 seconds**, median **14.32 seconds**, worst **17.49 seconds**. **The ten-second target is not met by these final measurements.** The unchanged harness reports correctness as PASSED and only notes over-ten-second timing; these are different outcomes. The initial final run also took 11.64 seconds and is retained. Earlier faster measurements remain historical evidence, not a reason to discard current results. No p95 is estimated from three runs.

The report still spills to temporary storage. Production load and the reported forty-minute report were not reproduced. Historical inconsistencies, payment/discount rules, timestamps without timezone and supplier lead times remain unverified. No current stock forecast was issued because recent demand history is insufficient. Administrators retain bypass rights; real application authentication and potentially separate warehouse permissions remain deployment work.

The initial final-suite source check failed only on CRLF/LF comparison after all functional tests passed. Normalizing line endings fixed the verifier; the next full run passed preservation checks. Evidence is retained in `tests/final_initial_validation.json` and the corresponding initial logs/plans. No checkout SQL was rewritten to resolve it.

## Exact reproduction commands

From Windows PowerShell:

```powershell
Set-Location '<PROJECT_DIR>'
python tests/final_verification.py
if ($LASTEXITCODE -ne 0) { throw 'Functional verification failed' }
python tests/check_submission.py
if ($LASTEXITCODE -ne 0) { throw 'Submission document verification failed' }
git status --short
git branch --show-current
```

For an independent fresh load, use a new name (never reset the existing database):

```powershell
$testDb = 'kloudkart_submission_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
python tests/final_verification.py --fresh --database $testDb
```

The updated functional runner returns failure on correctness/install/preservation errors and on any flash run over ten seconds, unless --allow-slow-race is explicitly selected. Inspect inspect `race.flash_target_all_runs_met` in `tests/final_evidence.json` and the measurement report. Subsequent runs overwrite final evidence; timings naturally vary. README contains container setup, installation-only, direct official-harness and all report commands, with private password entry.

## Git and submission state

Branch remains `new`; seven existing files are modified and the new deliverables/evidence are untracked for review. The confidential `data/` directory remains ignored. No files were staged, committed or pushed. This is a complete set of deliverable artifacts with an explicit flash-sale performance gap, not a claim of full production readiness.


## Selected follow-up and final submission state

The selected lock-first implementation is installed from `functions/phase3_place_order.sql` and integrated through the existing run_all.sql path. The unchanged original harness passed all four correctness tests; all 19 checkout edge/rollback checks and all 12 role-permission tests passed. Historical fingerprints, original files/CSVs and the starting Git HEAD remain unchanged.

Authenticated Linux timings were **9.29, 7.98, 7.54 and 19.62 seconds** (last observation: final full suite). Median **8.635 seconds**, worst **19.62 seconds**. **Consistent ten-second compliance remains unresolved.** All observations, including rejected candidate results, are retained. The user requested that comparison work stop and one version be finalized; the lock-first version was selected. No further performance work is pending in this handover.

The default verification now uses `tests/race_client.py` and the pinned `tests/phase3/Dockerfile.client`, with 400 independent connections and matching SCRAM authentication. Native Windows timings are separate diagnostics. See `tests/phase3/logs/flash_final_selected.json` and `flash_final_full.log` for current confirmation. Report measurements were preserved from the prior validated run because reporting SQL was unchanged. All five deliverable artifacts remain present; the latency acceptance gap is disclosed in the memo and measurement report.

Follow-up source changes: selected checkout SQL; tests/final_verification.py; tests/race_client.py; tests/phase3/Dockerfile.client; tuning/control scripts and trial evidence; ADR-001/002; README and final documentation. Starting HEAD was 56a328f (final submit); it was not changed by this follow-up. No commit or push was performed.

Current three-minute pass: branch new-gapfix was created from new at the existing HEAD. No commit or push was performed by this pass; historical statements above describe earlier work. The repository already contains user-created commits. See gapfix_summary.md for the current verification limits.
