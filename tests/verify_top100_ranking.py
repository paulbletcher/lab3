"""Aggregate-only Step 3.6 comparison using the actual reusable SQL.

Run: python tests/verify_top100_ranking.py
Standard library + Docker psql only. Live analysis, independent references and
VALUES fixtures share one read-only REPEATABLE READ transaction. No objects or
records are created; customer-level results never leave PostgreSQL.
"""

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid


ROOT = Path(__file__).resolve().parents[1]


def load_reports():
    names = ('top_100_ranking_analysis.sql', 'customer_spending.sql',
             'running_customer_totals.sql', 'monthly_spending.sql')
    analysis, lifetime, running, monthly = [
        (ROOT / name).read_text(encoding='utf-8').strip().removesuffix(';')
        for name in names
    ]
    base = (ROOT / 'report_base.sql').read_text(encoding='utf-8')
    cutoffs = [re.search(r"SELECT TIMESTAMP '([^']+)' AS cutoff", s).group(1)
               for s in (analysis, lifetime, running, monthly)]
    cutoffs.append(re.search(r"\\set reporting_cutoff '([^']+)'", base).group(1))
    if set(cutoffs) != {'2026-11-27 00:00:00'}:
        raise ValueError('Ranking/prior reporting cutoffs differ from the agreed cutoff')
    for cte, sources in (
        ('report_base', (analysis, lifetime, running, monthly, base)),
        ('customer_spending', (analysis, lifetime, running)),
    ):
        definitions = [' '.join(re.search(cte + r' AS \((.*?)\n\)', s, re.S)
                               .group(1).split()) for s in sources]
        if len(set(definitions)) != 1:
            raise ValueError(cte + ' differs from prior reporting logic')
    # Extract the actual ranking CTE, never a separately reimplemented window.
    marker = '\nspending_groups AS ('
    if analysis.count(marker) != 1:
        raise ValueError('Cannot locate the reusable customer_rankings CTE')
    rankings = analysis.split(marker, 1)[0].rstrip().removesuffix(',')
    rankings += '\nSELECT * FROM customer_rankings'
    return analysis, rankings, lifetime, cutoffs[0]


