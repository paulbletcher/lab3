"""Aggregate-only verification of the actual Step 3.5 query.

Run: python tests/verify_running_totals.py
Standard library + Docker psql only; read-only REPEATABLE READ. VALUES fixtures
create no objects/records. Individual report rows never leave PostgreSQL.
"""

from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
import uuid


ROOT = Path(__file__).resolve().parents[1]


def load_reports():
    names = ('running_customer_totals.sql','customer_spending.sql','monthly_spending.sql')
    running,lifetime,monthly = [(ROOT/name).read_text(encoding='utf-8').strip().removesuffix(';')
                                for name in names]
    cutoffs = [re.search(r"SELECT TIMESTAMP '([^']+)' AS cutoff", s).group(1)
               for s in (running,lifetime,monthly)]
    base = (ROOT/'report_base.sql').read_text(encoding='utf-8')
    cutoffs.append(re.search(r"\\set reporting_cutoff '([^']+)'",base).group(1))
    if len(set(cutoffs)) != 1:
        raise ValueError('Running/lifetime/monthly/base cutoffs differ')
    for cte, sources in [('report_base',(running,lifetime,monthly,base)),
                         ('customer_spending',(running,lifetime))]:
        definitions = [' '.join(re.search(cte+r' AS \((.*?)\n\)',s,re.S).group(1).split())
                       for s in sources]
        if len(set(definitions)) != 1:
            raise ValueError(cte+' definitions differ from previous reporting scripts')
    # Reuse the actual rank CTE as well, including customers absent from order output.
    ranks = running.rsplit('\nSELECT ',1)[0] + '\nSELECT customer_id, customer_total_spend_rank FROM customer_ranks'
    return running,lifetime,ranks,cutoffs[0]


