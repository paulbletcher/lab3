"""Verify the exact reusable customer query without printing individual rows.

Run: python tests/verify_customer_spending.py
Standard library + Docker's psql only. All live and VALUES-based checks share
one read-only REPEATABLE READ transaction. No fixtures or database objects are
created. Evidence filenames are unique and previous evidence is never replaced.
"""

from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]


def build_validation_sql():
    report = (ROOT / 'customer_spending.sql').read_text(encoding='utf-8').strip().removesuffix(';')
    base_script = (ROOT / 'report_base.sql').read_text(encoding='utf-8')
    cutoff = re.search(r"SELECT TIMESTAMP '([^']+)' AS cutoff", report).group(1)
    original_cutoff = re.search(r"\\set reporting_cutoff '([^']+)'", base_script).group(1)
    if cutoff != original_cutoff:
        raise ValueError('Customer/report-base cutoff definitions differ')
    # Detect accidental divergence from the original, validated base CTE.
    base_pattern = r'report_base AS \((.*?)\n\)'
    normalize = lambda value: ' '.join(value.split())
    if normalize(re.search(base_pattern, report, re.S).group(1)) != \
            normalize(re.search(base_pattern, base_script, re.S).group(1)):
        raise ValueError('Customer/report-base eligibility CTE definitions differ')

    live = f"""
        WITH customer_report AS (
            {report}
        ),
        independent_orders AS (
            SELECT o.order_id, o.customer_id, o.total_amount
            FROM orders AS o
            WHERE LOWER(TRIM(o.status)) IN ('complete', 'completed')
              AND o.order_date < TIMESTAMP '{cutoff}'
              AND EXISTS (SELECT 1 FROM customers AS c WHERE c.customer_id=o.customer_id)
        ),
        independent_customer_totals AS (
            SELECT customer_id, COUNT(order_id) AS order_count,
                   COALESCE(SUM(total_amount),0) AS spending,
                   COUNT(*) FILTER (WHERE total_amount IS NULL) AS missing_count
            FROM independent_orders GROUP BY customer_id
        ),
        source_totals AS (
            SELECT COUNT(*) AS orders, COUNT(DISTINCT customer_id) AS purchasing_customers,
                   COUNT(DISTINCT order_id) AS distinct_orders,
                   COALESCE(SUM(total_amount),0) AS spending,
                   COUNT(*) FILTER (WHERE total_amount IS NULL) AS missing_count
            FROM independent_orders
        ),
        report_totals AS (
            SELECT COUNT(*) AS customer_rows, COUNT(DISTINCT customer_id) AS distinct_customer_ids,
                   COUNT(*) FILTER (WHERE completed_order_count>0) AS purchasing_customers,
                   COUNT(*) FILTER (WHERE completed_order_count=0) AS nonpurchasing_customers,
                   COALESCE(SUM(completed_order_count),0) AS orders,
                   COALESCE(SUM(total_recorded_spending),0) AS spending,
                   COALESCE(SUM(missing_amount_count),0) AS missing_count,
                   COUNT(*) FILTER (WHERE missing_amount_count>0) AS customers_with_unknown_amounts,
                   COUNT(*)-COUNT(DISTINCT customer_id) AS duplicate_customer_ids,
                   COUNT(*) FILTER (WHERE completed_order_count=0 AND
                       (total_recorded_spending<>0 OR missing_amount_count<>0)) AS bad_zero_rows
            FROM customer_report
        ),
        coverage AS (
            SELECT COUNT(*) FILTER (WHERE r.customer_id IS NULL) AS missing_customers,
                   COUNT(*) FILTER (WHERE c.customer_id IS NULL) AS nonexistent_customers
            FROM customers AS c FULL JOIN customer_report AS r USING (customer_id)
        ),
        per_customer AS (
            SELECT COUNT(*) AS mismatches
            FROM customer_report AS r LEFT JOIN independent_customer_totals AS i USING (customer_id)
            WHERE r.completed_order_count IS DISTINCT FROM COALESCE(i.order_count,0)
               OR r.total_recorded_spending IS DISTINCT FROM COALESCE(i.spending,0)
               OR r.missing_amount_count IS DISTINCT FROM COALESCE(i.missing_count,0)
        ),
        metrics AS (
            SELECT v.metric, v.expected, v.actual
            FROM report_totals AS r
            CROSS JOIN LATERAL (VALUES
                ('Total customer rows',40420::numeric,r.customer_rows),
                ('Distinct customer IDs',40420,r.distinct_customer_ids),
                ('Customers with eligible orders',37900,r.purchasing_customers),
                ('Customers without eligible orders',2520,r.nonpurchasing_customers),
                ('Completed-order count',111195,r.orders),
                ('Recorded completed-order spending',339184984.53,r.spending),
                ('Duplicate customer IDs',0,r.duplicate_customer_ids),
                ('Missing eligible order amounts',0,r.missing_count),
                ('Customers with unknown amounts',0,r.customers_with_unknown_amounts)
            ) AS v(metric,expected,actual)
        ),
        checks AS (
            SELECT v.check_name, v.ok
            FROM report_totals AS r CROSS JOIN source_totals AS s
            CROSS JOIN coverage AS c CROSS JOIN per_customer AS p
            CROSS JOIN LATERAL (VALUES
                ('Every customer appears exactly once',
                    r.customer_rows=(SELECT COUNT(*) FROM customers)
                    AND r.duplicate_customer_ids=0 AND c.missing_customers=0),
                ('No nonexistent customer appears',c.nonexistent_customers=0),
                ('No-order customers have zero spending/count/missing amounts',r.bad_zero_rows=0),
                ('Purchasing-customer count matches live eligible orders',
                    r.purchasing_customers=s.purchasing_customers),
                ('Order counts reconcile to live eligible orders',r.orders=s.orders),
                ('Spending reconciles to live eligible orders',r.spending=s.spending),
                ('Missing amounts reconcile to live eligible orders',r.missing_count=s.missing_count),
                ('Each customer matches independent grouped eligible orders',p.mismatches=0),
                ('Eligible order identifiers are unique',s.orders=s.distinct_orders)
            ) AS v(check_name,ok)
        )
        SELECT json_build_object(
            'metadata', json_build_object('database',current_database(),'user',current_user,
                'cluster_identifier',(SELECT system_identifier::text FROM pg_control_system()),
                'isolation',current_setting('transaction_isolation'),
                'read_only',current_setting('transaction_read_only'),'cutoff','{cutoff}'),
            'metrics',(SELECT json_agg(row_to_json(m)) FROM metrics AS m),
            'checks',(SELECT json_agg(row_to_json(c)) FROM checks AS c),
            'live_checks_ok',(SELECT bool_and(ok) FROM checks),
            'historical_values_match',(SELECT bool_and(expected=actual) FROM metrics)
        );
    """

    synthetic = f"""
        WITH customers(customer_id,email) AS (VALUES
            (1,'shared@example.invalid'),(2,'shared@example.invalid'),
            (3,'three@example.invalid'),(4,'four@example.invalid'),
            (5,'five@example.invalid'),(6,'six@example.invalid')
        ),
        orders(order_id,customer_id,order_date,total_amount,status) AS (VALUES
            (1,1,TIMESTAMP '2026-11-26 23:59:59',10::numeric,' Completed '),
            (2,1,TIMESTAMP '2020-01-01',20,'COMPLETE'),
            (3,3,TIMESTAMP '2026-01-01',NULL,'completed'),
            (4,4,TIMESTAMP '2026-01-01',7.50,'complete'),
            (5,4,TIMESTAMP '2026-01-02',NULL,'completed'),
            (6,5,TIMESTAMP '2026-01-01',0,'completed'),
            (7,5,TIMESTAMP '2026-01-02',-5,'completed'),
            (8,6,TIMESTAMP '2026-01-01',99,'pending'),
            (9,999,TIMESTAMP '2026-01-01',100,'completed'),
            (10,1,TIMESTAMP '2026-01-01',100,'cancelled'),
            (11,1,TIMESTAMP '2026-11-27 00:00:00',100,'completed'),
            (12,1,TIMESTAMP '2026-11-28',100,'completed'),
            (13,1,NULL,100,'completed'),
            (14,1,TIMESTAMP '2026-01-01',100,NULL),
            (15,1,TIMESTAMP '2026-01-01',100,'   ')
        ),
        customer_report AS (
            {report}
        ),
        expected(customer_id,total_recorded_spending,completed_order_count,missing_amount_count) AS (
            VALUES (1,30::numeric,2,0),(2,0,0,0),(3,0,1,1),
                   (4,7.50,2,1),(5,-5,2,0),(6,0,0,0)
        ),
        case_checks AS (
            SELECT r.customer_id,
                   r.total_recorded_spending=e.total_recorded_spending
                       AND r.completed_order_count=e.completed_order_count
                       AND r.missing_amount_count=e.missing_amount_count AS ok
            FROM customer_report AS r JOIN expected AS e USING (customer_id)
        ),
        checks AS (
            SELECT v.test_id,v.scenario,v.ok FROM (VALUES
                ('SYN-01','Multiple orders, normalized statuses, lifetime history',
                    (SELECT ok FROM case_checks WHERE customer_id=1)),
                ('SYN-02','Customer without orders receives zero values',
                    (SELECT ok FROM case_checks WHERE customer_id=2)),
                ('SYN-03','All-NULL amounts remain distinguishable from no orders',
                    (SELECT ok FROM case_checks WHERE customer_id=3)),
                ('SYN-04','Mixed known/NULL amounts retain known sum and missing count',
                    (SELECT ok FROM case_checks WHERE customer_id=4)),
                ('SYN-05','Zero and negative amounts are retained',
                    (SELECT ok FROM case_checks WHERE customer_id=5)),
                ('SYN-06','Only ineligible orders still yields a zero customer row',
                    (SELECT ok FROM case_checks WHERE customer_id=6)),
                ('SYN-07','No extra/missing/duplicated rows after boundary and orphan exclusions',
                    (SELECT COUNT(*)=6 AND COUNT(DISTINCT customer_id)=6 FROM customer_report)
                    AND NOT EXISTS (SELECT * FROM customer_report EXCEPT SELECT * FROM expected)
                    AND NOT EXISTS (SELECT * FROM expected EXCEPT SELECT * FROM customer_report)),
                ('SYN-08','Aggregate known spending/orders/NULL amounts reconcile',
                    (SELECT SUM(total_recorded_spending)=32.50 AND SUM(completed_order_count)=7
                        AND SUM(missing_amount_count)=2 FROM customer_report)),
                ('SYN-09','Shared email does not merge customer IDs',
                    (SELECT COUNT(*)=2 FROM customer_report WHERE customer_id IN (1,2)))
            ) AS v(test_id,scenario,ok)
        )
        SELECT json_build_object('synthetic_checks',json_agg(row_to_json(c)),
                                 'synthetic_checks_ok',bool_and(ok IS TRUE)) FROM checks AS c;
    """
    return ('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;\n'
            "SET LOCAL statement_timeout='60s';\n" + live + synthetic + '\nCOMMIT;\n')