def context(analysis, rankings, lifetime, cutoff):
    return f"""
    analysis_report AS ({analysis}),
    ranking_report AS ({rankings}),
    lifetime_report AS ({lifetime}),
    source_grouped AS (
        -- Aggregate source orders first, independently of the reusable left join.
        SELECT o.customer_id, COALESCE(SUM(o.total_amount), 0) AS spending,
               COUNT(*) AS orders,
               COUNT(*) FILTER (WHERE o.total_amount IS NULL) AS missing
        FROM orders o
        WHERE LOWER(TRIM(o.status)) IN ('complete', 'completed')
          AND o.order_date < TIMESTAMP '{cutoff}'
          AND EXISTS (SELECT 1 FROM customers c WHERE c.customer_id = o.customer_id)
        GROUP BY o.customer_id
    ),
    reference_totals AS (
        SELECT c.customer_id, COALESCE(s.spending, 0) AS spending,
               COALESCE(s.orders, 0) AS orders, COALESCE(s.missing, 0) AS missing
        FROM customers c LEFT JOIN source_grouped s USING (customer_id)
    ),
    buckets AS (
        SELECT spending, COUNT(*) AS customers,
               ARRAY_AGG(customer_id ORDER BY customer_id) AS ordered_ids
        FROM reference_totals GROUP BY spending
    ),
    bucket_offsets AS (
        -- Counting higher-spending customers/levels needs no ranking functions.
        SELECT *, COALESCE(SUM(customers) OVER preceding_levels, 0) AS higher_customers,
               COUNT(*) OVER preceding_levels AS higher_levels
        FROM buckets
        WINDOW preceding_levels AS (
            ORDER BY spending DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        )
    ),
    reference_rankings AS (
        SELECT t.*, b.higher_customers + ARRAY_POSITION(b.ordered_ids, t.customer_id) AS expected_position,
               b.higher_customers + 1 AS expected_rank,
               b.higher_levels + 1 AS expected_dense_rank
        FROM reference_totals t JOIN bucket_offsets b USING (spending)
    ),
    reference_boundary AS (
        SELECT * FROM bucket_offsets
        WHERE higher_customers < 100 AND higher_customers + customers >= 100
    ),
    reference_analysis AS (
        -- Independent bucket arithmetic verifies every field of the full SQL output.
        SELECT COUNT(*) AS customer_rows, COUNT(DISTINCT customer_id) AS distinct_customer_ids,
               COUNT(*) FILTER (WHERE orders > 0) AS customers_with_eligible_orders,
               COUNT(*) FILTER (WHERE orders = 0) AS customers_without_eligible_orders,
               COALESCE(SUM(missing), 0) AS missing_eligible_order_amounts,
               LEAST(100, COUNT(*)) AS row_number_top100_customers,
               (SELECT COALESCE(SUM(customers), 0) FROM bucket_offsets
                WHERE higher_customers < 100) AS rank_top100_customers,
               (SELECT COALESCE(SUM(customers), 0) FROM bucket_offsets
                WHERE higher_levels < 100) AS dense_rank_top100_customers,
               (SELECT COUNT(*) FROM bucket_offsets WHERE higher_customers < 100)
                   AS row_number_top100_distinct_spending_values,
               (SELECT COUNT(*) FROM buckets WHERE customers > 1) AS population_spending_tie_groups,
               (SELECT COALESCE(SUM(LEAST(customers, GREATEST(100 - higher_customers, 0))), 0)
                FROM bucket_offsets WHERE customers > 1) AS top100_customers_in_population_ties,
               (SELECT COALESCE(SUM(LEAST(customers, GREATEST(100 - higher_customers, 0))), 0)
                FROM bucket_offsets WHERE LEAST(customers, GREATEST(100 - higher_customers, 0)) > 1)
                   AS top100_customers_in_internal_ties,
               (SELECT spending FROM reference_boundary) AS boundary_recorded_spending,
               (SELECT higher_customers + 1 FROM reference_boundary) AS boundary_rank,
               (SELECT higher_levels + 1 FROM reference_boundary) AS boundary_dense_rank,
               COALESCE((SELECT customers FROM reference_boundary), 0) AS boundary_customers,
               COALESCE((SELECT 100 - higher_customers FROM reference_boundary), 0)
                   AS boundary_included_row_number,
               COALESCE((SELECT customers FROM reference_boundary), 0) AS boundary_included_rank,
               COALESCE((SELECT customers FROM reference_boundary), 0) AS boundary_included_dense_rank,
               EXISTS (SELECT 1 FROM reference_boundary WHERE higher_customers + customers > 100)
                   AS tie_crosses_100th_boundary
        FROM reference_totals
    ),
    coverage AS (
        SELECT COUNT(*) FILTER (WHERE r.customer_id IS NULL) AS missing_customers,
               COUNT(*) FILTER (WHERE e.customer_id IS NULL) AS nonexistent_customers,
               COUNT(*) FILTER (WHERE r.total_recorded_spending IS DISTINCT FROM e.spending
                   OR r.completed_order_count IS DISTINCT FROM e.orders
                   OR r.missing_amount_count IS DISTINCT FROM e.missing) AS total_mismatches,
               COUNT(*) FILTER (WHERE r.row_number_position IS DISTINCT FROM e.expected_position)
                   AS position_mismatches,
               COUNT(*) FILTER (WHERE r.spending_rank IS DISTINCT FROM e.expected_rank) AS rank_mismatches,
               COUNT(*) FILTER (WHERE r.spending_dense_rank IS DISTINCT FROM e.expected_dense_rank)
                   AS dense_mismatches
        FROM ranking_report r FULL JOIN reference_rankings e USING (customer_id)
    ),
    rank_groups AS (
        SELECT total_recorded_spending, COUNT(*) AS customers,
               MIN(spending_rank) AS min_rank, MAX(spending_rank) AS max_rank,
               MIN(spending_dense_rank) AS min_dense, MAX(spending_dense_rank) AS max_dense
        FROM ranking_report GROUP BY total_recorded_spending
    ),
    group_transitions AS (
        SELECT *, LAG(min_rank) OVER descending_spending AS previous_rank,
               LAG(customers) OVER descending_spending AS previous_customers,
               LAG(min_dense) OVER descending_spending AS previous_dense
        FROM rank_groups
        WINDOW descending_spending AS (ORDER BY total_recorded_spending DESC)
    ),
    checks AS (
        SELECT v.check_name, v.ok FROM coverage c
        CROSS JOIN analysis_report a CROSS JOIN reference_analysis e
        CROSS JOIN LATERAL (VALUES
            ('Every existing customer appears exactly once', c.missing_customers = 0
                AND a.customer_rows = (SELECT COUNT(*) FROM customers)
                AND a.distinct_customer_ids = a.customer_rows),
            ('No nonexistent customer appears', c.nonexistent_customers = 0),
            ('All customer spending/order/missing totals match independent source aggregation',
                c.total_mismatches = 0),
            ('Every customer has exactly one non-NULL value for each ranking method',
                NOT EXISTS (SELECT 1 FROM ranking_report GROUP BY customer_id
                    HAVING COUNT(*) <> 1 OR COUNT(row_number_position) <> 1
                        OR COUNT(spending_rank) <> 1 OR COUNT(spending_dense_rank) <> 1)),
            ('ROW_NUMBER values are unique and sequential from one',
                (SELECT COUNT(DISTINCT row_number_position) = COUNT(*)
                    AND COALESCE(MIN(row_number_position), 1) = 1
                    AND COALESCE(MAX(row_number_position), 0) = COUNT(*) FROM ranking_report)),
            ('ROW_NUMBER top 100 returns min(100, population)',
                a.row_number_top100_customers = LEAST(100, a.customer_rows)),
            ('ROW_NUMBER uses spending then ascending customer ID deterministically',
                c.position_mismatches = 0),
            ('Equal spending receives equal RANK values',
                NOT EXISTS (SELECT 1 FROM rank_groups WHERE min_rank <> max_rank)),
            ('Equal spending receives equal DENSE_RANK values',
                NOT EXISTS (SELECT 1 FROM rank_groups WHERE min_dense <> max_dense)),
            ('RANK starts at one and skips exactly the preceding tie size',
                NOT EXISTS (SELECT 1 FROM group_transitions
                    WHERE min_rank <> COALESCE(previous_rank + previous_customers, 1))),
            ('DENSE_RANK starts at one and increments once per spending level',
                NOT EXISTS (SELECT 1 FROM group_transitions
                    WHERE min_dense <> COALESCE(previous_dense + 1, 1))),
            ('RANK matches independently counted higher-spending customers', c.rank_mismatches = 0),
            ('DENSE_RANK matches independently counted higher spending levels', c.dense_mismatches = 0),
            ('Spending ties are not broken by customer ID or order count',
                NOT EXISTS (SELECT 1 FROM rank_groups WHERE customers > 1
                    AND (min_rank <> max_rank OR min_dense <> max_dense))),
            ('Rankings match the independent spending reference for every customer',
                c.missing_customers = 0 AND c.nonexistent_customers = 0 AND c.total_mismatches = 0
                AND c.position_mismatches = 0 AND c.rank_mismatches = 0 AND c.dense_mismatches = 0),
            ('Reusable customer totals match unchanged Step 3.3 query',
                NOT EXISTS (SELECT customer_id, total_recorded_spending, completed_order_count,
                    missing_amount_count FROM ranking_report EXCEPT SELECT * FROM lifetime_report)
                AND NOT EXISTS (SELECT * FROM lifetime_report EXCEPT SELECT customer_id,
                    total_recorded_spending, completed_order_count, missing_amount_count FROM ranking_report)),
            ('Zero-order customers retain zero spending and missing count',
                NOT EXISTS (SELECT 1 FROM ranking_report WHERE completed_order_count = 0
                    AND (total_recorded_spending <> 0 OR missing_amount_count <> 0))),
            ('All aggregate analysis fields match independent bucket arithmetic',
                TO_JSONB(a) = TO_JSONB(e)),
            ('All three candidate counts match independent bucket thresholds',
                a.row_number_top100_customers = e.row_number_top100_customers
                AND a.rank_top100_customers = e.rank_top100_customers
                AND a.dense_rank_top100_customers = e.dense_rank_top100_customers),
            ('Boundary amount/ranks/counts match the independent qualifying bucket',
                a.boundary_recorded_spending IS NOT DISTINCT FROM e.boundary_recorded_spending
                AND a.boundary_rank IS NOT DISTINCT FROM e.boundary_rank
                AND a.boundary_dense_rank IS NOT DISTINCT FROM e.boundary_dense_rank
                AND a.boundary_customers = e.boundary_customers
                AND a.boundary_included_row_number = e.boundary_included_row_number
                AND a.boundary_included_rank = e.boundary_included_rank
                AND a.boundary_included_dense_rank = e.boundary_included_dense_rank
                AND a.tie_crosses_100th_boundary = e.tie_crosses_100th_boundary),
            ('Boundary tie counts reconcile with all three top-100 candidate counts',
                a.rank_top100_customers = a.row_number_top100_customers
                    + a.boundary_customers - a.boundary_included_row_number
                AND a.boundary_included_rank = a.boundary_customers
                AND a.boundary_included_dense_rank = a.boundary_customers
                AND a.dense_rank_top100_customers - a.rank_top100_customers =
                    (SELECT COUNT(*) FROM reference_rankings
                     WHERE expected_dense_rank <= 100 AND expected_rank > 100))
        ) AS v(check_name, ok)
    )
    """


