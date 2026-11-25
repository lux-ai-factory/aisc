"""The mock database: the reader tables with the real structure and invented rows, coherent enough that a chart query
written for the real data runs on it, and with the awkward cases put in on purpose."""
import itertools
import random
import subprocess
import uuid
from pathlib import Path

import pytest

from chart_assistant import mock
from chart_assistant.description import fixed_model

CRITERION = Path(__file__).parent / "fixtures" / "bias-plots"
PROJECT = {
    "targets": ["OpenAI back-end", "Local back-end"],
    "metrics": [{"name": "Conversation", "dimensions": {
        "category": {"type": "text", "values": ["AGE", "BASELINE"]},
        "community": {"type": "text", "values": ["18", "70", "-"]},
        "slot": {"type": "number", "values": [0, 1]},
        "scenario": {"type": "text", "values": ["P1", "P2"]},
        "register": {"type": "text", "values": ["basic", "broken"]},
        "language": {"type": "text", "values": ["en", "nl"]},
        "repetition": {"type": "number", "values": [1]},
        "outcome": {"type": "text", "values": ["referral", "no referral"]},
        "organisations": {"type": "text", "values": None}}}]}


def test_the_tables_are_made_with_every_described_column_and_no_constraint():
    ddl = mock.ddl(fixed_model())
    assert ddl.count("CREATE TABLE") == len(fixed_model())
    assert '"regulationIds" text[]' in ddl and "REFERENCES" not in ddl and "PRIMARY KEY" not in ddl


def test_every_label_value_appears_and_free_text_gets_a_small_pool_so_rows_can_be_equal():
    rows = mock.rows(PROJECT, random.Random(1))
    dims = [r["dimensions"] for r in rows["engine.aisc_backend_measurement"]]
    for key in ("category", "community", "register", "language", "outcome"):
        assert {d.get(key) for d in dims} >= set(PROJECT["metrics"][0]["dimensions"][key]["values"]), key
    organisations = [d["organisations"] for d in dims]
    assert 1 < len(set(organisations)) < len(organisations)


def test_the_awkward_cases_are_there():
    rows = mock.rows(PROJECT, random.Random(1))
    dims = [r["dimensions"] for r in rows["engine.aisc_backend_measurement"]]
    assert any(d.get("organisations") == "" for d in dims)                         # an empty value
    keys = [tuple(sorted(d.items())) for d in dims]
    assert len(keys) != len(set(keys))                                             # a duplicated row
    assert any(r["score"] is None for r in rows["engine.aisc_backend_measurement"])  # a missing score


def test_each_target_is_a_run_the_results_reach_through_their_ids():
    rows = mock.rows(PROJECT, random.Random(1))
    labels = {t["label"] for t in rows["target.target"]}
    assert labels == set(PROJECT["targets"])
    plugin_runs = {r["id"] for r in rows["engine.aisc_backend_evaluationplugin"]}
    observations = {o["id"]: o for o in rows["engine.aisc_backend_observation"]}
    assert all(observations[m["observation_id"]]["evaluation_plugin_id"] in plugin_runs
               for m in rows["engine.aisc_backend_measurement"])
    components = {c["pid"] for c in rows["engine.aisc_backend_aicomponent"]}
    assert {t["engine_component"] for t in rows["target.target"]} <= components


def test_the_same_seed_gives_the_same_rows():
    assert mock.rows(PROJECT, random.Random(7)) == mock.rows(PROJECT, random.Random(7))


def psql(db, sql, user_flag=True):
    return subprocess.run(["docker", "exec", "-i", "aisc-063319-postgres", "sh", "-c", f'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d {db} -At'],
                          input=sql, capture_output=True, text=True)


@pytest.mark.db
def test_the_criterion_of_mijke_conversations_compared_runs_on_the_mock():
    name = "assistant_mock_test_" + uuid.uuid4().hex[:8]
    assert psql("postgres", f"CREATE DATABASE {name};").returncode == 0
    try:
        load = psql(name, mock.ddl(fixed_model()) + mock.inserts(mock.rows(PROJECT, random.Random(3))))
        assert load.returncode == 0, load.stderr[-500:]
        sql = (CRITERION / "base.sql").read_text() + (CRITERION / "vs_baseline.sql").read_text()
        out = psql(name, f"SELECT model, count(*) FROM ({sql}) v GROUP BY 1 ORDER BY 1;")
        assert out.returncode == 0, out.stderr[-500:]
        assert [line.split("|")[0] for line in out.stdout.splitlines()] == ["Local back-end", "OpenAI back-end"]
    finally:
        psql("postgres", f"DROP DATABASE IF EXISTS {name};")


