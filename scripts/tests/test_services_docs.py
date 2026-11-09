"""docs/appendices/services.md has a row for every service compose runs, and data.md names every database a
service makes on the shared Postgres: an operator reading them learns what runs and where its data lives."""
import re

import yaml

from conftest import ROOT

COMPOSE = ("docker-compose-infra.development.yml", "docker-compose.development.yml")


def test_every_compose_service_has_a_row_in_services_md():
    first_cells = re.findall(r"^\| ([^|]+) \|", (ROOT / "docs/appendices/services.md").read_text(), re.M)
    rows = {name for cell in first_cells for name in re.findall(r"`([a-z0-9_-]+)`", cell)}
    services = {name for f in COMPOSE for name in yaml.safe_load((ROOT / f).read_text())["services"]}
    assert sorted(services - rows) == []


def test_data_md_names_the_chart_assistant_s_mock_databases():
    data = (ROOT / "docs/appendices/data.md").read_text()
    assert re.search(r"^\| `assistant_mock_[^|]*\|.*`chart-assistant`", data, re.M)
