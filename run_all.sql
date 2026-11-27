-- Install into a loaded database during a maintenance window.
-- No DROP/TRUNCATE, CSV reload, or historical correction occurs here.
-- Use the guarded tests/final_verification.py runner for the disposable environment.
\set ON_ERROR_STOP on
\pset pager off
\ir setup_checks.sql
\ir integrity_checks.sql
\ir migrations/phase2_create_id_sequences.sql
\ir functions/phase3_place_order.sql
\ir functions/phase3_inventory_movement.sql
\ir functions/phase3_inventory_permissions.sql
\ir reports/phase4_customer_spending.sql
\ir reports/phase5_low_stock.sql
\ir reports/order_review_queue.sql
\ir reports/stock_vs_log_reconciliation.sql
\ir tests/final_assertions.sql
\echo 'Solution installed; all installation assertions passed.'
