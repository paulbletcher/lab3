"""Verify the four actual Step 3.7 SELECTs without exporting client records.

Run: python tests/verify_monday_spending_report.py
Requires psycopg2-binary and the existing kloudkart container. All live, legacy
and VALUES-only comparisons use one read-only REPEATABLE READ transaction.
DATABASE_URL may be supplied; otherwise local Docker connection settings are
read privately. Credentials, driver error details and report rows are not logged.
"""

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

import psycopg2
from psycopg2.extras import register_default_json


ROOT = Path(__file__).resolve().parents[1]
COLUMNS = (
    ('customer_id', 'total_recorded_spending', 'completed_order_count',
     'missing_amount_count', 'customer_total_spend_rank'),
    ('customer_id', 'total_recorded_spending', 'completed_order_count', 'customer_total_spend_rank'),
    ('customer_id', 'spending_month', 'monthly_recorded_spending',
     'completed_order_count', 'missing_amount_count'),
    ('customer_id', 'order_id', 'order_date', 'total_amount', 'running_recorded_spending',
     'running_missing_amount_count', 'running_order_count', 'previous_order_date',
     'days_since_previous_order'),
)


def cte(query, name):
    match = re.search(name + r' AS \((.*?)\n\)', query, re.S)
    if not match:
        raise ValueError('Required reporting CTE missing: ' + name)
    return ' '.join(match.group(1).split())


def load_reports():
    script = (ROOT / 'monday_spending_report.sql').read_text(encoding='utf-8')
    definitions = re.findall(r"(?m)^\\set reporting_cutoff '([^']+)'$", script)
    if definitions != ['2026-11-27 00:00:00']:
        raise ValueError('Expected one agreed reporting cutoff definition')
    cutoff = definitions[0]
    parts = re.split(r'(?m)^-- Result set ([1-4]): [^\n]+\n', script)
    if len(parts) != 9 or parts[1::2] != ['1', '2', '3', '4']:
        raise ValueError('Expected exactly four labeled result sets')
    header = '\n'.join(line for line in parts[0].splitlines()
                       if line.strip() and not line.startswith('--'))
    expected_header = ("\\set ON_ERROR_STOP on\n\\pset null '[NULL]'\n"
                       f"\\set reporting_cutoff '{cutoff}'\n"
                       "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
                       "SET LOCAL statement_timeout = '60s';")
    if header != expected_header or not parts[-1].rstrip().endswith('\nCOMMIT;'):
        raise ValueError('Reporting error handling/transaction/timeout controls differ')
    raw = parts[2::2]
    raw[-1] = raw[-1].rstrip().removesuffix('\nCOMMIT;')
    queries = []
    for query in raw:
        query = query.strip()
        statements = re.sub(r'(?m)^\s*--[^\n]*', '', query)
        if statements.count(';') != 1 or not query.endswith(';') or not query.startswith('WITH '):
            raise ValueError('Each result set must be one reusable SELECT statement')
        query = query.removesuffix(';')
        if query.count(":'reporting_cutoff'") != 1:
            raise ValueError('Each result set must use the shared cutoff once')
        if cte(query, 'report_parameters') != "SELECT TIMESTAMP :'reporting_cutoff' AS cutoff":
            raise ValueError('A result set has a different cutoff rule')
        queries.append(query.replace(":'reporting_cutoff'", '%(reporting_cutoff)s'))

    names = ('customer_spending.sql', 'monthly_spending.sql',
             'running_customer_totals.sql', 'top_100_ranking_analysis.sql')
    lifetime, monthly, running, ranking = [
        (ROOT / name).read_text(encoding='utf-8').strip().removesuffix(';') for name in names
    ]
    base = (ROOT / 'report_base.sql').read_text(encoding='utf-8')
    if re.search(r"\\set reporting_cutoff '([^']+)'", base).group(1) != cutoff:
        raise ValueError('Original report-base cutoff differs')
    for prior in (lifetime, monthly, running, ranking):
        if re.search(r"SELECT TIMESTAMP '([^']+)' AS cutoff", prior).group(1) != cutoff:
            raise ValueError('Prior report cutoff differs')
    if len({cte(q, 'report_base') for q in (*queries, lifetime, monthly, running, ranking, base)}) != 1:
        raise ValueError('Eligibility differs between report components')
    if len({cte(q, 'customer_spending') for q in (*queries[:2], lifetime, running, ranking)}) != 1:
        raise ValueError('Customer aggregation differs from prior reports')
    for name in ('month_anchor', 'report_window', 'reporting_months', 'windowed_orders',
                 'monthly_totals', 'customer_month_grid'):
        if cte(queries[2], name) != cte(monthly, name):
            raise ValueError('Monthly CTE differs from Step 3.4: ' + name)
    if cte(queries[3], 'order_windows') != cte(running, 'order_windows'):
        raise ValueError('Running windows differ from Step 3.5')
    if cte(queries[0], 'ranked_customers') != cte(queries[1], 'ranked_customers'):
        raise ValueError('Summary and top-100 ranking populations differ')
    for query in queries[:2]:
        if re.findall(r'(?<![A-Z_])RANK\(\) OVER \((.*?)\)', query, re.S) != [
                '\n               ORDER BY total_recorded_spending DESC\n           ']:
            raise ValueError('Expected spending-only RANK ordering')
    rank_query = ranking.split('\nspending_groups AS (', 1)[0].rstrip().removesuffix(',')
    rank_query += '\nSELECT * FROM customer_rankings'
    legacy = (lifetime, monthly, running, rank_query)
    # psycopg2 binds the same named cutoff in every actual and prior query.
    legacy = tuple(q.replace(f"TIMESTAMP '{cutoff}'", 'TIMESTAMP %(reporting_cutoff)s') for q in legacy)
    return queries, legacy, cutoff


