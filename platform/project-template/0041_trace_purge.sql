-- An owner may delete a run (platform_service/run_purge.py). Its recorded calls leave trace.call only through
-- trace.purge_runs, which first keeps a tombstone per run in trace.purged: how many calls there were and the
-- chain's last hash, so the ledger and the tombstone still prove what was removed. The tombstones only grow.
--
-- The append-only guard on trace.call lets a DELETE through only inside that function: the session acts as
-- platform_owner (the function is SECURITY DEFINER, owned by it) and the function has marked the transaction
-- as purging. platform_rw still cannot delete a call itself; it may only call the function.
CREATE TABLE IF NOT EXISTS trace.purged (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    evaluation_plugin uuid NOT NULL,
    run               text NOT NULL,
    calls             integer NOT NULL CHECK (calls >= 1),
    digest            text NOT NULL CHECK (digest ~ '^[0-9a-f]{64}$'),
    purged_at         timestamptz NOT NULL DEFAULT clock_timestamp(),
    purged_by         text NOT NULL,
    reason            text NOT NULL
);

CREATE OR REPLACE FUNCTION trace.purged_refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'trace.purged is append-only: a tombstone is never changed or removed';
END $$;
CREATE OR REPLACE TRIGGER purged_append_only BEFORE UPDATE OR DELETE ON trace.purged
    FOR EACH ROW EXECUTE FUNCTION trace.purged_refuse_change();
CREATE OR REPLACE TRIGGER purged_no_truncate BEFORE TRUNCATE ON trace.purged
    FOR EACH STATEMENT EXECUTE FUNCTION trace.purged_refuse_change();

CREATE OR REPLACE FUNCTION trace.refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND current_user = 'platform_owner' AND current_setting('aisc.purging', true) = 'trace' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'trace.call is append-only: a recorded call is never changed or removed';
END $$;

-- The calls of these tests go, a tombstone per run first; what it answers: {"calls": n, "trace_digests": {run: hash}}.
CREATE OR REPLACE FUNCTION trace.purge_runs(p_evaluation_plugins uuid[], p_by text, p_reason text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, trace, pg_temp AS $$
DECLARE
    r record;
    digests jsonb := '{}'::jsonb;
    total integer := 0;
BEGIN
    IF coalesce(btrim(p_reason), '') = '' OR coalesce(btrim(p_by), '') = '' THEN
        RAISE EXCEPTION 'a purge names who asked for it and why';
    END IF;
    FOR r IN
        SELECT c.evaluation_plugin, c.run, count(*)::integer AS calls,
               (array_agg(c.hash ORDER BY c.seq DESC))[1] AS digest
          FROM trace.call c
         WHERE c.evaluation_plugin = ANY (p_evaluation_plugins)
         GROUP BY c.evaluation_plugin, c.run
         ORDER BY c.run
    LOOP
        INSERT INTO trace.purged (evaluation_plugin, run, calls, digest, purged_by, reason)
        VALUES (r.evaluation_plugin, r.run, r.calls, r.digest, p_by, p_reason);
        digests := digests || jsonb_build_object(r.run, r.digest);
        total := total + r.calls;
    END LOOP;
    PERFORM set_config('aisc.purging', 'trace', true);
    DELETE FROM trace.call c WHERE c.evaluation_plugin = ANY (p_evaluation_plugins);
    PERFORM set_config('aisc.purging', '', true);
    RETURN jsonb_build_object('calls', total, 'trace_digests', digests);
END $$;

REVOKE ALL ON trace.purged FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, TRIGGER, REFERENCES ON trace.purged FROM platform_rw;
GRANT SELECT ON trace.purged TO platform_rw;
REVOKE ALL ON FUNCTION trace.purge_runs(uuid[], text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION trace.purge_runs(uuid[], text, text) TO platform_rw;
