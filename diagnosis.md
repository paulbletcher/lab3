- Check 1 — Order → customer. A LEFT JOIN found 210 orders pointing to
  missing customers and 0 with a NULL customer ID. Any affected orders
  that qualify as spending would be omitted from customer totals when
  the report uses an INNER JOIN to customers.

- Check 2 — Order item → order. A LEFT JOIN found 692 item rows pointing
  to missing orders and 0 with a NULL order ID. Reports that require a
  matching order would omit those lines. Multiple items can reference
  the same missing order.

- Check 3 — Order item → product. Found 0 order items pointing to
  missing products and 0 with a NULL product ID. Every line item can
  be linked to a product for sales reporting and stock reconciliation.

- Check 4 — Inventory log → product. A LEFT JOIN found 120 log entries
  pointing to missing products and 0 with a NULL product ID. These
  stock movements cannot be matched to a product in the current catalog,
  making them harder to verify during an inventory audit.

- Check 5 — Product → category. A LEFT JOIN found 0 products pointing
  to missing categories and 37 with a NULL category ID. Any of those
  37 products that are low in stock would be left out of the category
  rollup unless the report shows uncategorized products separately.

- Check 6 — Category → parent category. A LEFT JOIN found 1 category
  pointing to a missing parent and 7 top-level categories with a NULL
  parent ID. A low-stock rollup that starts at the top-level categories
  would miss the category with the broken link and any of its descendants.

- Check 7 — Category loops. Following parent links from every category
  found 2 categories in loops and 0 other categories leading into them.
  A low-stock rollup that starts at top-level categories would miss
  products assigned to those 2 categories. A traversal that reaches a
  loop needs to stop when it sees a category again.

- Check 8 — Product stock quantities. Found 14 products with a stock
  balance below zero and 0 with a NULL balance. Checkout would decline
  new purchases for those 14 products while their recorded balance is
  negative. The balances need to be reconciled against inventory records.

- Check 9 — Order item quantities. Found 0 negative, 0 zero, and
  0 NULL quantities. Every order item has a positive quantity.

- Check 10 — Order item unit prices. Found 0 negative, 152 zero,
  and 148 NULL unit prices. Zero prices may represent free items.
  The 148 missing prices leave those line amounts unknown. Since SUM
  skips NULL amounts, an order with both priced and unpriced items
  can appear to have a complete total when only some lines were added.

- Check 11 — Order total reconciliation. Found 0 orders without items,
  147 with incomplete line amounts, and 0 with a NULL stored total.
  Among orders with complete line amounts, 2,279 stored totals differed
  from the calculated line sum. The choice of amount could change
  customer spending totals and rankings. Checkout rules for discounts
  and fees may explain some differences.

- Check 12 — Order statuses. Found 15 distinct stored values, with
  differences in capitalization, leading spaces, and spelling.
  Treating 'complete' as equivalent to 'completed' gives 111,351
  completed orders. An exact match on 'completed' would count only
  22,091 of them, understating customer spending and order counts.

- Check 13 — Order dates. Found 0 orders with a NULL order date.
  Recorded dates range from 2025-08-02 through 2027-08-20. The monthly
  spending report needs an explicit cutoff to define its 12-month window.

- Check 14 — Inventory movement quantities. Found 0 NULL quantities
  and 90 entries that record no stock change. The reason recorded
  on each entry can help explain whether the zero was intentional.

- Check 15 — Inventory movement reasons. All 90 zero-quantity entries
  were labeled 'stock_take'. They may record stock counts that required
  no adjustment. The other reasons had the expected movement directions.

- Check 16 — Catalog prices. Found 0 negative, 0 zero, and 0 NULL
  prices. Every product has a positive catalog price for checkout.

- Check 17 — Shared customer emails. After trimming spaces and
  ignoring case, 533 email addresses appeared on 1,068 customer rows.
  If some rows belong to the same person, their spending may be split
  across customer IDs and affect their ranking. Shared addresses need
  review before any accounts are merged.

