-- Preliminary check: Determine safe starting points
-- for automatic ID generation.

SELECT
    (SELECT MAX(order_id)
     FROM orders) AS max_order_id,

    (SELECT MAX(order_id)
     FROM order_items) AS max_referenced_order_id,

    (SELECT MAX(order_item_id)
     FROM order_items) AS max_order_item_id,

    (SELECT MAX(log_id)
     FROM inventory_log) AS max_log_id;

-- Verify that all three sequences are correctly initialized.

SELECT 'orders' AS table_name,
       last_value,
       is_called
FROM orders_order_id_seq
UNION ALL
SELECT 'order_items',
       last_value,
       is_called
FROM order_items_order_item_id_seq
UNION ALL
SELECT 'inventory_log',
       last_value,
       is_called
FROM inventory_log_log_id_seq;