def context(running,lifetime,ranks,cutoff):
    return f"""
    order_report AS ({running}),
    lifetime_report AS ({lifetime}),
    rank_report AS ({ranks}),
    eligible_orders AS (
        SELECT o.order_id,o.customer_id,o.order_date,o.total_amount FROM orders o
        WHERE LOWER(TRIM(o.status)) IN ('complete','completed')
          AND o.order_date<TIMESTAMP '{cutoff}'
          AND EXISTS (SELECT 1 FROM customers c WHERE c.customer_id=o.customer_id)
    ),
    reference_orders AS (
        SELECT e.*,ROW_NUMBER() OVER reference_order AS position,
               LAG(order_id) OVER reference_order AS previous_id,
               LAG(order_date) OVER reference_order AS expected_previous_date,
               COUNT(*) OVER (PARTITION BY customer_id) AS customer_orders
        FROM eligible_orders e
        WINDOW reference_order AS (PARTITION BY customer_id ORDER BY order_date,order_id)
    ),
    customer_totals AS (
        SELECT c.customer_id,COALESCE(SUM(e.total_amount),0) AS spending
        FROM customers c LEFT JOIN eligible_orders e USING (customer_id) GROUP BY c.customer_id
    ),
    spending_buckets AS (
        SELECT spending,COUNT(*) AS customers FROM customer_totals GROUP BY spending
    ),
    ranked_buckets AS (
        SELECT spending,1+COALESCE(SUM(customers) OVER (
            ORDER BY spending DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ),0) AS expected_rank FROM spending_buckets
    ),
    expected_ranks AS (
        SELECT c.customer_id,c.spending,b.expected_rank
        FROM customer_totals c JOIN ranked_buckets b USING (spending)
    ),
    timestamp_groups AS (
        SELECT customer_id,order_date,COUNT(*) AS peer_rows,
               COALESCE(SUM(total_amount),0) AS peer_spending
        FROM eligible_orders GROUP BY customer_id,order_date
    ),
    reference_range AS (
        SELECT customer_id,order_date,SUM(peer_spending) OVER (
            PARTITION BY customer_id ORDER BY order_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS expected_peer_spending FROM timestamp_groups
    ),
    coverage AS (
        SELECT COUNT(*) FILTER (WHERE r.order_id IS NULL) AS missing_orders,
               COUNT(*) FILTER (WHERE e.order_id IS NULL) AS extra_orders,
               COUNT(*) FILTER (WHERE r.customer_id IS DISTINCT FROM e.customer_id
                   OR r.order_date IS DISTINCT FROM e.order_date
                   OR r.total_amount IS DISTINCT FROM e.total_amount) AS wrong_source_values
        FROM order_report r FULL JOIN eligible_orders e USING (order_id)
    ),
    detail_checks AS (
        SELECT COUNT(*) FILTER (WHERE e.position=1 AND
                   (r.running_recorded_spending IS DISTINCT FROM COALESCE(e.total_amount,0)
                    OR r.running_missing_amount_count IS DISTINCT FROM
                        CASE WHEN e.total_amount IS NULL THEN 1::bigint ELSE 0::bigint END)) AS bad_first,
               COUNT(*) FILTER (WHERE r.running_order_count IS DISTINCT FROM e.position) AS bad_positions,
               COUNT(*) FILTER (WHERE r.running_recorded_spending IS DISTINCT FROM
                   COALESCE(p.running_recorded_spending,0)+COALESCE(e.total_amount,0)) AS bad_recurrence,
               COUNT(*) FILTER (WHERE r.running_missing_amount_count IS DISTINCT FROM
                   COALESCE(p.running_missing_amount_count,0)+CASE WHEN e.total_amount IS NULL THEN 1 ELSE 0 END) AS bad_missing,
               COUNT(*) FILTER (WHERE r.previous_order_date IS DISTINCT FROM e.expected_previous_date) AS bad_lag,
               COUNT(*) FILTER (WHERE r.days_since_previous_order IS DISTINCT FROM
                   e.order_date::date-e.expected_previous_date::date) AS bad_gaps,
               COUNT(*) FILTER (WHERE e.position=1 AND
                   (r.previous_order_date IS NOT NULL OR r.days_since_previous_order IS NOT NULL)) AS bad_first_lag,
               COUNT(*) FILTER (WHERE r.date_peer_recorded_spending IS DISTINCT FROM q.expected_peer_spending) AS bad_range
        FROM reference_orders e JOIN order_report r USING (order_id)
        LEFT JOIN order_report p ON p.order_id=e.previous_id
        JOIN reference_range q ON q.customer_id=e.customer_id AND q.order_date=e.order_date
    ),
    final_checks AS (
        SELECT COUNT(*) AS final_customers,
               COUNT(*) FILTER (WHERE r.running_recorded_spending IS DISTINCT FROM l.total_recorded_spending) AS bad_spending,
               COUNT(*) FILTER (WHERE r.running_missing_amount_count IS DISTINCT FROM l.missing_amount_count) AS bad_missing,
               COUNT(*) FILTER (WHERE r.running_order_count IS DISTINCT FROM l.completed_order_count) AS bad_orders
        FROM reference_orders e JOIN order_report r USING (order_id)
        JOIN lifetime_report l ON l.customer_id=e.customer_id WHERE e.position=e.customer_orders
    ),
    rank_checks AS (
        SELECT COUNT(*) FILTER (WHERE r.customer_id IS NULL OR e.customer_id IS NULL
                   OR r.customer_total_spend_rank IS DISTINCT FROM e.expected_rank) AS mismatches
        FROM rank_report r FULL JOIN expected_ranks e USING (customer_id)
    ),
    tie_groups AS (
        SELECT e.spending,COUNT(*) AS customers,
               MIN(r.customer_total_spend_rank)=MAX(r.customer_total_spend_rank) AS equal_ranks
        FROM expected_ranks e JOIN rank_report r USING (customer_id)
        GROUP BY e.spending HAVING COUNT(*)>1
    ),
    report_summary AS (
        SELECT COUNT(*) AS rows,COUNT(DISTINCT order_id) AS distinct_orders,
               COUNT(DISTINCT customer_id) AS purchasing_customers,
               COUNT(*)-COUNT(DISTINCT order_id) AS duplicates,
               COUNT(*) FILTER (WHERE total_amount IS NULL) AS missing_amounts
        FROM order_report
    ),
    source_summary AS (
        SELECT COUNT(*) AS orders,COUNT(DISTINCT customer_id) AS customers FROM eligible_orders
    ),
    diagnostics AS (
        SELECT (SELECT COUNT(DISTINCT customer_id) FROM timestamp_groups WHERE peer_rows>1) AS customers_with_timestamp_ties,
               (SELECT COUNT(DISTINCT customer_id) FROM (
                    SELECT customer_id,order_date::date FROM eligible_orders
                    GROUP BY customer_id,order_date::date HAVING COUNT(*)>1
               ) AS days) AS customers_with_calendar_day_ties,
               COUNT(DISTINCT customer_id) FILTER (WHERE running_recorded_spending IS DISTINCT FROM
                   date_peer_recorded_spending) AS customers_with_frame_differences,
               COUNT(*) FILTER (WHERE running_recorded_spending IS DISTINCT FROM
                   date_peer_recorded_spending) AS affected_order_rows,
               COUNT(*) FILTER (WHERE running_recorded_spending IS DISTINCT FROM
                   date_peer_recorded_spending)>0 AS real_frame_difference_observed
        FROM order_report
    )
    """


