-- Read-only checks: valid before and after the identity migration.
-- Run in VS Code and Docker to compare the actual connection targets.
SELECT current_database() AS database_name,
       current_user AS database_user,
       current_setting('server_version') AS server_version,
       (pg_control_system()).system_identifier AS cluster_identifier,
       current_setting('data_directory') AS data_directory,
       inet_server_addr() AS server_address,
       current_setting('port') AS server_port,
       current_setting('search_path') AS search_path;

-- These are dataset boundaries, not instructions to rewind a used sequence.
SELECT
    (SELECT MAX(order_id)::bigint FROM public.orders) AS max_order_id,
    (SELECT MAX(order_id)::bigint FROM public.order_items) AS max_referenced_order_id,
    (SELECT MAX(order_item_id)::bigint FROM public.order_items) AS max_order_item_id,
    (SELECT MAX(log_id)::bigint FROM public.inventory_log) AS max_log_id;

SELECT c.table_name, c.column_name, c.data_type, c.column_default,
       c.is_identity, c.identity_generation, s.sequence_name,
       p.seqincrement AS increment_by, p.seqmin AS minimum_value,
       p.seqmax AS maximum_value, p.seqcache AS cache_size, p.seqcycle AS cycles
FROM information_schema.columns AS c
LEFT JOIN LATERAL (
    SELECT pg_get_serial_sequence(
        format('%I.%I', c.table_schema, c.table_name), c.column_name)::regclass
        AS sequence_name
) AS s ON true
LEFT JOIN pg_sequence AS p ON p.seqrelid = s.sequence_name
WHERE c.table_schema = 'public'
  AND (c.table_name, c.column_name) IN (
      ('orders', 'order_id'), ('order_items', 'order_item_id'), ('inventory_log', 'log_id'))
ORDER BY c.table_name;

-- Discover names dynamically; absent sequences are expected before migration.
-- Notices show exact state without consuming an ID. With is_called=false,
-- last_value itself is the next ID; otherwise add the sequence increment.
DO $inspection$
DECLARE
    target record;
    sequence_last bigint;
    sequence_called boolean;
BEGIN
    FOR target IN
        SELECT pg_get_serial_sequence(format('public.%I', t), c)::regclass AS seq
        FROM (VALUES ('orders', 'order_id'), ('order_items', 'order_item_id'),
                     ('inventory_log', 'log_id')) AS targets(t, c)
    LOOP
        IF target.seq IS NULL THEN
            RAISE NOTICE 'No associated sequence (identity not yet configured)';
        ELSE
            EXECUTE format('SELECT last_value, is_called FROM %s', target.seq)
                INTO sequence_last, sequence_called;
            RAISE NOTICE '%: last_value=%, is_called=%',
                target.seq, sequence_last, sequence_called;
        END IF;
    END LOOP;
END
$inspection$;
