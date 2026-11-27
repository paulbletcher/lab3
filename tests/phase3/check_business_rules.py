"""Rollback-only edge-case and atomicity checks; run outside performance trials.

Uses existing valid customer internally, synthetic product only, no personal
details or record identifiers in output. Every fixture/write is rolled back.
"""
import argparse
import json
from datetime import datetime, timezone
from run_experiment import connect, safety, LOGS, write

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('label')
    args=parser.parse_args()
    c,_,_=connect()
    before=safety(c)
    checks=[]
    c.autocommit=False
    try:
        with c.cursor() as cur:
            cur.execute('SELECT min(customer_id),max(customer_id)::bigint+1 FROM public.customers')
            customer,missing_customer=cur.fetchone()
            cur.execute('SELECT max(product_id)::bigint+1600 FROM public.products')
            product=cur.fetchone()[0]
            cur.execute('SELECT count(*) FROM public.order_items WHERE product_id=%s',(product,))
            assert cur.fetchone()[0]==0
            cur.execute('SELECT count(*) FROM public.inventory_log WHERE product_id=%s',(product,))
            assert cur.fetchone()[0]==0
            cur.execute("INSERT INTO public.products(product_id,product_name,price,stock_quantity) VALUES (%s,'PHASE3 ROLLBACK FIXTURE',100,10)",(product,))
            def call(cust,prod,qty):
                cur.execute('SELECT success,order_id,message FROM public.place_order(%s,%s,%s)',(cust,prod,qty))
                return cur.fetchone()
            def refused(label,cust,prod,qty,text):
                row=call(cust,prod,qty)
                assert row[0] is False and row[1] is None and text.lower() in row[2].lower()
                checks.append({'check':label,'passed':True})
            refused('null customer',None,product,1,'invalid checkout')
            refused('null product',customer,None,1,'invalid checkout')
            refused('null quantity',customer,product,None,'invalid checkout')
            refused('zero quantity',customer,product,0,'invalid checkout')
            refused('negative quantity',customer,product,-1,'invalid checkout')
            refused('missing customer',missing_customer,product,1,'customer not found')
            refused('missing product',customer,product+1,1,'product not found')
            refused('product bigint outside integer range',customer,2**40,1,'product not found')
            refused('customer precedence when product also missing',missing_customer,product+1,1,'customer not found')
            refused('insufficient stock',customer,product,11,'out of stock')
            for value,label in ((None,'null price'),(-1,'negative price')):
                cur.execute('UPDATE public.products SET price=%s WHERE product_id=%s',(value,product))
                refused(label,customer,product,1,'invalid product price')
            cur.execute('UPDATE public.products SET price=100,stock_quantity=NULL WHERE product_id=%s',(product,))
            refused('null stock',customer,product,1,'out of stock')
            cur.execute('UPDATE public.products SET stock_quantity=10 WHERE product_id=%s',(product,))
            row=call(customer,product,3)
            assert row[0] is True and row[1] is not None
            order=row[1]
            cur.execute('SELECT stock_quantity FROM public.products WHERE product_id=%s',(product,))
            assert cur.fetchone()[0]==7
            cur.execute("SELECT count(*) FROM public.orders WHERE order_id=%s AND customer_id=%s AND total_amount=300 AND status='pending'",(order,customer))
            assert cur.fetchone()[0]==1
            cur.execute('SELECT count(*) FROM public.order_items WHERE order_id=%s AND product_id=%s AND quantity=3 AND unit_price=100',(order,product))
            assert cur.fetchone()[0]==1
            cur.execute("SELECT count(*) FROM public.inventory_log WHERE product_id=%s AND change_qty=-3 AND reason='sale'",(product,))
            assert cur.fetchone()[0]==1
            checks.append({'check':'multi-unit success: stock/order/item/movement consistent','passed':True})
            refused('insufficient after success',customer,product,8,'out of stock')
            cur.execute('UPDATE public.products SET price=0 WHERE product_id=%s',(product,))
            assert call(customer,product,1)[0] is True
            checks.append({'check':'zero price is valid under original rules','passed':True})
            # Force an actual INSERT error after successful stock deduction.
            cur.execute('UPDATE public.products SET price=9999999999.99,stock_quantity=2 WHERE product_id=%s',(product,))
            cur.execute('SELECT (SELECT count(*) FROM public.orders),(SELECT count(*) FROM public.order_items),(SELECT count(*) FROM public.inventory_log)')
            counts_before_error=cur.fetchone()
            cur.execute('SAVEPOINT insertion_failure')
            failed=False
            try:
                call(customer,product,2)  # total_amount exceeds numeric(12,2)
            except Exception as exc:
                if getattr(exc,'pgcode',None)!='22003':
                    raise
                failed=True
                cur.execute('ROLLBACK TO SAVEPOINT insertion_failure')
            assert failed
            cur.execute('SELECT stock_quantity FROM public.products WHERE product_id=%s',(product,))
            assert cur.fetchone()[0]==2
            cur.execute('SELECT (SELECT count(*) FROM public.orders),(SELECT count(*) FROM public.order_items),(SELECT count(*) FROM public.inventory_log)')
            assert cur.fetchone()==counts_before_error
            checks.append({'check':'post-stock INSERT failure rolls back deduction and partial writes','passed':True})
    finally:
        c.rollback()
        c.autocommit=True
        after=safety(c)
        c.close()
        assert before==after
    out={'label':args.label,'checks':checks,'passed':len(checks),'rollback_cleanup_verified':True}
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    write(LOGS/f'business_rules_{args.label}_{stamp}.json',out)
    print(json.dumps(out))

if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error_type':type(exc).__name__,'sqlstate':getattr(exc,'pgcode',None)}))
        raise SystemExit(1) from None
