# Three-minute gap-fix summary

Date: 2026-11-27. Working branch: new-gapfix, created from new. No commit or push performed.

| Task | Changed / measured result | Remaining or unverified |
|---|---|---|
| 1 Stock versus log | Added Check 22, reusable view and installer integration. 144/4,023 products differ; net -2,375 units; absolute 2,553. Excluding future movements resolves zero differences. 120 orphan logs net -120 units. Top twenty product IDs saved in tests/gapfix_stock_reconciliation.json. Findings rank this High as uncertainty, not proven corruption; memo and ADR-003 updated. | Opening balances and physical counts absent. Implied opening reconstruction is an identity, not independent validation. |
| 2 Shipped assumption | Existing eligibility left intact. | Alternative totals/rank changes and configurable status policy not implemented. |
| 3 Naive report / memory / index tests | Existing report and measured evidence preserved. | New experiments not run within limit. |
| 4 Flash-sale isolation | Existing evidence retained, including 19.62-second slow result. | Pooling and server-only isolation not implemented; consistent ten-second target remains unproven. |
| 5 Trigger-only experiment | Existing reasoning retained. | New 100-round experiment not run. |
| 6 Hygiene / memo / actionable queue | Personal project paths replaced by PROJECT_DIR placeholders; tests/README marks historical evidence; five deliverables linked; current Git scope clarified; memo includes stock uncertainty. | Review workflow/log table, shipped assumption and pooling advice not invented. Memo word-count checked; updated visual page render not repeated. |

A new disposable database, kloudkart_submission_gapfix_20261127_155445, was created in kloudkart_rebuild. Original supplied schema and CSV loader were used. Two installation attempts and their actual outputs are saved in tests/gapfix_install.log and tests/gapfix_reinstall.log; completion is recorded separately in tests/gapfix_validation.json. Original databases were not reset.

The required final_verification.py --fresh attempt failed at the existing branch assertion: Expected branch new. The requested new-gapfix branch conflicts with that guard; the assertion was not weakened. No new race-suite pass is claimed. Original schema.sql, load.sql, race_test.py and data files were not modified. Existing SHA checks are retained. Work stopped at the three-minute limit; uncompleted tasks are explicitly left open.
