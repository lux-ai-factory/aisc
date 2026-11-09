"""R4, R5: a query the assistant may run is one read-only SELECT on the reader tables, with no dangerous function."""
import pytest

from chart_assistant.query_check import QueryRefused, check, fingerprint

READERS = {"engine.aisc_backend_measurement", "engine.aisc_backend_metric", "target.target", "project.system"}


def ok(sql):
    return check(sql, READERS)


def test_a_select_on_reader_tables_is_taken_and_comes_back_normalised():
    out = ok("select m.score from engine.aisc_backend_measurement m join engine.aisc_backend_metric t on t.id = m.metric_id")
    assert out.lower().startswith("select")


def test_a_with_query_is_taken():
    ok("WITH x AS (SELECT score FROM engine.aisc_backend_measurement) SELECT avg(score) FROM x")


def test_json_operators_and_aggregates_are_taken():
    ok("SELECT dimensions->>'category' AS c, avg(score) FROM engine.aisc_backend_measurement GROUP BY 1")


@pytest.mark.parametrize("sql", [
    "DELETE FROM engine.aisc_backend_measurement",
    "UPDATE engine.aisc_backend_metric SET name = 'x'",
    "INSERT INTO target.target VALUES (1)",
    "DROP TABLE target.target",
    "CREATE TABLE x (a int)",
    "SELECT 1; SELECT 2",
    "SELECT 1; DELETE FROM target.target",
    "COPY target.target TO '/tmp/x'",
    "SELECT * INTO new_table FROM target.target",
    "SELECT * FROM target.target FOR UPDATE",
])
def test_anything_but_one_read_is_refused(sql):
    with pytest.raises(QueryRefused):
        ok(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM trace.call",
    "SELECT * FROM connection.endpoint",
    "SELECT * FROM aisc_backend_measurement",
    "SELECT * FROM pg_catalog.pg_authid",
    "SELECT * FROM information_schema.tables",
    "WITH x AS (SELECT * FROM trace.call) SELECT * FROM x",
    "SELECT (SELECT count(*) FROM trace.call)",
])
def test_a_table_off_the_reader_list_is_refused(sql):
    with pytest.raises(QueryRefused, match="table"):
        ok(sql)


def test_a_name_defined_by_the_query_itself_is_not_a_table():
    ok("WITH conv AS (SELECT score FROM engine.aisc_backend_measurement) SELECT * FROM conv c JOIN conv d ON true")


@pytest.mark.parametrize("sql", [
    # a name defined inside a subquery does not cover a table of that name outside it
    "SELECT x.* FROM (WITH pg_authid AS (SELECT score FROM engine.aisc_backend_measurement) SELECT * FROM pg_authid) x"
    " CROSS JOIN pg_authid",
    # nor one in a sibling subquery
    "SELECT (SELECT count(*) FROM pg_authid), (WITH pg_authid AS (SELECT 1) SELECT count(*) FROM pg_authid)",
    # a non-recursive WITH item sees only the items before it
    "WITH a AS (SELECT * FROM pg_authid), pg_authid AS (SELECT score FROM engine.aisc_backend_measurement) SELECT * FROM a",
])
def test_a_name_defined_by_the_query_covers_only_the_tables_in_its_scope(sql):
    with pytest.raises(QueryRefused, match="table"):
        ok(sql)


def test_a_name_defined_by_an_outer_query_or_an_earlier_item_is_in_scope():
    ok("WITH a AS (SELECT score FROM engine.aisc_backend_measurement), b AS (SELECT * FROM a) "
       "SELECT (SELECT count(*) FROM b), x.* FROM (SELECT * FROM a) x")
    ok("WITH RECURSIVE n AS (SELECT 1 AS i UNION ALL SELECT i + 1 FROM n WHERE i < 3) SELECT * FROM n")


@pytest.mark.parametrize("sql", [
    "SELECT pg_sleep(10)",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT * FROM dblink('x', 'select 1') AS t(a int)",
    "SELECT lo_import('/etc/passwd')",
    "SELECT set_config('role', 'x', false)",
    "SELECT current_setting('x')",
    "SELECT nextval('x')",
])
def test_a_function_off_the_allow_list_is_refused(sql):
    with pytest.raises(QueryRefused, match="function"):
        ok(sql)


def test_an_unparsable_query_is_refused():
    with pytest.raises(QueryRefused):
        ok("SELEC score FROM")


@pytest.mark.parametrize("sql", ["SELECT 'abc", "SELECT $$abc", 'SELECT "abc'])
def test_a_query_that_cannot_even_be_split_into_words_is_refused(sql):
    with pytest.raises(QueryRefused, match="cannot be read"):
        ok(sql)


def test_the_fingerprint_is_the_sha256_of_the_exact_text():
    a = "SELECT 1 FROM target.target"
    assert fingerprint(a) == fingerprint(a) and len(fingerprint(a)) == 64
    assert fingerprint(a) != fingerprint(a + " ")


@pytest.mark.parametrize("sql", ["SELECT to_char(now(), 'DD Mon YYYY')", "SELECT string_agg(x, ',' ORDER BY x) FROM unnest(string_to_array('a,b', ',')) AS x",
                                 "SELECT dense_rank() OVER (ORDER BY 1)", "SELECT initcap(lower(btrim(' a ')))"])
def test_the_functions_the_criterion_uses_are_taken(sql):
    check(sql, READERS)
