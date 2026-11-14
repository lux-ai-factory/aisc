"""The engine webapp tests and the results dashboard sign-in tests run in CI, and CI runs on the working
branch.

The webapp's vitest files and the dashboard's SSO tests (tests/test_sso_login.py, which needs the built
image) never ran anywhere: no CI job ran them and the dashboard row ignored the file. The node matrix now
carries each app's typecheck and tests, and the registry has a row that runs the sign-in tests inside the
built image.

Read-only: the workflow and scripts/suites.py are read, nothing is run.
"""
from __future__ import annotations

import sys

import yaml

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import suites  # noqa: E402

CI = ROOT / ".github/workflows/ci.yml"


def node_matrix() -> dict[str, dict]:
    include = yaml.safe_load(CI.read_text())["jobs"]["node"]["strategy"]["matrix"]["include"]
    return {entry["app"]: entry for entry in include}


def test_the_engine_webapp_tests_run_in_ci():
    matrix = node_matrix()
    assert "webapp" in matrix, f"the node matrix runs only {sorted(matrix)}"
    webapp = matrix["webapp"]
    assert webapp.get("tests") == "npx vitest run"
    row = next(s for s in suites.SUITES if s.name == "engine webapp")
    assert row.command == "cd apps/webapp && " + webapp["tests"]


def test_each_node_app_says_its_typecheck_and_tests():
    for app, entry in node_matrix().items():
        assert entry.get("typecheck") and entry.get("tests"), f"{app} has no typecheck or tests in the matrix"


def test_the_node_steps_run_the_matrix_commands():
    steps = yaml.safe_load(CI.read_text())["jobs"]["node"]["steps"]
    runs = [str(step.get("run", "")) for step in steps]
    assert "${{ matrix.typecheck }}" in runs and "${{ matrix.tests }}" in runs, runs
    database = [step for step in steps if step.get("run") == "${{ matrix.database }}"]
    assert database and database[0].get("if") == "matrix.database", "the database step runs for every app"


def test_the_dashboard_sign_in_tests_run_inside_the_built_image():
    row = next((s for s in suites.SUITES if s.name == "results dashboard sso"), None)
    assert row is not None, "no suite row runs the dashboard's sign-in tests"
    assert row.ci and "docker build" in row.command and "tests/test_sso_login.py" in row.command
    assert "--ignore" not in row.command


def test_ci_runs_on_pushes_to_the_working_branch():
    on = yaml.safe_load(CI.read_text())[True]          # PyYAML reads the key `on` as True
    assert "pilot" in on["push"]["branches"]
