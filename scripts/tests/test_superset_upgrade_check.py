"""The Superset upgrade check (plugin dashboards 2026-10-04, T8): scripts/check-superset-upgrade.sh.

Static checks always; the live run (it starts containers, about 3 minutes) only with AISC_SUPERSET_CHECK=1:
it passes on the stack's Superset and fails, naming the charts, when a column they read is removed."""
import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

SCRIPT = ROOT / "scripts/check-superset-upgrade.sh"
CHECKER = ROOT / "scripts/superset_upgrade_check.py"
FIXTURES = ROOT / "scripts/fixtures/superset_upgrade"


def test_t8_it_uses_throwaway_containers_only_and_removes_them():
    text = SCRIPT.read_text()
    assert os.access(SCRIPT, os.X_OK)
    names = re.findall(r'(NET|PG|REDIS|SUP)="(aisc-t-sup-[a-z-]*)\$TAG"', text)
    assert {n for n, _ in names} == {"NET", "PG", "REDIS", "SUP"}
    assert "trap cleanup EXIT" in text and "docker rm -f" in text and "docker network rm" in text
    published = re.findall(r"-p\s+(\S+)", text)                       # only Superset, on a free local port
    assert published == ['"127.0.0.1:$PORT:8088"'], published


def test_t8_it_runs_the_stacks_superset_by_default_and_the_real_extension():
    text = SCRIPT.read_text()
    stock = re.search(r"^FROM (\S+)", (ROOT / "apps/results-dashboard/Dockerfile").read_text(), re.M).group(1)
    assert f'IMAGE="${{1:-{stock}}}"' in text
    assert "superset_config.py:/app/pythonpath/superset_config.py:ro" in text
    assert "aisc_ext:/app/pythonpath/aisc_ext:ro" in text


def test_t8_the_fixture_holds_the_plugins_real_default_charts():
    fixture = json.loads((FIXTURES / "visualizations.json").read_text())
    labels = [p["label"] for p in fixture["plugins"]]
    assert labels == ["Data Drift", "LangBiTe"]
    assert all(p["visualizations"] for p in fixture["plugins"])
    sql = (FIXTURES / "project.sql").read_text()
    assert "data-monitor::DataDriftPlugin (v0.4.1)" in sql and "LangBiteEvaluationPlugin (v0.2.6)" in sql


def test_t8_verify_offers_it_as_an_opt_in():
    assert "--superset-upgrade" in (ROOT / "scripts/verify.sh").read_text()


@pytest.mark.skipif(os.environ.get("AISC_SUPERSET_CHECK") != "1" or not shutil.which("docker"),
                    reason="the live check starts containers: AISC_SUPERSET_CHECK=1")
def test_t8_1_t8_2_it_passes_and_fails_when_it_should():
    ok = subprocess.run([str(SCRIPT)], capture_output=True, text=True, timeout=1200)
    assert ok.returncode == 0, ok.stdout[-2000:]
    assert "all checks held" in ok.stdout
    broken = subprocess.run([str(SCRIPT), "--break"], capture_output=True, text=True, timeout=1200)
    assert broken.returncode != 0
    assert "FAIL Data Drift: chart 'Default · PSI per feature'" in broken.stdout


def test_t8_it_checks_syncs_at_once_and_a_stale_dataset():
    """2026-10-05 on the stack: two syncs at once failed on the dashboard's slug, and a dataset registered
    by older code kept no run column. The live check covers both, before --break removes its column."""
    text = (ROOT / "scripts/superset_upgrade_check.py").read_text()
    assert "three at once" in text and "one dashboard after the syncs at once" in text
    assert "a stale results dataset is brought up to date by the next sync" in text
    assert text.index("brought up to date by the next sync") < text.index("if args.broken:")


def test_t8_supersets_own_data_is_in_postgres_as_on_the_stack():
    """The project lock is a Postgres advisory lock: on SQLite the syncs-at-once check would prove nothing."""
    text = SCRIPT.read_text()
    assert 'CREATE DATABASE superset' in text
    assert 'SUPERSET_DB_URI="postgresql+psycopg2://aisc-postgres-user:$PG_PW@$PG:5432/superset"' in text
    assert "sqlite:" not in text


def test_t8_the_check_reads_langbites_failed_answers_on_its_tile():
    """LangBiTe 0.2.6: the tile lists every failed answer as the target gave it (fixture project.sql)."""
    sql = (FIXTURES / "project.sql").read_text()
    text = (ROOT / "scripts/superset_upgrade_check.py").read_text()
    for answer in ("Yes, on average women are less suited to engineering.", "No, gender does not decide that."):
        assert answer in sql and answer in text
    fixture = json.loads((FIXTURES / "visualizations.json").read_text())
    langbite = next(p for p in fixture["plugins"] if p["label"] == "LangBiTe")
    assert [v["title"] for v in langbite["visualizations"]] == ["Pass rate per concern", "Failed cases"]
