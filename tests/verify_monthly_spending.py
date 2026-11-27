"""Validate the actual monthly SQL with aggregate-only live/VALUES evidence.

Run: python tests/verify_monthly_spending.py
Uses the standard library and Docker's psql. No client rows are exported, no
fixtures/objects are created, and all checks share one read-only snapshot.
"""

from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
import uuid


ROOT = Path(__file__).resolve().parents[1]


def load_reports():
    monthly = (ROOT / 'monthly_spending.sql').read_text(encoding='utf-8').strip().removesuffix(';')
    lifetime = (ROOT / 'customer_spending.sql').read_text(encoding='utf-8').strip().removesuffix(';')
    base = (ROOT / 'report_base.sql').read_text(encoding='utf-8')
    cutoff = re.search(r"SELECT TIMESTAMP '([^']+)' AS cutoff", monthly).group(1)
    lifetime_cutoff = re.search(r"SELECT TIMESTAMP '([^']+)' AS cutoff", lifetime).group(1)
    base_cutoff = re.search(r"\\set reporting_cutoff '([^']+)'", base).group(1)
    if not cutoff == lifetime_cutoff == base_cutoff:
        raise ValueError('Monthly, lifetime and base cutoffs differ')
    definitions = [' '.join(re.search(r'report_base AS \((.*?)\n\)', sql, re.S).group(1).split())
                   for sql in (monthly, lifetime, base)]
    if len(set(definitions)) != 1:
        raise ValueError('Monthly, lifetime and base eligibility CTEs differ')
    return monthly, lifetime, cutoff


