"""The shape of one schema, read from the catalogue, to compare before and after applying a file again.

schema_shape(conn, schema) -> {"tables", "columns", "constraints", "indexes", "triggers", "policies",
"grants"}, each a set of tuples: equal shapes mean the second apply changed nothing a test can see.
"""
from __future__ import annotations

QUERIES = {
    "tables": "SELECT table_name FROM information_schema.tables WHERE table_schema = %(s)s",
    "columns": "SELECT table_name, column_name, data_type, is_nullable, column_default"
               " FROM information_schema.columns WHERE table_schema = %(s)s",
    "constraints": "SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c"
                   " JOIN pg_namespace n ON n.oid = c.connamespace WHERE n.nspname = %(s)s",
    "indexes": "SELECT tablename, indexdef FROM pg_indexes WHERE schemaname = %(s)s",
    "triggers": "SELECT t.tgrelid::regclass::text, t.tgname, pg_get_triggerdef(t.oid) FROM pg_trigger t"
                " JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace"
                " WHERE n.nspname = %(s)s AND NOT t.tgisinternal",
    "policies": "SELECT tablename, policyname, cmd, qual, with_check FROM pg_policies WHERE schemaname = %(s)s",
    "grants": "SELECT table_name, grantee, privilege_type FROM information_schema.role_table_grants"
              " WHERE table_schema = %(s)s",
}


def schema_shape(conn, schema: str) -> dict[str, set[tuple]]:
    return {key: {tuple(row) for row in conn.execute(sql, {"s": schema}).fetchall()} for key, sql in QUERIES.items()}