- Check 18 — Completed orders tied to missing customers. Of the 210
  orders with missing customer records, 144 had a completed status
  after normalizing the labels. Their stored totals sum to 388,780.89
  across all loaded dates. An INNER JOIN to customers would omit
  these orders and their value from customer spending totals.

- Check 19 — Completed order total mismatches. Across all loaded
  dates, 1,624 completed orders with complete line amounts had a
  stored total that differed from the sum of their items. Stored
  totals were lower by 1,266,190.96 overall, and the absolute
  differences totaled 2,074,053.86. The amount used in the spending
  report could materially change customer totals and rankings.
  Payment records would help establish which amounts were charged.

- Check 20 — Completed orders with incomplete line items. The check
  found 95 completed orders with at least one item missing a quantity
  or unit price. The stored totals for those orders added up to
  455,904.42. The missing values prevented a reliable comparison
  between the stored totals and the sum of the items.

- Check 21 — Stock movement timestamps. Found 0 stock-changing
  entries with a missing timestamp. Every recorded stock change had
  a timestamp that can be used to reconstruct the movement timeline.

## Ranked Integrity Findings

The findings below are ranked by their impact on stock accuracy, order fulfilment, customer-spending reports and inventory visibility, rather than by the number of affected records.

### 1. Negative Inventory Balances — Critical

- **Evidence (Check 8):** 14 products have negative stock quantities.
- **Cause:** The products table has no constraint preventing negative stock balances.
- **Detection:** Filtered products where `stock_quantity < 0`.
- **Business impact:** Negative stock balances make it difficult for Kloud Kart to determine how much inventory is actually available. Incorrect stock records can lead to overselling, refunds, customer complaints or the refusal of legitimate purchases. The number of affected sales and their financial cost cannot be established from the negative balances alone.
- **Recommendation:** Implement concurrency-safe order placement, prevent new negative stock balances and reconcile existing negative balances against physical inventory. Automatically setting negative quantities to zero would hide discrepancies without establishing the actual stock available.

### 2. Inconsistent Order Totals — High

- **Evidence (Checks 11 and 19):** 2,279 orders have stored totals that differ from their calculated line-item totals. Of these, 1,624 are completed orders with complete line amounts. Across those completed orders, stored totals are lower by 1,266,190.96 overall, with absolute differences totalling 2,074,053.86.
- **Cause:** Order totals are stored separately from line-item amounts, without an enforced mechanism ensuring consistency.
- **Detection:** Calculated order totals using the sum of quantity multiplied by unit price and compared them against stored totals.
- **Business impact:** Customer-spending totals and top-100 rankings may change materially depending on which amount is used in the Monday report. These differences do not establish that Kloud Kart lost money or charged customers incorrectly.
- **Recommendation:** Calculate new order totals within the checkout transaction and investigate historical differences using payment records and any applicable discounts, taxes or delivery charges. Avoid overwriting historical totals without establishing the correct amount.

### 3. Inconsistent Order Statuses — High

- **Evidence (Check 12):** There are 15 distinct stored order status values. An exact match on `completed` returns 22,091 orders, while normalizing case and spaces and treating `complete` as equivalent to `completed` returns 111,351 orders.
- **Cause:** The status column accepts unrestricted text without an enforced set of valid values.
- **Detection:** Grouped orders by their stored status and compared exact and normalized status values.
- **Business impact:** A report filtering only for the exact value `completed` would exclude 89,260 orders, approximately 80.16% of the orders that qualify under the proposed normalized definition. This could substantially understate customer spending and order counts and distort customer rankings.
- **Recommendation:** Apply a documented status mapping in the spending report and enforce standardized values for future orders. Confirm the intended meaning of ambiguous statuses before permanently changing historical records.

### 4. Orders Referencing Missing Customers — High

- **Evidence (Checks 1 and 18):** 210 orders reference customers that do not exist. Of these, 144 are completed orders with stored totals of 388,780.89.
- **Cause:** There is no foreign key between orders and customers.
- **Detection:** Used a LEFT JOIN to identify orders whose non-null customer IDs have no corresponding customer record.
- **Business impact:** An INNER JOIN between orders and customers excludes these orders from customer-level reporting. The stored value of the 144 completed orders cannot be attributed to existing customer accounts, potentially understating reported spending and affecting rankings.
- **Recommendation:** Investigate the missing customer references and introduce referential integrity for future orders. Do not delete affected orders or assign them to unrelated customers simply to satisfy a foreign key.

