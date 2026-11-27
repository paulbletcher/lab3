
-- Phase 2: Verify automatic ID generation.
-- Purpose: Confirm that PostgreSQL generates IDs automatically
-- for orders, order_items and inventory_log.
--
-- Temporary records are inserted inside a transaction and rolled back.
-- Sequence values are still consumed after rollback.

BEGIN;

-- Insert a temporary order without specifying order_id.
WITH new_order AS (
    INSERT INTO orders (
        customer_id,
        order_date,
        status,
        total_amount
    )
    VALUES (
        NULL,
        CURRENT_TIMESTAMP,
        'PHASE2_ID_GENERATION_TEST',
        0.00
    )
    RETURNING order_id
),

-- Insert an order item without specifying order_item_id.
new_order_item AS (
    INSERT INTO order_items (
        order_id,
        product_id,
        quantity,
        unit_price
    )
    SELECT
        order_id,
        NULL,
        1,
        0.00
    FROM new_order
    RETURNING order_item_id, order_id
),

-- Insert an inventory log without specifying log_id.
new_inventory_log AS (
    INSERT INTO inventory_log (
        product_id,
        change_qty,
        reason,
        created_at,
        note
    )
    VALUES (
        NULL,
        0,
        'ID_GENERATION_TEST',
        CURRENT_TIMESTAMP,
        'Temporary ID generation test record.'
    )
    RETURNING log_id
)

-- Display the generated IDs.
SELECT
    new_order.order_id AS generated_order_id,
    new_order_item.order_item_id AS generated_order_item_id,
    new_inventory_log.log_id AS generated_inventory_log_id,
    new_order_item.order_id AS order_id_linked_to_item
FROM new_order
CROSS JOIN new_order_item
CROSS JOIN new_inventory_log;


-- Remove all temporary test records.
ROLLBACK;
