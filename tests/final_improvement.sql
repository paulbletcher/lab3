\set ON_ERROR_STOP on
\ir test_support.sql
BEGIN;
SELECT pg_temp.check(COUNT(*) FILTER (WHERE exception_type='missing_customer')=144
    AND COUNT(*) FILTER (WHERE exception_type='incomplete_line_amount')=95
    AND COUNT(*) FILTER (WHERE exception_type='total_mismatch')=1624,
    'review queue reproduces three established completed-order counts')
FROM public.report_order_review_queue;
SELECT pg_temp.check(SUM(difference)=-1266190.96 AND SUM(ABS(difference))=2074053.86,
    'review queue mismatch net and absolute amounts reconcile')
FROM public.report_order_review_queue WHERE exception_type='total_mismatch';
SELECT pg_temp.check(SUM(stored_amount)=388780.89,'missing-customer recorded amounts reconcile')
FROM public.report_order_review_queue WHERE exception_type='missing_customer';
SELECT pg_temp.check(SUM(stored_amount)=455904.42 AND BOOL_AND(calculated_line_amount IS NULL)
    AND BOOL_AND(difference IS NULL),'incomplete amounts stay unknown')
FROM public.report_order_review_queue WHERE exception_type='incomplete_line_amount';
INSERT INTO public.orders(order_id,customer_id,order_date,status,total_amount) VALUES
    (-860000000,-860000000,CURRENT_DATE,' Completed ',100),
    (-860000001,-860000000,CURRENT_DATE,'pending',100),
    (-860000002,-860000000,CURRENT_DATE+INTERVAL '10 days','complete',10),
    (-860000003,-860000000,CURRENT_DATE,'complete',0);
INSERT INTO public.order_items(order_item_id,order_id,product_id,quantity,unit_price) VALUES
    (-860000000,-860000000,1,1,NULL),
    (-860000001,-860000001,1,1,NULL),
    (-860000002,-860000002,1,1,12);
SELECT pg_temp.check(COUNT(*)=2 AND COUNT(*) FILTER (WHERE exception_type='total_mismatch')=0,
    'overlapping missing-customer and incomplete-line flags, no invented line sum')
FROM public.report_order_review_queue WHERE order_id=-860000000;
SELECT pg_temp.check(COUNT(*)=0,'pending order excluded')
FROM public.report_order_review_queue WHERE order_id=-860000001;
SELECT pg_temp.check(COUNT(*)=2 AND MIN(difference)=-2,
    'future completed order stays reviewable; signed difference is stored minus lines')
FROM public.report_order_review_queue WHERE order_id=-860000002;
SELECT pg_temp.check(COUNT(*)=2 AND BOOL_AND(calculated_line_amount IS NULL),
    'order with no lines is incomplete rather than zero-valued')
FROM public.report_order_review_queue WHERE order_id=-860000003;
ROLLBACK;
