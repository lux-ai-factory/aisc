-- ledger.emit runs as its owner (SECURITY DEFINER): pg_temp last on its search_path, as the PostgreSQL
-- documentation advises, so a later unqualified name can never be a caller's temporary table (phase 3
-- review m11). Every name in it is schema-qualified today; this keeps it safe if one is not.
ALTER FUNCTION ledger.emit(jsonb) SET search_path = pg_catalog, ledger, pg_temp;
