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
