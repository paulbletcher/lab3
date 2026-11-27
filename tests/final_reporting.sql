\set ON_ERROR_STOP on
\ir test_support.sql
BEGIN ISOLATION LEVEL REPEATABLE READ;
\ir reference_customer_spending.sql
SELECT pg_temp.check(COUNT(*) = 0, 'optimized output equals original: both EXCEPT ALL directions')
FROM ((SELECT * FROM public.report_customer_spending EXCEPT ALL SELECT * FROM reference_customer_spending)
      UNION ALL
      (SELECT * FROM reference_customer_spending EXCEPT ALL SELECT * FROM public.report_customer_spending)) d;
SELECT CURRENT_DATE = DATE '2026-11-27' AS snapshot_date \gset
\if :snapshot_date
SELECT pg_temp.check(COUNT(*)=40420 AND COUNT(*) FILTER (WHERE order_count=0)=2520
    AND SUM(order_count)=111195 AND SUM(total_spent)=339184984.53,
    'actual-data customer baseline as of 2026-11-27') FROM public.report_customer_spending;
\else
\echo 'Fixed 2026-11-27 eligible-order baseline not applicable today; semantic reconciliations still run.'
\endif
SELECT pg_temp.check(NOT EXISTS (
    SELECT FROM public.report_customer_spending r
    WHERE (SELECT COUNT(*) FROM jsonb_object_keys(r.monthly_spend_trailing_12_months)) <> 12),
    'every customer has twelve calendar-month entries');
-- Independent full-data monthly reconciliation, including zero-valued months.
SELECT pg_temp.check(NOT EXISTS (
    SELECT FROM public.report_customer_spending r
    CROSS JOIN LATERAL jsonb_each_text(r.monthly_spend_trailing_12_months) m
    LEFT JOIN (
        SELECT customer_id, TO_CHAR(order_month,'YYYY-MM') AS month_key, SUM(order_spend) AS amount
        FROM public.report_eligible_completed_orders
        WHERE order_month >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '11 months'
        GROUP BY customer_id, order_month
    ) e ON e.customer_id=r.customer_id AND e.month_key=m.key
    WHERE m.value::numeric IS DISTINCT FROM COALESCE(e.amount,0)),
    'all twelve monthly amounts reconcile to eligible orders');
SELECT pg_temp.check(NOT EXISTS (
    SELECT FROM (
        SELECT *, SUM(order_spend) OVER (PARTITION BY customer_id) AS expected,
               ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date DESC,order_id DESC) AS last_row
        FROM public.report_customer_order_running_totals
    ) r WHERE last_row=1 AND running_customer_spend IS DISTINCT FROM expected),
    'last running total reconciles for every customer');
INSERT INTO public.customers(customer_id,full_name) VALUES
    (-880000000,'SYNTHETIC REPORT CUSTOMER'),(-879999999,'SYNTHETIC ZERO CUSTOMER'),
    (-879999998,'SYNTHETIC TIED CUSTOMER');
INSERT INTO public.orders(order_id,customer_id,order_date,status,total_amount) VALUES
    (-880000011,-880000000,DATE_TRUNC('month',CURRENT_DATE)-INTERVAL '12 months','completed',5),
    (-880000010,-880000000,CURRENT_DATE,' Completed ',10),
    (-880000009,-880000000,CURRENT_DATE,'complete',20),
    (-880000008,-880000000,CURRENT_DATE+INTERVAL '1 day','completed',100),
    (-880000007,-880000000,CURRENT_DATE,'pending',30),
    (-880000006,-880000000,CURRENT_DATE,'completed',NULL),
    (-880000005,-879999998,CURRENT_DATE,'completed',35);
SELECT pg_temp.check(order_count=3 AND total_spent=35
    AND (monthly_spend_trailing_12_months->>TO_CHAR(CURRENT_DATE,'YYYY-MM'))::numeric=30,
    'synthetic: normalization, future cutoff, lifetime and monthly window')
FROM public.report_customer_spending WHERE customer_id=-880000000;
SELECT pg_temp.check(order_count=0 AND total_spent=0,
    'synthetic: customer without qualifying orders remains')
FROM public.report_customer_spending WHERE customer_id=-879999999;
SELECT pg_temp.check(running_customer_spend=15 AND previous_order_date=
    DATE_TRUNC('month',CURRENT_DATE)-INTERVAL '12 months',
    'synthetic: running total uses date then order ID')
FROM public.report_customer_order_running_totals WHERE order_id=-880000010;
SELECT pg_temp.check(a.spending_rank=b.spending_rank AND a.top_100_position<b.top_100_position
    AND a.spending_rank=1+(SELECT COUNT(*) FROM public.report_customer_spending WHERE total_spent>35),
    'synthetic: shared rank and deterministic customer-ID tie break')
FROM public.report_customer_spending a CROSS JOIN public.report_customer_spending b
WHERE a.customer_id=-880000000 AND b.customer_id=-879999998;
ROLLBACK;