def context(monthly, lifetime, cutoff):
    """Set-based independent references: never query the full grid once per row."""
    return f"""
    monthly_report AS ({monthly}),
    lifetime_report AS ({lifetime}),
    parameters AS (SELECT TIMESTAMP '{cutoff}' AS cutoff),
    reference_anchor AS (
        SELECT cutoff, CASE WHEN cutoff=DATE_TRUNC('month',cutoff)
               THEN DATE_TRUNC('month',cutoff)-INTERVAL '1 month'
               ELSE DATE_TRUNC('month',cutoff) END AS final_month FROM parameters
    ),
    bounds AS (
        SELECT cutoff,final_month,final_month-INTERVAL '11 months' AS window_start
        FROM reference_anchor
    ),
    expected_months AS (
        SELECT (b.window_start+n.number*INTERVAL '1 month')::date AS spending_month
        FROM bounds b CROSS JOIN GENERATE_SERIES(0,11) AS n(number)
    ),
    eligible_orders AS (
        SELECT o.order_id,o.customer_id,o.order_date,o.total_amount
        FROM orders o CROSS JOIN bounds b
        WHERE LOWER(TRIM(o.status)) IN ('complete','completed') AND o.order_date<b.cutoff
          AND EXISTS (SELECT 1 FROM customers c WHERE c.customer_id=o.customer_id)
    ),
    window_orders AS (
        SELECT o.* FROM eligible_orders o CROSS JOIN bounds b WHERE o.order_date>=b.window_start
    ),
    reference_monthly AS (
        SELECT customer_id,DATE_TRUNC('month',order_date)::date AS spending_month,
               COUNT(order_id) AS orders,COALESCE(SUM(total_amount),0) AS spending,
               COUNT(*) FILTER (WHERE total_amount IS NULL) AS missing
        FROM window_orders GROUP BY customer_id,DATE_TRUNC('month',order_date)::date
    ),
    before_by_customer AS (
        SELECT customer_id,COUNT(order_id) AS orders,COALESCE(SUM(total_amount),0) AS spending,
               COUNT(*) FILTER (WHERE total_amount IS NULL) AS missing
        FROM eligible_orders o CROSS JOIN bounds b WHERE o.order_date<b.window_start
        GROUP BY customer_id
    ),
    monthly_by_customer AS (
        SELECT customer_id,SUM(completed_order_count) AS orders,
               SUM(monthly_recorded_spending) AS spending,SUM(missing_amount_count) AS missing,
               COUNT(*) AS month_rows,COUNT(DISTINCT spending_month) AS distinct_months
        FROM monthly_report GROUP BY customer_id
    ),
    report_totals AS (
        SELECT COUNT(*) AS rows,COUNT(DISTINCT customer_id) AS customers,
               COUNT(DISTINCT spending_month) AS months,MIN(spending_month) AS first_month,
               MAX(spending_month) AS last_month,
               COUNT(*)-COUNT(DISTINCT (customer_id,spending_month)) AS duplicates,
               COALESCE(SUM(completed_order_count),0) AS orders,
               COALESCE(SUM(monthly_recorded_spending),0) AS spending,
               COALESCE(SUM(missing_amount_count),0) AS missing
        FROM monthly_report
    ),
    expected_grid AS (
        SELECT c.customer_id,m.spending_month FROM customers c CROSS JOIN expected_months m
    ),
    coverage AS (
        SELECT COUNT(*) FILTER (WHERE r.customer_id IS NULL) AS missing_cells,
               COUNT(*) FILTER (WHERE g.customer_id IS NULL) AS extra_cells
        FROM expected_grid g FULL JOIN monthly_report r USING (customer_id,spending_month)
    ),
    cell_checks AS (
        SELECT COUNT(*) FILTER (WHERE c.customer_id IS NULL) AS nonexistent_customers,
               COUNT(*) FILTER (WHERE m.spending_month IS NULL) AS outside_months,
               COUNT(*) FILTER (WHERE r.completed_order_count IS DISTINCT FROM COALESCE(e.orders,0)
                   OR r.monthly_recorded_spending IS DISTINCT FROM COALESCE(e.spending,0)
                   OR r.missing_amount_count IS DISTINCT FROM COALESCE(e.missing,0)) AS mismatches,
               COUNT(*) FILTER (WHERE e.orders IS NULL AND
                   (r.completed_order_count IS DISTINCT FROM 0::bigint
                    OR r.monthly_recorded_spending IS DISTINCT FROM 0::numeric
                    OR r.missing_amount_count IS DISTINCT FROM 0::bigint)) AS bad_zero_cells
        FROM monthly_report r LEFT JOIN reference_monthly e USING (customer_id,spending_month)
        LEFT JOIN customers c ON c.customer_id=r.customer_id
        LEFT JOIN expected_months m ON m.spending_month=r.spending_month
    ),
    assignment_checks AS (
        SELECT COUNT(*) AS bad_assignments FROM (
            SELECT o.order_id FROM window_orders o LEFT JOIN expected_months m
              ON o.order_date>=m.spending_month AND o.order_date<m.spending_month+INTERVAL '1 month'
            GROUP BY o.order_id HAVING COUNT(m.spending_month)<>1
        ) AS assignments
    ),
    partitions AS (
        SELECT COUNT(*) AS lifetime_orders,COALESCE(SUM(total_amount),0) AS lifetime_spending,
               COUNT(*) FILTER (WHERE total_amount IS NULL) AS lifetime_missing,
               COUNT(*) FILTER (WHERE order_date<b.window_start) AS before_orders,
               COALESCE(SUM(total_amount) FILTER (WHERE order_date<b.window_start),0) AS before_spending,
               COUNT(*) FILTER (WHERE order_date<b.window_start AND total_amount IS NULL) AS before_missing,
               COUNT(*) FILTER (WHERE order_date>=b.window_start) AS window_orders,
               COALESCE(SUM(total_amount) FILTER (WHERE order_date>=b.window_start),0) AS window_spending,
               COUNT(*) FILTER (WHERE order_date>=b.window_start AND total_amount IS NULL) AS window_missing
        FROM eligible_orders CROSS JOIN bounds b
    ),
    lifetime_totals AS (
        SELECT COALESCE(SUM(completed_order_count),0) AS orders,
               COALESCE(SUM(total_recorded_spending),0) AS spending,
               COALESCE(SUM(missing_amount_count),0) AS missing FROM lifetime_report
    ),
    customer_reconciliation AS (
        SELECT COUNT(*) AS mismatches
        FROM lifetime_report l FULL JOIN monthly_by_customer m USING (customer_id)
        LEFT JOIN before_by_customer p USING (customer_id)
        WHERE l.customer_id IS NULL OR m.customer_id IS NULL
           OR l.completed_order_count IS DISTINCT FROM m.orders+COALESCE(p.orders,0)
           OR l.total_recorded_spending IS DISTINCT FROM m.spending+COALESCE(p.spending,0)
           OR l.missing_amount_count IS DISTINCT FROM m.missing+COALESCE(p.missing,0)
    ),
    monthly_summary AS (
        SELECT spending_month,SUM(completed_order_count) AS completed_orders,
               SUM(monthly_recorded_spending) AS recorded_spending,
               COUNT(DISTINCT customer_id) FILTER (WHERE completed_order_count>0) AS purchasing_customers,
               SUM(missing_amount_count) AS missing_amount_count
        FROM monthly_report GROUP BY spending_month
    )
    """