### 5. Order Items Referencing Missing Orders — High

- **Evidence (Check 2):** 692 order items reference orders that do not exist. No order items have a NULL order ID.
- **Cause:** There is no foreign key between order_items and orders.
- **Detection:** Used a LEFT JOIN to identify order items whose order IDs have no matching order record.
- **Business impact:** Reports that require matching orders will exclude these 692 line items. This may understate product sales and quantities sold and make inventory reconciliation more difficult. The financial impact on completed sales cannot be reliably determined because the corresponding order records, statuses and dates are missing. Multiple affected items may also belong to the same missing order.
- **Recommendation:** Investigate the missing order records and enforce valid order references for future order items. Preserve existing orphaned items until their original transactions can be established.

### 6. Incomplete Order Line Amounts — High

- **Evidence (Checks 10, 11 and 20):** 148 order items have missing unit prices. Overall, 147 orders contain incomplete line amounts, including 95 completed orders with stored totals of 455,904.42.
- **Cause:** The schema allows missing unit prices and quantities in order items.
- **Detection:** Checked for NULL values in quantity and unit price and identified the orders containing incomplete line amounts.
- **Business impact:** Reliable line-item totals cannot be calculated for the affected orders. SQL aggregates may silently omit incomplete line amounts, producing misleading spending figures if those totals are used without validation.
- **Recommendation:** Require valid quantities and unit prices for future order items. Investigate historical missing values using original transaction records rather than substituting zero or the current product price.

### 7. Inventory Logs Referencing Missing Products — Medium

- **Evidence (Check 4):** 120 inventory log entries reference products that do not exist.
- **Cause:** There is no foreign key between inventory_log and products.
- **Detection:** Used a LEFT JOIN to identify inventory movements without matching product records.
- **Business impact:** Auditors cannot reliably associate these 120 movements with existing products. This reduces the ability to reconcile historical inventory movements and investigate stock discrepancies. The financial impact cannot be determined without additional information about the missing products.
- **Recommendation:** Investigate whether the products were deleted or incorrectly referenced. Preserve historical inventory records and enforce valid references for future movements, with an appropriate product-retirement policy.

### 8. Circular Category Relationships — Medium

- **Evidence (Check 7):** Two categories participate in circular parent-child relationships. No additional categories were found leading into these loops.
- **Cause:** The schema does not enforce an acyclic category hierarchy.
- **Detection:** Used a recursive CTE to follow category parent relationships and identify repeated category IDs along each path.
- **Business impact:** Recursive category queries that encounter these loops without cycle protection may fail to terminate. Queries that start exclusively from top-level categories may omit products assigned to the affected categories. Either outcome prevents Nana from obtaining a complete and reliable low-stock summary. The number of affected low-stock products has not yet been established.
- **Recommendation:** Implement cycle detection in the category rollup and prevent future circular relationships. Correct the affected parent assignments only after establishing their intended positions in the hierarchy.

### 9. Broken Category Parent Reference — Medium

- **Evidence (Check 6):** One category references a parent category that does not exist.
- **Cause:** The category parent ID has no self-referencing foreign key.
- **Detection:** Used a self-referencing LEFT JOIN to identify categories with non-null parent IDs that have no matching category.
- **Business impact:** A category rollup starting exclusively from valid root categories may omit the affected category, its descendants and their products. This could conceal products requiring replenishment. The number of affected low-stock products has not yet been established.
- **Recommendation:** Include disconnected categories in a separately identified reporting group and investigate the intended parent relationship before correcting the data.

## Observations Requiring Business Clarification

The following observations are not classified as confirmed integrity faults because they may represent legitimate business activity.

### Shared Customer Emails (Check 17)

After normalizing email addresses by trimming spaces and ignoring case, 533 email groups were found across 1,068 customer records.

If multiple records belong to the same customer, their spending may be split across different customer IDs, affecting customer counts and spending rankings. However, different customers may legitimately share an email address.

