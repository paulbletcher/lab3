-- Investigation 4: aggregate-only activity during the official flash sale.
-- Use autocommit so each sample reads fresh activity, not a held transaction.
-- No query text, customer information, backend IDs or transaction IDs leave SQL.
-- One JSON row is returned even when no other connections exist.
\set ON_ERROR_STOP on
\pset pager off
\pset format unaligned
\pset tuples_only on

WITH activity AS (
    SELECT datname, state, wait_event_type, wait_event,
           state = 'active'
               AND query LIKE 'SELECT success, order_id, message FROM place_order(%'
               AS active_checkout,
           query_start
    FROM pg_stat_activity
    WHERE backend_type = 'client backend'
      AND pid <> pg_backend_pid()
),
sessions AS (
    SELECT * FROM activity WHERE datname = current_database()
),
event_groups AS (
    SELECT state, wait_event_type, wait_event, COUNT(*) AS connection_count,
           COUNT(*) FILTER (WHERE active_checkout) AS active_checkout_count
    FROM sessions
    GROUP BY state, wait_event_type, wait_event
)
SELECT json_build_object(
    'sampled_at', clock_timestamp(),
    'database_connections_excluding_monitor', (SELECT COUNT(*) FROM sessions),
    'database_connections_including_monitor', (SELECT COUNT(*) + 1 FROM sessions),
    'cluster_client_connections_including_monitor', (SELECT COUNT(*) + 1 FROM activity),
    'active_connections_excluding_monitor', (SELECT COUNT(*) FROM sessions WHERE state = 'active'),
    'active_connections_including_monitor', (SELECT COUNT(*) + 1 FROM sessions WHERE state = 'active'),
    'active_checkout_connections', (SELECT COUNT(*) FROM sessions WHERE active_checkout),
    'oldest_active_checkout_ms', (SELECT MAX(EXTRACT(EPOCH FROM (clock_timestamp() - query_start)) * 1000)
                                  FROM sessions WHERE active_checkout),
    'events', (SELECT COALESCE(json_agg(row_to_json(e) ORDER BY connection_count DESC,
                                       state, wait_event_type, wait_event), '[]'::json)
               FROM event_groups e)
);

-- Explicit named arguments; no row-count condition that could end quiet sampling.
-- The diagnostic driver can instead repeat the SQL at 0.5-second intervals until
-- the official test and its cleanup finish, then collect post-test samples.
\watch interval=0.5 count=240
