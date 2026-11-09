"""The barrier before a query runs anywhere (spec R4, R5): one read-only SELECT, tables on the reader list only,
functions on an allow list only. The database role is the second barrier; this one says why a query was refused.

The fingerprint is the SHA-256 of the exact text: what a person validates is what runs (R3)."""
from __future__ import annotations

import hashlib

import sqlglot
from sqlglot import exp

#: functions a chart query may call: aggregates, conditionals, text, dates, maths, JSON reading, window functions
ALLOWED_FUNCTIONS = frozenset("""
avg count sum min max stddev stddev_pop stddev_samp variance var_pop var_samp percentile_cont percentile_disc mode
bool_and bool_or every string_agg array_agg json_agg jsonb_agg json_object_agg jsonb_object_agg
coalesce nullif greatest least case if
lower upper initcap trim btrim ltrim rtrim length char_length substring substr replace split_part position strpos
left right concat concat_ws format lpad rpad reverse regexp_replace regexp_match starts_with string_to_array
array_to_string unnest array_length cardinality to_char to_date to_timestamp to_number
date_trunc date_part extract now current_timestamp current_date age make_date make_interval
abs round ceil ceiling floor trunc mod power sqrt exp ln log sign width_bucket
jsonb_array_length json_array_length jsonb_extract_path_text json_extract_path_text jsonb_typeof json_typeof
jsonb_array_elements jsonb_array_elements_text json_array_elements jsonb_object_keys json_object_keys
row_number rank dense_rank percent_rank cume_dist ntile lag lead first_value last_value nth_value
cast try_cast
""".split())


class QueryRefused(ValueError):
    """Why a query may not run."""


def fingerprint(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _function_name(node: exp.Expression) -> str:
    """The name PostgreSQL would call: the parser's own names (TIME_TO_STR for to_char) are not what runs."""
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    written = node.sql(dialect="postgres")
    head = written.split("(", 1)[0].strip().lower()
    return head if head.replace("_", "").isalnum() else (node.sql_name() or type(node).__name__).lower()


def _defined_in_scope(table: exp.Table, name: str) -> bool:
    """Whether a WITH item called name is visible where table stands, as PostgreSQL resolves it: the WITH of the
    query table is in or of any query around it; inside a WITH item, only the items before it (all of them when the
    WITH is RECURSIVE). A name defined elsewhere does not hide a table of that name (pg_catalog's, for one)."""
    child, node = table, table.parent
    while node is not None:
        if isinstance(node, exp.With):
            items = node.expressions
            at = next((i for i, item in enumerate(items) if item is child), len(items))
            visible = items if node.args.get("recursive") else items[:at]
            if any(item.alias_or_name.lower() == name for item in visible):
                return True
        else:
            with_ = node.args.get("with")
            if with_ is not None and with_ is not child and any(
                    item.alias_or_name.lower() == name for item in with_.expressions):
                return True
        child, node = node, node.parent
    return False


def check(sql: str, readers: set[str] | frozenset[str]) -> str:
    """The query, normalised, when it may run; QueryRefused otherwise. readers: "schema.table" names."""
    if not isinstance(sql, str) or not sql.strip():
        raise QueryRefused("the query is empty")
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.SqlglotError as exc:
        raise QueryRefused(f"the query cannot be read: {str(exc).splitlines()[0]}") from None
    if len(statements) != 1:
        raise QueryRefused("one query only")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise QueryRefused("only a SELECT (or WITH ... SELECT) may run")
    for node in tree.walk():
        if isinstance(node, (exp.Into, exp.Lock)):
            raise QueryRefused("only a plain SELECT may run: no INTO, no FOR UPDATE")
        if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command)):
            raise QueryRefused("only a SELECT may run")
    for table in tree.find_all(exp.Table):
        if isinstance(table.this, exp.Anonymous) or table.this is None:
            continue
        name = table.name.lower()
        schema = (table.db or "").lower()
        if not schema and _defined_in_scope(table, name):
            continue
        if f"{schema}.{name}" not in readers:
            raise QueryRefused(f"table {(schema + '.' if schema else '') + name} is not one the assistant may read")
    for node in tree.find_all(exp.Func):
        if isinstance(node, (exp.Cast, exp.TryCast, exp.Case, exp.If, exp.JSONExtract, exp.JSONExtractScalar,
                             exp.JSONBExtract, exp.JSONBExtractScalar, exp.Coalesce, exp.Paren)):
            continue
        name = _function_name(node)
        if name not in ALLOWED_FUNCTIONS:
            raise QueryRefused(f"function {name} is not one a chart query may call")
    for node in tree.find_all(exp.Table):
        if isinstance(node.this, exp.Anonymous):
            name = str(node.this.this).lower()
            if name not in ALLOWED_FUNCTIONS:
                raise QueryRefused(f"function {name} is not one a chart query may call")
    return tree.sql(dialect="postgres")
