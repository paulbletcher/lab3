-- Recurring Finance/Ops queue. All loaded dates, including future dates.
-- One row per exception; an order can appear more than once. No data is changed.
CREATE OR REPLACE VIEW public.report_order_review_queue AS
WITH line_totals AS (
    SELECT order_id, COUNT(*) AS line_count,
           COUNT(*) FILTER (WHERE quantity IS NULL OR unit_price IS NULL) AS incomplete_lines,
           SUM(quantity::numeric * unit_price) AS line_sum
    FROM public.order_items
    GROUP BY order_id
), reviewed AS (
    SELECT o.order_id, o.total_amount AS stored_amount,
           CASE WHEN lt.line_count > 0 AND lt.incomplete_lines = 0
                THEN lt.line_sum END AS calculated_line_amount,
           c.customer_id IS NULL AS missing_customer,
           lt.order_id IS NULL OR lt.incomplete_lines > 0 AS incomplete_amount,
           lt.line_count > 0 AND lt.incomplete_lines = 0
               AND o.total_amount IS DISTINCT FROM lt.line_sum AS total_mismatch
    FROM public.orders AS o
    LEFT JOIN public.customers AS c USING (customer_id)
    LEFT JOIN line_totals AS lt USING (order_id)
    WHERE LOWER(BTRIM(o.status)) IN ('complete', 'completed')
)
SELECT r.order_id, e.exception_type, r.stored_amount, r.calculated_line_amount,
       r.stored_amount - r.calculated_line_amount AS difference,
       e.explanation
FROM reviewed AS r
CROSS JOIN LATERAL (VALUES
    ('missing_customer'::text, r.missing_customer,
     'Completed order has no matching customer; confirm attribution before changing it.'::text),
    ('incomplete_line_amount', r.incomplete_amount,
     'Completed order has missing lines, quantities or prices; its full line amount is unknown.'),
    ('total_mismatch', r.total_mismatch,
     'Stored total differs from complete line amounts or is missing; verify charges, discounts and fees.')
) AS e(exception_type, needs_review, explanation)
WHERE e.needs_review;