def live_sql(analysis, rankings, lifetime, cutoff):
    return 'WITH ' + context(analysis, rankings, lifetime, cutoff) + """,
    baselines AS (
        SELECT v.metric, v.expected, v.actual FROM analysis_report a
        CROSS JOIN LATERAL (VALUES
            ('Total customer rows', 40420::bigint, a.customer_rows),
            ('Distinct customer IDs', 40420, a.distinct_customer_ids),
            ('Customers with eligible orders', 37900, a.customers_with_eligible_orders),
            ('Customers without eligible orders', 2520, a.customers_without_eligible_orders),
            ('ROW_NUMBER top-100 rows', 100, a.row_number_top100_customers)
        ) AS v(metric, expected, actual)
    )
    SELECT json_build_object(
        'metadata', json_build_object('database', current_database(), 'user', current_user,
            'cluster_identifier', (SELECT system_identifier::text FROM pg_control_system()),
            'server_version', current_setting('server_version'),
            'isolation', current_setting('transaction_isolation'),
            'read_only', current_setting('transaction_read_only'),
            'snapshot', pg_current_snapshot()::text, 'cutoff', '""" + cutoff + """'),
        'analysis', (SELECT row_to_json(a) FROM analysis_report a),
        'baselines', (SELECT json_agg(row_to_json(b)) FROM baselines b),
        'checks', (SELECT json_agg(row_to_json(c)) FROM checks c),
        'checks_ok', (SELECT bool_and(ok IS TRUE) FROM checks),
        'baselines_ok', (SELECT bool_and(expected = actual) FROM baselines)
    );
    """


