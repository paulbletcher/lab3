-- Phase 2, step 1: automatic IDs only; no checkout function.
-- Run the complete script with psql -v ON_ERROR_STOP=1.
BEGIN;
SET LOCAL lock_timeout = '10s';

-- Freeze table writes while calculating the historical ID boundaries.
LOCK TABLE public.orders, public.order_items, public.inventory_log
    IN ACCESS EXCLUSIVE MODE;

DO $migration$
DECLARE
    target record;
    identity_kind text;
    identity_sequence regclass;
    sequence_config record;
    sequence_last bigint;
    sequence_called boolean;
    required_next bigint;
    available_next bigint;
BEGIN
    FOR target IN
        SELECT * FROM (VALUES
            ('orders', 'order_id'),
            ('order_items', 'order_item_id'),
            ('inventory_log', 'log_id')
        ) AS targets(table_name, column_name)
    LOOP
        SELECT attidentity INTO STRICT identity_kind
        FROM pg_attribute
        WHERE attrelid = format('public.%I', target.table_name)::regclass
          AND attname = target.column_name AND NOT attisdropped;

        IF identity_kind = '' THEN
            EXECUTE format(
                'ALTER TABLE public.%I ALTER COLUMN %I ADD GENERATED ALWAYS AS IDENTITY',
                target.table_name, target.column_name);
        ELSIF identity_kind = 'd' THEN
            EXECUTE format(
                'ALTER TABLE public.%I ALTER COLUMN %I SET GENERATED ALWAYS',
                target.table_name, target.column_name);
        END IF; -- An existing ALWAYS identity needs no replacement.

        identity_sequence := pg_get_serial_sequence(
            format('public.%I', target.table_name), target.column_name)::regclass;
        IF identity_sequence IS NULL THEN
            RAISE EXCEPTION 'No identity sequence for public.%.%',
                target.table_name, target.column_name;
        END IF;

        -- This DDL also locks the sequence against direct nextval() calls
        -- until COMMIT. NO CYCLE prevents wrapping around to earlier IDs.
        EXECUTE format('ALTER SEQUENCE %s NO CYCLE', identity_sequence);
        SELECT * INTO STRICT sequence_config
        FROM pg_sequence WHERE seqrelid = identity_sequence;

        -- The supplied integer keys use ordinary, uncached ascending IDs.
        -- Stop for unexpected settings rather than silently changing them.
        IF sequence_config.seqtypid <> 'integer'::regtype
           OR sequence_config.seqincrement <> 1
           OR sequence_config.seqcache <> 1 THEN
            RAISE EXCEPTION '% requires an integer sequence with INCREMENT 1 and CACHE 1',
                identity_sequence;
        END IF;

        EXECUTE format('SELECT last_value, is_called FROM %s', identity_sequence)
            INTO sequence_last, sequence_called;
        available_next := sequence_last + CASE WHEN sequence_called THEN 1 ELSE 0 END;

        EXECUTE format('SELECT COALESCE(MAX(%I)::bigint, 0) + 1 FROM public.%I',
                       target.column_name, target.table_name)
            INTO required_next;
        IF target.table_name = 'orders' THEN
            -- Include historical references, not just existing order IDs.
            SELECT GREATEST(required_next, COALESCE(MAX(order_id)::bigint, 0) + 1)
                INTO required_next FROM public.order_items;
        END IF;

        IF GREATEST(required_next, available_next) > sequence_config.seqmax THEN
            RAISE EXCEPTION 'No safe integer IDs remain for %', identity_sequence;
        END IF;

        IF available_next < required_next THEN
            -- Forward only. Unlike setval(), RESTART is transactional.
            EXECUTE format('ALTER SEQUENCE %s RESTART WITH %s',
                           identity_sequence, required_next);
            available_next := required_next;
        END IF;

        RAISE NOTICE 'public.%.%: next ID %, minimum safe ID %',
            target.table_name, target.column_name, available_next, required_next;
    END LOOP;
END
$migration$;

COMMIT;