def verify(log):
    sql = build_validation_sql()
    result = subprocess.run(
        ['docker','exec','-w','/lab','-i','kloudkart','psql','-U','postgres','-d','postgres',
         '-X','-qAt','-v','ON_ERROR_STOP=1','-P','pager=off','-f','-'],
        input=sql,text=True,capture_output=True,timeout=90)
    if result.returncode != 0:
        raise RuntimeError('SQL verification failed; server output withheld to protect source data')
    payloads = [json.loads(line, parse_float=Decimal) for line in result.stdout.splitlines() if line.strip()]
    if len(payloads) != 2:
        raise RuntimeError('Expected live and synthetic aggregate results')
    live, synthetic = payloads
    metadata = live['metadata']
    log('Connection: ' + json.dumps(metadata))
    valid_target = metadata['database']=='postgres' and metadata['user']=='postgres' \
        and metadata['isolation']=='repeatable read' and metadata['read_only']=='on'
    log('Step 3.2 cutoff and eligibility definition consistency: PASS')
    for row in live['metrics']:
        status = 'PASS' if row['expected']==row['actual'] else 'FAIL'
        log(f"{row['metric']}: expected={row['expected']} actual={row['actual']} {status}")
    for row in live['checks']:
        log(row['check_name'] + ': ' + ('PASS' if row['ok'] is True else 'FAIL'))
    for row in synthetic['synthetic_checks']:
        log(row['test_id'] + ': ' + ('PASS' if row['ok'] is True else 'FAIL') + '; ' + row['scenario'])
    if not (valid_target and live['live_checks_ok'] is True
            and live['historical_values_match'] is True and synthetic['synthetic_checks_ok'] is True):
        raise RuntimeError('Customer-spending assertions failed; review aggregate evidence')
    log('Overall customer-spending validation: PASS')
    log('Read-only transaction completed; VALUES fixtures created no database objects or records.')


if __name__ == '__main__':
    path = ROOT / 'tests' / 'results' / ('phase3_customer_spending_' + uuid.uuid4().hex[:12] + '.txt')
    with path.open('x',encoding='utf-8') as evidence:
        def log(message):
            print(message,flush=True)
            evidence.write(message + '\n')
            evidence.flush()
        try:
            verify(log)
        except Exception as error:
            log('FAIL: ' + (str(error) if isinstance(error,(RuntimeError,ValueError))
                            else type(error).__name__))
            raise SystemExit(1)
    print('Execution evidence: ' + str(path.relative_to(ROOT)),flush=True)
