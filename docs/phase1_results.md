# Phase 1 Verification Results

Phase 1 data diagnosis is complete. All 21 integrity checks executed successfully. The [diagnosis](diagnosis.md) explains the findings, business implications, and risk ranking.

## Environment

- PostgreSQL: `18.7 (Debian 18.7-1.pgdg13+5)`.
- Docker container: `kloudkart`; project mount: `/lab`.
- Database and user: `postgres` / `postgres`.

Verification uses aggregate queries and database metadata. Individual customer and transaction records are excluded from this document.

## Schema verification

All **31 column definitions** across the six tables match `schema.sql`: names, order, types, nullability, defaults, and identity generation. The primary keys are:

| Table | Primary key | Constraint |
|---|---|---|
| categories | category_id | categories_pkey |
| customers | customer_id | customers_pkey |
| inventory_log | log_id | inventory_log_pkey |
| order_items | order_item_id | order_items_pkey |
| orders | order_id | orders_pkey |
| products | product_id | products_pkey |

| Column | is_identity | identity_generation | column_default |
|---|---|---|---|
| orders.order_id | NO | NULL | NULL |
| order_items.order_item_id | NO | NULL | NULL |
| inventory_log.log_id | NO | NULL | NULL |

Metadata verification found zero identity columns, zero user sequences, zero user routines, and zero user triggers. The only indexes are the six primary-key indexes. Constraints are the six original primary keys and their six required NOT NULL constraints; there are no foreign keys or additional unique/check constraints.

## Dataset row counts

| Table / dataset | Row count |
|---|---:|
| categories | 94 |
| products | 4,023 |
| customers | 40,420 |
| orders | 159,384 |
| order_items | 336,559 |
| inventory_log | 282,352 |

## All 21 integrity check results

The existing `integrity_checks.sql` completed with `ON_ERROR_STOP=1`. The results below support the diagnosis; no historical values were changed to resolve its findings.

| Check | Result |
| --- | --- |
| 1. Orders to customers | 210 orphan references; 0 NULL customer IDs |
| 2. Items to orders | 692 orphan references; 0 NULL order IDs |
| 3. Items to products | 0 orphan references; 0 NULL product IDs |
| 4. Inventory logs to products | 120 orphan references; 0 NULL product IDs |
| 5. Products to categories | 0 orphan references; 37 NULL category IDs |
| 6. Category parents | 1 missing parent; 7 top-level categories |
| 7. Category loops | 2 categories in loops; 0 leading into loops |
| 8. Product stock | 14 negative balances; 0 NULL balances |
| 9. Item quantities | 0 negative; 0 zero; 0 NULL |
| 10. Item unit prices | 0 negative; 152 zero; 148 NULL |
| 11. Order totals | 0 orders without items; 147 with incomplete lines; 0 NULL totals; 2,279 mismatches among orders with complete line amounts |
| 12. Order statuses | 15 stored values; 111,351 completed after normalization; 22,091 exactly `completed` |
| 13. Order dates | 0 NULL dates; 2025-08-02 through 2027-08-20 |
| 14. Stock-change quantities | 0 NULL; 90 zero |
| 15. Movement reasons | All 90 zero changes are `stock_take`; other directions consistent with the diagnosis |
| 16. Product prices | 0 negative; 0 zero; 0 NULL |
| 17. Normalized duplicate emails | 533 groups containing 1,068 customer rows |
| 18. Completed orders with missing customers | 144 orders; stored totals 388,780.89 |
| 19. Completed-order total mismatches | 1,624 orders; net difference -1,266,190.96; absolute difference 2,074,053.86 |
| 20. Completed orders with incomplete lines | 95 orders; stored totals 455,904.42 |
| 21. Stock changes without timestamps | 0 |
The completed-status definition uses `LOWER(TRIM(status)) IN ('complete', 'completed')` without changing the stored labels.

### Check 12: complete status distribution

Quotes delimit the stored labels; the leading space in `' completed'` is significant.

| Recorded status | Orders |
|---|---:|
| `' completed'` | 22,395 |
| `'COMPLETED'` | 22,392 |
| `'complete'` | 22,285 |
| `'Completed'` | 22,188 |
| `'completed'` | 22,091 |
| `'Pending'` | 8,081 |
| `'pending'` | 7,928 |
| `'shipped'` | 6,516 |
| `'Shipped'` | 6,332 |
| `'Refunded'` | 3,262 |
| `'cancelled'` | 3,238 |
| `'refunded'` | 3,217 |
| `'canceled'` | 3,209 |
| `'Cancelled'` | 3,131 |
| `'CANCELLED'` | 3,119 |

### Check 15: complete movement-reason distribution

| Recorded reason | Decreases | Zero changes | Increases | Total |
|---|---:|---:|---:|---:|
| sale | 262,088 | 0 | 0 | 262,088 |
| restock | 0 | 0 | 18,857 | 18,857 |
| return | 0 | 0 | 564 | 564 |
| correction | 290 | 0 | 195 | 485 |
| damage | 268 | 0 | 0 | 268 |
| stock_take | 0 | 90 | 0 | 90 |

## Historical-data preservation policy

**Decision: preserve historical records while keeping their integrity problems visible.**

The diagnosis identified negative stock balances, missing references, inconsistent order totals and statuses, and other issues. These findings establish discrepancies, but they do not establish the correct replacement values or the original business events. Some observations, such as free items, shared email addresses, and zero-change stock takes, may be legitimate.

We chose not to delete, overwrite, merge, or arbitrarily correct historical records without sufficient business evidence. Investigations may require payment records, original orders, promotion rules, product-retirement information, or physical inventory counts.

Deleting orphaned order items would remove evidence of historical purchases. Assigning them to an unrelated order would create a false sales history. Replacing missing prices with current catalog prices or overwriting stored totals could misrepresent the amount originally charged. Setting negative stock to zero could hide an unresolved inventory discrepancy.

For Kloud Kart, preserving this evidence supports reliable customer-spending analysis and an inventory trail that can be investigated. Reports will need explicit, documented handling of unresolved records, and any later correction must be supported by evidence.

Preventing new faults and correcting historical faults are separate responsibilities. Future checkout validation, stock controls, and audit behavior can protect new transactions without assuming that existing records have been repaired.

## Project status

Phases 0 and 1 are complete. Phases 2 through 5 are not started. Checkout and the inventory audit mechanism are future work.
