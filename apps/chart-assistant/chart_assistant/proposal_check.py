"""The gates a proposal passes before a person sees it, beyond query_check (which says what may run).

A query may read from `dimensions` only the keys the project's results have: a key that does not exist reads NULL on
every row, and the chart shows nothing, or one empty group, while looking valid. And its result on the mock data must
give each chart point one filled row: a column empty in every row reads something this data does not have, and several
rows for one point would be drawn as their maximum. A table may list rows as they come."""
from __future__ import annotations

from collections import Counter

import sqlglot
from sqlglot import exp

_EXTRACTS = (exp.JSONExtract, exp.JSONExtractScalar, exp.JSONBExtract, exp.JSONBExtractScalar)


def _first_key(node: exp.Expression) -> str | None:
    """The first key of an extraction whose innermost operand is a column called dimensions; None otherwise."""
    inner, key = node, None
    while isinstance(inner, _EXTRACTS):
        path = inner.expression
        if isinstance(path, exp.JSONPath):
            keys = [p.this for p in path.expressions if isinstance(p, exp.JSONPathKey)]
        elif isinstance(path, exp.Literal) and path.name.startswith("{") and path.name.endswith("}"):
            keys = [k.strip().strip('"') for k in path.name[1:-1].split(",") if k.strip()]   # #>> '{a,b}'
        elif isinstance(path, exp.Literal):
            keys = [path.name]
        else:
            keys = []
        key = keys[0] if keys else None
        inner = inner.this
    return key if isinstance(inner, exp.Column) and inner.name.lower() == "dimensions" else None


def dimension_keys(sql: str) -> set[str]:
    """The keys a query reads from a column called dimensions, with -> or ->>, anywhere in it."""
    tree = sqlglot.parse_one(sql, read="postgres")
    found = set()
    for node in tree.find_all(*_EXTRACTS):
        if isinstance(node.parent, _EXTRACTS) and node.parent.this is node:
            continue                       # the inner part of a longer path: its outermost extraction names the key
        key = _first_key(node)
        if key is not None:
            found.add(key)
    return found


def unknown_keys(sql: str, known: frozenset[str]) -> list[str]:
    """The dimension keys a query reads that the project's results do not have, sorted."""
    return sorted(dimension_keys(sql) - set(known))


def result_problem(chart: dict, result: dict) -> str | None:
    """What is wrong with a proposal's result on the mock data, or None."""
    columns, rows = list(result.get("columns") or []), list(result.get("rows") or [])
    if not rows:
        return "the query returns no rows on the mock data"
    for role in ("category", "series", "value"):
        name = chart.get(role)
        if not name or name not in columns:
            continue
        at = columns.index(name)
        if all(row[at] is None for row in rows):
            return f"'{name}' is empty in every row: it reads something this data does not have"
    if chart.get("kind") == "table":
        return None
    point = [columns.index(chart[r]) for r in ("category", "series") if chart.get(r) and chart[r] in columns]
    largest = max(Counter(tuple(row[i] for i in point) for row in rows).values())
    if largest > 1:
        return f"{largest} rows share the same category and series: aggregate so that each has one row"
    return None
