-- Diagnostic only: an unknown opening balance prevents proof of a stock error.
CREATE OR REPLACE VIEW public.report_stock_vs_log_reconciliation AS
WITH movements AS (
 SELECT product_id,COUNT(*) AS movement_count,SUM(change_qty::bigint) AS logged_net_units,
        COALESCE(SUM(change_qty::bigint) FILTER (WHERE created_at::date>CURRENT_DATE),0) AS future_net_units,
        COUNT(*) FILTER (WHERE created_at IS NULL) AS missing_timestamp_count
 FROM public.inventory_log GROUP BY product_id
)
SELECT p.product_id,p.stock_quantity,COALESCE(m.movement_count,0) AS movement_count,
       COALESCE(m.logged_net_units,0) AS logged_net_units,
       p.stock_quantity::bigint-COALESCE(m.logged_net_units,0) AS difference_units,
       COALESCE(m.future_net_units,0) AS future_net_units,
       p.stock_quantity::bigint-(COALESCE(m.logged_net_units,0)-COALESCE(m.future_net_units,0)) AS difference_excluding_future,
       p.stock_quantity::bigint-COALESCE(m.logged_net_units,0) AS implied_opening_balance,
       COALESCE(m.missing_timestamp_count,0) AS missing_timestamp_count
FROM public.products p LEFT JOIN movements m USING(product_id);
