"""The root CI workflow runs every Python suite of this checkout: the engine (sqlite and throwaway Postgres), the
eval worker (tests and lint), the plugin-manager, the plugin interface and the report generator, besides the
suites it ran before.

Read-only checks of .github/workflows/ci.yml. Only the root's workflow is read here; the submodules' and the
plugin repos' workflows are proven by running them.
"""

from __future__ import annotations

import shlex

import pytest
import yaml

from conftest import ROOT

CI = ROOT / ".github/workflows/ci.yml"

SUITES = {
    "identity", "platform", "control-objectives", "report-composer",
    "engine", "engine on postgres", "eval", "eval lint", "plugin-manager", "plugin-interface", "report-generator",
}


def workflow() -> dict:
    return yaml.safe_load(CI.read_text())


def triggers(doc: dict) -> dict:
    # pyyaml reads the bare key `on` as the boolean True
    return doc.get("on", doc.get(True))


def matrix_runs() -> dict[str, str]:
    include = workflow()["jobs"]["python"]["strategy"]["matrix"]["include"]
    return {entry["suite"]: str(entry["run"]) for entry in include}


def run_of(suite: str) -> str:
    runs = matrix_runs()
    assert suite in runs, f"the python matrix has no suite {suite!r}: {sorted(runs)}"
    return runs[suite]


def commands(run: str) -> list[list[str]]:
    """The commands of a one-line `run`, split at `&&`, each as its words."""
    return [shlex.split(part) for part in run.split("&&")]


def pytest_commands(run: str) -> list[list[str]]:
    return [words for words in commands(run) if "pytest" in words]


def test_the_python_matrix_holds_every_suite():
    assert set(matrix_runs()) == SUITES


def test_the_engine_runs_through_its_script_in_both_modes():
    assert commands(run_of("engine")) == [["scripts/lib/engine-tests.sh"]]
    assert commands(run_of("engine on postgres")) == [["scripts/lib/engine-tests.sh", "--postgres"]]


def test_the_eval_tests_run_in_both_deployment_modes_from_the_lock():
    run = run_of("eval")
    assert commands(run)[0] == ["cd", "apps/eval"]
    runs = pytest_commands(run)
    assert len(runs) == 2, f"eval runs pytest {len(runs)} times, not twice: {run}"
    default, configurator = runs
    assert not any(w.startswith("AISC_DEPLOYMENT=") for w in default), "the first run is the default mode"
    assert configurator[0] == "AISC_DEPLOYMENT=configurator", "the second run is the configurator mode"
    for words in runs:
        text = " ".join(words)
        assert "uv run --locked --no-dev --group test pytest" in text, text


def test_the_eval_lint_runs_ruff_check_and_format_check_from_the_lock():
    run = run_of("eval lint")
    assert commands(run)[0] == ["cd", "apps/eval"]
    texts = [" ".join(words) for words in commands(run)[1:]]
    assert "uv run --locked --only-group dev ruff check ." in texts, run
    assert "uv run --locked --only-group dev ruff format --check ." in texts, run


@pytest.mark.parametrize("suite, folder", [
    ("plugin-manager", "shared/plugin-manager"),
    ("plugin-interface", "shared/plugin-interface"),
    ("report-generator", "apps/report-generator"),
])
def test_the_shared_libraries_and_the_renderer_run_from_their_folders_and_locks(suite, folder):
    run = run_of(suite)
    assert commands(run)[0] == ["cd", folder], run
    runs = pytest_commands(run)
    assert len(runs) == 1, run
    assert "--locked" in runs[0], run


def test_the_report_generator_runs_without_the_callers_database_urls():
    words = pytest_commands(run_of("report-generator"))[0]
    assert words[:5] == ["env", "-u", "DATABASE_URL", "-u", "PLATFORM_TEST_DATABASE_URL"], words


def test_no_root_job_downloads_lfs_objects():
    assert workflow()["env"]["GIT_LFS_SKIP_SMUDGE"] == "1"


def test_the_python_job_pins_python_and_a_timeout():
    job = workflow()["jobs"]["python"]
    assert job["env"]["UV_PYTHON"] == "3.12"
    assert job["timeout-minutes"] == 60


def test_the_triggers_are_unchanged():
    on = triggers(workflow())
    assert set(on) == {"push", "pull_request"}
    assert on["push"]["branches"] == ["pilot", "main", "master"]
    assert not on["pull_request"], "pull_request takes every base branch"