def fixtures():
    """Explicit synthetic expectations; never computed using a ranking function.

    Expected rows: ID, spending, order count, missing count, ROW_NUMBER, RANK,
    DENSE_RANK. Larger VALUES lists follow simple, stated fixture constructions.
    """
    distinct_small = [(i, 60 - 10*i, 1, 0, i, i, i) for i in range(1, 6)]
    distinct_large = [(i, 1000-i, 1, 0, i, i, i) for i in range(1, 106)]
    internal = [(i, 1000 if i <= 2 else 1000-i, 1, 0,
                 i, 1 if i <= 2 else i, 1 if i <= 2 else i-1) for i in range(1, 106)]
    crossing = [(i, 1000-i if i <= 98 else 900 if i <= 102 else 800-100*(i-103),
                 1, 0, i, i if i <= 98 else 99 if i <= 102 else i,
                 i if i <= 98 else 99 if i <= 102 else i-3) for i in range(1, 106)]
    all_tied = [(i, 100, 1, 0, i, 1, 1) for i in range(1, 103)]
    edge = [(1, 30, 2, 0, 2, 2, 2), (2, 30, 1, 0, 3, 2, 2),
            (3, 0, 1, 0, 4, 4, 3), (4, -10, 2, 0, 8, 8, 4),
            (5, 0, 0, 0, 5, 4, 3), (6, 0, 1, 1, 6, 4, 3),
            (7, 0, 0, 0, 7, 4, 3), (8, 40, 1, 0, 1, 1, 1)]
    edge_orders = [
        (11, 1, '2020-01-01', 20, ' Completed '),
        (12, 1, '2020-01-02', 10, 'COMPLETE'),
        (21, 2, '2020-01-01', 30, 'completed'),
        (31, 3, '2020-01-01', 0, 'complete'),
        (41, 4, '2020-01-01', 0, 'completed'),
        (42, 4, '2020-01-02', -10, 'completed'),
        (61, 6, '2020-01-01', None, 'completed'),
        (71, 7, '2020-01-01', 999, 'pending'),
        (81, 8, '2026-11-26 23:59:59.999999', 40, 'completed'),
        (82, 8, '2026-11-27 00:00:00', 999, 'completed'),
        (83, 8, '2026-11-28', 999, 'completed'),
        (84, 8, None, 999, 'completed'),
        (85, 8, '2020-01-01', 999, 'cancelled'),
        (86, 8, '2020-01-01', 999, None),
        (87, 8, '2020-01-01', 999, '   '),
        (91, 999, '2020-01-01', 999, 'completed'),
        (92, None, '2020-01-01', 999, 'completed'),
    ]
    # Each tuple: name, full expected rows, explicit expected candidate counts,
    # boundary amount/size/included ROW_NUMBER/RANK/DENSE_RANK/ranks/crossing,
    # and optional order fixtures. Reverse inputs to challenge deterministic ties.
    return [
        ('distinct_small', distinct_small, (5, 5, 5), None, None),
        ('distinct_large', distinct_large, (100, 100, 100),
         (900, 1, 1, 1, 1, 100, 100, False), None),
        ('internal_top_tie', internal, (100, 100, 101),
         (900, 1, 1, 1, 1, 100, 99, False), None),
        ('crossing_boundary_tie', crossing, (100, 102, 103),
         (900, 4, 2, 4, 4, 99, 99, True), None),
        ('all_tied_over100', all_tied, (100, 102, 102),
         (100, 102, 100, 102, 102, 1, 1, True), None),
        ('eligibility_zero_negative', edge, (8, 8, 8), None, edge_orders),
        ('empty_population', [], (0, 0, 0), None, []),
    ]


