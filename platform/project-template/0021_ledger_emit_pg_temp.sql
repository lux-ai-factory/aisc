-- ledger.emit runs as its owner (SECURITY DEFINER): pg_temp last on its search_path, as the PostgreSQL
-- documentation advises, so an unqualified name can never resolve to a caller's temporary table.
-- Every name in it is schema-qualified; this keeps it safe if one is not.
ALTER FUNCTION ledger.emit(jsonb) SET search_path = pg_catalog, ledger, pg_temp;