def connect():
    inspected = subprocess.run(['docker', 'inspect', 'kloudkart'], text=True,
                               capture_output=True, timeout=20)
    if inspected.returncode:
        raise RuntimeError('The existing kloudkart container is unavailable')
    config = json.loads(inspected.stdout)[0]
    if not config['State']['Running']:
        raise RuntimeError('The existing kloudkart container must be running')
    mounts = [m for m in config['Mounts'] if m['Destination'] == '/lab']
    if len(mounts) != 1 or Path(mounts[0]['Source']).resolve() != ROOT.resolve():
        raise RuntimeError('The /lab mount does not identify this project')
    if os.environ.get('DATABASE_URL'):
        return psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=15,
                                application_name='verify_monday_spending_report')
    env = dict(item.split('=', 1) for item in config['Config']['Env'] if '=' in item)
    bindings = config['NetworkSettings']['Ports'].get('5432/tcp') or []
    if not bindings:
        raise RuntimeError('Set DATABASE_URL for a connection to the existing lab')
    return psycopg2.connect(host='127.0.0.1', port=bindings[0]['HostPort'],
                            dbname='postgres', user='postgres', password=env.get('POSTGRES_PASSWORD'),
                            connect_timeout=15, application_name='verify_monday_spending_report')


def context(queries, legacy):
    summary, top, monthly, running = queries
    old_lifetime, old_monthly, old_running, old_ranks = legacy
    return f"""
    summary_report AS ({summary}), top_report AS ({top}),
    monthly_report AS ({monthly}), running_report AS ({running}),
    prior_lifetime AS ({old_lifetime}), prior_monthly AS ({old_monthly}),
    prior_running AS ({old_running}), prior_ranks AS ({old_ranks}),
    parameters AS (SELECT TIMESTAMP %(reporting_cutoff)s AS cutoff),
    bounds AS (
        SELECT cutoff, CASE WHEN cutoff = DATE_TRUNC('month', cutoff)
               THEN DATE_TRUNC('month', cutoff) - INTERVAL '1 month'
               ELSE DATE_TRUNC('month', cutoff) END AS last_month FROM parameters
    ),
    months AS (
        SELECT (b.last_month - n * INTERVAL '1 month')::date AS spending_month
        FROM bounds b CROSS JOIN GENERATE_SERIES(0, 11) n
    ),
    eligible AS (
        SELECT o.order_id, o.customer_id, o.order_date, o.total_amount
        FROM orders o CROSS JOIN parameters p
        WHERE LOWER(TRIM(o.status)) IN ('complete', 'completed') AND o.order_date < p.cutoff
          AND EXISTS (SELECT 1 FROM customers c WHERE c.customer_id = o.customer_id)
    ),
    grouped_orders AS (
        SELECT customer_id, COALESCE(SUM(total_amount), 0) AS spending, COUNT(*) AS orders,
               COUNT(*) FILTER (WHERE total_amount IS NULL) AS missing
        FROM eligible GROUP BY customer_id
    ),
    customer_reference AS (
        SELECT c.customer_id, COALESCE(g.spending, 0) AS spending,
               COALESCE(g.orders, 0) AS orders, COALESCE(g.missing, 0) AS missing
        FROM customers c LEFT JOIN grouped_orders g USING (customer_id)
    ),
    buckets AS (
        SELECT spending, COUNT(*) AS customers FROM customer_reference GROUP BY spending
    ),
    bucket_ranks AS (
        SELECT spending, 1 + COALESCE(SUM(customers) OVER (
            ORDER BY spending DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ), 0) AS expected_rank FROM buckets
    ),
    summary_reference AS (
        SELECT c.customer_id, c.spending, c.orders, c.missing, b.expected_rank
        FROM customer_reference c JOIN bucket_ranks b USING (spending)
    ),
    window_orders AS (
        SELECT e.* FROM eligible e CROSS JOIN bounds b
        WHERE e.order_date >= b.last_month - INTERVAL '11 months'
    ),
    monthly_grouped AS (
        SELECT customer_id, DATE_TRUNC('month', order_date)::date AS spending_month,
               COALESCE(SUM(total_amount), 0) AS spending, COUNT(*) AS orders,
               COUNT(*) FILTER (WHERE total_amount IS NULL) AS missing
        FROM window_orders GROUP BY customer_id, DATE_TRUNC('month', order_date)::date
    ),
    monthly_reference AS (
        SELECT c.customer_id, m.spending_month, COALESCE(g.spending, 0) AS spending,
               COALESCE(g.orders, 0) AS orders, COALESCE(g.missing, 0) AS missing
        FROM customers c CROSS JOIN months m
        LEFT JOIN monthly_grouped g ON g.customer_id = c.customer_id AND g.spending_month = m.spending_month
    ),
    running_reference AS (
        -- Independent prefix join, without SUM windows or LAG. Each current
        -- order is paired only with preceding/same eligible orders of its customer.
        SELECT e.customer_id, e.order_id, e.order_date, e.total_amount,
               COALESCE(SUM(p.total_amount), 0) AS spending,
               COUNT(*) FILTER (WHERE p.total_amount IS NULL) AS missing,
               COUNT(*) AS orders,
               (ARRAY_AGG(p.order_date ORDER BY p.order_date DESC, p.order_id DESC))[2] AS previous_date
        FROM eligible e JOIN eligible p ON p.customer_id = e.customer_id
          AND (p.order_date, p.order_id) <= (e.order_date, e.order_id)
        GROUP BY e.customer_id, e.order_id, e.order_date, e.total_amount
    ),
    expected_running AS (
        SELECT customer_id, order_id, order_date, total_amount, spending, missing, orders,
               previous_date, order_date::date - previous_date::date AS gap FROM running_reference
    ),
    final_running AS (
        SELECT DISTINCT ON (customer_id) * FROM running_report
        ORDER BY customer_id, order_date DESC, order_id DESC
    ),
    monthly_per_customer AS (
        SELECT customer_id, SUM(monthly_recorded_spending) AS spending,
               SUM(completed_order_count) AS orders, SUM(missing_amount_count) AS missing
        FROM monthly_report GROUP BY customer_id
    ),
    before_window AS (
        SELECT customer_id, COALESCE(SUM(total_amount), 0) AS spending, COUNT(*) AS orders,
               COUNT(*) FILTER (WHERE total_amount IS NULL) AS missing
        FROM eligible e CROSS JOIN bounds b WHERE e.order_date < b.last_month - INTERVAL '11 months'
        GROUP BY customer_id
    ),
    metrics AS (
        SELECT (SELECT COUNT(*) FROM summary_report) AS summary_rows,
               (SELECT COUNT(DISTINCT customer_id) FROM summary_report) AS distinct_customers,
               (SELECT COUNT(*) FROM summary_report WHERE completed_order_count > 0) AS purchasing_customers,
               (SELECT COUNT(*) FROM summary_report WHERE completed_order_count = 0) AS nonpurchasing_customers,
               (SELECT COALESCE(SUM(total_recorded_spending), 0) FROM summary_report) AS lifetime_spending,
               (SELECT COALESCE(SUM(completed_order_count), 0) FROM summary_report) AS lifetime_orders,
               (SELECT COALESCE(SUM(missing_amount_count), 0) FROM summary_report) AS lifetime_missing,
               (SELECT COUNT(*) FROM top_report) AS top_rows,
               (SELECT COUNT(*) FROM monthly_report) AS monthly_rows,
               (SELECT COUNT(DISTINCT (customer_id, spending_month)) FROM monthly_report) AS distinct_customer_months,
               (SELECT COUNT(DISTINCT spending_month) FROM monthly_report) AS months,
               (SELECT MIN(spending_month)::text FROM monthly_report) AS first_month,
               (SELECT MAX(spending_month)::text FROM monthly_report) AS last_month,
               (SELECT COALESCE(SUM(monthly_recorded_spending), 0) FROM monthly_report) AS monthly_spending,
               (SELECT COALESCE(SUM(completed_order_count), 0) FROM monthly_report) AS monthly_orders,
               (SELECT COALESCE(SUM(missing_amount_count), 0) FROM monthly_report) AS monthly_missing,
               (SELECT COUNT(*) FROM monthly_report WHERE completed_order_count = 0) AS zero_activity_cells,
               (SELECT COUNT(*) FROM running_report) AS running_rows,
               (SELECT COUNT(DISTINCT order_id) FROM running_report) AS distinct_running_orders,
               (SELECT COUNT(*) FROM final_running) AS final_running_customers,
               (SELECT COALESCE(SUM(running_recorded_spending), 0) FROM final_running) AS final_running_spending,
               (SELECT COALESCE(SUM(running_order_count), 0) FROM final_running) AS final_running_orders,
               (SELECT COALESCE(SUM(spending), 0) FROM before_window) AS before_window_spending,
               (SELECT COALESCE(SUM(orders), 0) FROM before_window) AS before_window_orders,
               pg_current_snapshot()::text AS snapshot
    ),
    checks AS (
        SELECT v.check_name, v.ok FROM metrics m CROSS JOIN LATERAL (VALUES
            ('A: Summary covers every customer once, with no nonexistent customer',
                m.summary_rows = m.distinct_customers AND m.summary_rows = (SELECT COUNT(*) FROM customers)
                AND NOT EXISTS (SELECT customer_id FROM customers EXCEPT SELECT customer_id FROM summary_report)
                AND NOT EXISTS (SELECT customer_id FROM summary_report EXCEPT SELECT customer_id FROM customers)),
            ('A: Every summary total and rank matches independent grouped orders and bucket counts',
                NOT EXISTS (SELECT * FROM summary_report EXCEPT SELECT * FROM summary_reference)
                AND NOT EXISTS (SELECT * FROM summary_reference EXCEPT SELECT * FROM summary_report)),
            ('A: Summary totals match unchanged Step 3.3',
                NOT EXISTS (SELECT customer_id, total_recorded_spending, completed_order_count,
                    missing_amount_count FROM summary_report EXCEPT SELECT * FROM prior_lifetime)
                AND NOT EXISTS (SELECT * FROM prior_lifetime EXCEPT SELECT customer_id, total_recorded_spending,
                    completed_order_count, missing_amount_count FROM summary_report)),
            ('A: Zero-order customers retain zero spending and missing count',
                NOT EXISTS (SELECT 1 FROM summary_report WHERE completed_order_count = 0
                    AND (total_recorded_spending <> 0 OR missing_amount_count <> 0))),
            ('A: Summary spending, orders and missing amounts reconcile to eligible source orders',
                m.lifetime_spending = (SELECT COALESCE(SUM(total_amount), 0) FROM eligible)
                AND m.lifetime_orders = (SELECT COUNT(*) FROM eligible)
                AND m.lifetime_missing = (SELECT COUNT(*) FROM eligible WHERE total_amount IS NULL)),
            ('B: Top report is exactly the independently ranked <= 100 set, retaining all ties',
                NOT EXISTS (SELECT * FROM top_report EXCEPT SELECT customer_id, spending, orders, expected_rank
                    FROM summary_reference WHERE expected_rank <= 100)
                AND NOT EXISTS (SELECT customer_id, spending, orders, expected_rank FROM summary_reference
                    WHERE expected_rank <= 100 EXCEPT SELECT * FROM top_report)),
            ('B: Top ranks match the actual Step 3.6 ranking CTE',
                NOT EXISTS (SELECT * FROM top_report EXCEPT SELECT customer_id, total_recorded_spending,
                    completed_order_count, spending_rank FROM prior_ranks WHERE spending_rank <= 100)
                AND NOT EXISTS (SELECT customer_id, total_recorded_spending, completed_order_count,
                    spending_rank FROM prior_ranks WHERE spending_rank <= 100 EXCEPT SELECT * FROM top_report)),
            ('B: Top rows are unique and all qualify by RANK <= 100',
                m.top_rows = (SELECT COUNT(DISTINCT customer_id) FROM top_report)
                AND NOT EXISTS (SELECT 1 FROM top_report WHERE customer_total_spend_rank IS NULL
                    OR customer_total_spend_rank NOT BETWEEN 1 AND 100)),
            ('B: Top customer values match the summary subset in both directions',
                NOT EXISTS (SELECT * FROM top_report EXCEPT SELECT customer_id, total_recorded_spending,
                    completed_order_count, customer_total_spend_rank FROM summary_report
                    WHERE customer_total_spend_rank <= 100)
                AND NOT EXISTS (SELECT customer_id, total_recorded_spending, completed_order_count,
                    customer_total_spend_rank FROM summary_report WHERE customer_total_spend_rank <= 100
                    EXCEPT SELECT * FROM top_report)),
            ('B: No spending tie is partially selected at a qualifying boundary',
                NOT EXISTS (SELECT 1 FROM summary_report s LEFT JOIN top_report t USING (customer_id)
                    GROUP BY s.total_recorded_spending HAVING COUNT(t.customer_id) > 0
                        AND COUNT(t.customer_id) <> COUNT(*))),
            ('C: Every customer has exactly twelve unique monthly rows without fanout',
                m.monthly_rows = 12 * m.summary_rows AND m.distinct_customer_months = m.monthly_rows
                AND NOT EXISTS (SELECT customer_id FROM monthly_report GROUP BY customer_id
                    HAVING COUNT(*) <> 12 OR COUNT(DISTINCT spending_month) <> 12)),
            ('C: Every monthly cell matches independent source grouping and the complete grid',
                NOT EXISTS (SELECT * FROM monthly_report EXCEPT SELECT * FROM monthly_reference)
                AND NOT EXISTS (SELECT * FROM monthly_reference EXCEPT SELECT * FROM monthly_report)),
            ('C: Monthly cells match unchanged Step 3.4',
                NOT EXISTS (SELECT * FROM monthly_report EXCEPT SELECT * FROM prior_monthly)
                AND NOT EXISTS (SELECT * FROM prior_monthly EXCEPT SELECT * FROM monthly_report)),
            ('C: Monthly dates match the twelve independently derived calendar months',
                NOT EXISTS (SELECT spending_month FROM monthly_report EXCEPT SELECT spending_month FROM months)
                AND NOT EXISTS (SELECT c.customer_id, x.spending_month FROM customers c CROSS JOIN months x
                    EXCEPT SELECT customer_id, spending_month FROM monthly_report)),
            ('C: Every zero-activity cell remains present with zero spending and missing count',
                NOT EXISTS (SELECT 1 FROM monthly_report WHERE completed_order_count = 0
                    AND (monthly_recorded_spending <> 0 OR missing_amount_count <> 0))),
            ('C: Monthly spending, order and missing counts reconcile to trailing-window source',
                m.monthly_spending = (SELECT COALESCE(SUM(total_amount), 0) FROM window_orders)
                AND m.monthly_orders = (SELECT COUNT(*) FROM window_orders)
                AND m.monthly_missing = (SELECT COUNT(*) FROM window_orders WHERE total_amount IS NULL)),
            ('D: Exactly one running row exists per eligible order, without fanout',
                m.running_rows = m.distinct_running_orders AND m.running_rows = (SELECT COUNT(*) FROM eligible)
                AND NOT EXISTS (SELECT order_id FROM eligible EXCEPT SELECT order_id FROM running_report)
                AND NOT EXISTS (SELECT order_id FROM running_report EXCEPT SELECT order_id FROM eligible)),
            ('D: Every running order has a valid customer',
                NOT EXISTS (SELECT 1 FROM running_report r LEFT JOIN customers c USING (customer_id)
                    WHERE c.customer_id IS NULL)),
            ('D: Every running value, previous date and calendar gap matches an independent prefix join',
                NOT EXISTS (SELECT * FROM running_report EXCEPT SELECT * FROM expected_running)
                AND NOT EXISTS (SELECT * FROM expected_running EXCEPT SELECT * FROM running_report)),
            ('D: Running values and previous-order calculations match unchanged Step 3.5',
                NOT EXISTS (SELECT * FROM running_report EXCEPT SELECT customer_id, order_id, order_date,
                    total_amount, running_recorded_spending, running_missing_amount_count,
                    running_order_count, previous_order_date, days_since_previous_order FROM prior_running)
                AND NOT EXISTS (SELECT customer_id, order_id, order_date, total_amount, running_recorded_spending,
                    running_missing_amount_count, running_order_count, previous_order_date,
                    days_since_previous_order FROM prior_running EXCEPT SELECT * FROM running_report)),
            ('D: First running rows have NULL previous date and gap',
                NOT EXISTS (SELECT 1 FROM running_report WHERE running_order_count = 1
                    AND (previous_order_date IS NOT NULL OR days_since_previous_order IS NOT NULL))),
            ('D: Final running spending/order/missing counts match Step 3.3 for each purchaser',
                m.final_running_customers = m.purchasing_customers
                AND NOT EXISTS (SELECT customer_id, running_recorded_spending, running_order_count,
                    running_missing_amount_count FROM final_running EXCEPT SELECT * FROM prior_lifetime
                    WHERE completed_order_count > 0)
                AND NOT EXISTS (SELECT * FROM prior_lifetime WHERE completed_order_count > 0
                    EXCEPT SELECT customer_id, running_recorded_spending, running_order_count,
                    running_missing_amount_count FROM final_running)),
            ('E: Lifetime totals equal monthly plus pre-window totals independently per customer',
                NOT EXISTS (SELECT 1 FROM summary_report s JOIN monthly_per_customer x USING (customer_id)
                    LEFT JOIN before_window b USING (customer_id)
                    WHERE s.total_recorded_spending IS DISTINCT FROM x.spending + COALESCE(b.spending, 0)
                       OR s.completed_order_count IS DISTINCT FROM x.orders + COALESCE(b.orders, 0)
                       OR s.missing_amount_count IS DISTINCT FROM x.missing + COALESCE(b.missing, 0))),
            ('E: Final running sums reconcile with lifetime summary spending and orders',
                m.final_running_spending = m.lifetime_spending AND m.final_running_orders = m.lifetime_orders),
            ('E: All components reconcile to one eligible source without monetary or order fanout',
                m.lifetime_spending = m.monthly_spending + m.before_window_spending
                AND m.lifetime_orders = m.monthly_orders + m.before_window_orders
                AND m.lifetime_orders = m.running_rows)
        ) AS v(check_name, ok)
    )
    """


