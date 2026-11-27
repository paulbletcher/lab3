-- Investigation 5: blocking relationships and requested lock targets.
-- Read-only SELECT. Repeat through an AUTOCOMMIT connection, approximately
-- every 0.5 seconds, from before Test 2 until its fixture cleanup completes.
-- No customer values, SQL text, transaction IDs or virtual transaction IDs
-- are output. Backend PIDs and physical tuple locations belong in LOCAL logs.
-- lock_target_number is a sample-local ordinal, NOT a transaction identifier.
-- One statement relates materialized activity and lock snapshots to actual
-- pg_blocking_pids() results. These changing sources are not globally atomic.
-- pg_blocking_pids() may report holders AND earlier conflicting queue members;
-- calling it frequently can itself add lock-manager overhead.

WITH sample_clock AS MATERIALIZED (
    SELECT clock_timestamp() AS started_at,
           (SELECT oid FROM pg_database WHERE datname = current_database()) AS database_oid
),
activity_snapshot AS MATERIALIZED (
    SELECT pid, datid, state, wait_event_type, wait_event,
           state = 'active'
               AND query LIKE 'SELECT success, order_id, message FROM place_order(%'
               AS active_checkout
    FROM pg_stat_activity
    WHERE backend_type = 'client backend' AND pid <> pg_backend_pid()
),
local_sessions AS MATERIALIZED (
    SELECT a.* FROM activity_snapshot a CROSS JOIN sample_clock s
    WHERE a.datid = s.database_oid
),
lock_snapshot AS MATERIALIZED (
    -- Sensitive target keys remain internal, solely for exact lock matching.
    SELECT locktype, database, relation, page, tuple, virtualxid, transactionid,
           classid, objid, objsubid, pid, mode, granted, waitstart
    FROM pg_locks
),
waiting_locks AS MATERIALIZED (
    SELECT l.* FROM lock_snapshot l JOIN local_sessions a USING (pid)
    WHERE NOT l.granted
),
blocking_candidates AS MATERIALIZED (
    SELECT pid FROM local_sessions WHERE wait_event_type = 'Lock'
    UNION
    SELECT pid FROM waiting_locks
),
blocking_arrays AS MATERIALIZED (
    -- Exactly one authority call per candidate in this sample, never inferred
    -- from a self-join or a wait-event label. LWLocks have no pg_locks targets.
    SELECT pid, pg_blocking_pids(pid) AS blocking_pids FROM blocking_candidates
),
blocking_edges AS MATERIALIZED (
    SELECT DISTINCT b.pid AS blocked_pid, p.blocker_pid
    FROM blocking_arrays b CROSS JOIN LATERAL UNNEST(b.blocking_pids) p(blocker_pid)
),
participants AS MATERIALIZED (
    SELECT blocked_pid AS pid FROM blocking_edges
    UNION SELECT blocker_pid FROM blocking_edges
    UNION SELECT pid FROM waiting_locks
),
wait_targets AS MATERIALIZED (
    SELECT DISTINCT locktype, database, relation, page, tuple, virtualxid,
           transactionid, classid, objid, objsubid FROM waiting_locks
),
numbered_targets AS MATERIALIZED (
    SELECT ROW_NUMBER() OVER (
               ORDER BY locktype, database, relation, page, tuple, virtualxid,
                        transactionid::text, classid, objid, objsubid
           ) AS lock_target_number, t.*
    FROM wait_targets t
),
fixture_locations AS MATERIALIZED (
    -- Only the official synthetic product is inspected, never customer data.
    -- Its currently visible tuple can move during updates; absence of a match
    -- cannot rule out contention on an earlier version of the fixture row.
    SELECT SPLIT_PART(TRIM(BOTH '()' FROM ctid::text), ',', 1)::integer AS page,
           SPLIT_PART(TRIM(BOTH '()' FROM ctid::text), ',', 2)::integer AS tuple
    FROM public.products WHERE product_name = 'RACE TEST FIXTURE T2 flash'
),
target_details AS MATERIALIZED (
    SELECT t.lock_target_number, t.locktype,
           t.relation AS relation_oid,
           CASE WHEN c.oid IS NOT NULL THEN n.nspname || '.' || c.relname END AS relation_name,
           c.relkind AS relation_kind, t.page, t.tuple,
           CASE WHEN t.locktype = 'tuple'
                     AND t.database = (SELECT database_oid FROM sample_clock)
                     AND t.relation = 'public.products'::regclass
                THEN EXISTS (SELECT 1 FROM fixture_locations f
                             WHERE f.page = t.page AND f.tuple = t.tuple)
                ELSE NULL END AS matches_visible_official_fixture_tuple
    FROM numbered_targets t
    LEFT JOIN pg_class c ON c.oid = t.relation
       AND (t.database = (SELECT database_oid FROM sample_clock) OR t.database = 0)
    LEFT JOIN pg_namespace n ON n.oid = c.relnamespace
),
locks_on_wait_targets AS MATERIALIZED (
    -- Include granted holders and queued requests on the exact same target.
    SELECT t.lock_target_number, l.pid, l.mode, l.granted, l.waitstart AS wait_started_at,
           CASE WHEN NOT l.granted AND l.waitstart IS NOT NULL
                THEN GREATEST(0, EXTRACT(EPOCH FROM (clock_timestamp() - l.waitstart)) * 1000)
                ELSE NULL END AS current_wait_age_ms
    FROM lock_snapshot l JOIN numbered_targets t
      ON l.locktype = t.locktype
     AND l.database IS NOT DISTINCT FROM t.database
     AND l.relation IS NOT DISTINCT FROM t.relation
     AND l.page IS NOT DISTINCT FROM t.page
     AND l.tuple IS NOT DISTINCT FROM t.tuple
     AND l.virtualxid IS NOT DISTINCT FROM t.virtualxid
     AND l.transactionid IS NOT DISTINCT FROM t.transactionid
     AND l.classid IS NOT DISTINCT FROM t.classid
     AND l.objid IS NOT DISTINCT FROM t.objid
     AND l.objsubid IS NOT DISTINCT FROM t.objsubid
),
blocker_counts AS MATERIALIZED (
    SELECT blocker_pid, COUNT(DISTINCT blocked_pid) AS blocked_sessions
    FROM blocking_edges GROUP BY blocker_pid
),
participant_states AS MATERIALIZED (
    SELECT p.pid AS backend_pid, a.state, a.wait_event_type, a.wait_event,
           a.active_checkout, a.pid IS NOT NULL AS activity_available,
           COALESCE(b.blocked_sessions, 0) AS blocked_sessions_as_blocker
    FROM participants p LEFT JOIN activity_snapshot a USING (pid)
    LEFT JOIN blocker_counts b ON b.blocker_pid = p.pid
),
granted_relation_context AS MATERIALIZED (
    -- Context only: holding a relation lock does NOT mean waiting on it.
    SELECT n.nspname || '.' || c.relname AS relation_name, c.relkind AS relation_kind,
           l.mode, COUNT(DISTINCT l.pid) AS participant_backends
    FROM lock_snapshot l JOIN participants p USING (pid)
    JOIN pg_class c ON c.oid = l.relation
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE l.granted AND l.locktype = 'relation'
      AND l.database = (SELECT database_oid FROM sample_clock)
    GROUP BY n.nspname, c.relname, c.relkind, l.mode
),
payload AS MATERIALIZED (
    SELECT jsonb_build_object(
        'sample_started_at', (SELECT started_at FROM sample_clock),
        'database_connections_excluding_monitor', (SELECT COUNT(*) FROM local_sessions),
        'active_checkout_connections', (SELECT COUNT(*) FROM local_sessions WHERE active_checkout),
        'lock_wait_activity_sessions', (SELECT COUNT(*) FROM local_sessions WHERE wait_event_type = 'Lock'),
        'blocking_function_calls', (SELECT COUNT(*) FROM blocking_candidates),
        'blocked_sessions', (SELECT COUNT(DISTINCT blocked_pid) FROM blocking_edges),
        'blockers', (SELECT COUNT(DISTINCT blocker_pid) FROM blocking_edges),
        'blocking_relationships', (SELECT COUNT(*) FROM blocking_edges),
        'ungranted_lock_count', (SELECT COUNT(*) FROM waiting_locks),
        'fixture_visible_tuple_count', (SELECT COUNT(*) FROM fixture_locations),
        'visible_fixture_locations', (SELECT COALESCE(jsonb_agg(to_jsonb(f)), '[]'::jsonb)
                                      FROM fixture_locations f),
        'edge_columns', jsonb_build_array('blocked_backend_pid', 'blocking_backend_pid'),
        'edges', (SELECT COALESCE(jsonb_agg(jsonb_build_array(blocked_pid, blocker_pid)
                                          ORDER BY blocked_pid, blocker_pid), '[]'::jsonb)
                  FROM blocking_edges),
        'participant_states', (SELECT COALESCE(jsonb_agg(to_jsonb(p) ORDER BY backend_pid), '[]'::jsonb)
                               FROM participant_states p),
        'lock_targets', (SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY lock_target_number), '[]'::jsonb)
                         FROM target_details t),
        'locks_on_wait_targets', (SELECT COALESCE(jsonb_agg(to_jsonb(l)
                                              ORDER BY lock_target_number, granted, pid), '[]'::jsonb)
                                  FROM locks_on_wait_targets l),
        'granted_relation_context', (SELECT COALESCE(jsonb_agg(to_jsonb(g) ORDER BY relation_name, mode), '[]'::jsonb)
                                    FROM granted_relation_context g)
    ) AS sample
)
SELECT sample || jsonb_build_object('sample_finished_at', clock_timestamp())
FROM payload;
