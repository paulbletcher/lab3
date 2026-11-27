\set ON_ERROR_STOP on
BEGIN;
INSERT INTO products(product_id,product_name,price,stock_quantity) VALUES(-840000000,'SYNTHETIC OPENING BALANCE',1,8);
INSERT INTO inventory_log(log_id,product_id,change_qty,reason,created_at) VALUES(-840000000,-840000000,3,'restock',CURRENT_TIMESTAMP);
DO $$ BEGIN IF NOT EXISTS(SELECT FROM report_stock_vs_log_reconciliation WHERE product_id=-840000000 AND difference_units=5 AND implied_opening_balance=5) THEN RAISE EXCEPTION 'Opening-balance test failed'; END IF; END $$;
UPDATE products SET stock_quantity=NULL WHERE product_id=-840000000;
DO $$ BEGIN IF NOT EXISTS(SELECT FROM report_stock_vs_log_reconciliation WHERE product_id=-840000000 AND difference_units IS NULL) THEN RAISE EXCEPTION 'NULL stock test failed'; END IF; END $$;
ROLLBACK;