def aggregate_sql(queries, legacy, fixture_prefix='', extra_checks=''):
    return 'WITH ' + fixture_prefix + context(queries, legacy) + extra_checks + """
    SELECT json_build_object('metrics', (SELECT row_to_json(m) FROM metrics m),
        'checks', (SELECT json_agg(row_to_json(c)) FROM checks c),
        'checks_ok', (SELECT bool_and(ok IS TRUE) FROM checks)
    );
    """


def literal(value):
    if value is None:
        return 'NULL'
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)


def values(rows, casts):
    if not rows:
        return 'SELECT ' + ','.join('NULL::' + cast for cast in casts) + ' WHERE FALSE'
    return 'VALUES ' + ','.join('(' + ','.join(literal(value) + '::' + cast
                    for value, cast in zip(row, casts)) + ')' for row in rows)


def fixtures():
    orders = [
        (10, 1, '2025-11-30 23:59:59.999999', 50, 'completed'),
        (12, 1, '2025-12-01', 20, 'COMPLETE'), (11, 1, '2025-12-01', 10, ' Completed '),
        (13, 1, '2026-01-15', 5, 'completed'), (14, 1, '2026-11-26 23:59:59.999999', 8, 'complete'),
        (30, 3, '2026-01-01', None, 'completed'), (40, 4, '2026-02-01', Decimal('7.50'), 'completed'),
        (41, 4, '2026-02-02', None, 'completed'), (50, 5, '2026-03-01', 0, 'completed'),
        (51, 5, '2026-03-02', -5, 'completed'), (60, 6, '2026-01-01', 999, 'pending'),
        (70, 7, '2020-01-01', 100, 'completed'), (80, 8, '2025-12-02', 93, 'completed'),
        (90, 1, '2026-11-27', 999, 'completed'), (91, 1, '2026-11-28', 999, 'completed'),
        (92, 1, None, 999, 'completed'), (93, 1, '2026-01-01', 999, 'cancelled'),
        (94, 1, '2026-01-01', 999, None), (95, 1, '2026-01-01', 999, '   '),
        (96, 999, '2026-01-01', 999, 'completed'), (97, None, '2026-01-01', 999, 'completed'),
    ]
    # These complete expected rows are stated independently of source aggregation.
    summary = [(1, 93, 5, 0, 2), (2, 0, 0, 0, 5), (3, 0, 1, 1, 5),
               (4, Decimal('7.50'), 2, 1, 4), (5, -5, 2, 0, 8), (6, 0, 0, 0, 5),
               (7, 100, 1, 0, 1), (8, 93, 1, 0, 2)]
    active = [(1, '2025-12-01', 30, 2, 0), (1, '2026-01-01', 5, 1, 0),
              (1, '2026-11-01', 8, 1, 0), (3, '2026-01-01', 0, 1, 1),
              (4, '2026-02-01', Decimal('7.50'), 2, 1), (5, '2026-03-01', -5, 2, 0),
              (8, '2025-12-01', 93, 1, 0)]
    expected_running = [
        (1, 10, '2025-11-30 23:59:59.999999', 50, 50, 0, 1, None, None),
        (1, 11, '2025-12-01', 10, 60, 0, 2, '2025-11-30 23:59:59.999999', 1),
        (1, 12, '2025-12-01', 20, 80, 0, 3, '2025-12-01', 0),
        (1, 13, '2026-01-15', 5, 85, 0, 4, '2025-12-01', 45),
        (1, 14, '2026-11-26 23:59:59.999999', 8, 93, 0, 5, '2026-01-15', 315),
        (3, 30, '2026-01-01', None, 0, 1, 1, None, None),
        (4, 40, '2026-02-01', Decimal('7.50'), Decimal('7.50'), 0, 1, None, None),
        (4, 41, '2026-02-02', None, Decimal('7.50'), 1, 2, '2026-02-01', 1),
        (5, 50, '2026-03-01', 0, 0, 0, 1, None, None),
        (5, 51, '2026-03-02', -5, -5, 0, 2, '2026-03-01', 1),
        (7, 70, '2020-01-01', 100, 100, 0, 1, None, None),
        (8, 80, '2025-12-02', 93, 93, 0, 1, None, None),
    ]
    crossing_summary = [(i, 1000-i if i <= 98 else 900 if i <= 102 else 800-100*(i-103),
                         1, 0, i if i <= 98 else 99 if i <= 102 else i) for i in range(1, 106)]
    crossing_orders = [(i, i, '2025-12-01', amount, 'completed')
                       for i, amount, *_ in crossing_summary]
    crossing_active = [(i, '2025-12-01', amount, 1, 0) for i, amount, *_ in crossing_summary]
    crossing_running = [(i, i, '2025-12-01', amount, amount, 0, 1, None, None)
                        for i, amount, *_ in crossing_summary]
    return [
        ('integration_edges', list(range(1, 9)), orders, summary, active, expected_running,
         {'summary_rows': 8, 'top_rows': 8, 'monthly_rows': 96, 'running_rows': 12,
          'lifetime_spending': Decimal('288.50'), 'lifetime_orders': 12, 'lifetime_missing': 2,
          'monthly_spending': Decimal('138.50'), 'monthly_orders': 10, 'monthly_missing': 2,
          'before_window_spending': 150, 'before_window_orders': 2, 'zero_activity_cells': 89}),
        ('boundary_tie', list(range(1, 106)), crossing_orders, crossing_summary, crossing_active,
         crossing_running, {'summary_rows': 105, 'top_rows': 102, 'monthly_rows': 1260,
          'running_rows': 105, 'lifetime_spending': 98849, 'lifetime_orders': 105,
          'monthly_spending': 98849, 'monthly_orders': 105, 'zero_activity_cells': 1155}),
        ('empty_population', [], [], [], [], [],
         {'summary_rows': 0, 'top_rows': 0, 'monthly_rows': 0, 'running_rows': 0,
          'lifetime_spending': 0, 'lifetime_orders': 0, 'monthly_spending': 0, 'monthly_orders': 0}),
    ]


