"""A project's database is named by one rule, aisc_identity.projectdb. Every projectdb module that can import it
does, keeping its own names as aliases; the copies that cannot (report generator, consistency checks, schema
diagrams, the report bed) run the shared cases, projectdb-cases.json, in their suites.

Read-only: the source files as text.
"""

from conftest import ROOT

IMPORTERS = ["platform/platform_service/projectdb.py", "apps/backend/aisc_backend/projectdb.py",
             "apps/control-objectives/src/aisc_control_objectives/projectdb.py",
             "apps/report-composer/report_composer/projectdb.py"]
COPIES = {"apps/report-generator/report_renderer/data/scope.py": "apps/report-generator/tests",
          "scripts/db_consistency/checks.py": "scripts/tests",
          "inspector/schema-docs/server.py": "scripts/tests",
          "scripts/lib/report_bed.py": "scripts/tests"}


def test_every_projectdb_module_imports_the_shared_rule():
    own = [f for f in IMPORTERS if "from aisc_identity.projectdb import" not in (ROOT / f).read_text()
           or '"project_" +' in (ROOT / f).read_text()]
    assert own == [], "these name a project's database by a rule of their own"


def test_every_copy_runs_the_shared_cases():
    missing = []
    for copy, suite in COPIES.items():
        tests = [p for p in (ROOT / suite).rglob("test_*.py") if p.name != "test_projectdb_one_rule.py"]
        if not any("projectdb-cases.json" in p.read_text() and copy.rsplit("/", 1)[-1].removesuffix(".py")
                   in p.read_text() for p in tests):
            missing.append(copy)
    assert missing == [], "these copies are not held to the shared cases"
