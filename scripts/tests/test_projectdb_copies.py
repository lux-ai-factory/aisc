"""Three copies of the project-database rule cannot import aisc_identity.projectdb (they run with no shared code
on their path): the consistency checks (db_consistency/checks.py), the schema diagrams server
(inspector/schema-docs/server.py) and the report bed (lib/report_bed.py). Each is held here to the shared cases,
shared/identity/projectdb-cases.json: a database name is a project's only when the shared rule gives a pid for it,
and a pid names the database the shared rule names. The copies do not refuse a pid themselves (their pids come
from core.project), so the refused pids are the shared rule's alone."""
import importlib.util
import json
import sys

import pytest

from conftest import ROOT

CASES = json.loads((ROOT / "shared/identity/projectdb-cases.json").read_text())
NAMED = [case for case in CASES["names"] if not case.get("refused")]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checks():
    sys.path.insert(0, str(ROOT / "scripts"))
    from db_consistency import checks
    return checks


@pytest.fixture(scope="module")
def server():
    return _load("schema_docs_projectdb", ROOT / "inspector/schema-docs/server.py")


@pytest.fixture(scope="module")
def report_bed():
    return _load("report_bed_projectdb", ROOT / "scripts/lib/report_bed.py")


class _Rows:
    def __init__(self, pid):
        self.platform_db, self.pid = "platform", pid

    def rows(self, database, sql):
        return [(self.pid, "slug")]


@pytest.mark.parametrize("case", CASES["pids"], ids=lambda c: c["name"])
def test_checks_and_server_take_a_name_for_a_project_database_as_the_shared_rule_does(checks, server, case):
    is_project = case["pid"] is not None
    assert bool(checks.PROJECT_DB.match(case["name"])) == is_project
    # the diagrams also serve the platform database itself
    assert bool(server.DATABASE.match(case["name"])) == (is_project or case["name"] == "platform")


@pytest.mark.parametrize("case", NAMED, ids=lambda c: c["pid"])
def test_checks_and_the_report_bed_name_a_pids_database_as_the_shared_rule_does(checks, report_bed, case):
    assert list(checks.core_projects(_Rows(case["pid"]))) == [case["name"]]
    assert report_bed.project_db(case["pid"]) == case["name"]