def sql_literal(value):
    if value is None:
        return 'NULL'
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)


def synthetic_sql(analysis, rankings, lifetime, cutoff, fixture):
    name, expected, candidate_counts, boundary, orders = fixture
    if orders is None:
        orders = [(i, i, '2020-01-01', spending, 'completed')
                  for i, spending, *_ in expected]
    customer_values = ','.join(f'({row[0]})' for row in reversed(expected))
    customers = ('VALUES ' + customer_values if expected else
                 'SELECT NULL::integer WHERE FALSE')
    order_values = ','.join('(' + ','.join(sql_literal(v) +
                          ('::timestamp' if index == 2 else '::numeric' if index == 3 else '')
                          for index, v in enumerate(row)) + ')' for row in reversed(orders))
    source_orders = ('VALUES ' + order_values if orders else
                     'SELECT NULL::integer,NULL::integer,NULL::timestamp,NULL::numeric,NULL::text WHERE FALSE')
    expected_values = ','.join('(' + ','.join(map(str, row)) + ')' for row in expected)
    expected_rows = ('VALUES ' + expected_values if expected else
                     'SELECT NULL::integer,NULL::numeric,NULL::bigint,NULL::bigint,'
                     'NULL::bigint,NULL::bigint,NULL::bigint WHERE FALSE')
    prefix = f"""customers(customer_id) AS ({customers}),
        orders(order_id, customer_id, order_date, total_amount, status) AS ({source_orders}),
        expected(customer_id, spending, orders, missing, position, rank, dense_rank) AS ({expected_rows}),
    """
    if boundary is None:
        boundary_check = """a.boundary_recorded_spending IS NULL AND a.boundary_rank IS NULL
            AND a.boundary_dense_rank IS NULL AND a.boundary_customers = 0
            AND a.boundary_included_row_number = 0 AND a.boundary_included_rank = 0
            AND a.boundary_included_dense_rank = 0 AND NOT a.tie_crosses_100th_boundary"""
    else:
        amount, size, rn, rank, dense, br, bd, crosses = boundary
        boundary_check = f"""a.boundary_recorded_spending = {amount} AND a.boundary_customers = {size}
            AND a.boundary_included_row_number = {rn} AND a.boundary_included_rank = {rank}
            AND a.boundary_included_dense_rank = {dense} AND a.boundary_rank = {br}
            AND a.boundary_dense_rank = {bd} AND a.tie_crosses_100th_boundary = {str(crosses).upper()}"""
    rn, rank, dense = candidate_counts
    return 'WITH ' + prefix + context(analysis, rankings, lifetime, cutoff) + f""",
    actual AS (
        SELECT customer_id, total_recorded_spending, completed_order_count, missing_amount_count,
               row_number_position, spending_rank, spending_dense_rank FROM ranking_report
    ),
    fixture_checks AS (
        SELECT v.check_name, v.ok FROM analysis_report a CROSS JOIN LATERAL (VALUES
            ('Exact expected customer totals and all ranking values',
                NOT EXISTS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
                AND NOT EXISTS (SELECT * FROM expected EXCEPT SELECT * FROM actual)
                AND (SELECT COUNT(*) FROM actual) = (SELECT COUNT(*) FROM expected)),
            ('Exact expected counts for all three top-100 methods',
                a.row_number_top100_customers = {rn} AND a.rank_top100_customers = {rank}
                AND a.dense_rank_top100_customers = {dense}),
            ('Exact expected 100th-position boundary findings', {boundary_check})
        ) AS v(check_name, ok)
    )
    SELECT json_build_object('fixture', '{name}',
        'snapshot', pg_current_snapshot()::text,
        'candidate_counts', json_build_array(a.row_number_top100_customers,
            a.rank_top100_customers, a.dense_rank_top100_customers),
        'expected_candidate_counts', json_build_array({rn}, {rank}, {dense}),
        'checks', (SELECT json_agg(row_to_json(c)) FROM (
            SELECT * FROM checks UNION ALL SELECT * FROM fixture_checks) c),
        'checks_ok', (SELECT bool_and(ok IS TRUE) FROM (
            SELECT * FROM checks UNION ALL SELECT * FROM fixture_checks) c)
    ) FROM analysis_report a;
    """


