"""`Throwaway.rows()` of scripts/pipeline_chain/throwaway.py (report run v2, part 2: 10-specs-part2.md
R2-D3.5.1, authorised by the user in BRIEF-2 D3.5).

`rows()` must return the query's rows as dicts for 0, 1 and many rows, and for values holding newlines, quotes
and non-ASCII text. psql's aligned output spreads json_agg over several lines and ends with a row-count footer
such as "(1 row)"; the helper must parse psql's whole tuples-only unaligned output as one JSON value and never
read that footer. On a failing query it raises AssertionError with psql's message, as today.

One throwaway postgres:14-alpine container (aisc-t-rows-<hex>, a kernel-chosen port, never the host's 5432),
removed at the end of the module.

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_throwaway_rows.py
"""

import inspect
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts/pipeline_chain"))
from throwaway import Throwaway  # noqa: E402


@pytest.fixture(scope="module")
def pg():
    t = Throwaway.start("rows")
    try:
        t.psql("platform", "CREATE TABLE note (id int PRIMARY KEY, body text);\n"
                           "INSERT INTO note VALUES (1, 'one'), (2, 'two'), (3, 'three');\n")
        yield t
    finally:
        t.stop()


def test_r2_d3_5_1_the_signature_is_unchanged():
    params = list(inspect.signature(Throwaway.rows).parameters)
    assert params == ["self", "db", "sql", "role"]


def test_r2_d3_5_1_no_rows_is_an_empty_list(pg):
    assert pg.rows("platform", "SELECT id FROM note WHERE id > 100") == []


def test_r2_d3_5_1_one_row(pg):
    assert pg.rows("platform", "SELECT id, body FROM note WHERE id = 1") == [{"id": 1, "body": "one"}]


def test_r2_d3_5_1_many_rows_spread_over_several_lines(pg):
    got = pg.rows("platform", "SELECT id, body FROM note ORDER BY id")
    assert got == [{"id": 1, "body": "one"}, {"id": 2, "body": "two"}, {"id": 3, "body": "three"}]


@pytest.mark.parametrize("expr, value", [
    ("'line one' || chr(10) || 'line two'", "line one\nline two"),
    ("'she said \"yes\"'", 'she said "yes"'),
    ("'it''s'", "it's"),
    ("'(1 row)'", "(1 row)"),
    ("'Évaluation, 日本語, ✓'", "Évaluation, 日本語, ✓"),
    ("'a | b + c'", "a | b + c"),
])
def test_r2_d3_5_1_awkward_text_values_come_back_as_written(pg, expr, value):
    got = pg.rows("platform", f"SELECT {expr}::text AS v UNION ALL SELECT 'second'")
    assert got == [{"v": value}, {"v": "second"}]


def test_r2_d3_5_1_a_multiline_query_still_works(pg):
    got = pg.rows("platform", "SELECT id\n  FROM note\n WHERE id <= 2\n ORDER BY id")
    assert got == [{"id": 1}, {"id": 2}]


def test_r2_d3_5_1_a_failing_query_raises_assertion_error_with_the_psql_message(pg):
    with pytest.raises(AssertionError) as e:
        pg.rows("platform", "SELECT * FROM no_such_table")
    assert "no_such_table" in str(e.value)
