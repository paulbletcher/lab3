SELECT table_name,
       column_name,
       is_identity
FROM information_schema.columns
WHERE table_schema = 'public'
    AND ((table_name = 'orders'
          AND column_name = 'order_id')
         OR (table_name = 'order_items'
             AND column_name = 'order_item_id')
         OR (table_name = 'inventory_log'
             AND column_name = 'log_id'))
ORDER BY table_name;