def synthetic_sql(queries, legacy, fixture):
    name, customers, orders, summary, active, running, expected_metrics = fixture
    prefix = ('customers(customer_id) AS (' + values([(i,) for i in reversed(customers)], ['integer']) + '),\n'
              'orders(order_id,customer_id,order_date,total_amount,status) AS ('
              + values(list(reversed(orders)), ['integer', 'integer', 'timestamp', 'numeric', 'text']) + '),\n')
    fixed_months = [('2025-12-01',)] + [(f'2026-{month:02d}-01',) for month in range(1, 12)]
    extra = ', expected_summary AS (' + values(summary, ['integer', 'numeric', 'bigint', 'bigint', 'bigint']) + '),\n'
    extra += 'expected_active(customer_id,spending_month,spending,orders,missing) AS (' + values(
        active, ['integer', 'date', 'numeric', 'bigint', 'bigint']) + '),\n'
    extra += 'fixed_months(spending_month) AS (' + values(fixed_months, ['date']) + '),\n'
    extra += '''expected_monthly AS (
        SELECT c.customer_id, m.spending_month, COALESCE(a.spending,0), COALESCE(a.orders,0), COALESCE(a.missing,0)
        FROM customers c CROSS JOIN fixed_months m LEFT JOIN expected_active a USING (customer_id,spending_month)
    ), expected_fixture_running AS (''' + values(running, ['integer', 'integer', 'timestamp', 'numeric',
        'numeric', 'bigint', 'bigint', 'timestamp', 'integer']) + '),\n'
    # Name expected columns so top-set checks cannot accidentally depend on order.
    extra += '''named_expected(customer_id,spending,orders,missing,rank) AS (SELECT * FROM expected_summary),
    exact_checks AS (
        SELECT v.check_name,v.ok FROM (VALUES
            ('SYN: Exact independently stated summary rows',
                NOT EXISTS (SELECT * FROM summary_report EXCEPT SELECT * FROM expected_summary)
                AND NOT EXISTS (SELECT * FROM expected_summary EXCEPT SELECT * FROM summary_report)),
            ('SYN: Exact qualifying top-customer rows, including all boundary ties',
                NOT EXISTS (SELECT * FROM top_report EXCEPT SELECT customer_id,spending,orders,rank
                    FROM named_expected WHERE rank<=100)
                AND NOT EXISTS (SELECT customer_id,spending,orders,rank FROM named_expected
                    WHERE rank<=100 EXCEPT SELECT * FROM top_report)),
            ('SYN: Exact monthly grid, active totals and zero cells',
                NOT EXISTS (SELECT * FROM monthly_report EXCEPT SELECT * FROM expected_monthly)
                AND NOT EXISTS (SELECT * FROM expected_monthly EXCEPT SELECT * FROM monthly_report)),
            ('SYN: Exact running totals, deterministic timestamp peers and previous-order fields',
                NOT EXISTS (SELECT * FROM running_report EXCEPT SELECT * FROM expected_fixture_running)
                AND NOT EXISTS (SELECT * FROM expected_fixture_running EXCEPT SELECT * FROM running_report))
        ) AS v(check_name,ok)
    )
    '''
    query = aggregate_sql(queries, legacy, prefix, extra)
    query = query.replace('FROM checks c)', 'FROM (SELECT * FROM checks UNION ALL SELECT * FROM exact_checks) c)')
    query = query.replace('FROM checks)', 'FROM (SELECT * FROM checks UNION ALL SELECT * FROM exact_checks) c)')
    return name, query, expected_metrics