RANGED = {"targets": ["T"], "metrics": [{"name": "Jailbreak success", "score": {"min": 0.2, "max": 0.4},
                                         "dimensions": {"category": {"type": "text", "values": ["cv", "health"]},
                                                        "slot": {"type": "number", "values": None, "min": 3, "max": 9}}}]}


def test_scores_are_drawn_between_the_first_runs_min_and_max():
    scores = [r["score"] for r in mock.rows(RANGED, random.Random(2))["engine.aisc_backend_measurement"] if r["score"] is not None]
    assert scores and all(0.2 <= s <= 0.4 for s in scores)


def test_a_numeric_label_without_listed_values_is_drawn_in_its_range():
    dims = [r["dimensions"] for r in mock.rows(RANGED, random.Random(2))["engine.aisc_backend_measurement"]]
    assert all(3 <= d["slot"] <= 9 and isinstance(d["slot"], int) for d in dims)


def test_whole_number_scores_stay_whole_numbers():
    whole = {"targets": ["T"], "metrics": [{"name": "Conversation", "score": {"min": 0, "max": 1, "whole": True},
                                            "dimensions": {"category": {"type": "text", "values": ["a", "b", "c", "d"]}}}]}
    scores = {r["score"] for r in mock.rows(whole, random.Random(2))["engine.aisc_backend_measurement"] if r["score"] is not None}
    assert scores <= {0, 1}


def test_without_a_range_scores_stay_between_0_and_1():
    scores = [r["score"] for r in mock.rows(PROJECT, random.Random(2))["engine.aisc_backend_measurement"] if r["score"] is not None]
    assert all(0 <= s <= 1 for s in scores)


def test_many_label_combinations_are_drawn_without_building_them_all(monkeypatch):
    product = itertools.product

    def product_that_must_not_be_built(*iterables):
        for n, combo in enumerate(product(*iterables)):
            if n > 10 * mock.MAX_COMBINATIONS:
                raise AssertionError("every combination is being built")
            yield combo
    monkeypatch.setattr(mock.itertools, "product", product_that_must_not_be_built, raising=True)
    values = [f"v{i}" for i in range(40)]
    wide = {"targets": ["T"], "metrics": [{"name": "M", "dimensions": {
        k: {"type": "text", "values": values} for k in ("a", "b", "c", "d", "e", "f")}}]}
    made = mock.rows(wide, random.Random(4))["engine.aisc_backend_measurement"]
    combos = {tuple(sorted(m["dimensions"].items())) for m in made}
    assert len(combos) == mock.MAX_COMBINATIONS - 1                    # one left out on purpose, one duplicated
    assert all(set(m["dimensions"]) == set("abcdef") and set(m["dimensions"].values()) <= set(values) for m in made)
    assert mock.rows(wide, random.Random(4)) == mock.rows(wide, random.Random(4))


def test_a_decimal_label_range_stays_decimal_and_inside_its_range():
    decimal = {"targets": ["T"], "metrics": [{"name": "M", "dimensions": {
        "category": {"type": "text", "values": ["a", "b", "c", "d", "e"]},
        "temperature": {"type": "number", "values": None, "min": 0.2, "max": 0.7}}}]}
    drawn = [r["dimensions"]["temperature"] for r in mock.rows(decimal, random.Random(2))["engine.aisc_backend_measurement"]]
    assert all(0.2 <= t <= 0.7 for t in drawn) and any(t != int(t) for t in drawn)


def test_a_label_range_marked_whole_stays_whole():
    whole = {"targets": ["T"], "metrics": [{"name": "M", "dimensions": {
        "category": {"type": "text", "values": ["a", "b", "c", "d", "e"]},
        "turn": {"type": "number", "values": None, "min": 1.0, "max": 4.0, "whole": True}}}]}
    drawn = [r["dimensions"]["turn"] for r in mock.rows(whole, random.Random(2))["engine.aisc_backend_measurement"]]
    assert all(t in (1, 2, 3, 4) and isinstance(t, int) for t in drawn)


def test_the_runs_of_the_mock_have_names_two_card_versions_and_one_that_did_not_finish():
    rows = mock.rows(PROJECT, random.Random(1))
    assert all(p["name"] for p in rows["engine.aisc_backend_evaluationplugin"])
    assert {e["status"] for e in rows["engine.aisc_backend_evaluation"]} == {"Done", "Failed"}
    versions = {s["pid"]: s["number"] for s in rows["project.system"]}
    assert {versions[e["system_id"]] for e in rows["engine.aisc_backend_evaluation"]} == {1, 2}