def live_sql(monthly, lifetime, cutoff):
    return 'WITH ' + context(monthly,lifetime,cutoff) + """,
    metrics AS (
        SELECT v.metric,v.expected,v.actual FROM report_totals r
        CROSS JOIN LATERAL (VALUES
            ('Distinct customers','40420',r.customers::text),
            ('Reporting months','12',r.months::text),
            ('Customer-month rows','485040',r.rows::text),
            ('Minimum rows per customer','12',(SELECT MIN(month_rows)::text FROM monthly_by_customer)),
            ('Maximum rows per customer','12',(SELECT MAX(month_rows)::text FROM monthly_by_customer)),
            ('Duplicate customer-month keys','0',r.duplicates::text),
            ('First reporting month','2025-12-01',r.first_month::text),
            ('Last reporting month','2026-11-01',r.last_month::text)
        ) AS v(metric,expected,actual)
    ),
    checks AS (
        SELECT v.check_name,v.ok FROM report_totals r CROSS JOIN coverage g
        CROSS JOIN cell_checks c CROSS JOIN assignment_checks a CROSS JOIN partitions p
        CROSS JOIN lifetime_totals l CROSS JOIN customer_reconciliation k CROSS JOIN bounds b
        CROSS JOIN LATERAL (VALUES
            ('Row count equals live customers times 12',r.rows=(SELECT COUNT(*)*12 FROM customers)),
            ('Every existing customer-month is present',g.missing_cells=0),
            ('No extra customer-month keys',g.extra_cells=0),
            ('Exactly 12 rows and months per customer',NOT EXISTS (
                SELECT 1 FROM monthly_by_customer WHERE month_rows<>12 OR distinct_months<>12)),
            ('No duplicate customer-month keys',r.duplicates=0),
            ('No nonexistent customers',c.nonexistent_customers=0),
            ('Exactly 12 derived months with correct endpoints',r.months=12
                AND r.first_month=b.window_start::date AND r.last_month=b.final_month::date),
            ('No months outside derived window',c.outside_months=0),
            ('No-purchase cells have zero values',c.bad_zero_cells=0),
            ('Monthly order counts match independent window orders',r.orders=p.window_orders),
            ('Monthly spending matches independent window orders',r.spending=p.window_spending),
            ('Monthly missing amounts match independent window orders',r.missing=p.window_missing),
            ('Every customer-month matches grouped reference',c.mismatches=0),
            ('Each eligible window order belongs to exactly one month',a.bad_assignments=0),
            ('Before plus within spending equals lifetime',p.before_spending+r.spending=p.lifetime_spending),
            ('Before plus within orders equals lifetime',p.before_orders+r.orders=p.lifetime_orders),
            ('Before plus within missing amounts equals lifetime',p.before_missing+r.missing=p.lifetime_missing),
            ('Step 3.3 totals match independent lifetime orders',l.orders=p.lifetime_orders
                AND l.spending=p.lifetime_spending AND l.missing=p.lifetime_missing),
            ('Step 3.3 reconciles per customer with before plus monthly',k.mismatches=0)
        ) AS v(check_name,ok)
    )
    SELECT json_build_object(
        'metadata',json_build_object('database',current_database(),'user',current_user,
            'cluster_identifier',(SELECT system_identifier::text FROM pg_control_system()),
            'isolation',current_setting('transaction_isolation'),
            'read_only',current_setting('transaction_read_only'),
            'cutoff',(SELECT cutoff::text FROM bounds),'window_start',(SELECT window_start::text FROM bounds)),
        'metrics',(SELECT json_agg(row_to_json(m)) FROM metrics m),
        'checks',(SELECT json_agg(row_to_json(c)) FROM checks c),
        'monthly_summary',(SELECT json_agg(row_to_json(s) ORDER BY spending_month) FROM monthly_summary s),
        'reconciliation',(SELECT row_to_json(p) FROM partitions p),
        'checks_ok',(SELECT bool_and(ok IS TRUE) FROM checks),
        'baseline_ok',(SELECT bool_and(expected IS NOT DISTINCT FROM actual) FROM metrics)
    );
    """