def log_payload(log, label, payload, expected, snapshot):
    metrics = payload['metrics']
    log(label + ' aggregate metrics: ' + json.dumps(metrics, default=str))
    ok = payload['checks_ok'] is True and metrics['snapshot'] == snapshot
    for row in payload['checks']:
        passed = row['ok'] is True
        log(label + ': ' + row['check_name'] + ': ' + ('PASS' if passed else 'FAIL'))
        ok = ok and passed
    for key, value in expected.items():
        passed = metrics[key] == value
        log(f'{label} expected {key}={value}; actual={metrics[key]}: ' + ('PASS' if passed else 'FAIL'))
        ok = ok and passed
    if not ok:
        raise RuntimeError(label + ' integration assertions failed; review aggregate evidence')
    return len(payload['checks']), len(expected)


def verify(log):
    queries, legacy, cutoff = load_reports()
    params = {'reporting_cutoff': cutoff}
    log('Execution UTC: ' + datetime.now(timezone.utc).isoformat())
    for name in ('monday_spending_report.sql', 'tests/verify_monday_spending_report.py',
                 'customer_spending.sql', 'monthly_spending.sql',
                 'running_customer_totals.sql', 'top_100_ranking_analysis.sql'):
        log(name + ' SHA-256: ' + hashlib.sha256((ROOT / name).read_bytes()).hexdigest())
    log('Four result sets, shared cutoff, transaction controls and prior CTE consistency: PASS')
    conn = connect()
    try:
        register_default_json(conn, loads=lambda value: json.loads(value, parse_float=Decimal))
        conn.set_session(isolation_level='REPEATABLE READ', readonly=True, autocommit=False)
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '60s'")
            cur.execute("""SELECT json_build_object('database',current_database(),'user',current_user,
                'cluster_identifier',system_identifier::text,'server_version',current_setting('server_version'),
                'isolation',current_setting('transaction_isolation'),'read_only',current_setting('transaction_read_only'),
                'snapshot',pg_current_snapshot()::text,'cutoff',%(reporting_cutoff)s) FROM pg_control_system()""", params)
            metadata = cur.fetchone()[0]
            log('Connection: ' + json.dumps(metadata))
            if not (metadata['database'] == 'postgres' and metadata['user'] == 'postgres'
                    and metadata['cluster_identifier'] == '7712053334814294059'
                    and metadata['isolation'] == 'repeatable read' and metadata['read_only'] == 'on'):
                raise RuntimeError('Connection fingerprint or read-only snapshot settings differ')
            for number, (query, expected_columns) in enumerate(zip(queries, COLUMNS), 1):
                cur.execute('SELECT * FROM (' + query + ') result LIMIT 0', params)
                if tuple(column.name for column in cur.description) != expected_columns:
                    raise RuntimeError('Unexpected output columns in result set ' + str(number))
                log(f'Result set {number} output columns: PASS')
            cur.execute(aggregate_sql(queries, legacy), params)
            # The connection-local JSON loader retains exact decimal amounts.
            live = cur.fetchone()[0]
            expected = {'summary_rows': 40420, 'distinct_customers': 40420,
                'purchasing_customers': 37900, 'nonpurchasing_customers': 2520,
                'lifetime_spending': Decimal('339184984.53'), 'lifetime_orders': 111195,
                'lifetime_missing': 0, 'top_rows': 100, 'monthly_rows': 485040,
                'distinct_customer_months': 485040, 'months': 12,
                'first_month': '2025-12-01', 'last_month': '2026-11-01',
                'monthly_spending': Decimal('313014045.03'), 'monthly_orders': 102463,
                'monthly_missing': 0, 'running_rows': 111195, 'distinct_running_orders': 111195,
                'final_running_customers': 37900, 'final_running_spending': Decimal('339184984.53'),
                'final_running_orders': 111195, 'before_window_spending': Decimal('26170939.50'),
                'before_window_orders': 8732}
            live_checks, baselines = log_payload(log, 'LIVE', live, expected, metadata['snapshot'])
            synthetic_checks = synthetic_baselines = 0
            cases = fixtures()
            for case in cases:
                name, query, expected_metrics = synthetic_sql(queries, legacy, case)
                cur.execute(query, params)
                checks, baselines_count = log_payload(log, 'SYNTHETIC ' + name, cur.fetchone()[0],
                                                      expected_metrics, metadata['snapshot'])
                synthetic_checks += checks
                synthetic_baselines += baselines_count
            cur.execute('SELECT pg_current_snapshot()::text')
            if cur.fetchone()[0] != metadata['snapshot']:
                raise RuntimeError('The reporting snapshot changed')
        conn.commit()
        log(f'Assertion totals: live={live_checks}; live baselines={baselines}; '
            f'synthetic={synthetic_checks}; synthetic baselines={synthetic_baselines}; fixtures={len(cases)}')
        log('All actual result sets, prior references and VALUES fixtures shared one read-only snapshot: PASS')
        log('Overall Monday spending report validation: PASS')
        log('Read-only transaction committed; no records or database objects were created or changed.')
    finally:
        conn.close()


if __name__ == '__main__':
    path = ROOT / 'tests' / 'results' / ('phase3_monday_spending_integration_' + uuid.uuid4().hex[:12] + '.txt')
    with path.open('x', encoding='utf-8') as evidence:
        def log(message):
            print(message, flush=True)
            evidence.write(message + '\n')
            evidence.flush()
        try:
            verify(log)
        except Exception as error:
            log('FAIL: ' + (str(error) if isinstance(error, (RuntimeError, ValueError)) else
                            type(error).__name__ + '; driver/server details withheld to protect client data'))
            raise SystemExit(1)
    print('Execution evidence: ' + str(path.relative_to(ROOT)), flush=True)
