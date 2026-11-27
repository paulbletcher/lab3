# Data findings — Kloud Kart

## Summary

All six files loaded with their expected counts and the retained 21 checks were rerun. Historical data was preserved. The nine findings below retain the original business-risk order in [diagnosis.md](diagnosis.md). Negative stock threatens fulfilment first; ambiguous recorded spending and missing relationships threaten the numbers used for decisions. Findings may overlap: neither record counts nor money amounts should be added as unique affected orders or losses.

## Reconciliation

| Stage | Rows | Delta | Reason |
|---|---:|---:|---|
| Loaded categories | 94 | 0 | Matches source CSV |
| Loaded products | 4,023 | 0 | Matches source CSV |
| Loaded customers | 40,420 | 0 | Matches source CSV |
| Loaded orders | 159,384 | 0 | Matches source CSV |
| Loaded order items | 336,559 | 0 | Matches source CSV |
| Loaded inventory movements | 282,352 | 0 | Matches source CSV |
| Orders retained after status normalization | 111,351 | -48,033 | Only complete/completed |
| Orders attributable to existing customers | 111,207 | -144 | Missing customers; recorded value 388,780.89 |
| Orders through 2026-11-27 | 111,195 | -12 | Future attributable completed orders; value 35,600.61 |
| Orders with known recorded amounts | 111,195 | 0 | No NULL totals in this eligible population |
| Customers in report | 40,420 | 0 | 37,900 with qualifying orders; 2,520 without |
| Reachable categories | 91 | -3 | Two cycle members and one missing parent |

Normalized completed recorded value is 339,609,366.03. Removing missing-customer orders leaves 339,220,585.14; the date cutoff leaves **339,184,984.53**. These are stored amounts, not independently verified receipts. All 40,420 customers have twelve monthly entries. The valid-root low-stock rollup covers 1,931 products at stock <= 10, with no duplicate contribution within a subtree. Ancestor totals deliberately overlap.

## Findings, ranked by risk

### F-01: Negative inventory balances — Severity: Critical

- **What it is:** Fourteen product balances are below zero.
- **How I detected it:** Check 8 filters stock_quantity < 0.
- **Scale:** 14 products; no NULL stock balances.
- **Effect on the client's number:** Availability is unreliable for those products; refund costs and affected sales cannot be priced from these balances.
- **What I did about it:** Retained the historical balances; new approved checkout and inventory deductions validate available stock atomically.
- **Residual risk:** Physical counts and opening balances are still needed. Administrator writes can bypass the approved path.

### F-02: Inconsistent order totals — Severity: Critical

- **What it is:** Stored order amounts differ from complete line sums.
- **How I detected it:** Checks 11 and 19 aggregate quantity times unit price, exclude incomplete sums and compare with stored totals.
- **Scale:** 2,279 orders overall; 1,624 completed orders. Completed net stored-minus-lines: -1,266,190.96; absolute differences: 2,074,053.86.
- **Effect on the client's number:** The choice of amount can change spending and rankings; these discrepancies are not proven financial losses.
- **What I did about it:** New checkout calculates its total from its item; historical recorded totals remain the report definition. The recurring review queue identifies discrepancies.
- **Residual risk:** Payment, discount, tax and delivery-charge records were not supplied.

### F-03: Inconsistent order statuses — Severity: High

- **What it is:** Completed statuses are spelled and spaced differently.
- **How I detected it:** Check 12 groups exact status labels and compares normalized labels.
- **Scale:** 15 exact values; 22,091 exact completed versus 111,351 normalized complete/completed orders.
- **Effect on the client's number:** An exact filter omits 89,260 orders (80.16% of normalized completed orders) across all loaded dates.
- **What I did about it:** Applied the documented lowercase/trim mapping in reusable views; new checkout writes pending.
- **Residual risk:** The business meaning of complete was assumed; a full lifecycle/status constraint has not been imposed on legacy writers.

### F-04: Orders referencing missing customers — Severity: High

- **What it is:** Orders point to absent customer accounts.
- **How I detected it:** Checks 1 and 18 use a LEFT JOIN and test for a missing customer match.
- **Scale:** 210 orders; 144 completed with recorded totals of 388,780.89 across all dates.
- **Effect on the client's number:** These completed amounts cannot be attributed to an existing customer and are excluded from customer spending.
- **What I did about it:** Preserved the orders, validated customers in checkout and exposed completed exceptions for review.
- **Residual risk:** No customer foreign key was added; privileged concurrent customer deletion and other legacy write paths remain outside the checkout contract.

### F-05: Order items referencing missing orders — Severity: High

- **What it is:** Line items have no matching parent order.
- **How I detected it:** Check 2 LEFT JOINs order_items to orders.
- **Scale:** 692 item rows; no NULL order IDs. Multiple lines may belong to the same absent order.
- **Effect on the client's number:** Sales quantities and values cannot be classified as completed spending without order dates/statuses.
- **What I did about it:** Preserved the lines and seeded the new order sequence above both real and orphan-referenced order IDs, preventing accidental reassociation.
- **Residual risk:** The original transactions cannot be reconstructed from the supplied files alone.

### F-06: Incomplete order line amounts — Severity: High

- **What it is:** Some prices are missing, so a full line sum is unknown.
- **How I detected it:** Checks 10, 11 and 20 count NULL quantities/prices before aggregating.
- **Scale:** 148 missing-price items; 147 orders with incomplete amounts, including 95 completed orders with stored totals of 455,904.42.
- **Effect on the client's number:** A partial SUM can masquerade as a complete total and distort reconciliation.
- **What I did about it:** The queue returns NULL for incomplete calculated amounts and differences; checkout inserts validated quantities/prices.
- **Residual risk:** Original invoices are needed; no replacement prices were invented. These amounts overlap other findings.