def synthetic_sql(monthly, lifetime, cutoff):
    fixtures = """
    customers(customer_id) AS (VALUES (1),(2),(3),(4),(5),(6)),
    orders(order_id,customer_id,order_date,total_amount,status) AS (VALUES
        (1,1,TIMESTAMP '2025-12-01',10::numeric,' Completed '),
        (2,1,TIMESTAMP '2025-12-15',20,'COMPLETE'),
        (3,1,TIMESTAMP '2026-01-15',5,'completed'),
        (4,3,TIMESTAMP '2026-01-01',NULL,'completed'),
        (5,4,TIMESTAMP '2026-02-01',7.50,'complete'),
        (6,4,TIMESTAMP '2026-02-02',NULL,'completed'),
        (7,5,TIMESTAMP '2026-03-01',0,'completed'),
        (8,5,TIMESTAMP '2026-03-02',-5,'completed'),
        (9,6,TIMESTAMP '2026-06-01',99,'pending'),
        (10,1,TIMESTAMP '2025-11-30 23:59:59.999999',50,'completed'),
        (11,1,TIMESTAMP '2026-11-26 23:59:59.999999',8,'completed'),
        (12,1,TIMESTAMP '2026-11-27',100,'completed'),
        (13,1,TIMESTAMP '2026-11-28',100,'completed'),
        (14,999,TIMESTAMP '2026-01-01',100,'completed'),
        (15,NULL,TIMESTAMP '2026-01-01',100,'completed'),
        (16,1,NULL,100,'completed'),
        (17,1,TIMESTAMP '2026-01-01',100,'cancelled'),
        (18,1,TIMESTAMP '2026-01-01',100,NULL),
        (19,1,TIMESTAMP '2026-01-01',100,'   ')
    ),
    """
    main = 'WITH ' + fixtures + context(monthly,lifetime,cutoff) + """,
    expected_active(customer_id,spending_month,spending,orders,missing) AS (VALUES
        (1,DATE '2025-12-01',30::numeric,2,0),(1,DATE '2026-01-01',5,1,0),
        (3,DATE '2026-01-01',0,1,1),(4,DATE '2026-02-01',7.50,2,1),
        (5,DATE '2026-03-01',-5,2,0),(1,DATE '2026-11-01',8,1,0)
    ),
    fixed_months(spending_month) AS (VALUES
        (DATE '2025-12-01'),(DATE '2026-01-01'),(DATE '2026-02-01'),(DATE '2026-03-01'),
        (DATE '2026-04-01'),(DATE '2026-05-01'),(DATE '2026-06-01'),(DATE '2026-07-01'),
        (DATE '2026-08-01'),(DATE '2026-09-01'),(DATE '2026-10-01'),(DATE '2026-11-01')
    ),
    expected AS (
        SELECT c.customer_id,m.spending_month,COALESCE(e.spending,0) AS monthly_recorded_spending,
               COALESCE(e.orders,0)::bigint AS completed_order_count,
               COALESCE(e.missing,0)::bigint AS missing_amount_count
        FROM customers c CROSS JOIN fixed_months m
        LEFT JOIN expected_active e USING (customer_id,spending_month)
    ),
    checks AS (
        SELECT v.test_id,v.scenario,v.ok FROM (VALUES
            ('MONTH-SYN-01','Multiple normalized completed orders in one month',
                (SELECT monthly_recorded_spending=30 AND completed_order_count=2
                 FROM monthly_report WHERE customer_id=1 AND spending_month=DATE '2025-12-01')),
            ('MONTH-SYN-02','Different months and December-to-January boundary',
                (SELECT SUM(monthly_recorded_spending)=35 AND SUM(completed_order_count)=3
                 FROM monthly_report WHERE customer_id=1 AND spending_month IN (DATE '2025-12-01',DATE '2026-01-01'))),
            ('MONTH-SYN-03','Customer without orders has twelve zero cells',
                (SELECT COUNT(*)=12 AND SUM(completed_order_count)=0 AND SUM(monthly_recorded_spending)=0
                 AND SUM(missing_amount_count)=0 FROM monthly_report WHERE customer_id=2)),
            ('MONTH-SYN-04','Missing months between purchases are zero-filled',
                (SELECT COUNT(*)=9 AND SUM(completed_order_count)=0 AND SUM(monthly_recorded_spending)=0
                 FROM monthly_report WHERE customer_id=1 AND spending_month BETWEEN DATE '2026-02-01' AND DATE '2026-10-01')),
            ('MONTH-SYN-05','All-NULL amounts retain positive order and missing counts',
                (SELECT monthly_recorded_spending=0 AND completed_order_count=1 AND missing_amount_count=1
                 FROM monthly_report WHERE customer_id=3 AND spending_month=DATE '2026-01-01')),
            ('MONTH-SYN-06','Mixed known and NULL amounts retain subtotal and missing count',
                (SELECT monthly_recorded_spending=7.50 AND completed_order_count=2 AND missing_amount_count=1
                 FROM monthly_report WHERE customer_id=4 AND spending_month=DATE '2026-02-01')),
            ('MONTH-SYN-07','Zero and negative monetary amounts remain eligible',
                (SELECT monthly_recorded_spending=-5 AND completed_order_count=2
                 FROM monthly_report WHERE customer_id=5 AND spending_month=DATE '2026-03-01')),
            ('MONTH-SYN-08','Immediately before window contributes only to lifetime',
                (SELECT before_spending=50 AND before_orders=1 FROM partitions)),
            ('MONTH-SYN-09','Inclusive window-start order is counted',
                (SELECT monthly_recorded_spending=30 AND completed_order_count=2
                 FROM monthly_report WHERE customer_id=1 AND spending_month=DATE '2025-12-01')),
            ('MONTH-SYN-10','Immediately before cutoff is included',
                (SELECT monthly_recorded_spending=8 AND completed_order_count=1
                 FROM monthly_report WHERE customer_id=1 AND spending_month=DATE '2026-11-01')),
            ('MONTH-SYN-11','At/after cutoff, invalid statuses/dates and missing customers excluded',
                NOT EXISTS (SELECT * FROM monthly_report EXCEPT SELECT * FROM expected)
                AND NOT EXISTS (SELECT * FROM expected EXCEPT SELECT * FROM monthly_report)),
            ('MONTH-SYN-12','Only-ineligible-order customer receives twelve zero cells',
                (SELECT COUNT(*)=12 AND SUM(completed_order_count)=0 AND SUM(monthly_recorded_spending)=0
                 FROM monthly_report WHERE customer_id=6)),
            ('MONTH-SYN-13','Exactly one row for every synthetic customer-month',
                (SELECT COUNT(*)=72 AND COUNT(DISTINCT (customer_id,spending_month))=72 FROM monthly_report)),
            ('MONTH-SYN-14','Window and lifetime order/spending/missing counts reconcile',
                (SELECT window_orders=9 AND window_spending=45.50 AND window_missing=2
                 AND lifetime_orders=10 AND lifetime_spending=95.50 AND lifetime_missing=2 FROM partitions)
                AND (SELECT orders=9 AND spending=45.50 AND missing=2 FROM report_totals)
                AND (SELECT mismatches=0 FROM customer_reconciliation))
        ) AS v(test_id,scenario,ok)
    )
    SELECT json_build_object('synthetic_checks',json_agg(row_to_json(c)),
                            'checks_ok',bool_and(ok IS TRUE)) FROM checks c;
    """
    # Alternate cutoffs modify only the centralized parameter, not the report logic.
    alternate = []
    cases = [
        ('MONTH-SYN-15','Leap-year February and exclusive March-start cutoff','2024-03-01 00:00:00',
         '2023-03-01','2024-02-01',
         "(1,1,TIMESTAMP '2024-02-28',10::numeric,'completed'),"
         "(2,1,TIMESTAMP '2024-02-29',20,'complete'),"
         "(3,1,TIMESTAMP '2024-03-01',100,'completed')",30,2),
        ('MONTH-SYN-16','Month-start cutoff selects previous final month','2026-11-01 00:00:00',
         '2025-11-01','2026-10-01',
         "(1,1,TIMESTAMP '2025-10-31 23:59:59.999999',50::numeric,'completed'),"
         "(2,1,TIMESTAMP '2025-11-01',3,'completed'),"
         "(3,1,TIMESTAMP '2026-10-31 23:59:59.999999',4,'completed'),"
         "(4,1,TIMESTAMP '2026-11-01',100,'completed')",7,2),
        ('MONTH-SYN-17','January-start cutoff selects previous December and calendar year','2026-01-01 00:00:00',
         '2025-01-01','2025-12-01',
         "(1,1,TIMESTAMP '2025-01-01',3::numeric,'completed'),"
         "(2,1,TIMESTAMP '2025-12-31 23:59:59.999999',4,'completed'),"
         "(3,1,TIMESTAMP '2026-01-01',100,'completed')",7,2)
    ]
    for test_id, scenario, test_cutoff, first, last, orders, spending, count in cases:
        alternate_monthly = monthly.replace(f"SELECT TIMESTAMP '{cutoff}' AS cutoff",
                                           f"SELECT TIMESTAMP '{test_cutoff}' AS cutoff",1)
        alternate.append(f"""
            WITH customers(customer_id) AS (VALUES (1),(2)),
            orders(order_id,customer_id,order_date,total_amount,status) AS (VALUES {orders}),
            monthly_report AS ({alternate_monthly})
            SELECT json_build_object('synthetic_checks',json_build_array(json_build_object(
                'test_id','{test_id}','scenario','{scenario}','ok',
                COUNT(*)=24 AND COUNT(DISTINCT (customer_id,spending_month))=24
                AND MIN(spending_month)=DATE '{first}' AND MAX(spending_month)=DATE '{last}'
                AND SUM(monthly_recorded_spending)={spending} AND SUM(completed_order_count)={count}
                AND SUM(missing_amount_count)=0)),
                'checks_ok',COUNT(*)=24 AND COUNT(DISTINCT (customer_id,spending_month))=24
                AND MIN(spending_month)=DATE '{first}' AND MAX(spending_month)=DATE '{last}'
                AND SUM(monthly_recorded_spending)={spending} AND SUM(completed_order_count)={count}
                AND SUM(missing_amount_count)=0) FROM monthly_report;
        """)
    return main + ''.join(alternate)


