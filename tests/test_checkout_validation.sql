-- Phase 2: Checkout input validation tests.
-- Verify that invalid basic parameters are rejected correctly.

\set ON_ERROR_STOP on
BEGIN;

CREATE TEMP TABLE checkout_validation_results ON COMMIT DROP AS
WITH test_cases AS (
    SELECT *
    FROM (
        VALUES
            ('VAL-01', NULL::bigint, 1::bigint, 1,
             'Required input is missing'),

            ('VAL-02', 1, NULL, 1,
             'Required input is missing'),

            ('VAL-03', 1, 1, NULL,
             'Required input is missing'),

            ('VAL-04', 1, 1, 0,
             'Quantity must be greater than zero'),

            ('VAL-05', 1, 1, -5,
             'Quantity must be greater than zero'),

            ('VAL-06', 2147483648::bigint, 1, 1,
             'Customer not found'),

            ('VAL-07', (SELECT MIN(customer_id)::bigint FROM customers),
             2147483648::bigint, 1,
             'Product not found')

    ) AS t (
        test_id,
        customer_id,
        product_id,
        quantity,
        expected_message
    )
)

SELECT
    t.test_id,
    t.expected_message,
    r.success,
    r.order_id,
    r.message AS actual_message,
    CASE
        WHEN COUNT(*) OVER (PARTITION BY t.test_id) = 1
         AND r.success IS FALSE
         AND r.order_id IS NULL
         AND r.message = t.expected_message
        THEN 'PASS'
        ELSE 'FAIL'
    END AS test_result
FROM test_cases AS t
LEFT JOIN LATERAL place_order(
    t.customer_id,
    t.product_id,
    t.quantity
) AS r ON true
ORDER BY t.test_id;

SELECT * FROM checkout_validation_results ORDER BY test_id;

DO $$
BEGIN
    IF (SELECT COUNT(*) FROM checkout_validation_results) <> 7
       OR EXISTS (
           SELECT 1 FROM checkout_validation_results
           WHERE test_result IS DISTINCT FROM 'PASS'
       ) THEN
        RAISE EXCEPTION 'Checkout validation assertions failed';
    END IF;
END;
$$;

ROLLBACK;