def live_sql(running,lifetime,ranks,cutoff):
    return 'WITH '+context(running,lifetime,ranks,cutoff)+""",
    metrics AS (
        SELECT v.metric,v.expected,v.actual FROM report_summary r
        CROSS JOIN LATERAL (VALUES
            ('Eligible order rows',111195::bigint,r.rows),
            ('Distinct order IDs',111195,r.distinct_orders),
            ('Purchasing customers',37900,r.purchasing_customers),
            ('Duplicate order IDs',0,r.duplicates),
            ('Missing order amounts',0,r.missing_amounts),
            ('Customers included in RANK',40420,(SELECT COUNT(*) FROM rank_report))
        ) AS v(metric,expected,actual)
    ),
    checks AS (
        SELECT v.check_name,v.ok FROM coverage c CROSS JOIN detail_checks d
        CROSS JOIN final_checks f CROSS JOIN rank_checks k CROSS JOIN report_summary r
        CROSS JOIN source_summary s CROSS JOIN LATERAL (VALUES
            ('Every eligible order appears exactly once',c.missing_orders=0 AND r.duplicates=0 AND r.rows=s.orders),
            ('No ineligible order or altered source value appears',c.extra_orders=0 AND c.wrong_source_values=0),
            ('No nonexistent customer appears',NOT EXISTS (
                SELECT 1 FROM order_report o LEFT JOIN customers c USING (customer_id) WHERE c.customer_id IS NULL)),
            ('No missing date or order at/beyond cutoff appears',NOT EXISTS (
                SELECT 1 FROM order_report WHERE order_date IS NULL OR order_date>=TIMESTAMP '"""+cutoff+"""')),
            ('First known spending and missing count are correct',d.bad_first=0),
            ('Deterministic chronological positions are correct',d.bad_positions=0),
            ('Known running spending satisfies independent recurrence',d.bad_recurrence=0),
            ('Running missing count satisfies independent recurrence',d.bad_missing=0),
            ('Final spending matches Step 3.3 for every purchasing customer',f.bad_spending=0 AND f.final_customers=s.customers),
            ('Final missing counts match Step 3.3',f.bad_missing=0),
            ('Final order counts match Step 3.3',f.bad_orders=0),
            ('Previous dates match preceding eligible orders',d.bad_lag=0),
            ('Calendar-day gaps are correct',d.bad_gaps=0),
            ('First orders have NULL previous date and gap',d.bad_first_lag=0),
            ('All-customer ranks match independent spending-bucket counts',k.mismatches=0
                AND (SELECT COUNT(*)=COUNT(DISTINCT customer_id) FROM rank_report)
                AND (SELECT COUNT(*) FROM rank_report)=(SELECT COUNT(*) FROM customers)),
            ('Order-level rank joins match actual customer rank CTE',NOT EXISTS (
                SELECT 1 FROM order_report o JOIN rank_report k USING (customer_id)
                WHERE o.customer_total_spend_rank IS DISTINCT FROM k.customer_total_spend_rank)),
            ('Equal spending totals preserve equal RANK values',NOT EXISTS (
                SELECT 1 FROM tie_groups WHERE equal_ranks IS NOT TRUE)),
            ('RANGE values match independently grouped timestamp peers',d.bad_range=0),
            ('No order maps to multiple customers or positions',r.duplicates=0 AND NOT EXISTS (
                SELECT 1 FROM order_report GROUP BY customer_id,running_order_count HAVING COUNT(*)<>1))
        ) AS v(check_name,ok)
    )
    SELECT json_build_object(
        'metadata',json_build_object('database',current_database(),'user',current_user,
            'cluster_identifier',(SELECT system_identifier::text FROM pg_control_system()),
            'isolation',current_setting('transaction_isolation'),
            'read_only',current_setting('transaction_read_only'),'cutoff','"""+cutoff+"""'),
        'metrics',(SELECT json_agg(row_to_json(m)) FROM metrics m),
        'checks',(SELECT json_agg(row_to_json(c)) FROM checks c),
        'frame_diagnostics',(SELECT row_to_json(d) FROM diagnostics d),
        'spending_tie_groups',(SELECT COUNT(*) FROM tie_groups),
        'checks_ok',(SELECT bool_and(ok IS TRUE) FROM checks),
        'baseline_ok',(SELECT bool_and(expected=actual) FROM metrics)
    );
    """