def verify(log):
    analysis, rankings, lifetime, cutoff = load_reports()
    cases = fixtures()
    sql = ('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;\n'
           "SET LOCAL statement_timeout = '60s';\n"
           + live_sql(analysis, rankings, lifetime, cutoff)
           + ''.join(synthetic_sql(analysis, rankings, lifetime, cutoff, case) for case in cases)
           + '\nCOMMIT;\n')
    log('Execution UTC: ' + datetime.now(timezone.utc).isoformat())
    for name in ('top_100_ranking_analysis.sql', 'customer_spending.sql'):
        log(name + ' SHA-256: ' + hashlib.sha256((ROOT / name).read_bytes()).hexdigest())
    result = subprocess.run(
        ['docker', 'exec', '-w', '/lab', '-i', 'kloudkart', 'psql', '-U', 'postgres', '-d', 'postgres',
         '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-P', 'pager=off', '-f', '-'],
        input=sql, text=True, capture_output=True, timeout=180)
    if result.returncode != 0:
        raise RuntimeError('Ranking SQL failed; server output withheld to protect source data')
    payloads = [json.loads(line, parse_float=Decimal) for line in result.stdout.splitlines() if line.strip()]
    if len(payloads) != 1 + len(cases):
        raise RuntimeError('Expected one live aggregate and all synthetic fixture result sets')
    live, *synthetic = payloads
    metadata = live['metadata']
    log('Connection: ' + json.dumps(metadata))
    log('Prior cutoff, eligibility and customer-spending CTE consistency: PASS')
    for key, value in live['analysis'].items():
        log(key + ': ' + str(value))
    for row in live['baselines']:
        log(f"{row['metric']}: expected={row['expected']} actual={row['actual']} "
            + ('PASS' if row['expected'] == row['actual'] else 'FAIL'))
    for row in live['checks']:
        log('LIVE: ' + row['check_name'] + ': ' + ('PASS' if row['ok'] is True else 'FAIL'))
    for case in synthetic:
        log('SYNTHETIC ' + case['fixture'] + ': expected ROW_NUMBER/RANK/DENSE_RANK='
            + str(case['expected_candidate_counts']) + '; actual=' + str(case['candidate_counts']))
        for row in case['checks']:
            log('  ' + row['check_name'] + ': ' + ('PASS' if row['ok'] is True else 'FAIL'))
    target_ok = (metadata['database'] == 'postgres' and metadata['user'] == 'postgres'
                 and metadata['cluster_identifier'] == '7712053334814294059'
                 and metadata['isolation'] == 'repeatable read' and metadata['read_only'] == 'on')
    snapshot_ok = all(case['snapshot'] == metadata['snapshot'] for case in synthetic)
    log('Target database/user/cluster and read-only REPEATABLE READ: ' + ('PASS' if target_ok else 'FAIL'))
    log('Live analysis and all fixtures used the same snapshot: ' + ('PASS' if snapshot_ok else 'FAIL'))
    live_count = len(live['checks'])
    synthetic_count = sum(len(case['checks']) for case in synthetic)
    log(f'Assertion totals: live={live_count}; baselines={len(live["baselines"])}; '
        f'synthetic={synthetic_count} across {len(synthetic)} fixtures')
    if not (target_ok and snapshot_ok and live['checks_ok'] is True and live['baselines_ok'] is True
            and all(case['checks_ok'] is True for case in synthetic)):
        raise RuntimeError('Top-100 ranking assertions failed; review aggregate evidence')
    log('Overall top-100 ranking comparison validation: PASS')
    log('Read-only transaction completed; VALUES fixtures created no records or database objects.')
    log('Comparison only; final ranking policy and combined report remain unselected.')


if __name__ == '__main__':
    path = ROOT / 'tests' / 'results' / ('phase3_top100_ranking_comparison_' + uuid.uuid4().hex[:12] + '.txt')
    with path.open('x', encoding='utf-8') as evidence:
        def log(message):
            print(message, flush=True)
            evidence.write(message + '\n')
            evidence.flush()
        try:
            verify(log)
        except Exception as error:
            log('FAIL: ' + (str(error) if isinstance(error, (RuntimeError, ValueError))
                            else type(error).__name__))
            raise SystemExit(1)
    print('Execution evidence: ' + str(path.relative_to(ROOT)), flush=True)
