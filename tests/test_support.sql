CREATE OR REPLACE FUNCTION pg_temp.check(p_ok boolean, p_label text)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    IF p_ok IS DISTINCT FROM TRUE THEN RAISE EXCEPTION 'FAIL: %', p_label; END IF;
    RAISE NOTICE 'PASS: %', p_label;
END;
$$;