def synthetic_sql(running,lifetime,ranks,cutoff):
    fixtures = """
    customers(customer_id) AS (VALUES (1),(2),(3),(4),(5),(6),(7),(8)),
    orders(order_id,customer_id,order_date,total_amount,status) AS (VALUES
        (11,1,TIMESTAMP '2020-01-01 08:00',20::numeric,'COMPLETE'),
        (10,1,TIMESTAMP '2020-01-01 08:00',10,' Completed '),
        (12,1,TIMESTAMP '2020-01-01 09:00',5,'completed'),
        (13,1,TIMESTAMP '2020-01-04',-5,'completed'),
        (20,2,TIMESTAMP '2020-01-02 23:59',30,'complete'),
        (30,3,TIMESTAMP '2020-01-01',NULL,'completed'),
        (31,3,TIMESTAMP '2020-01-02',NULL,'completed'),
        (40,4,TIMESTAMP '2020-01-01 23:59',NULL,'completed'),
        (41,4,TIMESTAMP '2020-01-02 00:01',5,'completed'),
        (60,6,TIMESTAMP '2020-01-01',0,'completed'),
        (61,6,TIMESTAMP '2020-01-02',-10,'completed'),
        (70,7,TIMESTAMP '2020-01-01',999,'pending'),
        (80,8,TIMESTAMP '2026-11-26 23:59:59.999999',40,'completed'),
        (81,8,TIMESTAMP '2026-11-27',100,'completed'),
        (82,8,TIMESTAMP '2026-11-28',100,'completed'),
        (90,1,TIMESTAMP '2020-01-01',100,'cancelled'),
        (91,1,TIMESTAMP '2020-01-01',100,NULL),
        (92,1,TIMESTAMP '2020-01-01',100,'   '),
        (97,1,NULL,100,'completed'),
        (98,NULL,TIMESTAMP '2020-01-01',100,'completed'),
        (99,999,TIMESTAMP '2020-01-01',100,'completed')
    ),
    """
    return 'WITH '+fixtures+context(running,lifetime,ranks,cutoff)+""",
    expected(order_id,spending,missing,position,previous_date,gap,rank,peer_spending) AS (VALUES
        (10,10::numeric,0::bigint,1::bigint,NULL::timestamp,NULL::integer,2::bigint,30::numeric),
        (11,30,0,2,TIMESTAMP '2020-01-01 08:00',0,2,30),
        (12,35,0,3,TIMESTAMP '2020-01-01 08:00',0,2,35),
        (13,30,0,4,TIMESTAMP '2020-01-01 09:00',3,2,30),
        (20,30,0,1,NULL,NULL,2,30),
        (30,0,1,1,NULL,NULL,5,0),
        (31,0,2,2,TIMESTAMP '2020-01-01',1,5,0),
        (40,0,1,1,NULL,NULL,4,0),
        (41,5,1,2,TIMESTAMP '2020-01-01 23:59',1,4,5),
        (60,0,0,1,NULL,NULL,8,0),
        (61,-10,0,2,TIMESTAMP '2020-01-01',1,8,-10),
        (80,40,0,1,NULL,NULL,1,40)
    ),
    actual AS (
        SELECT order_id,running_recorded_spending,running_missing_amount_count,running_order_count,
               previous_order_date,days_since_previous_order,customer_total_spend_rank,date_peer_recorded_spending
        FROM order_report
    ),
    checks AS (
        SELECT v.test_id,v.scenario,v.ok FROM (VALUES
            ('RUN-SYN-01','Multiple chronological orders retain separate running values',
                (SELECT COUNT(*)=4 AND MAX(running_order_count)=4 FROM order_report WHERE customer_id=1)),
            ('RUN-SYN-02','Different customer partitions accumulate independently',
                (SELECT running_recorded_spending=30 FROM order_report WHERE order_id=20)),
            ('RUN-SYN-03','Timestamp ties use order ID despite shuffled input',
                (SELECT running_recorded_spending=10 AND running_order_count=1 FROM order_report WHERE order_id=10)
                AND (SELECT running_recorded_spending=30 AND running_order_count=2 FROM order_report WHERE order_id=11)),
            ('RUN-SYN-04','RANGE shares a cumulative value across exact timestamp peers',
                (SELECT COUNT(*)=2 AND MIN(date_peer_recorded_spending)=30 AND MAX(date_peer_recorded_spending)=30
                 FROM order_report WHERE order_id IN (10,11))),
            ('RUN-SYN-05','Same calendar day with distinct timestamps is not one RANGE peer group',
                (SELECT date_peer_recorded_spending=35 FROM order_report WHERE order_id=12)
                AND (SELECT date_peer_recorded_spending=30 FROM order_report WHERE order_id=10)),
            ('RUN-SYN-06','Single-order customer has NULL first LAG and gap',
                (SELECT previous_order_date IS NULL AND days_since_previous_order IS NULL
                 FROM order_report WHERE order_id=20)),
            ('RUN-SYN-07','Same-day and same-timestamp gaps are zero',
                (SELECT COUNT(*)=2 AND MIN(days_since_previous_order)=0 AND MAX(days_since_previous_order)=0
                 FROM order_report WHERE order_id IN (11,12))),
            ('RUN-SYN-08','Multi-day gap is a calendar-day difference',
                (SELECT days_since_previous_order=3 FROM order_report WHERE order_id=13)),
            ('RUN-SYN-09','Two minutes across midnight gives one calendar day',
                (SELECT days_since_previous_order=1 FROM order_report WHERE order_id=41)),
            ('RUN-SYN-10','All-NULL amounts have zero known sum and increasing missing count',
                (SELECT running_recorded_spending=0 AND running_missing_amount_count=2
                 FROM order_report WHERE order_id=31)),
            ('RUN-SYN-11','Mixed known and NULL amounts retain known subtotal and missing count',
                (SELECT running_recorded_spending=5 AND running_missing_amount_count=1
                 FROM order_report WHERE order_id=41)),
            ('RUN-SYN-12','Zero and negative amounts remain and may decrease the running sum',
                (SELECT running_recorded_spending=-10 AND running_order_count=2 FROM order_report WHERE order_id=61)),
            ('RUN-SYN-13','RANK preserves spending ties and gaps',
                (SELECT COUNT(*)=2 AND MIN(customer_total_spend_rank)=2 AND MAX(customer_total_spend_rank)=2
                 FROM rank_report WHERE customer_id IN (1,2))
                AND (SELECT customer_total_spend_rank=4 FROM rank_report WHERE customer_id=4)),
            ('RUN-SYN-14','Zero-order customers affect ranks but have no order-output rows',
                (SELECT COUNT(*)=8 FROM rank_report)
                AND (SELECT COUNT(*)=0 FROM order_report WHERE customer_id IN (5,7))
                AND (SELECT customer_total_spend_rank=8 FROM rank_report WHERE customer_id=6)),
            ('RUN-SYN-15','Ineligible statuses, dates and customer references are excluded',
                (SELECT COUNT(*)=12 AND COUNT(DISTINCT order_id)=12 FROM order_report)),
            ('RUN-SYN-16','Just-before cutoff is included, exact/after cutoff excluded',
                (SELECT COUNT(*)=1 FROM order_report WHERE order_id IN (80,81,82))),
            ('RUN-SYN-17','Lifetime history older than the monthly window is retained',
                (SELECT COUNT(*)=4 FROM order_report WHERE customer_id=1)),
            ('RUN-SYN-18','Full expected running/LAG/rank/RANGE rows match',
                NOT EXISTS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
                AND NOT EXISTS (SELECT * FROM expected EXCEPT SELECT * FROM actual)),
            ('RUN-SYN-19','Synthetic ROWS/RANGE difference affects one customer and one row',
                (SELECT customers_with_frame_differences=1 AND affected_order_rows=1
                 AND real_frame_difference_observed FROM diagnostics)),
            ('RUN-SYN-20','Final known spending/missing/order counts match Step 3.3',
                (SELECT final_customers=6 AND bad_spending=0 AND bad_missing=0 AND bad_orders=0 FROM final_checks)
                AND (SELECT SUM(total_recorded_spending)=95 AND SUM(completed_order_count)=12
                     AND SUM(missing_amount_count)=3 FROM lifetime_report))
        ) AS v(test_id,scenario,ok)
    )
    SELECT json_build_object('synthetic_checks',json_agg(row_to_json(c)),
                            'checks_ok',bool_and(ok IS TRUE)) FROM checks c;
    """


