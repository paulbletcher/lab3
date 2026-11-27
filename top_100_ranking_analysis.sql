-- Phase 3, Step 3.6: compare candidate policies; no final policy is selected.
-- Only aggregate counts, the boundary amount and a boundary-tie indicator leave SQL.
-- Run with snapshot validation: python tests/verify_top100_ranking.py
WITH report_parameters AS (
    SELECT TIMESTAMP '2026-11-27 00:00:00' AS cutoff
),
report_base AS (
    SELECT o.order_id,
           o.customer_id,
           o.order_date,
           o.total_amount
    FROM orders AS o
    INNER JOIN customers AS c ON c.customer_id = o.customer_id
    CROSS JOIN report_parameters AS rp
    WHERE LOWER(TRIM(o.status)) IN ('complete', 'completed')
      AND o.order_date < rp.cutoff
),
customer_spending AS (
    SELECT c.customer_id,
           COALESCE(SUM(b.total_amount), 0) AS total_recorded_spending,
           COUNT(b.order_id) AS completed_order_count,
           COUNT(b.order_id) FILTER (
               WHERE b.total_amount IS NULL
           ) AS missing_amount_count
    FROM customers AS c
    LEFT JOIN report_base AS b ON b.customer_id = c.customer_id
    GROUP BY c.customer_id
),
customer_rankings AS (
    SELECT customer_id,
           total_recorded_spending,
           completed_order_count,
           missing_amount_count,
           ROW_NUMBER() OVER (
               ORDER BY total_recorded_spending DESC,
                        customer_id ASC
           ) AS row_number_position,
           RANK() OVER (
               ORDER BY total_recorded_spending DESC
           ) AS spending_rank,
           DENSE_RANK() OVER (
               ORDER BY total_recorded_spending DESC
           ) AS spending_dense_rank
    FROM customer_spending
),
spending_groups AS (
    SELECT total_recorded_spending,
           COUNT(*) AS customers,
           COUNT(*) FILTER (WHERE row_number_position <= 100) AS row_number_top100_customers
    FROM customer_rankings
    GROUP BY total_recorded_spending
),
boundary AS (
    -- MAX over a single position exposes no customer identifier.
    -- NULL means that this population has fewer than 100 customers.
    SELECT MAX(total_recorded_spending) FILTER (
               WHERE row_number_position = 100
           ) AS boundary_recorded_spending,
           MAX(spending_rank) FILTER (
               WHERE row_number_position = 100
           ) AS boundary_rank,
           MAX(spending_dense_rank) FILTER (
               WHERE row_number_position = 100
           ) AS boundary_dense_rank
    FROM customer_rankings
),
boundary_counts AS (
    SELECT COUNT(*) AS boundary_customers,
           COUNT(*) FILTER (WHERE r.row_number_position <= 100) AS boundary_included_row_number,
           COUNT(*) FILTER (WHERE r.spending_rank <= 100) AS boundary_included_rank,
           COUNT(*) FILTER (WHERE r.spending_dense_rank <= 100) AS boundary_included_dense_rank
    FROM customer_rankings AS r
    CROSS JOIN boundary AS b
    WHERE r.total_recorded_spending = b.boundary_recorded_spending
)
SELECT COUNT(*) AS customer_rows,
       COUNT(DISTINCT r.customer_id) AS distinct_customer_ids,
       COUNT(*) FILTER (WHERE completed_order_count > 0) AS customers_with_eligible_orders,
       COUNT(*) FILTER (WHERE completed_order_count = 0) AS customers_without_eligible_orders,
       COALESCE(SUM(missing_amount_count), 0) AS missing_eligible_order_amounts,
       COUNT(*) FILTER (WHERE row_number_position <= 100) AS row_number_top100_customers,
       COUNT(*) FILTER (WHERE spending_rank <= 100) AS rank_top100_customers,
       COUNT(*) FILTER (WHERE spending_dense_rank <= 100) AS dense_rank_top100_customers,
       COUNT(DISTINCT total_recorded_spending) FILTER (
           WHERE row_number_position <= 100
       ) AS row_number_top100_distinct_spending_values,
       (SELECT COUNT(*) FROM spending_groups WHERE customers > 1) AS population_spending_tie_groups,
       -- Count selected customers whose spending is tied anywhere in the population.
       (SELECT COALESCE(SUM(row_number_top100_customers), 0)
        FROM spending_groups WHERE customers > 1) AS top100_customers_in_population_ties,
       -- Also disambiguate ties wholly observable within the selected 100 rows.
       (SELECT COALESCE(SUM(row_number_top100_customers), 0)
        FROM spending_groups WHERE row_number_top100_customers > 1) AS top100_customers_in_internal_ties,
       (SELECT boundary_recorded_spending FROM boundary) AS boundary_recorded_spending,
       (SELECT boundary_rank FROM boundary) AS boundary_rank,
       (SELECT boundary_dense_rank FROM boundary) AS boundary_dense_rank,
       (SELECT boundary_customers FROM boundary_counts) AS boundary_customers,
       (SELECT boundary_included_row_number FROM boundary_counts) AS boundary_included_row_number,
       (SELECT boundary_included_rank FROM boundary_counts) AS boundary_included_rank,
       (SELECT boundary_included_dense_rank FROM boundary_counts) AS boundary_included_dense_rank,
       (SELECT boundary_included_row_number > 0
               AND boundary_customers > boundary_included_row_number
        FROM boundary_counts) AS tie_crosses_100th_boundary
FROM customer_rankings AS r;
