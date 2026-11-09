"""The test beds' copies of the risk tables have the columns the modules' migrations leave.

A risk no longer records the provider's measure against it (control, its VAIR term) or what follows
when that is not enough (follow-up control, its term): qualification's and control-objectives'
migrations drop those columns. The report bed (fixtures/report: schemas and seeds) and the
live-shape snapshot (fixtures/isolation/live_shape.sql) must not create, add or fill them.
"""
import re

import pytest

from conftest import ROOT

FIXTURES = ROOT / "scripts/tests/fixtures"
GONE = {"qualification.qualification_risk": {"control", "control_term", "followUpControl", "follow_up_control_term"},
        "control_objectives.risk": {"control", "follow_up_control"}}


def _columns_created(text: str, table: str) -> set[str]:
    m = re.search(rf"^CREATE TABLE {re.escape(table)} \((.*?)^\);", text, re.M | re.S)
    if not m:
        return set()
    return {line.strip().split()[0].strip('"') for line in m.group(1).splitlines() if line.strip()}


def _columns_added(text: str, table: str) -> set[str]:
    return set(re.findall(rf"^ALTER TABLE {re.escape(table)} ADD COLUMN \"?(\w+)\"?", text, re.M))


def _columns_inserted(text: str, table: str) -> set[str]:
    cols = set()
    for m in re.finditer(rf"^INSERT INTO {re.escape(table)} \(([^)]*)\)", text, re.M):
        cols |= {c.strip().strip('"') for c in m.group(1).split(",")}
    return cols


@pytest.mark.parametrize("path", ["report/schema_qualification.sql", "report/schema_control_objectives.sql",
                                  "isolation/live_shape.sql"])
def test_no_schema_copy_creates_a_risk_measure_column(path):
    text = (FIXTURES / path).read_text()
    for table, gone in GONE.items():
        assert not gone & (_columns_created(text, table) | _columns_added(text, table)), (path, table)


@pytest.mark.parametrize("path", ["report/seed_platform.sql", "report/seed_tools.sql"])
def test_no_seed_fills_a_risk_measure_column(path):
    text = (FIXTURES / path).read_text()
    for table, gone in GONE.items():
        assert _columns_inserted(text, table), (path, table)
        assert not gone & _columns_inserted(text, table), (path, table)