def verify(log):
    running,lifetime,ranks,cutoff = load_reports()
    sql = ("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
           "SET LOCAL statement_timeout='60s';\n"+live_sql(running,lifetime,ranks,cutoff)
           +synthetic_sql(running,lifetime,ranks,cutoff)+'\nCOMMIT;\n')
    result = subprocess.run(
        ['docker','exec','-w','/lab','-i','kloudkart','psql','-U','postgres','-d','postgres',
         '-X','-qAt','-v','ON_ERROR_STOP=1','-P','pager=off','-f','-'],
        input=sql,text=True,capture_output=True,timeout=120)
    if result.returncode != 0:
        raise RuntimeError('Running-total SQL failed; server details withheld to protect client data')
    payloads = [json.loads(line,parse_float=Decimal) for line in result.stdout.splitlines() if line.strip()]
    if len(payloads) != 2:
        raise RuntimeError('Expected live and synthetic aggregate result sets')
    live,synthetic = payloads
    metadata = live['metadata']
    log('Connection: '+json.dumps(metadata))
    log('Prior cutoff, eligibility and customer-total CTE consistency: PASS')
    for row in live['metrics']:
        log(f"{row['metric']}: expected={row['expected']} actual={row['actual']} "
            +('PASS' if row['expected']==row['actual'] else 'FAIL'))
    log('ROWS/RANGE aggregate diagnostics: '+json.dumps(live['frame_diagnostics']))
    log('All-customer spending tie groups: '+str(live['spending_tie_groups']))
    for row in live['checks']:
        log(row['check_name']+': '+('PASS' if row['ok'] is True else 'FAIL'))
    for row in synthetic['synthetic_checks']:
        log(row['test_id']+': '+('PASS' if row['ok'] is True else 'FAIL')+'; '+row['scenario'])
    target_ok = metadata['database']=='postgres' and metadata['user']=='postgres' \
        and metadata['isolation']=='repeatable read' and metadata['read_only']=='on'
    if not (target_ok and live['checks_ok'] is True and live['baseline_ok'] is True
            and synthetic['checks_ok'] is True):
        raise RuntimeError('Running-total assertions failed; review aggregate evidence')
    log('Overall running-total validation: PASS')
    log('Read-only transaction completed; VALUES fixtures created no records or database objects.')


if __name__ == '__main__':
    path = ROOT/'tests'/'results'/('phase3_running_totals_'+uuid.uuid4().hex[:12]+'.txt')
    with path.open('x',encoding='utf-8') as evidence:
        def log(message):
            print(message,flush=True)
            evidence.write(message+'\n')
            evidence.flush()
        try:
            verify(log)
        except Exception as error:
            log('FAIL: '+(str(error) if isinstance(error,(RuntimeError,ValueError)) else type(error).__name__))
            raise SystemExit(1)
    print('Execution evidence: '+str(path.relative_to(ROOT)),flush=True)