### F-07: Stock cannot be independently reconstructed from movements ? Severity: High

- **What it is:** Recorded balances differ from summed movements for 144 products; this is a reconciliation uncertainty, not 144 proven errors.
- **How I detected it:** New Check 22 and report_stock_vs_log_reconciliation compare balances with signed net movements. Future means a movement calendar date after CURRENT_DATE.
- **Scale:** 144 of 4,023 products; net difference -2,375 units; absolute difference 2,553 units. All products have logs. Excluding future movements resolves zero existing differences; 33 products have future net movements. Separately, 120 orphan movements net to -120 units and cannot explain balances for existing product IDs.
- **Effect on the client's number:** Current availability cannot be certified against this ledger without opening stock and evidence of complete movement capture; these units are not established losses.
- **What I did about it:** Added a reusable read-only view, aggregate check and saved product-ID-only top twenty in tests/gapfix_stock_reconciliation.json. No historical balance was corrected.
- **Residual risk:** Implied opening stock equals current stock minus net movements; adding it back reconstructs stock by definition, not independent evidence. High priority is justified by fulfilment decisions, below confirmed critical balance/amount faults. Opening counts and physical stock are missing.

### F-08: Inventory logs referencing missing products — Severity: Medium

- **What it is:** Recorded movements cannot be linked to the catalog.
- **How I detected it:** Check 4 LEFT JOINs inventory_log to products.
- **Scale:** 120 orphan movements; no NULL product IDs.
- **Effect on the client's number:** Auditors cannot attribute these movements to current products; a reliable financial impact is unavailable.
- **What I did about it:** Preserved records; approved inventory operations require an existing product and write one transactional movement.
- **Residual risk:** Product retirement/deletion policy is unverified; administrators can still delete catalog records.

### F-09: Circular category relationships — Severity: Medium

- **What it is:** Two category parent links form a loop.
- **How I detected it:** Check 7 follows parent paths and detects repeated IDs; report_category_cycles also searches disconnected components.
- **Scale:** 2 cycle members; no other categories leading into loops in the original diagnosis.
- **Effect on the client's number:** Products assigned there cannot be included in a valid-root rollup; naive recursion may fail to terminate.
- **What I did about it:** Retained category links, added cycle-safe reports and explicit unreachable exceptions; removed the original fixed depth cutoff.
- **Residual risk:** Intended hierarchy positions remain unknown; reporting does not prevent future catalog cycles.

### F-10: Broken category parent reference — Severity: Medium

- **What it is:** A category refers to a parent that is absent.
- **How I detected it:** Check 6 joins categories to their parents and tests missing non-NULL references.
- **Scale:** 1 missing-parent category; together with the cycle, 3 categories are unreachable.
- **Effect on the client's number:** The valid-root low-stock total excludes disconnected assignments and may omit replenishment needs if the exception list is ignored.
- **What I did about it:** Showed exceptions separately and reconciled only eligible reachable products. All 94 categories remain visible in the rollup view.
- **Residual risk:** Category assignments require business review; a disconnected category can display zero eligible counts without proving it has no stock issues.

## Looked wrong, is not wrong

These records have plausible legitimate explanations; the evidence does not certify every individual record.

| Apparent problem | Why it looks wrong | Why it is actually fine |
|---|---|---|
| 533 shared email groups on 1,068 customer records | May look like duplicate customers | Households or shared addresses can be legitimate; do not merge without identity evidence |
| 152 zero-price items | May look like missing revenue | Promotional/free items can legitimately cost zero; missing prices are a separate issue |
| 37 products without categories | Missing classification | Deliberate uncategorized listings are possible; display them separately for inventory visibility |
| 90 zero-change movements | No stock change occurred | All are stock_take records and can document a successful physical count |
| Seven categories without parents | Looks like broken references | NULL parent identifies a valid root, unlike a missing non-NULL parent |

Checks with no detected fault: all item product references exist (3); all item quantities are positive and known (9); every catalog price is positive and known (16); every stock-changing movement has a timestamp (21). Check 14 found no NULL movement quantities, and check 15 found expected directions for the six reason types. These observations are not future guarantees.

## Could not verify

- Actual cash received, discounts, fees, refunds and taxes; stored spending is not certified revenue. The exception queue identifies 144 missing-customer, 95 incomplete-line and 1,624 mismatched-total flags without rewriting their values.
- Order dates span 2025-08-02 to 2027-08-20 with no NULL dates (13). Future dates need source-system confirmation. The report uses UTC session dates and includes today; timestamps carry no timezone. The original business timezone is unknown.
- Inventory timestamps are present, but there are no sale movements in the thirty complete days preceding 2026-11-27, and 33 sale movements are future-dated. Recent demand cannot be inferred from absence in this stale extract. No stock-runway forecast was released. See [improvement.md](improvement.md).
- Reliable opening balances, complete movement capture and physical counts; historical negative stock does not prove every discrepancy was caused by concurrency.
- Supplier order and receipt dates are absent. No replenishment lead time is inferred.
- Production volume, network, concurrent workloads and the reported forty-minute Monday runtime have not been reproduced. Local tests establish the observed behavior only.

Detection SQL: [integrity_checks.sql](../integrity_checks.sql). Original full observations and exact distributions remain in [phase1_results.md](phase1_results.md). Current aggregate checks, hashes and synthetic rollback evidence are in [tests/final_evidence.json](../tests/final_evidence.json).
