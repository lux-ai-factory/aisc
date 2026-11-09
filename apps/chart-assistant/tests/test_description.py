"""The description of the data model: the reader tables (the same list the read-only roles are granted), each column
with its type and, for the tables a chart needs, its meaning. Checked against the scripts and the live catalog."""
import json
import re
import subprocess
from pathlib import Path

import pytest

from chart_assistant.description import READERS, fixed_model, for_model
from chart_assistant.query_check import check

ROOT = Path(__file__).resolve().parents[3]
CRITERION = Path.home() / "aisc-working-notes/bias-plots/superset"


def granted_readers() -> set[str]:
    text = (ROOT / "scripts/report-grants.sh").read_text()
    body = text[text.index("listed text[] := ARRAY["):text.index("-- the schemas a reader may enter")]
    names = set(re.findall(r"'([a-z_]+\.[a-z_]+)'", body))
    names |= {"engine." + t for t in re.findall(r"'(aisc_backend_[a-z_]+)'", body)}
    return {n for n in names if not n.startswith("engine.") or n.startswith("engine.aisc_backend_")}


def test_the_reader_list_is_the_one_the_read_only_roles_are_granted():
    assert READERS == frozenset(granted_readers())


def test_every_reader_table_is_described_and_nothing_else():
    assert set(fixed_model()) == set(READERS)


def test_the_tables_a_chart_needs_say_what_they_hold():
    model = fixed_model()
    for table in ("engine.aisc_backend_measurement", "engine.aisc_backend_metric", "engine.aisc_backend_observation",
                  "engine.aisc_backend_evaluation", "engine.aisc_backend_evaluationplugin", "target.target"):
        assert model[table]["meaning"], table
        assert all(c.get("meaning") for c in model[table]["columns"].values()), table


def test_the_risk_tables_describe_no_provider_measure():
    # the card no longer records what the provider does about a risk, and step 2 keeps no copy
    model = fixed_model()
    assert not {"control", "control_term", "followUpControl", "follow_up_control_term"} & \
        set(model["qualification.qualification_risk"]["columns"])
    assert not {"control", "follow_up_control"} & set(model["control_objectives.risk"]["columns"])


def test_the_criterion_of_mijke_conversations_compared_passes_the_check():
    sql = (CRITERION / "base.sql").read_text() + (CRITERION / "vs_baseline.sql").read_text()
    check(sql, READERS)
    check((CRITERION / "base.sql").read_text() + (CRITERION / "widest_pair.sql").read_text(), READERS)


def test_what_the_model_reads_holds_the_description_and_the_projects_metrics_and_nothing_else():
    project = {"metrics": [{"name": "Conversation", "rows": 1740,
                            "dimensions": {"category": {"type": "text", "values": ["AGE", "BASELINE"]},
                                           "organisations": {"type": "text", "values": None}}}]}
    text = for_model(project)
    assert "engine.aisc_backend_measurement" in text and "Conversation" in text and "AGE" in text
    assert "1740" not in text                    # counts of real rows are data, not structure


@pytest.mark.db
def test_every_described_column_exists_with_its_type_in_a_project_database():
    pid_db = subprocess.run(["docker", "exec", "aisc-063319-postgres", "sh", "-c",
                             'psql -U "$POSTGRES_USER" -d postgres -Atc "SELECT datname FROM pg_database WHERE datname LIKE \'project_%\' LIMIT 1"'],
                            capture_output=True, text=True).stdout.strip()
    if not pid_db:
        pytest.skip("no project database on this machine")
    sql = ("SELECT json_object_agg(table_schema||'.'||table_name||'.'||column_name, data_type) FROM information_schema.columns "
           "WHERE table_schema IN ('project','target','controls','qualification','control_objectives','engine')")
    out = subprocess.run(["docker", "exec", "aisc-063319-postgres", "sh", "-c",
                          f'psql -U "$POSTGRES_USER" -d {pid_db} -Atc "{sql}"'], capture_output=True, text=True).stdout
    catalog = json.loads(out)
    for table, spec in fixed_model().items():
        for column, c in spec["columns"].items():
            assert f"{table}.{column}" in catalog, f"{table}.{column}"
            assert catalog[f"{table}.{column}"] == c["type"], f"{table}.{column}"
        live = {k.rsplit(".", 1)[1] for k in catalog if k.rsplit(".", 1)[0] == table}
        assert live == set(spec["columns"]), table


def test_the_model_reads_each_metrics_range_and_nothing_more_of_its_values():
    text = for_model({"metrics": [{"name": "M", "score": {"min": 0.2, "max": 0.4},
                                   "dimensions": {"slot": {"type": "number", "values": None, "min": 3, "max": 9}}}]})
    assert "between 0.2 and 0.4" in text and "between 3 and 9" in text