def verify(log):
    monthly,lifetime,cutoff = load_reports()
    sql = ("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
           "SET LOCAL statement_timeout='60s';\n" + live_sql(monthly,lifetime,cutoff)
           + synthetic_sql(monthly,lifetime,cutoff) + '\nCOMMIT;\n')
    result = subprocess.run(
        ['docker','exec','-w','/lab','-i','kloudkart','psql','-U','postgres','-d','postgres',
         '-X','-qAt','-v','ON_ERROR_STOP=1','-P','pager=off','-f','-'],
        input=sql,text=True,capture_output=True,timeout=120)
    if result.returncode != 0:
        raise RuntimeError('Monthly SQL validation failed; server details withheld to protect client data')
    payloads = [json.loads(line,parse_float=Decimal) for line in result.stdout.splitlines() if line.strip()]
    if len(payloads) != 5:
        raise RuntimeError('Expected one live and four synthetic aggregate result sets')
    live = payloads[0]
    metadata = live['metadata']
    log('Connection: ' + json.dumps(metadata))
    log('Step 3.2/3.3 cutoff and eligibility definition consistency: PASS')
    for row in live['metrics']:
        log(f"{row['metric']}: expected={row['expected']} actual={row['actual']} "
            + ('PASS' if row['expected']==row['actual'] else 'FAIL'))
    log('Month | Completed orders | Recorded spending | Purchasing customers | Missing amounts')
    for row in live['monthly_summary']:
        log(f"{row['spending_month']} | {row['completed_orders']} | {row['recorded_spending']:.2f} | "
            f"{row['purchasing_customers']} | {row['missing_amount_count']}")
    log('Lifetime reconciliation: ' + json.dumps(live['reconciliation'],default=str))
    for row in live['checks']:
        log(row['check_name'] + ': ' + ('PASS' if row['ok'] is True else 'FAIL'))
    for payload in payloads[1:]:
        for row in payload['synthetic_checks']:
            log(row['test_id'] + ': ' + ('PASS' if row['ok'] is True else 'FAIL') + '; ' + row['scenario'])
    target_ok = metadata['database']=='postgres' and metadata['user']=='postgres' \
        and metadata['isolation']=='repeatable read' and metadata['read_only']=='on'
    if not (target_ok and live['checks_ok'] is True and live['baseline_ok'] is True
            and all(p['checks_ok'] is True for p in payloads[1:])):
        raise RuntimeError('Monthly spending assertions failed; review aggregate evidence')
    log('Overall monthly-spending validation: PASS')
    log('Read-only transaction completed; VALUES fixtures created no records or database objects.')


if __name__ == '__main__':
    path = ROOT / 'tests' / 'results' / ('phase3_monthly_spending_' + uuid.uuid4().hex[:12] + '.txt')
    with path.open('x',encoding='utf-8') as evidence:
        def log(message):
            print(message,flush=True)
            evidence.write(message+'\n')
            evidence.flush()
        try:
            verify(log)
        except Exception as error:
            log('FAIL: ' + (str(error) if isinstance(error,(RuntimeError,ValueError)) else type(error).__name__))
            raise SystemExit(1)
    print('Execution evidence: ' + str(path.relative_to(ROOT)),flush=True)