Customer accounts should not be merged or restricted based solely on matching email addresses without further verification.

### Zero-Priced Order Items (Check 10)

152 order items have a zero unit price. These may represent promotional items, complimentary products or other legitimate transactions.

Without information about Kloud Kart's promotional and pricing policies, these records cannot be classified as incorrect. Zero-priced items should not be removed or assigned replacement prices automatically.

### Uncategorized Products (Check 5)

37 products have no assigned category. No products reference nonexistent categories.

The uncategorized products may have been intentionally left without a category. However, any of these products that are low in stock could be excluded from the category rollup if the report only includes products with valid category assignments.

Uncategorized products should be displayed separately to maintain complete inventory visibility.

### Zero-Change Inventory Movements (Checks 14 and 15)

90 inventory entries record zero quantity changes. All 90 entries have the reason `stock_take`.

These entries may legitimately document physical stock verification where the recorded balance matched the actual quantity and no adjustment was necessary.

They should be preserved as part of the inventory audit trail rather than treated as invalid movements.

## Reporting Considerations

### Order Date Range (Check 13)

No orders have a NULL order date. Recorded order dates range from August 2, 2025, to August 20, 2027.

The trailing 12-month spending report must use an explicitly defined reporting cutoff so that the reporting period is consistent and reproducible.

The presence of later dates in the extract does not establish that the records are incorrect. The reporting cutoff and its justification will be documented during report development.

## Checks With No Faults Detected

The following checks did not identify integrity faults within the conditions tested:

- **Check 3 — Order item product references:** All order items reference existing products, with no orphaned or NULL product IDs.
- **Check 9 — Order item quantities:** No negative, zero or NULL order item quantities were found.
- **Check 16 — Catalog prices:** No negative, zero or NULL product prices were found.
- **Check 21 — Stock movement timestamps:** No stock-changing inventory entries have missing timestamps.

These results establish that the tested conditions are currently satisfied. They do not guarantee that future records will remain valid without appropriate database controls.

## Justification of Risk Ranking

Negative inventory balances are ranked highest because unreliable stock directly affects Kloud Kart's ability to fulfil customer orders. Preventing overselling is also Nana's most immediate operational requirement, particularly with the upcoming flash sales.

Order total discrepancies and inconsistent statuses are ranked next because they can materially affect the accuracy of the Monday spending report and the customer rankings Nana uses to make decisions.

Missing customer and order references, together with incomplete line amounts, are classified as high-risk findings because they compromise the completeness and reliability of sales reporting and transaction reconciliation.

Inventory log and category hierarchy faults are classified as medium-risk findings because their primary impact is on auditability, replenishment decisions and inventory reporting. Although they require attention, their immediate financial impact has not been established.

The ranking prioritizes business consequences rather than affected record counts.

## Scope and Limitations

- The diagnosis covers all dates in the loaded extract, rather than a specific 12-month reporting period.
- Financial figures represent recorded order values and discrepancies, not verified payments or confirmed financial losses.
- Some findings may affect the same orders. Their financial values must not be added together as though they represent independent losses.
- The exact impact on the Monday spending report will depend on the reporting cutoff and the definition of customer spending selected during report development.
- Negative stock balances demonstrate an inventory integrity problem but do not establish that concurrent checkout activity caused every affected balance.
- Shared email addresses do not establish that customer accounts are duplicates.
- Order total discrepancies may have legitimate explanations, including discounts, taxes and delivery charges.
- Historical inventory balances cannot be fully verified without reliable opening balances, movement records and physical inventory counts.
- The risk classifications represent an engineering assessment based on the lab brief and the available data, rather than confirmed classifications provided by Nana.

No historical records were modified during the diagnosis phase. Corrections requiring additional business evidence are identified for investigation rather than applied automatically.

The subsequent implementation will focus on preventing new integrity faults, producing reliable reports and maintaining visibility of unresolved historical discrepancies.

## Supporting SQL Checks

The detection queries for all 21 checks are contained in `integrity_checks.sql`. The detailed check-by-check observations below provide the supporting evidence for the ranked findings.
