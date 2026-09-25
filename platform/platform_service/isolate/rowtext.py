"""Row text, checksums and key filters (01-specs.md I12.7, I12.10).

Both sides of every comparison run under SETTINGS, so ROW(...)::text is the same text
for the same value on the source and on the target (floats, bytea, timestamps).
"""
from __future__ import annotations

from psycopg import sql

SETTINGS = (
    ("TimeZone", "UTC"),
    ("DateStyle", "ISO"),
    ("extra_float_digits", "3"),
    ("bytea_output", "hex"),
    ("IntervalStyle", "postgres"),
)


def apply_settings(conn, local: bool = True) -> None:
    for name, value in SETTINGS:
        conn.execute(sql.SQL("SET {} {} = {}").format(
            sql.SQL("LOCAL") if local else sql.SQL(""), sql.Identifier(name), sql.Literal(value)))


def ident(table: str) -> sql.Composable:
    return sql.Identifier(*table.split("."))


def cols_sql(cols) -> sql.Composable:
    return sql.SQL(", ").join(sql.Identifier(c) for c in cols)


def key_filter(pk: tuple[str, ...], keys) -> sql.Composable:
    """`(pk::text, ...) IN (VALUES ...)` for a set of text keys; FALSE for none."""
    keys = sorted(keys)
    if not keys:
        return sql.SQL("FALSE")
    left = sql.SQL("({})").format(sql.SQL(", ").join(sql.SQL("{}::text").format(sql.Identifier(c)) for c in pk))
    values = sql.SQL(", ").join(
        sql.SQL("({})").format(sql.SQL(", ").join(sql.Literal(v) for v in k)) for k in keys)
    return sql.SQL("{} IN (VALUES {})").format(left, values)


def checksum(conn, table: str, cols, pk, keys=None) -> tuple[int, str]:
    """count and md5(string_agg(ROW(cols)::text, E'\\n' ORDER BY row_text)) over the rows with
    these keys (every row when keys is None), exactly the formula of I12.10."""
    where = sql.SQL("") if keys is None else sql.SQL(" WHERE ") + key_filter(pk, keys)
    q = sql.SQL(
        "SELECT count(*), md5(coalesce(string_agg(r, E'\\n' ORDER BY r), '')) FROM"
        " (SELECT ROW({cols})::text AS r FROM {t}{w}) s").format(cols=cols_sql(cols), t=ident(table), w=where)
    n, md5 = conn.execute(q).fetchone()
    return int(n), md5


def key_md5s(conn, table: str, cols, pk) -> dict[tuple, str]:
    """Every row's key (text) -> md5 of its row text over `cols`."""
    q = sql.SQL("SELECT {keys}, md5(ROW({cols})::text) FROM {t}").format(
        keys=sql.SQL(", ").join(sql.SQL("{}::text").format(sql.Identifier(c)) for c in pk),
        cols=cols_sql(cols), t=ident(table))
    return {tuple(r[:-1]): r[-1] for r in conn.execute(q).fetchall()}


def count(conn, table: str) -> int:
    return int(conn.execute(sql.SQL("SELECT count(*) FROM {}").format(ident(table))).fetchone()[0])
